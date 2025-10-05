#!/bin/bash
set -e

echo "🚀 Starting Bol.com Scraper..."

# Wacht tot alle services klaar zijn
echo "⏳ Waiting for services to be ready..."

# Controleer of Playwright browsers geïnstalleerd zijn
if [ ! -d "/root/.cache/ms-playwright" ]; then
    echo "📦 Installing Playwright browsers..."
    python -m playwright install chromium
    python -m playwright install-deps chromium
fi

# Maak directories aan als ze niet bestaan
mkdir -p static/images/products
mkdir -p bol_scraper

# Controleer of Excel template bestaat
if [ ! -f "bol_scraper/Export_generic_template_20251004_07 PM052.xlsx" ]; then
    echo "⚠️  Excel template not found, creating empty one..."
    python -c "
import pandas as pd
import os
os.makedirs('bol_scraper', exist_ok=True)
df = pd.DataFrame(columns=[
    'Productnaam', 'Beschrijving', 'Interne referentie', 'EAN', 'Conditie', 
    'Conditie commentaar', 'Voorraad', 'Prijs', 'Levertijd', 'Afleverwijze', 
    'Te koop', 'Hoofdafbeelding', 'Marktdeelnemer', 'Additionele afbeeldingen'
])
df.to_excel('bol_scraper/Export_generic_template_20251004_07 PM052.xlsx', index=False)
print('✅ Excel template created')
"
fi

# Start de applicatie
echo "🎯 Starting Flask application..."
exec "$@"
