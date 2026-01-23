"""
Flask app voor Bol.com scraper
"""
import os
import io
import re
import hashlib
from typing import Dict, Any, Optional, List, Tuple
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, jsonify
import google.generativeai as genai
from dotenv import load_dotenv

from scraper.printables import scrape_printables_product
from scraper.bol import scrape_bol_product
from scraper.amazon import scrape_amazon_product

load_dotenv()
load_dotenv('.env.local')

# Configure Google AI
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
    except Exception as e:
        print(f"Error configuring Google AI: {e}")

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')

# Configuratie
HEADLESS = os.getenv('HEADLESS', 'true').lower() == 'true'
OUTPUT_EXCEL = os.getenv('OUTPUT_EXCEL', 'Export_generic_template_20251004_07 PM052.xlsx')
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', '').rstrip('/')  # optioneel, bv. https://example.com

# Static pad voor afbeeldingen (Flask serveert /static automatisch vanuit deze map)
STATIC_IMAGES_DIR = os.path.join(os.path.dirname(__file__), 'static', 'images', 'products')
os.makedirs(STATIC_IMAGES_DIR, exist_ok=True)

# Excel kolomvolgorde (exact zoals gespecificeerd in template)
EXCEL_COLUMNS = [
    'Productnaam',           # title
    'Beschrijving',          # description
    'Interne referentie',    # internal_reference
    'EAN',                   # ean
    'Conditie',              # condition
    'Conditie commentaar',   # condition_comment
    'Voorraad',              # stock
    'Prijs',                 # list_price_value
    'Levertijd',             # delivery_time
    'Afleverwijze',          # delivery_method
    'Te koop',               # for_sale
    'Hoofdafbeelding',       # main_image
    'Marktdeelnemer',        # marketplace_participant
    'Additionele afbeeldingen' # all_images
]

@app.route('/printables')
def printables_index():
    """Printables Scraper hoofdpagina."""
    return render_template('printables_index.html')


@app.route('/printables/scrape', methods=['POST'])
def printables_scrape():
    """Start scrape van Printables URL."""
    url = request.form.get('url', '').strip()
    
    if not url:
        flash('Voer een URL in', 'error')
        return redirect(url_for('printables_index'))
    
    if 'printables.com' not in url:
        flash('URL moet van printables.com zijn', 'error')
        return redirect(url_for('printables_index'))
        
    try:
        # Scrape product
        product_data = scrape_printables_product(url, headless=HEADLESS)
        
        # Download afbeeldingen naar /static en vervang URLs door serveerbare lokale URLs
        try:
            new_main, new_all = process_images_into_static(
                product_data.get('main_image', ''),
                product_data.get('all_images', ''),
                title=product_data.get('title', ''),
                ean=f"PR-{int(time.time())}" # Fake EAN/ID voor unieke bestandsnamen
            )
            product_data['main_image'] = new_main
            product_data['all_images'] = new_all
        except Exception:
            pass
        
        # Zet in session
        session['current_row'] = product_data
        # Gebruik de BOL edit flow voor nu, want de velden zijn gemapped
        # Maar we moeten wel weten dat we terug naar printables moeten als we cancelen?
        # Voorlopig linken we naar dezelfde edit pagina, maar die post naar /bol/edit...
        # Dat is niet handig. We moeten een /printables/edit hebben of de edit pagina slim maken.
        # Laten we voor consistentie /printables/edit maken.
        
        return redirect(url_for('printables_edit'))
        
    except Exception as e:
        flash(f'Scrape fout: {str(e)}', 'error')
        return redirect(url_for('printables_index'))


@app.route('/printables/edit', methods=['GET', 'POST'])
def printables_edit():
    """Formulier voor bewerken van Printables data."""
    if 'current_row' not in session:
        flash('Geen data om te bewerken', 'error')
        return redirect(url_for('printables_index'))
    
    if request.method == 'POST':
        # Reuse logic from bol_edit but redirect to printables confirm
        # ... (kopie van bol_edit logica) ...
        current_data = session['current_row'].copy()
        
        field_mapping = {
            'Productnaam': 'title',
            'Beschrijving': 'description', 
            'Interne referentie': 'internal_reference',
            'EAN': 'ean',
            'Conditie': 'condition',
            'Conditie commentaar': 'condition_comment',
            'Voorraad': 'stock',
            'Prijs': 'list_price_value',
            'Levertijd': 'delivery_time',
            'Afleverwijze': 'delivery_method',
            'Te koop': 'for_sale',
            'Hoofdafbeelding': 'main_image',
            'Marktdeelnemer': 'marketplace_participant',
            'Additionele afbeeldingen': 'all_images'
        }
        
        for excel_field, internal_field in field_mapping.items():
            if excel_field in request.form:
                value = request.form[excel_field].strip()
                if internal_field == 'list_price_value':
                    try:
                        current_data[internal_field] = float(value) if value else None
                    except ValueError:
                        current_data[internal_field] = None
                elif internal_field == 'stock':
                    try:
                        current_data[internal_field] = int(value) if value else 69
                    except ValueError:
                        current_data[internal_field] = 69
                else:
                    current_data[internal_field] = value
        
        session['current_row'] = current_data
        return redirect(url_for('printables_confirm'))
    
    # We gebruiken een specifieke template of hergebruiken edit.html met een flag
    return render_template('edit.html', data=session['current_row'], platform='printables')


@app.route('/printables/confirm', methods=['GET', 'POST'])
def printables_confirm():
    if 'current_row' not in session:
        flash('Geen data om te bevestigen', 'error')
        return redirect(url_for('printables_index'))
    
    if request.method == 'POST':
        try:
            if 'editing_row_index' in session:
                update_excel_row(session['editing_row_index'], session['current_row'])
                flash('Product bijgewerkt!', 'success')
                session.pop('editing_row_index', None)
                return redirect(url_for('printables_rows'))
            else:
                append_to_excel(session['current_row'])
                flash('Product opgeslagen in Excel!', 'success')
                return redirect(url_for('printables_index'))
            session.pop('current_row', None)
        except Exception as e:
            flash(f'Opslaan fout: {str(e)}', 'error')
    
    return render_template('confirm.html', data=session['current_row'], platform='printables')


@app.route('/printables/rows')
def printables_rows():
    """Overzicht rijen (gedeelde Excel)."""
    # Reuse bol logic but render with platform='printables' for back links
    try:
        df = get_excel_data()
        df = df.dropna(how='all')
        rows_data = df.to_dict('records')
        for row in rows_data:
             for col in EXCEL_COLUMNS:
                if col not in row or pd.isna(row[col]):
                    row[col] = ''
                elif col == 'Prijs':
                    if pd.isna(row[col]) or row[col] == '':
                        row[col] = ''
                    elif isinstance(row[col], (int, float)):
                        row[col] = float(row[col])
                    else:
                        try:
                            row[col] = float(str(row[col]).replace(',', '.'))
                        except:
                            row[col] = ''
                elif isinstance(row[col], (int, float)) and not isinstance(row[col], bool):
                    if pd.isna(row[col]):
                        row[col] = ''
                    else:
                        row[col] = str(row[col])
                        
        return render_template('rows.html', rows=rows_data, platform='printables')
    except Exception as e:
        flash(f'Fout: {str(e)}', 'error')
        return redirect(url_for('printables_index'))
        
        
@app.route('/printables/edit_row/<int:row_index>')
def printables_edit_row(row_index):
    # Reuse logic
    try:
        df = get_excel_data()
        if row_index >= len(df):
            return redirect(url_for('printables_rows'))
        row_data = df.iloc[row_index].to_dict()
        internal_data = {
            'title': row_data.get('Productnaam', ''),
            'description': row_data.get('Beschrijving', ''),
            'internal_reference': row_data.get('Interne referentie', ''),
            'ean': row_data.get('EAN', ''),
            'condition': row_data.get('Conditie', ''),
            'condition_comment': row_data.get('Conditie commentaar', ''),
            'stock': row_data.get('Voorraad', 69),
            'list_price_value': row_data.get('Prijs', None),
            'delivery_time': row_data.get('Levertijd', ''),
            'delivery_method': row_data.get('Afleverwijze', ''),
            'for_sale': row_data.get('Te koop', 'ja'),
            'main_image': row_data.get('Hoofdafbeelding', ''),
            'marketplace_participant': row_data.get('Marktdeelnemer', ''),
            'all_images': row_data.get('Additionele afbeeldingen', '')
        }
        session['current_row'] = internal_data
        session['editing_row_index'] = row_index
        return redirect(url_for('printables_edit'))
    except Exception as e:
         return redirect(url_for('printables_rows'))

@app.route('/printables/delete_row/<int:row_index>')
def printables_delete_row(row_index):
    try:
        df = get_excel_data()
        if row_index < len(df):
            df = df.drop(df.index[row_index])
            df.to_excel(OUTPUT_EXCEL, index=False)
            flash('Verwijderd', 'success')
        return redirect(url_for('printables_rows'))
    except:
        return redirect(url_for('printables_rows'))
        
@app.route('/printables/export')
def printables_export():
    return bol_export() # Reuse export logic




def validate_bol_url(url: str) -> bool:
    """Valideer of URL van bol.com is."""
    try:
        parsed = urlparse(url)
        return parsed.netloc and 'bol.com' in parsed.netloc
    except:
        return False


def normalize_bol_url(url: str) -> str:
    """Probeer van invoer een geldige bol.com URL te maken.
    - Voegt https:// toe als schema ontbreekt
    - Trimt whitespace
    - Accepteert www.bol.com/... of bol.com/...
    """
    if not url:
        return ''
    raw = url.strip()
    # Pad-only invoer direct mappen naar bol.com
    if raw.startswith('/'):
        return 'https://www.bol.com' + raw
    # Geen schema opgegeven
    if not re.match(r'^https?://', raw, flags=re.IGNORECASE):
        first_token = raw.split('/')[0].lower()
        if '.' in first_token:
            # Lijkt een host (bijv. bol.com/... of www.bol.com/...)
            raw = 'https://' + raw
        else:
            # Lijkt een pad zonder leading slash (bijv. product/123)
            return 'https://www.bol.com/' + raw
    parsed = urlparse(raw)
    # Als nog steeds geen host, behandel het als pad
    if not parsed.netloc and parsed.path:
        return 'https://www.bol.com' + (parsed.path if parsed.path.startswith('/') else ('/' + parsed.path)) + (('?' + parsed.query) if parsed.query else '')
    # Host controle
    host = (parsed.netloc or '').lower()
    if host.endswith('bol.com'):
        return raw
    # Forceer bol.com met behoud van pad en query
    if parsed.path:
        return 'https://www.bol.com' + (parsed.path if parsed.path.startswith('/') else ('/' + parsed.path)) + (('?' + parsed.query) if parsed.query else '')
    return raw


def is_valid_image_source_url(url: str) -> bool:
    """Valideer bron-URL tegen Bol eisen (basis checks; uiteindelijke URL wordt lokaal)."""
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        # Geen shorteners (simpele blacklist)
        host = parsed.netloc.lower()
        if host in { 'bit.ly', 't.ly', 'tinyurl.com', 'goo.gl', 'ow.ly', 'buff.ly' }:
            return False
        return True
    except Exception:
        return False


def guess_extension(content_type: str, fallback: str = '.jpg') -> str:
    ct = (content_type or '').lower()
    if 'jpeg' in ct:
        return '.jpg'
    if 'jpg' in ct:
        return '.jpg'
    if 'png' in ct:
        return '.png'
    return fallback


def sanitize_filename(name: str) -> str:
    """Maak veilige bestandsnaam: geen spaties/rare chars, lowercase."""
    name = name.strip().lower()
    name = name.replace(' ', '-')
    # Alleen a-z0-9-_ .
    name = re.sub(r'[^a-z0-9\-_.]', '', name)
    name = re.sub(r'-{2,}', '-', name)
    name = name.strip('-.')
    return name or 'image'


def build_image_filename(title: str, ean: str, index: int, ext: str, source_url: str) -> str:
    base = sanitize_filename(f"{title}-{ean}" if ean else title)
    # Hash erbij voor uniqueness bij gelijke titels
    url_hash = hashlib.sha1(source_url.encode('utf-8')).hexdigest()[:8]
    filename = f"{base}-{index+1}-{url_hash}{ext}"
    return filename


def download_image_to_static(source_url: str, title: str, ean: str, index: int) -> Optional[str]:
    """Download afbeelding en sla op in static, return serveerbare URL (/static/...)."""
    if not is_valid_image_source_url(source_url):
        return None
    try:
        req = Request(source_url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; BolScraper/1.0)'
        })
        with urlopen(req, timeout=20) as resp:
            content_type = resp.headers.get('Content-Type', '')
            if not any(x in (content_type or '').lower() for x in ['image/jpeg', 'image/jpg', 'image/png']):
                return None
            data = resp.read()
            ext = guess_extension(content_type)
    except (HTTPError, URLError, TimeoutError):
        return None
    except Exception:
        return None

    filename = build_image_filename(title, ean, index, ext, source_url)
    abs_path = os.path.join(STATIC_IMAGES_DIR, filename)
    try:
        with open(abs_path, 'wb') as f:
            f.write(data)
    except Exception:
        return None

    # Bouw publieke/serveerbare URL (zonder spaties, eindigt op .jpg/.png)
    rel_path = f"/static/images/products/{filename}"
    # Gebruik PUBLIC_BASE_URL of fallback naar localhost:5001 (nooit relatieve paden)
    base = PUBLIC_BASE_URL if PUBLIC_BASE_URL else "http://localhost:5001"
    return f"{base}{rel_path}"


def process_images_into_static(main_image_url: str, all_images_concat: str, title: str, ean: str) -> Tuple[str, str]:
    """Download hoofd- en additionele afbeeldingen en return lokale URLs (gescheiden door |)."""
    urls: List[str] = []
    if main_image_url:
        urls.append(main_image_url)
    if all_images_concat:
        urls.extend([u for u in all_images_concat.split('|') if u])

    # Dedupe met behoud van volgorde
    seen = set()
    ordered_urls = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered_urls.append(u)

    stored_urls: List[str] = []
    for i, src in enumerate(ordered_urls):
        stored = download_image_to_static(src, title=title or 'product', ean=ean or '', index=i)
        if stored:
            stored_urls.append(stored)

    new_main = stored_urls[0] if stored_urls else ''
    new_all = '|'.join(stored_urls)
    return new_main, new_all


def ensure_excel_exists() -> None:
    """Zorg dat Excel bestand bestaat met juiste kolommen."""
    # Gebruik altijd het template bestand
    template_file = 'Export_generic_template_20251004_07 PM052.xlsx'
    if os.path.exists(template_file):
        # Kopieer template naar output bestand als het nog niet bestaat
        if not os.path.exists(OUTPUT_EXCEL):
            import shutil
            shutil.copy2(template_file, OUTPUT_EXCEL)


def map_data_to_excel_columns(data: Dict[str, Any]) -> Dict[str, Any]:
    """Map onze data naar Excel kolom namen."""
    return {
        'Productnaam': data.get('title', ''),
        'Beschrijving': data.get('description', ''),
        'Interne referentie': data.get('internal_reference', ''),
        'EAN': data.get('ean', ''),
        'Conditie': data.get('condition', ''),
        'Conditie commentaar': data.get('condition_comment', ''),
        'Voorraad': data.get('stock', 69),
        'Prijs': data.get('list_price_value', None),
        'Levertijd': data.get('delivery_time', ''),
        'Afleverwijze': data.get('delivery_method', ''),
        'Te koop': data.get('for_sale', 'ja'),
        'Hoofdafbeelding': data.get('main_image', ''),
        'Marktdeelnemer': data.get('marketplace_participant', ''),
        'Additionele afbeeldingen': data.get('all_images', '')
    }


def append_to_excel(data: Dict[str, Any]) -> None:
    """Append data naar Excel bestand."""
    ensure_excel_exists()
    
    # Map data naar Excel kolommen
    excel_data = map_data_to_excel_columns(data)
    
    # Maak DataFrame van data
    df_new = pd.DataFrame([excel_data])
    
    # Lees bestaande data
    df_existing = pd.read_excel(OUTPUT_EXCEL)
    
    # Combineer en schrijf terug
    df_combined = pd.concat([df_existing, df_new], ignore_index=True)
    df_combined.to_excel(OUTPUT_EXCEL, index=False)


def update_excel_row(row_index: int, data: Dict[str, Any]) -> None:
    """Update een bestaande rij in Excel bestand."""
    # Map data naar Excel kolommen
    excel_data = map_data_to_excel_columns(data)
    
    # Lees bestaande data
    df = pd.read_excel(OUTPUT_EXCEL)
    
    # Update de specifieke rij
    for col, value in excel_data.items():
        if col in df.columns:
            df.at[row_index, col] = value
    
    # Schrijf terug
    df.to_excel(OUTPUT_EXCEL, index=False)


def get_excel_data() -> pd.DataFrame:
    """Lees alle data uit Excel bestand."""
    if not os.path.exists(OUTPUT_EXCEL):
        return pd.DataFrame(columns=EXCEL_COLUMNS)
    
    df = pd.read_excel(OUTPUT_EXCEL)
    
    # Filter alleen de gewenste kolommen en verwijder oude kolommen
    if all(col in df.columns for col in EXCEL_COLUMNS):
        df = df[EXCEL_COLUMNS]
    else:
        # Maak nieuwe DataFrame met alleen gewenste kolommen
        df_clean = pd.DataFrame(columns=EXCEL_COLUMNS)
        for col in EXCEL_COLUMNS:
            if col in df.columns:
                df_clean[col] = df[col]
            else:
                df_clean[col] = ''
        df = df_clean
    
    # Vervang NaN waarden met lege strings
    df = df.fillna('')
    
    return df


@app.route('/')
def home():
    """Nieuwe home pagina met scraper selectie."""
    return render_template('home.html')


@app.route('/bol')
def bol_index():
    """Bol.com Scraper hoofdpagina."""
    return render_template('bol_index.html')


@app.route('/bol/scrape', methods=['POST'])
def bol_scrape():
    """Start scrape van bol.com URL."""
    incoming = request.form.get('url', '').strip()
    url = normalize_bol_url(incoming)
    
    if not url:
        flash('Voer een URL in', 'error')
        return redirect(url_for('bol_index'))
    
    if not validate_bol_url(url):
        flash('URL moet van bol.com zijn (invoer automatisch proberen te corrigeren is mislukt)', 'error')
        return redirect(url_for('bol_index'))
    
    try:
        # Scrape product
        product_data = scrape_bol_product(url, headless=HEADLESS)
        
        # Voeg standaard waarden toe voor nieuwe velden
        product_data['condition'] = 'nieuw'
        product_data['condition_comment'] = ''
        product_data['internal_reference'] = ''
        product_data['stock'] = 69
        product_data['delivery_time'] = ''
        product_data['delivery_method'] = ''
        product_data['for_sale'] = 'ja'
        product_data['marketplace_participant'] = ''

        # Download afbeeldingen naar /static en vervang URLs door serveerbare lokale URLs
        try:
            new_main, new_all = process_images_into_static(
                product_data.get('main_image', ''),
                product_data.get('all_images', ''),
                title=product_data.get('title', ''),
                ean=product_data.get('ean', '')
            )
            product_data['main_image'] = new_main
            product_data['all_images'] = new_all
        except Exception:
            # Bij fout: laat originele URLs staan
            pass
        
        # Zet in session
        session['current_row'] = product_data
        
        return redirect(url_for('bol_edit'))
        
    except Exception as e:
        flash(f'Scrape fout: {str(e)}', 'error')
        return redirect(url_for('bol_index'))


@app.route('/bol/edit', methods=['GET', 'POST'])
def bol_edit():
    """Formulier voor bewerken van gescrapete data."""
    if 'current_row' not in session:
        flash('Geen data om te bewerken', 'error')
        return redirect(url_for('bol_index'))
    
    if request.method == 'POST':
        # Update session data met formulier data
        current_data = session['current_row'].copy()
        
        # Map Excel kolommen naar onze interne veld namen
        field_mapping = {
            'Productnaam': 'title',
            'Beschrijving': 'description', 
            'Interne referentie': 'internal_reference',
            'EAN': 'ean',
            'Conditie': 'condition',
            'Conditie commentaar': 'condition_comment',
            'Voorraad': 'stock',
            'Prijs': 'list_price_value',
            'Levertijd': 'delivery_time',
            'Afleverwijze': 'delivery_method',
            'Te koop': 'for_sale',
            'Inkoopprijs': 'cost_price',
            'Verzendkosten': 'shipping_costs',
            'Commissie Percentage': 'commission_percentage',
            'Commissie Vast': 'commission_fixed',
            'Bol Commissie': 'commission_amount',
            'Marge': 'margin',
            'Hoofdafbeelding': 'main_image',
            'Marktdeelnemer': 'marketplace_participant',
            'Additionele afbeeldingen': 'all_images'
        }
        
        for excel_field, internal_field in field_mapping.items():
            if excel_field in request.form:
                value = request.form[excel_field].strip()
                
                # Speciale behandeling voor numerieke velden
                if internal_field in ['list_price_value', 'cost_price', 'shipping_costs', 'commission_percentage', 'commission_fixed', 'commission_amount', 'margin']:
                    try:
                        current_data[internal_field] = float(value) if value else None
                    except ValueError:
                        current_data[internal_field] = None
                elif internal_field == 'stock':
                    try:
                        current_data[internal_field] = int(value) if value else 69
                    except ValueError:
                        current_data[internal_field] = 69
                else:
                    current_data[internal_field] = value
        
        session['current_row'] = current_data
        return redirect(url_for('bol_confirm'))
    
    # GET: toon formulier
    return render_template('edit.html', data=session['current_row'])


@app.route('/bol/confirm', methods=['GET', 'POST'])
def bol_confirm():
    """Bevestigingspagina met data overzicht."""
    if 'current_row' not in session:
        flash('Geen data om te bevestigen', 'error')
        return redirect(url_for('bol_index'))
    
    if request.method == 'POST':
        # Sla op in Excel
        try:
            # Check of we een bestaande rij bewerken
            if 'editing_row_index' in session:
                # Update bestaande rij
                update_excel_row(session['editing_row_index'], session['current_row'])
                flash('Product bijgewerkt!', 'success')
                session.pop('editing_row_index', None)
                return redirect(url_for('bol_rows'))
            else:
                # Nieuwe rij toevoegen
                append_to_excel(session['current_row'])
                flash('Product opgeslagen in Excel!', 'success')
                return redirect(url_for('bol_index'))
            
            # Clear session
            session.pop('current_row', None)
            
        except Exception as e:
            flash(f'Opslaan fout: {str(e)}', 'error')
    
    # GET: toon data overzicht
    return render_template('confirm.html', data=session['current_row'])


@app.route('/bol/rows')
def bol_rows():
    """Overzicht van alle opgeslagen rijen."""
    try:
        df = get_excel_data()
        
        # Filter lege rijen (alleen rijen met echte data)
        df = df.dropna(how='all')
        
        # Converteer naar dict lijst voor template
        rows_data = df.to_dict('records')
        
        # Zorg dat elke rij alle verwachte velden heeft en geen NaN waarden
        for row in rows_data:
            for col in EXCEL_COLUMNS:
                if col not in row or pd.isna(row[col]):
                    row[col] = ''
                # Speciale behandeling voor prijs velden
                elif col == 'Prijs':
                    if pd.isna(row[col]) or row[col] == '':
                        row[col] = ''
                    elif isinstance(row[col], (int, float)):
                        row[col] = float(row[col])  # Behoud als float voor formatting
                    else:
                        try:
                            row[col] = float(str(row[col]).replace(',', '.'))
                        except (ValueError, TypeError):
                            row[col] = ''
                # Converteer andere velden naar string om slicing problemen te voorkomen
                elif isinstance(row[col], (int, float)) and not isinstance(row[col], bool):
                    if pd.isna(row[col]):
                        row[col] = ''
                    else:
                        row[col] = str(row[col])
        
        # Debug info
        print(f"DEBUG: Aantal rijen gevonden: {len(rows_data)}")
        if len(rows_data) > 0:
            print(f"DEBUG: Eerste rij: {rows_data[0]}")
        
        return render_template('rows.html', rows=rows_data)
    except Exception as e:
        print(f"DEBUG: Fout in rows functie: {str(e)}")
        flash(f'Fout bij laden data: {str(e)}', 'error')
        return redirect(url_for('bol_index'))


@app.route('/bol/edit_row/<int:row_index>')
def bol_edit_row(row_index):
    """Bewerk een bestaande rij."""
    try:
        df = get_excel_data()
        
        if row_index >= len(df):
            flash('Rij niet gevonden', 'error')
            return redirect(url_for('bol_rows'))
        
        # Haal de rij data op
        row_data = df.iloc[row_index].to_dict()
        
        # Converteer naar interne format
        internal_data = {
            'title': row_data.get('Productnaam', ''),
            'description': row_data.get('Beschrijving', ''),
            'internal_reference': row_data.get('Interne referentie', ''),
            'ean': row_data.get('EAN', ''),
            'condition': row_data.get('Conditie', ''),
            'condition_comment': row_data.get('Conditie commentaar', ''),
            'stock': row_data.get('Voorraad', 69),
            'list_price_value': row_data.get('Prijs', None),
            'delivery_time': row_data.get('Levertijd', ''),
            'delivery_method': row_data.get('Afleverwijze', ''),
            'for_sale': row_data.get('Te koop', 'ja'),
            'cost_price': row_data.get('Inkoopprijs', None),
            'shipping_costs': row_data.get('Verzendkosten', None),
            'commission_percentage': row_data.get('Commissie Percentage', None),
            'commission_fixed': row_data.get('Commissie Vast', None),
            'commission_amount': row_data.get('Bol Commissie', None),
            'margin': row_data.get('Marge', None),
            'main_image': row_data.get('Hoofdafbeelding', ''),
            'marketplace_participant': row_data.get('Marktdeelnemer', ''),
            'all_images': row_data.get('Additionele afbeeldingen', '')
        }
        
        # Zet in session met row index voor update
        session['current_row'] = internal_data
        session['editing_row_index'] = row_index
        
        return redirect(url_for('bol_edit'))
        
    except Exception as e:
        flash(f'Fout bij laden rij: {str(e)}', 'error')
        return redirect(url_for('bol_rows'))


@app.route('/bol/delete_row/<int:row_index>')
def bol_delete_row(row_index):
    """Verwijder een rij."""
    try:
        df = get_excel_data()
        
        if row_index >= len(df):
            flash('Rij niet gevonden', 'error')
            return redirect(url_for('bol_rows'))
        
        # Verwijder de rij
        df = df.drop(df.index[row_index])
        
        # Schrijf terug naar Excel
        df.to_excel(OUTPUT_EXCEL, index=False)
        
        flash('Product verwijderd!', 'success')
        return redirect(url_for('bol_rows'))
        
    except Exception as e:
        flash(f'Fout bij verwijderen: {str(e)}', 'error')
        return redirect(url_for('bol_rows'))


@app.route('/bol/export')
def bol_export():
    """Download Excel bestand."""
    try:
        # Lees alleen het output bestand, niet het template
        if os.path.exists(OUTPUT_EXCEL):
            df = pd.read_excel(OUTPUT_EXCEL)
        else:
            # Maak lege DataFrame met juiste kolommen
            df = pd.DataFrame(columns=EXCEL_COLUMNS)
        
        # Filter alleen de gewenste kolommen en verwijder oude kolommen
        df_clean = df[EXCEL_COLUMNS] if all(col in df.columns for col in EXCEL_COLUMNS) else pd.DataFrame(columns=EXCEL_COLUMNS)
        
        # Zorg dat alle verwachte kolommen bestaan
        for col in EXCEL_COLUMNS:
            if col not in df_clean.columns:
                df_clean[col] = ''
        
        # Vervang NaN waarden met lege strings
        df_clean = df_clean.fillna('')
        
        # Maak in-memory stream
        output = io.BytesIO()
        df_clean.to_excel(output, index=False, engine='openpyxl')
        output.seek(0)
        
        return send_file(
            output,
            as_attachment=True,
            download_name='Export_generic_template_20251004_07 PM052.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        flash(f'Export fout: {str(e)}', 'error')
        return redirect(url_for('bol_index'))


@app.route('/amazon')
def amazon_index():
    """Amazon Scraper hoofdpagina."""
    return render_template('amazon_index.html')


@app.route('/amazon/scrape', methods=['POST'])
def amazon_scrape():
    """Start scrape van Amazon URL."""
    url = request.form.get('url', '').strip()
    
    if not url:
        flash('Voer een URL in', 'error')
        return redirect(url_for('amazon_index'))
    
    # Simpele validatie
    if 'amazon' not in url:
        flash('URL moet van amazon zijn', 'error')
        return redirect(url_for('amazon_index'))
        
    try:
        # Scrape product
        product_data = scrape_amazon_product(url, headless=HEADLESS)
        
        # Voeg standaard waarden toe
        product_data['condition'] = 'nieuw'
        product_data['condition_comment'] = ''
        product_data['internal_reference'] = product_data.get('asin', '')
        product_data['stock'] = 69
        product_data['delivery_time'] = ''
        product_data['delivery_method'] = ''
        product_data['for_sale'] = 'ja'
        product_data['marketplace_participant'] = ''
        
        # Amazon specifiek: Scraped prijs is Inkoopprijs
        product_data['cost_price'] = product_data.get('price_value')
        product_data['shipping_costs'] = 6.90
        product_data['list_price_value'] = None # Verkoopprijs is nog te bepalen -> leeg laten of default? User implies "The price that scrapes from amazon can be put directly into the cost price". Usually you then calculate a sell price. 
        # But wait, if 'list_price_value' is used as 'Prijs' (Selling Price) in the edit form, we should probably clear it or set it to a target price?
        # Let's just set cost_price and leave list_price_value (Selling Price) empty or as is (if amazon has a list price, maybe that's the RRP/Adviesprijs).
        # In amazon.py, 'list_price_value' is likely the scratched price (RRP).
        # 'price_value' is the current amazon price.
        
        # Mapping:
        # Amazon Price (price_value) -> Inkoopprijs (cost_price)
        # Amazon List Price (list_price_value) -> Adviesprijs (list_price_value in internal model? Wait. In bol.py mapping: 'list_price_value' maps to 'Prijs' (Selling Price) column in Excel?
        # Let's check `bol_edit` mapping again.
        # 'Prijs': 'list_price_value'. So 'list_price_value' IS the field that ends up in the 'Prijs' column in Excel.
        # If we want the *Selling Price* to be something else, we should set 'list_price_value' to that.
        # If the user says "The price that scrapes... put in cost price", they likely imply:
        # Scraped Amazon Price -> Cost Price.
        # Selling Price -> To be entered by user (or maybe we keep it empty?)
        # Let's set cost_price = price_value.
        # And let's NOT set list_price_value to price_value (which would be selling at cost).
        
        # Let's looking at the code I'm replacing:
        # It doesn't explicitly set list_price_value here, it comes from scrape_amazon_product.
        # scrape_amazon_product likely returns 'price_value' and 'list_price_value'.
        # I should probably overwrite list_price_value to None or keep it as RRP?
        # In the context of "Bol Scraper" (the app name), the Excel 'Prijs' column is the price on BOL.
        # So we probably don't want the Amazon Buy Price in the Bol Sell Price column.
        # So I will wipe list_price_value (Selling Price) so the user is forced/encouraged to enter a margin-based price, 
        # OR I calculate a default sell price?
        # User didn't ask for auto-calc sell price. Just "put amazon price in cost price".
        
        product_data['list_price_value'] = None # Reset selling price so user can calculate it

        # Download afbeeldingen
        try:
            new_main, new_all = process_images_into_static(
                product_data.get('main_image', ''),
                product_data.get('all_images', ''),
                title=product_data.get('title', ''),
                ean=product_data.get('ean', '') or f"AMZ-{int(time.time())}"
            )
            product_data['main_image'] = new_main
            product_data['all_images'] = new_all
        except Exception:
            pass
        
        # Zet in session
        session['current_row'] = product_data
        
        return redirect(url_for('amazon_edit'))
        
    except Exception as e:
        flash(f'Scrape fout: {str(e)}', 'error')
        return redirect(url_for('amazon_index'))


@app.route('/amazon/edit', methods=['GET', 'POST'])
def amazon_edit():
    """Formulier voor bewerken van Amazon data."""
    if 'current_row' not in session:
        flash('Geen data om te bewerken', 'error')
        return redirect(url_for('amazon_index'))
    
    if request.method == 'POST':
        current_data = session['current_row'].copy()
        
        field_mapping = {
            'Productnaam': 'title',
            'Beschrijving': 'description', 
            'Interne referentie': 'internal_reference',
            'EAN': 'ean',
            'Conditie': 'condition',
            'Conditie commentaar': 'condition_comment',
            'Voorraad': 'stock',
            'Prijs': 'list_price_value',
            'Levertijd': 'delivery_time',
            'Afleverwijze': 'delivery_method',
            'Te koop': 'for_sale',
            'Inkoopprijs': 'cost_price',
            'Verzendkosten': 'shipping_costs',
            'Commissie Percentage': 'commission_percentage',
            'Commissie Vast': 'commission_fixed',
            'Bol Commissie': 'commission_amount',
            'Marge': 'margin',
            'Hoofdafbeelding': 'main_image',
            'Marktdeelnemer': 'marketplace_participant',
            'Additionele afbeeldingen': 'all_images'
        }
        
        for excel_field, internal_field in field_mapping.items():
            if excel_field in request.form:
                value = request.form[excel_field].strip()
                
                # Speciale behandeling voor numerieke velden
                if internal_field in ['list_price_value', 'cost_price', 'shipping_costs', 'commission_percentage', 'commission_fixed', 'commission_amount', 'margin']:
                    try:
                        current_data[internal_field] = float(value) if value else None
                    except ValueError:
                        current_data[internal_field] = None
                elif internal_field == 'stock':
                    try:
                        current_data[internal_field] = int(value) if value else 69
                    except ValueError:
                        current_data[internal_field] = 69
                else:
                    current_data[internal_field] = value
        
        session['current_row'] = current_data
        return redirect(url_for('amazon_confirm'))
    
    return render_template('edit.html', data=session['current_row'], platform='amazon')


@app.route('/amazon/confirm', methods=['GET', 'POST'])
def amazon_confirm():
    if 'current_row' not in session:
        flash('Geen data om te bevestigen', 'error')
        return redirect(url_for('amazon_index'))
    
    if request.method == 'POST':
        try:
            if 'editing_row_index' in session:
                update_excel_row(session['editing_row_index'], session['current_row'])
                flash('Product bijgewerkt!', 'success')
                session.pop('editing_row_index', None)
                return redirect(url_for('amazon_rows'))
            else:
                append_to_excel(session['current_row'])
                flash('Product opgeslagen in Excel!', 'success')
                return redirect(url_for('amazon_index'))
            session.pop('current_row', None)
        except Exception as e:
            flash(f'Opslaan fout: {str(e)}', 'error')
    
    return render_template('confirm.html', data=session['current_row'], platform='amazon')


@app.route('/amazon/rows')
def amazon_rows():
    """Overzicht rijen (Amazon)."""
    return bol_rows() # Re-use bol_rows logic, but ensure template knows it's amazon if needed for links?
    # bol_rows uses 'bol_rows' template logic or similar. 
    # Actually, bol_rows renders 'rows.html' which might need a platform var.
    # Let's inspect bol_rows again. It renders 'rows.html'.
    # We should probably copy the logic to pass platform='amazon' to rows.html so back buttons work
    try:
        df = get_excel_data()
        df = df.dropna(how='all')
        rows_data = df.to_dict('records')
        
        for row in rows_data:
            for col in EXCEL_COLUMNS:
                if col not in row or pd.isna(row[col]):
                    row[col] = ''
                elif col == 'Prijs':
                    if pd.isna(row[col]) or row[col] == '':
                        row[col] = ''
                    elif isinstance(row[col], (int, float)):
                        row[col] = float(row[col])
                    else:
                        try:
                            row[col] = float(str(row[col]).replace(',', '.'))
                        except:
                            row[col] = ''
                elif isinstance(row[col], (int, float)) and not isinstance(row[col], bool):
                    if pd.isna(row[col]):
                        row[col] = ''
                    else:
                        row[col] = str(row[col])
                        
        return render_template('rows.html', rows=rows_data, platform='amazon')
    except Exception as e:
        flash(f'Fout: {str(e)}', 'error')
        return redirect(url_for('amazon_index'))


@app.route('/amazon/edit_row/<int:row_index>')
def amazon_edit_row(row_index):
    # Reuse logic
    try:
        df = get_excel_data()
        if row_index >= len(df):
            return redirect(url_for('amazon_rows'))
        row_data = df.iloc[row_index].to_dict()
        internal_data = {
            'title': row_data.get('Productnaam', ''),
            'description': row_data.get('Beschrijving', ''),
            'internal_reference': row_data.get('Interne referentie', ''),
            'ean': row_data.get('EAN', ''),
            'condition': row_data.get('Conditie', ''),
            'condition_comment': row_data.get('Conditie commentaar', ''),
            'stock': row_data.get('Voorraad', 69),
            'list_price_value': row_data.get('Prijs', None),
            'delivery_time': row_data.get('Levertijd', ''),
            'delivery_method': row_data.get('Afleverwijze', ''),
            'for_sale': row_data.get('Te koop', 'ja'),
            'cost_price': row_data.get('Inkoopprijs', None),
            'shipping_costs': row_data.get('Verzendkosten', None),
            'commission_percentage': row_data.get('Commissie Percentage', None),
            'commission_fixed': row_data.get('Commissie Vast', None),
            'commission_amount': row_data.get('Bol Commissie', None),
            'margin': row_data.get('Marge', None),
            'main_image': row_data.get('Hoofdafbeelding', ''),
            'marketplace_participant': row_data.get('Marktdeelnemer', ''),
            'all_images': row_data.get('Additionele afbeeldingen', '')
        }
        session['current_row'] = internal_data
        session['editing_row_index'] = row_index
        return redirect(url_for('amazon_edit'))
    except Exception as e:
         return redirect(url_for('amazon_rows'))


@app.route('/amazon/delete_row/<int:row_index>')
def amazon_delete_row(row_index):
    try:
        df = get_excel_data()
        if row_index < len(df):
            df = df.drop(df.index[row_index])
            df.to_excel(OUTPUT_EXCEL, index=False)
            flash('Verwijderd', 'success')
        return redirect(url_for('amazon_rows'))
    except:
        return redirect(url_for('amazon_rows'))


@app.route('/amazon/export')
def amazon_export():
    return bol_export()


@app.route('/api/optimize-description', methods=['POST'])
def optimize_description():
    """Gebruik Google AI om een betere productbeschrijving te genereren."""
    if not GOOGLE_API_KEY:
        return jsonify({'error': 'Geen Google API key geconfigureerd'}), 500
        
    data = request.get_json()
    title = data.get('title', '')
    current_description = data.get('description', '')
    
    if not title and not current_description:
        return jsonify({'error': 'Geen titel of beschrijving opgegeven'}), 400
        
    try:
        model = genai.GenerativeModel('models/gemini-3-pro-preview')
        
        prompt = f"""
        Schrijf een professionele, verkoopkrachtige productbeschrijving voor Bol.com.
        
        Product Titel: {title}
        Huidige Beschrijving/Info: {current_description}
        
        Richtlijnen:
        - Gebruik makkelijk leesbare paragrafen
        - Gebruik opsommingstekens voor kenmerken (indien van toepassing)
        - Schrijf in het Nederlands
        - Focus op voordelen voor de klant
        - Maak het SEO vriendelijk
        - Geen inleiding of slot, alleen de beschrijving zelf
        """
        
        response = model.generate_content(prompt)
        optimized_text = response.text
        
        return jsonify({'result': optimized_text})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/optimize-title', methods=['POST'])
def optimize_title():
    """Gebruik Google AI om een betere producttitel te genereren."""
    if not GOOGLE_API_KEY:
        return jsonify({'error': 'Geen Google API key geconfigureerd'}), 500
        
    data = request.get_json()
    current_title = data.get('title', '')
    description = data.get('description', '')
    
    if not current_title and not description:
        return jsonify({'error': 'Geen titel of beschrijving beschikbaar'}), 400
        
    try:
        model = genai.GenerativeModel('models/gemini-3-pro-preview')
        
        prompt = f"""
        Herschrijf de producttitel voor Bol.com volgens exact deze structuur:
        [Merknaam] [Serie] - [Productgroep] - [Kenmerk 1] - [Kenmerk 2] - [Kenmerk 3]
        
        Input Titel: {current_title}
        Input Beschrijving: {description}
        
        Richtlijnen:
        - Haal merk, serie en kenmerken uit de input.
        - Als een serie niet bestaat, sla die over.
        - Zorg dat het professioneel klinkt.
        - Geen inleiding, alleen de titelsuggestie.
        - Houd het beknopt maar informatief.
        """
        
        response = model.generate_content(prompt)
        optimized_title = response.text.strip()
        
        # Verwijder quotes als die eromheen staan
        if optimized_title.startswith('"') and optimized_title.endswith('"'):
            optimized_title = optimized_title[1:-1]
            
        return jsonify({'result': optimized_title})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    # Zorg dat Excel bestand bestaat bij startup
    ensure_excel_exists()
    
    # Gebruik 0.0.0.0 voor Docker compatibility
    port = int(os.environ.get('PORT', 5002))
    app.run(debug=True, host='0.0.0.0', port=port)
