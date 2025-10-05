"""
Flask app voor Bol.com scraper
"""
import os
import io
import uuid
import requests
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse
from urllib.request import urlretrieve

import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, send_from_directory, Response
from dotenv import load_dotenv

from scraper.bol import scrape_bol_product

# Load environment variables
load_dotenv()

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')

# Configuratie
HEADLESS = os.getenv('HEADLESS', 'true').lower() == 'true'
OUTPUT_EXCEL = os.getenv('OUTPUT_EXCEL', 'Export_generic_template_20251004_07 PM052.xlsx')

# Lokale afbeelding configuratie
IMAGE_BASE_URL = os.getenv('IMAGE_BASE_URL', 'http://localhost:5000')

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


def validate_bol_url(url: str) -> bool:
    """Valideer of URL van bol.com is."""
    try:
        parsed = urlparse(url)
        return parsed.netloc and 'bol.com' in parsed.netloc
    except:
        return False


def validate_image_url_for_bol(image_url: str) -> bool:
    """Valideer of afbeelding URL voldoet aan bol.com vereisten."""
    if not image_url:
        return False
    
    try:
        # Controleer of URL eindigt op toegestane extensies
        valid_extensions = ['.jpg', '.jpeg', '.png']
        if not any(image_url.lower().endswith(ext) for ext in valid_extensions):
            return False
        
        # Controleer op spaties in URL
        if ' ' in image_url:
            return False
        
        # Controleer of het een geldige URL is
        parsed = urlparse(image_url)
        if not parsed.netloc or not parsed.scheme.startswith('http'):
            return False
        
        # Controleer of het geen verkorte URL is (geen bit.ly, tinyurl, etc.)
        shorteners = ['bit.ly', 'tinyurl.com', 'short.link', 't.co']
        if any(shortener in parsed.netloc.lower() for shortener in shorteners):
            return False
        
        # Controleer of het geen Dropbox URL is
        if 'dropbox.com' in parsed.netloc.lower():
            return False
        
        # Controleer of het geen kleine afbeelding is (thumbnails)
        small_image_indicators = ['thumb', 'small', 'mini', 'icon']
        if any(indicator in image_url.lower() for indicator in small_image_indicators):
            return False
        
        return True
        
    except Exception:
        return False


def get_image_dimensions(image_url: str) -> tuple:
    """Haal afbeelding dimensies op om te controleren of deze groot genoeg zijn."""
    try:
        response = requests.head(image_url, timeout=10)
        if response.status_code == 200:
            # Probeer dimensies uit headers te halen
            content_length = response.headers.get('content-length')
            if content_length:
                size_bytes = int(content_length)
                # Als afbeelding kleiner is dan 50KB, is het waarschijnlijk te klein
                if size_bytes < 50000:
                    return (0, 0)  # Te klein
            return (1200, 1200)  # Aanname dat het groot genoeg is
    except Exception:
        pass
    return (0, 0)


def download_and_save_image(image_url: str, product_id: str, image_index: int = 0) -> Optional[str]:
    """Download een afbeelding en sla lokaal op, retourneer de lokale URL."""
    try:
        if not image_url or not image_url.startswith('http'):
            return None
        
        # Maak unieke bestandsnaam
        file_extension = '.jpg'  # Forceer JPG voor bol.com compatibiliteit
        filename = f"{product_id}_{image_index}{file_extension}"
        filepath = os.path.join('static', 'images', 'products', filename)
        
        # Maak directory aan als het niet bestaat
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Download de afbeelding
        response = requests.get(image_url, timeout=30, stream=True)
        response.raise_for_status()
        
        # Controleer content type
        content_type = response.headers.get('content-type', '')
        if not content_type.startswith('image/'):
            print(f"URL is geen afbeelding: {image_url}")
            return None
        
        # Sla op als JPG
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        # Controleer of bestand groot genoeg is (minimaal 50KB)
        file_size = os.path.getsize(filepath)
        if file_size < 50000:
            print(f"Afbeelding te klein ({file_size} bytes): {image_url}")
            os.remove(filepath)  # Verwijder te kleine afbeelding
            return None
        
        # Retourneer de absolute URL die bol.com kan bereiken
        absolute_url = f"{IMAGE_BASE_URL}/images/products/{filename}"
        print(f"Afbeelding opgeslagen: {absolute_url} ({file_size} bytes)")
        return absolute_url
        
    except Exception as e:
        print(f"Fout bij downloaden van afbeelding {image_url}: {e}")
        return None


def download_product_images(product_data: Dict[str, Any]) -> Dict[str, Any]:
    """Download alle afbeeldingen van een product en sla lokaal op."""
    try:
        # Genereer unieke ID voor dit product
        product_id = str(uuid.uuid4())[:8]
        
        # Download hoofdafbeelding
        main_image_url = None
        if product_data.get('main_image'):
            local_url = download_and_save_image(product_data['main_image'], product_id, 0)
            if local_url:
                main_image_url = local_url
            elif validate_image_url_for_bol(product_data['main_image']):
                # Gebruik originele URL als download mislukt maar URL wel geldig is
                main_image_url = product_data['main_image']
        
        # Download additionele afbeeldingen
        all_images_urls = []
        if product_data.get('all_images'):
            image_urls = product_data['all_images'].split('|')
            for i, img_url in enumerate(image_urls[:10]):  # Max 10 afbeeldingen
                if img_url.strip():
                    local_url = download_and_save_image(img_url.strip(), product_id, i + 1)
                    if local_url:
                        all_images_urls.append(local_url)
                    elif validate_image_url_for_bol(img_url.strip()):
                        # Gebruik originele URL als download mislukt maar URL wel geldig is
                        all_images_urls.append(img_url.strip())
        
        # Update product data met URLs
        updated_data = product_data.copy()
        updated_data['main_image'] = main_image_url or ''
        updated_data['all_images'] = '|'.join(all_images_urls)
        
        return updated_data
        
    except Exception as e:
        print(f"Fout bij downloaden van afbeeldingen: {e}")
        return product_data  # Retourneer originele data bij fout


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


def get_excel_data() -> pd.DataFrame:
    """Lees alle data uit Excel bestand."""
    if not os.path.exists(OUTPUT_EXCEL):
        # Gebruik template bestand als fallback
        template_file = 'Export_generic_template_20251004_07 PM052.xlsx'
        if os.path.exists(template_file):
            return pd.read_excel(template_file)
        return pd.DataFrame(columns=EXCEL_COLUMNS)
    
    return pd.read_excel(OUTPUT_EXCEL)


@app.route('/')
def index():
    """Hoofdpagina met URL input."""
    return render_template('index.html')


@app.route('/scrape', methods=['POST'])
def scrape():
    """Start scrape van bol.com URL."""
    url = request.form.get('url', '').strip()
    
    if not url:
        flash('Voer een URL in', 'error')
        return redirect(url_for('index'))
    
    if not validate_bol_url(url):
        flash('URL moet van bol.com zijn', 'error')
        return redirect(url_for('index'))
    
    try:
        # Scrape product
        product_data = scrape_bol_product(url, headless=HEADLESS)
        
        # Download afbeeldingen lokaal en vervang URLs met lokale URLs
        product_data = download_product_images(product_data)
        
        # Voeg standaard waarden toe voor nieuwe velden
        product_data['condition'] = 'Nieuw'
        product_data['condition_comment'] = ''
        product_data['internal_reference'] = ''
        product_data['stock'] = 69
        product_data['delivery_time'] = ''
        product_data['delivery_method'] = ''
        product_data['for_sale'] = 'ja'
        product_data['marketplace_participant'] = ''
        
        # Zet in session
        session['current_row'] = product_data
        
        return redirect(url_for('edit'))
        
    except Exception as e:
        flash(f'Scrape fout: {str(e)}', 'error')
        return redirect(url_for('index'))


@app.route('/edit', methods=['GET', 'POST'])
def edit():
    """Formulier voor bewerken van gescrapete data."""
    if 'current_row' not in session:
        flash('Geen data om te bewerken', 'error')
        return redirect(url_for('index'))
    
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
            'Hoofdafbeelding': 'main_image',
            'Marktdeelnemer': 'marketplace_participant',
            'Additionele afbeeldingen': 'all_images'
        }
        
        for excel_field, internal_field in field_mapping.items():
            if excel_field in request.form:
                value = request.form[excel_field].strip()
                
                # Speciale behandeling voor numerieke velden
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
        return redirect(url_for('confirm'))
    
    # GET: toon formulier
    return render_template('edit.html', data=session['current_row'])


@app.route('/confirm', methods=['GET', 'POST'])
def confirm():
    """Bevestigingspagina met data overzicht."""
    if 'current_row' not in session:
        flash('Geen data om te bevestigen', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        # Sla op in Excel
        try:
            current_data = session['current_row']
            
            # Check of we een bestaande rij bewerken
            if 'edit_row_id' in current_data:
                # Bewerk bestaande rij
                edit_row_id = current_data.pop('edit_row_id')  # Verwijder uit data
                df = get_excel_data()
                
                if edit_row_id < len(df):
                    # Map data naar Excel kolommen
                    excel_data = map_data_to_excel_columns(current_data)
                    
                    # Update de rij
                    for col, value in excel_data.items():
                        df.at[edit_row_id, col] = value
                    
                    # Sla op
                    df.to_excel(OUTPUT_EXCEL, index=False)
                    flash('Product bijgewerkt!', 'success')
                else:
                    flash('Product niet gevonden voor bewerking', 'error')
            else:
                # Voeg nieuwe rij toe
                append_to_excel(current_data)
                flash('Product opgeslagen in Excel!', 'success')
            
            # Clear session
            session.pop('current_row', None)
            
            return redirect(url_for('rows'))
        except Exception as e:
            flash(f'Opslaan fout: {str(e)}', 'error')
    
    # GET: toon data overzicht
    return render_template('confirm.html', data=session['current_row'])


@app.route('/rows')
def rows():
    """Overzicht van alle opgeslagen rijen."""
    try:
        df = get_excel_data()
        # Converteer naar dict lijst voor template
        rows_data = df.to_dict('records')
        return render_template('rows.html', rows=rows_data)
    except Exception as e:
        flash(f'Fout bij laden data: {str(e)}', 'error')
        return redirect(url_for('index'))


@app.route('/export')
def export():
    """Download Excel bestand."""
    try:
        # Lees Excel data met opgeslagen producten
        df = get_excel_data()
        
        # Maak in-memory stream
        output = io.BytesIO()
        df.to_excel(output, index=False, engine='openpyxl')
        output.seek(0)
        
        return send_file(
            output,
            as_attachment=True,
            download_name='Export_generic_template_20251004_07 PM052.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        flash(f'Export fout: {str(e)}', 'error')
        return redirect(url_for('index'))


@app.route('/images/products/<filename>')
def serve_product_image(filename):
    """Serveer product afbeeldingen met juiste headers voor bol.com."""
    try:
        return send_from_directory(
            'static/images/products',
            filename,
            mimetype='image/jpeg',
            as_attachment=False
        )
    except Exception as e:
        print(f"Fout bij serveren van afbeelding {filename}: {e}")
        return "Afbeelding niet gevonden", 404


@app.route('/edit_row/<int:row_id>', methods=['POST'])
def edit_row(row_id):
    """Bewerk een bestaande rij."""
    try:
        df = get_excel_data()
        
        if row_id >= len(df):
            flash('Product niet gevonden', 'error')
            return redirect(url_for('rows'))
        
        # Haal de rij op en converteer naar onze interne data structuur
        row_data = df.iloc[row_id].to_dict()
        
        # Map Excel kolommen terug naar interne velden
        internal_data = {
            'source_url': '',  # We hebben geen source_url in Excel
            'title': row_data.get('Productnaam', ''),
            'brand': '',  # We hebben geen brand in Excel
            'list_price_value': row_data.get('Prijs', None),
            'ean': row_data.get('EAN', ''),
            'description': row_data.get('Beschrijving', ''),
            'main_image': row_data.get('Hoofdafbeelding', ''),
            'all_images': row_data.get('Additionele afbeeldingen', ''),
            'condition': row_data.get('Conditie', 'Nieuw'),
            'condition_comment': row_data.get('Conditie commentaar', ''),
            'internal_reference': row_data.get('Interne referentie', ''),
            'stock': row_data.get('Voorraad', 69),
            'delivery_time': row_data.get('Levertijd', ''),
            'delivery_method': row_data.get('Afleverwijze', ''),
            'for_sale': row_data.get('Te koop', 'ja'),
            'marketplace_participant': row_data.get('Marktdeelnemer', ''),
            'edit_row_id': row_id  # Onthoud welke rij we bewerken
        }
        
        # Zet in session
        session['current_row'] = internal_data
        
        return redirect(url_for('edit'))
        
    except Exception as e:
        flash(f'Fout bij laden product: {str(e)}', 'error')
        return redirect(url_for('rows'))


@app.route('/delete_row/<int:row_id>', methods=['POST'])
def delete_row(row_id):
    """Verwijder een rij uit het Excel bestand."""
    try:
        df = get_excel_data()
        
        if row_id >= len(df):
            flash('Product niet gevonden', 'error')
            return redirect(url_for('rows'))
        
        # Verwijder de rij
        df_updated = df.drop(df.index[row_id]).reset_index(drop=True)
        
        # Sla op
        df_updated.to_excel(OUTPUT_EXCEL, index=False)
        
        flash('Product verwijderd!', 'success')
        return redirect(url_for('rows'))
        
    except Exception as e:
        flash(f'Fout bij verwijderen: {str(e)}', 'error')
        return redirect(url_for('rows'))


if __name__ == '__main__':
    # Zorg dat de output directory bestaat
    os.makedirs(os.path.dirname(OUTPUT_EXCEL), exist_ok=True)
    os.makedirs('static/images/products', exist_ok=True)
    
    # Zorg dat het Excel template bestaat
    ensure_excel_exists()
    
    # Docker-friendly configuratie
    debug_mode = os.getenv('FLASK_ENV', 'development') == 'development'
    host = '0.0.0.0'  # Accepteer verbindingen van alle interfaces (Docker)
    port = int(os.getenv('PORT', 5000))
    
    print(f"🚀 Starting Bol.com Scraper on {host}:{port}")
    print(f"📁 Excel output: {OUTPUT_EXCEL}")
    print(f"🖼️  Image base URL: {IMAGE_BASE_URL}")
    print(f"🔧 Debug mode: {debug_mode}")
    print(f"🌐 Headless browser: {HEADLESS}")
    
    app.run(debug=debug_mode, host=host, port=port)
