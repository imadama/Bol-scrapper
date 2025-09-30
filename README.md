# 🛒 Bol.com Scraper

Een productie-klare mini-app waarmee je bol.com productpagina's kunt scrapen, data kunt bewerken in een UI en kunt exporteren naar Excel.

## ✨ Features

- **Scrapen**: Automatisch extraheren van productdata van bol.com
- **UI Bewerking**: Handmatig bewerken van gescrapete data
- **Excel Export**: Opslaan en exporteren naar .xlsx bestanden
- **Robuust**: Selectors met fallbacks en nette error handling
- **Modern UI**: Clean en responsive interface

## 📊 Gescrapete Data

De scraper extraheert de volgende productinformatie:

- **Titel** - Productnaam
- **Prijs** - Actuele verkoopprijs (tekst + numerieke waarde)
- **Adviesprijs** - Doorgestreepte prijs (indien aanwezig)
- **Merk** - Productmerk
- **EAN** - Productcode
- **Beschrijving** - Productbeschrijving
- **Afbeeldingen** - Hoofdafbeelding + galerij (max 20)

## 🚀 Quickstart

### 1. Installatie

```bash
# Clone repository
git clone <repository-url>
cd Bol-scrapper

# Maak virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# of
venv\\Scripts\\activate  # Windows

# Installeer dependencies
pip install -r requirements.txt

# Installeer Playwright browsers
python -m playwright install
```

### 2. Configuratie

```bash
# Kopieer environment template
cp .env.example .env

# Bewerk .env bestand (optioneel)
nano .env
```

### 3. Starten

```bash
cd bol_scraper
python app.py
```

De app is nu beschikbaar op: http://127.0.0.1:5000

## ⚙️ Configuratie

### Environment Variabelen (.env)

```env
# Verplicht
FLASK_SECRET_KEY=changeme                    # Flask secret key
HEADLESS=true                               # Browser headless mode
OUTPUT_EXCEL=scraped_products.xlsx         # Excel bestandsnaam

# Optioneel
HTTP_PROXY=http://user:pass@host:port      # HTTP proxy
HTTPS_PROXY=http://user:pass@host:port     # HTTPS proxy
```

### Excel Kolomvolgorde

De data wordt opgeslagen in exact deze volgorde:

1. `source_url` - Bron URL
2. `title` - Producttitel
3. `brand` - Merk
4. `price_text` - Prijs als tekst (bijv. "64,74")
5. `price_value` - Prijs als float (bijv. 64.74)
6. `list_price_text` - Adviesprijs als tekst
7. `list_price_value` - Adviesprijs als float
8. `ean` - EAN code
9. `description` - Beschrijving
10. `main_image` - Hoofdafbeelding URL
11. `all_images` - Alle afbeeldingen (gescheiden door |)

## 🎯 Gebruik

### 1. Product Scrapen

1. Ga naar http://127.0.0.1:5000
2. Plak een bol.com product-URL in het invoerveld
3. Klik op "🔍 Scrape Product"
4. Wacht 2-5 seconden voor het resultaat

### 2. Data Bewerken

1. Na scrapen wordt je doorgestuurd naar het bewerkingsscherm
2. Controleer en pas alle velden aan indien nodig
3. Klik op "Bevestigen →"

### 3. Opslaan

1. Controleer de data in het bevestigingsscherm
2. Klik op "💾 Opslaan in Excel"
3. Data wordt toegevoegd aan het Excel bestand

### 4. Overzicht & Export

- **Bekijk Opgeslagen**: Overzicht van alle opgeslagen producten
- **Exporteer Excel**: Download het complete Excel bestand

## 🔧 Technische Details

### Stack

- **Python 3.11+**
- **Flask** - Web framework
- **Playwright** - Browser automation (Chromium)
- **BeautifulSoup4 + lxml** - HTML parsing
- **pandas + openpyxl** - Excel handling
- **python-dotenv** - Environment configuratie

### Scraper Selectors

De scraper gebruikt robuuste selectors met fallbacks:

#### Titel
- Primair: `span[data-test="title"]`
- Fallbacks: `h1[data-test="product-title"]`, `h1`, `meta[property="og:title"]`

#### Prijs
- Primair: `span.promo-price[data-test="price"]` + `sup.promo-price__fraction[data-test="price-fraction"]`
- Fallbacks: `div[data-test="priceBlockPrice"] [data-test="price"]`, `meta[property="product:price:amount"]`

#### Adviesprijs
- Primair: `del.buy-block__list-price[data-test="list-price"]`
- Fallbacks: `span[data-test="list-price"]`, `div[data-test="buy-block"] del`

#### Merk
- Primair: `div[data-test="brand"] a`
- Fallback: `div[data-test="brand"]` (strip "Merk:")

#### EAN
- Primair: `dt.specs__title` met "EAN" → `dd` erna
- Fallback: `table tr` → `th == "EAN"` → `td`

#### Beschrijving
- Primair: `div[data-test="description"].product-description`
- Fallbacks: `[data-test="description"]`, `section#productDescription`

#### Afbeeldingen
- Primair: `.filmstrip-viewport img`
- Fallback: alle `img` waar URL `bol.com` + `media` bevat

## 🛡️ Error Handling

- **URL Validatie**: Controleert of URL van bol.com is
- **Scrape Fouten**: Toont nette error messages
- **Ontbrekende Velden**: Vult met lege strings/None
- **Excel Fouten**: Graceful handling van file operations

## 📁 Projectstructuur

```
bol_scraper/
├── app.py                 # Flask applicatie
├── scraper/
│   ├── __init__.py
│   └── bol.py            # Scraper implementatie
├── templates/
│   ├── index.html        # Hoofdpagina
│   ├── edit.html         # Bewerkingsscherm
│   ├── confirm.html      # Bevestigingsscherm
│   └── rows.html         # Overzichtspagina
├── static/               # (optioneel)
├── requirements.txt      # Dependencies
└── .env.example         # Environment template
```

## ⚠️ Belangrijke Opmerkingen

### Rate Limiting & Proxy

Voor productie gebruik:

- **Rate Limiting**: Voeg delays toe tussen requests
- **Proxy Support**: Gebruik HTTP_PROXY/HTTPS_PROXY environment variabelen
- **User Agent**: Overweeg custom user agents

### Juridische Aspecten

- **ToS Respect**: Respecteer bol.com's Terms of Service
- **Robots.txt**: Controleer robots.txt voor toegestane scraping
- **Officiële API**: Overweeg gebruik van bol.com's officiële API
- **Persoonlijk Gebruik**: Gebruik alleen voor persoonlijke/educatieve doeleinden

### Selector Updates

Bol.com kan hun HTML structuur wijzigen. Als scraping faalt:

1. Inspecteer de pagina handmatig
2. Update selectors in `scraper/bol.py`
3. Test met verschillende producten

## 🐛 Troubleshooting

### Playwright Installatie

```bash
# Als browsers niet geïnstalleerd zijn
python -m playwright install

# Voor specifieke browser
python -m playwright install chromium
```

### Common Issues

1. **"Browser not found"**: Run `python -m playwright install`
2. **"Timeout errors"**: Verhoog timeout in scraper of check internetverbinding
3. **"Empty data"**: Bol.com heeft mogelijk hun HTML gewijzigd
4. **"Excel errors"**: Controleer file permissions en disk space

### Debug Mode

```bash
# Start met debug logging
FLASK_DEBUG=1 python app.py
```

## 📈 Performance

- **Scrape Tijd**: 2-5 seconden per product (normale verbinding)
- **Memory**: ~50MB per browser instance
- **Concurrent**: Niet aanbevolen (rate limiting)

## 🤝 Contributing

1. Fork het project
2. Maak een feature branch
3. Commit je wijzigingen
4. Push naar de branch
5. Open een Pull Request

## 📄 License

Dit project is voor educatieve doeleinden. Respecteer bol.com's Terms of Service.

---

**Disclaimer**: Deze tool is bedoeld voor persoonlijk gebruik. Respecteer altijd de Terms of Service van websites en overweeg het gebruik van officiële APIs voor commerciële doeleinden.
