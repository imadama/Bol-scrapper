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

# Excel kolomvolgorde (exact zoals gespecificeerd)
EXCEL_COLUMNS = [
    'source_url',
    'title', 
    'brand',
    'price_text',
    'price_value',
    'list_price_text',
    'list_price_value',
    'ean',
    'description',
    'main_image',
    'all_images'
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
    if not os.path.exists(OUTPUT_EXCEL):
        # Maak lege DataFrame met juiste kolommen
        df = pd.DataFrame(columns=EXCEL_COLUMNS)
        df.to_excel(OUTPUT_EXCEL, index=False)


def append_to_excel(data: Dict[str, Any]) -> None:
    """Append data naar Excel bestand."""
    ensure_excel_exists()
    
    # Maak DataFrame van data
    df_new = pd.DataFrame([data])
    
    # Lees bestaande data
    df_existing = pd.read_excel(OUTPUT_EXCEL)
    
    # Combineer en schrijf terug
    df_combined = pd.concat([df_existing, df_new], ignore_index=True)
    df_combined.to_excel(OUTPUT_EXCEL, index=False)


def get_excel_data() -> pd.DataFrame:
    """Lees alle data uit Excel bestand."""
    if not os.path.exists(OUTPUT_EXCEL):
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
        
        for field in EXCEL_COLUMNS:
            if field in request.form:
                value = request.form[field].strip()
                
                # Speciale behandeling voor numerieke velden
                if field in ['price_value', 'list_price_value']:
                    try:
                        current_data[field] = float(value) if value else None
                    except ValueError:
                        current_data[field] = None
                else:
                    current_data[field] = value
        
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
            append_to_excel(session['current_row'])
            flash('Product opgeslagen in Excel!', 'success')
            
            # Clear session
            session.pop('current_row', None)
            
            return redirect(url_for('index'))
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
        # Lees Excel data
        df = get_excel_data()
        
        # Maak in-memory stream
        output = io.BytesIO()
        df.to_excel(output, index=False, engine='openpyxl')
        output.seek(0)
        
        return send_file(
            output,
            as_attachment=True,
            download_name=OUTPUT_EXCEL,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        flash(f'Export fout: {str(e)}', 'error')
        return redirect(url_for('index'))


if __name__ == '__main__':
    # Zorg dat Excel bestand bestaat bij startup
    ensure_excel_exists()
    
    app.run(debug=True, host='127.0.0.1', port=5000)
