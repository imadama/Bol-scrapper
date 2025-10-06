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
OUTPUT_EXCEL = os.getenv('OUTPUT_EXCEL', 'scraped_products.xlsx')

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
    elif not os.path.exists(OUTPUT_EXCEL):
        # Als template niet bestaat, maak leeg Excel bestand met juiste kolommen
        df_empty = pd.DataFrame(columns=EXCEL_COLUMNS)
        df_empty.to_excel(OUTPUT_EXCEL, index=False)


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
        'Te koop': data.get('for_sale', 'Ja'),
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
        
        # Voeg standaard waarden toe voor nieuwe velden
        product_data['condition'] = 'Nieuw'
        product_data['condition_comment'] = ''
        product_data['internal_reference'] = ''
        product_data['stock'] = 69
        product_data['delivery_time'] = ''
        product_data['delivery_method'] = ''
        product_data['for_sale'] = 'Ja'
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
            download_name='scraped_products.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        flash(f'Export fout: {str(e)}', 'error')
        return redirect(url_for('index'))


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
            'for_sale': row_data.get('Te koop', 'Ja'),
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
    # Zorg dat Excel bestand bestaat bij startup
    ensure_excel_exists()
    
    app.run(debug=True, host='127.0.0.1', port=5000)