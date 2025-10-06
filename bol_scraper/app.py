"""
Flask app voor Bol.com scraper
"""
import os
import io
from typing import Dict, Any, Optional
from urllib.parse import urlparse

import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from dotenv import load_dotenv

from scraper.bol import scrape_bol_product

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')

# Configuratie
HEADLESS = os.getenv('HEADLESS', 'true').lower() == 'true'
OUTPUT_EXCEL = os.getenv('OUTPUT_EXCEL', 'Export_generic_template_20251004_07 PM052.xlsx')

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
        
        # Voeg standaard waarden toe voor nieuwe velden
        product_data['condition'] = 'nieuw'
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
            # Check of we een bestaande rij bewerken
            if 'editing_row_index' in session:
                # Update bestaande rij
                update_excel_row(session['editing_row_index'], session['current_row'])
                flash('Product bijgewerkt!', 'success')
                session.pop('editing_row_index', None)
                return redirect(url_for('rows'))
            else:
                # Nieuwe rij toevoegen
                append_to_excel(session['current_row'])
                flash('Product opgeslagen in Excel!', 'success')
                return redirect(url_for('index'))
            
            # Clear session
            session.pop('current_row', None)
            
        except Exception as e:
            flash(f'Opslaan fout: {str(e)}', 'error')
    
    # GET: toon data overzicht
    return render_template('confirm.html', data=session['current_row'])


@app.route('/rows')
def rows():
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
        return redirect(url_for('index'))


@app.route('/edit_row/<int:row_index>')
def edit_row(row_index):
    """Bewerk een bestaande rij."""
    try:
        df = get_excel_data()
        
        if row_index >= len(df):
            flash('Rij niet gevonden', 'error')
            return redirect(url_for('rows'))
        
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
            'main_image': row_data.get('Hoofdafbeelding', ''),
            'marketplace_participant': row_data.get('Marktdeelnemer', ''),
            'all_images': row_data.get('Additionele afbeeldingen', '')
        }
        
        # Zet in session met row index voor update
        session['current_row'] = internal_data
        session['editing_row_index'] = row_index
        
        return redirect(url_for('edit'))
        
    except Exception as e:
        flash(f'Fout bij laden rij: {str(e)}', 'error')
        return redirect(url_for('rows'))


@app.route('/delete_row/<int:row_index>')
def delete_row(row_index):
    """Verwijder een rij."""
    try:
        df = get_excel_data()
        
        if row_index >= len(df):
            flash('Rij niet gevonden', 'error')
            return redirect(url_for('rows'))
        
        # Verwijder de rij
        df = df.drop(df.index[row_index])
        
        # Schrijf terug naar Excel
        df.to_excel(OUTPUT_EXCEL, index=False)
        
        flash('Product verwijderd!', 'success')
        return redirect(url_for('rows'))
        
    except Exception as e:
        flash(f'Fout bij verwijderen: {str(e)}', 'error')
        return redirect(url_for('rows'))


@app.route('/export')
def export():
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
        return redirect(url_for('index'))


if __name__ == '__main__':
    # Zorg dat Excel bestand bestaat bij startup
    ensure_excel_exists()
    
    app.run(debug=True, host='127.0.0.1', port=5000)
