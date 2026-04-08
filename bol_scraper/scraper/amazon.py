"""
Amazon scraper module
"""
import re
import time
from typing import List, Optional, Tuple, Dict, Any
from urllib.parse import urlparse, quote

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Browser, Page


def text(selectors: List[str], soup: BeautifulSoup) -> str:
    """Zoek eerste match uit lijst van selectors en return gestripte tekst."""
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            return element.get_text(strip=True)
    return ""


def clean_image_url(url: str) -> Optional[str]:
    """Schoon afbeeldings-URL op voor Bol.com eisen."""
    if not url:
        return None
        
    # Zoek naar .jpg, .jpeg, of .png en negeer alles erachter (zoals ? parameters)
    match = re.search(r'(.*?\.((?:jpg)|(?:jpeg)|(?:png)))(?:[?#].*)?$', url, re.IGNORECASE)
    if not match:
        return None
        
    clean_url = match.group(1)
    # Vervang spaties door %20
    clean_url = quote(clean_url, safe=':/_%?&=')
    return clean_url


def to_float_price(s: str) -> Optional[float]:
    """Converteer prijs string naar float."""
    if not s:
        return None
    
    # Verwijder valuta symbolen en tekst, houd cijfers, komma en punt over
    # Amazon NL gebruikt komma als decimaal, EN als duizendtal separator soms, maar meestal punt voor duizend?
    # NL locale: 1.234,56
    # Amazon NL: doorgaans "12,99" of "1.234,00"
    
    cleaned = re.sub(r'[^\d,.]', '', s)
    if not cleaned:
        return None

    # Als er zowel punten als komma's zijn:
    # punt is duizendtal, komma is decimaal (NL)
    if '.' in cleaned and ',' in cleaned:
        cleaned = cleaned.replace('.', '') # verwijder duizendtallen
        cleaned = cleaned.replace(',', '.') # maak decimaal punt
    elif ',' in cleaned:
        # Alleen komma: waarschijnlijk decimaal
        cleaned = cleaned.replace(',', '.')
    
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_price(soup: BeautifulSoup) -> Tuple[str, Optional[float]]:
    """Extraheer actuele verkoopprijs."""
    # Amazon prijs structuur: .a-price > .a-offscreen (tekst)
    selectors = [
        'span.a-price span.a-offscreen',
        'span.a-price-whole', # Alleen hele getallen
        '#priceblock_ourprice',
        '#priceblock_dealprice',
        '.header-price'
    ]
    
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            price_text = element.get_text(strip=True)
            # Als we .a-price-whole pakken, moeten we kijken of fraction er is
            if selector == 'span.a-price-whole':
                fraction = soup.select_one('span.a-price-fraction')
                if fraction:
                    price_text = f"{price_text},{fraction.get_text(strip=True)}"
            
            val = to_float_price(price_text)
            if val is not None:
                return price_text, val
                
    return "", None


def extract_list_price(soup: BeautifulSoup) -> Tuple[str, Optional[float]]:
    """Extraheer adviesprijs (doorgestreept)."""
    selectors = [
        'span.a-text-price span.a-offscreen',
        'span[data-a-strike="true"]',
        '#priceblock_listprice'
    ]
    
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            price_text = element.get_text(strip=True)
            val = to_float_price(price_text)
            if val is not None:
                return price_text, val
    return "", None


def extract_brand(soup: BeautifulSoup) -> str:
    """Extraheer merk."""
    selectors = [
        '#bylineInfo',
        'a#brand',
        '#productOverview_feature_div tr.a-spacing-small:has(span:contains("Merk")) td:last-child span',
        '#productOverview_feature_div tr.a-spacing-small:has(span:contains("Brand")) td:last-child span'
    ]
    
    val = text(selectors, soup)
    if val:
        # Soms staat er "Bezoek de X-store" of "Merk: X"
        val = val.replace('Bezoek de ', '').replace('-store', '').replace('Merk:', '').strip()
        return val
    return ""


def extract_details(soup: BeautifulSoup) -> str:
    """Extraheer details/specs als tekst blob."""
    # Amazon table specs
    specs = []
    
    # Product details table
    tables = soup.select('#productDetails_techSpec_section_1, #productDetails_feature_div table, .a-keyvalue')
    for table in tables:
        rows = table.select('tr')
        for row in rows:
            th = row.select_one('th')
            td = row.select_one('td')
            if th and td:
                key = th.get_text(strip=True)
                val = td.get_text(strip=True)
                specs.append(f"{key}: {val}")
                
    # Bullet points (features)
    bullets = soup.select('#feature-bullets li span.a-list-item')
    if bullets:
        specs.append("\nKenmerken:")
        for b in bullets:
            t = b.get_text(strip=True)
            if t:
                specs.append(f"- {t}")

    return "\n".join(specs)


def extract_ean(soup: BeautifulSoup) -> str:
    """Probeer EAN te vinden (lastig op Amazon, soms ASIN)."""
    # Zoek in tables naar "EAN" of "Item model number" als fallback
    text_content = soup.get_text()
    # Soms staat het expliciet in specs
    # We proberen gewoon te zoeken in de details blob die we net maakten of rauwe HTML zoeken
    
    # Specifieke tabel cel check
    # Vaak heet het 'Itemmodelnummer' of 'Modelnummer item'
    
    return "" # Amazon toont zelden EAN publiekelijk, meestal ASIN.


def extract_asin(soup: BeautifulSoup, url: str) -> str:
    """Extraheer ASIN van URL of pagina."""
    # 1. Probeer URL regex
    match = re.search(r'/(?:dp|gp/product)/(B[0-9A-Z]{9})', url)
    if match:
        return match.group(1)
        
    # 2. Hidden input
    asin_input = soup.select_one('input[name="ASIN"], #ASIN')
    if asin_input:
        val = asin_input.get('value')
        if val:
            return val
            
    # 3. Details tabel search
    # Soms staat "ASIN" in de details tabel
    tables = soup.select('#productDetails_techSpec_section_1 tr, #prodDetails tr')
    for tr in tables:
        th = tr.select_one('th')
        if th and 'ASIN' in th.get_text(strip=True):
            td = tr.select_one('td')
            if td:
                return td.get_text(strip=True)
                
    return ""


def extract_images(soup: BeautifulSoup) -> List[str]:
    """Extraheer afbeeldingen."""
    images = []
    
    # Hoofdafbeelding
    main = soup.select_one('#landingImage, #imgBlkFront')
    if main:
        src = main.get('data-old-hires') or main.get('data-a-dynamic-image') or main.get('src')
        if src:
            # data-a-dynamic-image is een JSON dict string, maar soms gewoon URL als key?
            # Simpelst: pak src, vaak goed genoeg large variant
            if src.startswith('{'):
                # Het is de JSON map, pak de grootste (laatste key/value?)
                # Dit is wat complexer parsing, laten we 'data-old-hires' proberen
                pass
            else:
               cleaned = clean_image_url(src)
               if cleaned:
                   images.append(cleaned)
    
    # Alt images (thumbnails klikken zou moeten in browser, maar in HTML staan ze soms in script blocks)
    # We kijken naar .a-button-text img
    
    thumb_reviews = soup.select('#altImages li.item img')
    for img in thumb_reviews:
        src = img.get('src')
        if src:
            # Convert thumb to high res: m.media-amazon.com/images/I/xxxx._AC_US40_.jpg -> ._AC_SL1500_.jpg
            # Of verwijder de resize suffix
            # Voorbeeld: .../I/71s+..._AC_SY606_.jpg
            base = re.split(r'\._AC_.*_\.', src)[0]
            if base != src:
                # Gok extentie jpg
                hi_res = f"{base}.jpg"
                cleaned = clean_image_url(hi_res)
                if cleaned:
                    images.append(cleaned)
            else:
                cleaned = clean_image_url(src)
                if cleaned:
                    images.append(cleaned)
                
    return list(dict.fromkeys(images))[:20]


def scrape_amazon_product(url: str, headless: bool = True) -> Dict[str, Any]:
    """
    Scrape Amazon product pagina.
    """
    parsed = urlparse(url)
    if 'amazon' not in (parsed.netloc or ''):
        raise ValueError("URL moet van amazon zijn")
    
    with sync_playwright() as p:
        browser: Browser = p.webkit.launch(headless=headless)
        # Gebruik context met specifieke user agent om detectie te verminderen
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
            viewport={'width': 1280, 'height': 800}
        )
        page: Page = context.new_page()
        
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # Wacht even, misschien cookie popup?
            # Amazon heeft vaak geen cookie popup die blokkeert, wel captchas
            # Checken op captcha kan, maar voor nu hopen we op het beste.
            
            time.sleep(2)
            
            html = page.content()
            soup = BeautifulSoup(html, 'lxml')
            
            # Check captcha
            if "Type the characters you see in this image" in html:
                raise Exception("Amazon Captcha gedetecteerd. Probeer later opnieuw of gebruik een proxy/andere user-agent.")

            title = text(['#productTitle', '#title'], soup)
            price_text, price_value = extract_price(soup)
            list_price_text, list_price_value = extract_list_price(soup)
            brand = extract_brand(soup)
            description = extract_details(soup) # We gebruiken de details/bullets als description
            # Amazon heeft ook #productDescription
            desc_text = text(['#productDescription'], soup)
            if desc_text:
                description = desc_text + "\n\n" + description
            
            asin = extract_asin(soup, url)
            
            images = extract_images(soup)
            main_image = images[0] if images else ""
            all_images = "\n".join(images)
            
            return {
                "source_url": url,
                "title": title,
                "brand": brand,
                "price_text": price_text,
                "price_value": price_value,
                "list_price_text": list_price_text,
                "list_price_value": list_price_value, # Gebruik list price als 'old' price
                "ean": "", 
                "asin": asin,
                "description": description,
                "main_image": main_image,
                "all_images": all_images
            }
            
        finally:
            browser.close()
