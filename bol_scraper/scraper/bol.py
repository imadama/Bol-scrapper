"""
Bol.com scraper module
"""
import re
import time
from typing import List, Optional, Tuple, Dict, Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Browser, Page


def text(selectors: List[str], soup: BeautifulSoup) -> str:
    """Zoek eerste match uit lijst van selectors en return gestripte tekst."""
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            return element.get_text(strip=True)
    return ""


def to_float_price(s: str) -> Optional[float]:
    """Converteer prijs string naar float (komma als decimaal)."""
    if not s:
        return None
    
    # Verwijder alles behalve cijfers, komma's en punten
    cleaned = re.sub(r'[^\d,.]', '', s)
    if not cleaned:
        return None
    
    # Vervang komma door punt voor float conversie
    cleaned = cleaned.replace(',', '.')
    
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_price_parts(soup: BeautifulSoup) -> Tuple[str, Optional[float]]:
    """Extraheer actuele verkoopprijs als tekst en float."""
    # Primair: integer + fractie
    integer_selector = 'span.promo-price[data-test="price"]'
    fraction_selector = 'sup.promo-price__fraction[data-test="price-fraction"]'
    
    integer_elem = soup.select_one(integer_selector)
    fraction_elem = soup.select_one(fraction_selector)
    
    if integer_elem and fraction_elem:
        price_text = f"{integer_elem.get_text(strip=True)},{fraction_elem.get_text(strip=True)}"
        price_value = to_float_price(price_text)
        return price_text, price_value
    
    # Fallbacks
    fallback_selectors = [
        'div[data-test="priceBlockPrice"] [data-test="price"]',
        'meta[property="product:price:amount"]',
        '[data-test="price"]'
    ]
    
    for selector in fallback_selectors:
        element = soup.select_one(selector)
        if element:
            if element.name == 'meta':
                price_text = element.get('content', '')
            else:
                price_text = element.get_text(strip=True)
            
            if price_text:
                price_value = to_float_price(price_text)
                return price_text, price_value
    
    return "", None


def extract_list_price(soup: BeautifulSoup) -> Tuple[str, Optional[float]]:
    """Extraheer adviesprijs/doorgestreepte prijs."""
    selectors = [
        'del.buy-block__list-price[data-test="list-price"]',
        'span[data-test="list-price"]',
        'div[data-test="buy-block"] del'
    ]
    
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            price_text = element.get_text(strip=True)
            if price_text:
                price_value = to_float_price(price_text)
                return price_text, price_value
    
    return "", None


def extract_brand(soup: BeautifulSoup) -> str:
    """Extraheer merk."""
    # Primair: div[data-test="brand"] a
    brand_link = soup.select_one('div[data-test="brand"] a')
    if brand_link:
        return brand_link.get_text(strip=True)
    
    # Fallback: div[data-test="brand"] (strip "Merk:")
    brand_div = soup.select_one('div[data-test="brand"]')
    if brand_div:
        brand_text = brand_div.get_text(strip=True)
        # Verwijder "Merk:" prefix als aanwezig
        if brand_text.startswith('Merk:'):
            brand_text = brand_text[5:].strip()
        return brand_text
    
    return ""


def extract_ean(soup: BeautifulSoup) -> str:
    """Extraheer EAN code."""
    # Primair: dt.specs__title met "EAN" -> dd erna
    ean_dt = soup.find('dt', class_='specs__title', string=re.compile(r'EAN', re.I))
    if ean_dt:
        ean_dd = ean_dt.find_next_sibling('dd')
        if ean_dd:
            ean_text = ean_dd.get_text(strip=True)
            # Alleen cijfers behouden
            ean_digits = re.sub(r'\D', '', ean_text)
            return ean_digits
    
    # Fallback: table tr -> th == "EAN" -> td
    ean_th = soup.find('th', string=re.compile(r'EAN', re.I))
    if ean_th:
        ean_td = ean_th.find_next_sibling('td')
        if ean_td:
            ean_text = ean_td.get_text(strip=True)
            ean_digits = re.sub(r'\D', '', ean_text)
            return ean_digits
    
    return ""


def extract_description(soup: BeautifulSoup) -> str:
    """Extraheer productbeschrijving."""
    selectors = [
        'div[data-test="description"].product-description',
        '[data-test="description"]',
        'section#productDescription'
    ]
    
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            return element.get_text(strip=True)
    
    return ""


def extract_gallery_images(soup: BeautifulSoup) -> List[str]:
    """Extraheer galerijafbeeldingen (max 20, dedupe)."""
    images = []
    
    # Primair: .filmstrip-viewport img
    filmstrip_imgs = soup.select('.filmstrip-viewport img')
    for img in filmstrip_imgs:
        src = img.get('src') or img.get('data-src')
        if src and 'bol.com' in src and 'media' in src:
            images.append(src)
    
    # Fallback: alle img waar URL bol.com + media bevat
    if not images:
        all_imgs = soup.find_all('img')
        for img in all_imgs:
            src = img.get('src') or img.get('data-src')
            if src and 'bol.com' in src and 'media' in src:
                images.append(src)
    
    # Dedupe en limiet
    unique_images = list(dict.fromkeys(images))[:20]
    return unique_images


def scrape_bol_product(url: str, headless: bool = True) -> Dict[str, Any]:
    """
    Scrape bol.com product pagina.
    
    Args:
        url: Bol.com product URL
        headless: Of browser headless moet draaien
        
    Returns:
        Dict met productdata
    """
    # Valideer URL
    parsed = urlparse(url)
    if not parsed.netloc or 'bol.com' not in parsed.netloc:
        raise ValueError("URL moet van bol.com zijn")
    
    with sync_playwright() as p:
        browser: Browser = p.chromium.launch(headless=headless)
        page: Page = browser.new_page()
        
        try:
            # Ga naar pagina
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(2)  # Korte sleep voor dynamiek
            
            # HTML ophalen en parsen
            html = page.content()
            soup = BeautifulSoup(html, 'lxml')
            
            # Extraheer alle data
            title = text([
                'span[data-test="title"]',
                'h1[data-test="product-title"]',
                'h1',
                'meta[property="og:title"]'
            ], soup)
            
            # Als meta tag, gebruik content attribute
            if not title:
                meta_title = soup.select_one('meta[property="og:title"]')
                if meta_title:
                    title = meta_title.get('content', '')
            
            price_text, price_value = extract_price_parts(soup)
            list_price_text, list_price_value = extract_list_price(soup)
            brand = extract_brand(soup)
            ean = extract_ean(soup)
            description = extract_description(soup)
            gallery_images = extract_gallery_images(soup)
            
            # Main image is eerste uit galerij
            main_image = gallery_images[0] if gallery_images else ""
            all_images = "|".join(gallery_images)
            
            return {
                "source_url": url,
                "title": title,
                "brand": brand,
                "price_text": price_text,
                "price_value": price_value,
                "list_price_text": list_price_text,
                "list_price_value": list_price_value,
                "ean": ean,
                "description": description,
                "main_image": main_image,
                "all_images": all_images
            }
            
        finally:
            browser.close()
