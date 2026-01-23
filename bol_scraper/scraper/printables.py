"""
Printables.com scraper module
"""
import re
import time
from typing import Dict, Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Browser, Page


def scrape_printables_product(url: str, headless: bool = True) -> Dict[str, Any]:
    """
    Scrape printables.com model pagina.
    
    Args:
        url: Printables.com model URL
        headless: Of browser headless moet draaien
        
    Returns:
        Dict met productdata
    """
    # Valideer URL
    parsed = urlparse(url)
    if not parsed.netloc or 'printables.com' not in parsed.netloc:
        raise ValueError("URL moet van printables.com zijn")
    
    with sync_playwright() as p:
        browser: Browser = p.webkit.launch(headless=headless)
        page: Page = browser.new_page()
        
        try:
            # Ga naar pagina
            page.goto(url, wait_until="networkidle", timeout=60000)
            
            # Wacht even op dynamische content (Svelte)
            # Wacht specifiek op de titel of gallery
            try:
                page.wait_for_selector('h1', state='visible', timeout=10000)
                # Scroll beetje om lazy loading te triggeren
                page.evaluate("window.scrollTo(0, 500)")
                time.sleep(2)
            except Exception:
                pass
            
            # HTML ophalen en parsen
            html = page.content()
            soup = BeautifulSoup(html, 'lxml')
            
            # 1. Title (H1)
            title_elem = soup.select_one('h1')
            title = title_elem.get_text(strip=True) if title_elem else ""
            
            # 2. Description (.user-inserted)
            desc_elem = soup.select_one('.user-inserted')
            # Behoud wat formatting indien mogelijk door text met spaces te pakken,
            # maar voor Excel is platte tekst vaak beter.
            description = desc_elem.get_text("\n", strip=True) if desc_elem else ""
            
            # 3. Main Image
            # Selector: #splide02-list .is-active img
            # Fallback: eerste img in #splide02-list if active niet gevonden
            main_image = ""
            main_img_elem = soup.select_one('#splide02-list .is-active img')
            if main_img_elem:
                main_image = main_img_elem.get('src', '')
            
            if not main_image:
                 # Probeer eerste van de lijst
                 first_img = soup.select_one('#splide02-list li img')
                 if first_img:
                     main_image = first_img.get('src', '')

            # 4. Gallery Images
            # Selector: #splide01-list img (thumbnails slider onderaan)
            # Of #splide02-list img (grote slider) -> beter om die te pakken want hogere res?
            # De thumbnails slider (#splide01) heeft vaak kleinere versies, maar soms ook de full res src.
            # Laten we de grote slider (#splide02) proberen te pakken voor alle images.
            gallery_images = []
            slider_imgs = soup.select('#splide02-list img')
            for img in slider_imgs:
                src = img.get('src', '')
                if src:
                    gallery_images.append(src)
            
            # Dedupe
            unique_images = list(dict.fromkeys(gallery_images))
            
            # Zorg dat main image ook in de lijst zit (of juist niet, afhankelijk van wens)
            # In Bol scraper is main_image apart, en all_images is de lijst.
            all_images = "|".join(unique_images)
            
            # Als we nog steeds geen main image hebben, pak de eerste van unique
            if not main_image and unique_images:
                main_image = unique_images[0]

            return {
                "source_url": url,
                "title": title,
                "description": description,
                "main_image": main_image,
                "all_images": all_images,
                # Default velden voor compatibiliteit met Excel template
                "brand": "", # Creator?
                "price_text": "Gratis",
                "price_value": 0.0,
                "ean": "",
                "list_price_value": None,
                "stock": 999,
                "condition": "nieuw",
                "condition_comment": "3D Model",
                "delivery_time": "Direct",
                "delivery_method": "Download",
                "for_sale": "nee", # Het is een download
                "marketplace_participant": "Printables"
            }
            
        finally:
            browser.close()
