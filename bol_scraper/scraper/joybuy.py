"""
Joybuy.nl scraper module

Joybuy.nl is het Europese verkoopplatform van JD.com. De productpagina's worden
client-side gerenderd (JS framework) en achter een agressieve "risk control"
(CAPTCHA / "Veiligheidscontrole" / "Tijdelijke serviceonderbreking") gezet.

Deze scraper:
  * gebruikt Chromium met realistische headers/locale om detectie te verminderen
  * accepteert/weigert de cookie-consent banner
  * detecteert de risk/CAPTCHA pagina en geeft een duidelijke foutmelding
  * extraheert data in volgorde van betrouwbaarheid:
        1. JSON-LD (application/ld+json)
        2. OpenGraph / meta tags
        3. Embedded JS state (__NEXT_DATA__ / __NUXT__ / window globals)
        4. CSS selector fallbacks
"""
import os
import re
import json
import time
from typing import List, Optional, Tuple, Dict, Any
from urllib.parse import urlparse, quote

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Browser, Page


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def text(selectors: List[str], soup: BeautifulSoup) -> str:
    """Zoek eerste match uit lijst van selectors en return gestripte tekst."""
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            value = element.get_text(strip=True)
            if value:
                return value
    return ""


def to_float_price(s: str) -> Optional[float]:
    """Converteer prijs string naar float. Ondersteunt NL (1.234,56) en EN (1,234.56)."""
    if not s:
        return None

    cleaned = re.sub(r'[^\d,.]', '', str(s))
    if not cleaned:
        return None

    # Beide separators aanwezig: de laatste is de decimaal-separator
    if '.' in cleaned and ',' in cleaned:
        if cleaned.rfind(',') > cleaned.rfind('.'):
            # NL: punt = duizendtal, komma = decimaal
            cleaned = cleaned.replace('.', '').replace(',', '.')
        else:
            # EN: komma = duizendtal, punt = decimaal
            cleaned = cleaned.replace(',', '')
    elif ',' in cleaned:
        # Alleen komma -> decimaal
        cleaned = cleaned.replace(',', '.')

    try:
        return float(cleaned)
    except ValueError:
        return None


def clean_image_url(url: str) -> Optional[str]:
    """
    Schoon een joybuy/joy-sourcing afbeeldings-URL op naar een bol.com-compatibel
    formaat (jpg/jpeg/png, geen query parameters).

    Joybuy serveert webp varianten met een size-prefix, bijv:
        https://images3.joy-sourcing.com/product/s32x32_.../naam.png.webp
    Wij:
        * verwijderen een trailing .webp om het originele png/jpg te krijgen
        * vergroten de size-prefix (sNNxNN_) naar een grote variant
        * strippen query/fragment
    """
    if not url:
        return None

    url = url.strip()
    if url.startswith('//'):
        url = 'https:' + url

    # Strip query/fragment
    url = url.split('?', 1)[0].split('#', 1)[0]

    # Verwijder een trailing .webp (joybuy hangt deze achter .png/.jpg)
    if url.lower().endswith('.webp'):
        url = url[:-5]

    # Vergroot de thumbnail size-prefix (sWxH_) naar een grote variant
    url = re.sub(r'/s\d+x\d+_', '/s800x800_', url)

    # Moet eindigen op jpg/jpeg/png
    match = re.search(r'^(.*\.(?:jpg|jpeg|png))$', url, re.IGNORECASE)
    if not match:
        return None

    return quote(match.group(1), safe=':/_%?&=.')


def _is_risk_page(html: str, current_url: str) -> bool:
    """Detecteer JD/joybuy risk-control / CAPTCHA pagina."""
    if '/user/risk/' in (current_url or ''):
        return True
    markers = [
        'Veiligheidscontrole',
        'Tijdelijke serviceonderbreking',
        'risk_handler',
        'Klik op de afbeelding',  # CAPTCHA instructie
    ]
    return any(m in html for m in markers)


# ---------------------------------------------------------------------------
# Structured-data extractie
# ---------------------------------------------------------------------------

def _iter_jsonld(soup: BeautifulSoup):
    """Yield alle JSON-LD objecten op de pagina."""
    for tag in soup.find_all('script', type='application/ld+json'):
        raw = tag.string or tag.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if isinstance(data, list):
            for item in data:
                yield item
        elif isinstance(data, dict):
            graph = data.get('@graph')
            if isinstance(graph, list):
                for item in graph:
                    yield item
            yield data


def _extract_from_jsonld(soup: BeautifulSoup) -> Dict[str, Any]:
    """Haal product velden uit JSON-LD (schema.org/Product)."""
    out: Dict[str, Any] = {}
    for item in _iter_jsonld(soup):
        if not isinstance(item, dict):
            continue
        itype = item.get('@type', '')
        if isinstance(itype, list):
            itype = ' '.join(itype)
        if 'Product' not in str(itype):
            continue

        out['title'] = item.get('name', '') or out.get('title', '')
        out['description'] = item.get('description', '') or out.get('description', '')

        brand = item.get('brand')
        if isinstance(brand, dict):
            out['brand'] = brand.get('name', '')
        elif isinstance(brand, str):
            out['brand'] = brand

        gtin = item.get('gtin13') or item.get('gtin') or item.get('gtin14')
        if gtin:
            out['ean'] = re.sub(r'\D', '', str(gtin))

        images = item.get('image')
        if isinstance(images, str):
            out['images'] = [images]
        elif isinstance(images, list):
            out['images'] = [i for i in images if isinstance(i, str)]

        offers = item.get('offers')
        if isinstance(offers, list):
            offers = offers[0] if offers else None
        if isinstance(offers, dict):
            price = offers.get('price') or offers.get('lowPrice')
            if price is not None:
                out['price_text'] = str(price)
                out['price_value'] = to_float_price(str(price))
        break
    return out


def _extract_embedded_state(page: Page) -> Dict[str, Any]:
    """
    Probeer product data uit embedded JS state te lezen.
    Joybuy/JD hydrateren vaak vanuit een global of __NEXT_DATA__ blob.
    Best-effort: we zoeken naar herkenbare velden.
    """
    script = r"""
    () => {
        const out = {};
        const pick = (obj) => {
            if (!obj || typeof obj !== 'object') return;
            const name = obj.name || obj.skuName || obj.title || obj.wareName;
            const price = obj.price || obj.jdPrice || obj.salePrice || obj.realPrice;
            const desc = obj.description || obj.desc || obj.wareDesc;
            const brand = obj.brand || obj.brandName;
            if (name && !out.title) out.title = name;
            if (price && !out.price) out.price = price;
            if (desc && !out.description) out.description = desc;
            if (brand && !out.brand) out.brand = brand;
            const imgs = obj.images || obj.imageList || obj.imgList || obj.skuImages;
            if (Array.isArray(imgs) && imgs.length && !out.images) {
                out.images = imgs.map(x => (typeof x === 'string' ? x : (x && (x.url || x.path || x.src)))).filter(Boolean);
            }
        };
        try {
            if (window.__NEXT_DATA__) {
                const props = window.__NEXT_DATA__.props || {};
                const page = props.pageProps || {};
                pick(page.product || page.detail || page.data || page);
            }
        } catch (e) {}
        try { if (window.__NUXT__) pick((window.__NUXT__.state || {}).product || window.__NUXT__); } catch (e) {}
        try { if (window.__INITIAL_STATE__) pick(window.__INITIAL_STATE__.product || window.__INITIAL_STATE__); } catch (e) {}
        try { if (window.pageData) pick(window.pageData.product || window.pageData); } catch (e) {}
        return out;
    }
    """
    try:
        data = page.evaluate(script)
        return data or {}
    except Exception:
        return {}


def _extract_meta(soup: BeautifulSoup) -> Dict[str, Any]:
    """OpenGraph / meta fallback."""
    out: Dict[str, Any] = {}

    og_title = soup.select_one('meta[property="og:title"], meta[name="og:title"], meta[name="title"]')
    if og_title and og_title.get('content'):
        out['title'] = og_title['content']

    og_desc = soup.select_one('meta[property="og:description"], meta[name="description"]')
    if og_desc and og_desc.get('content'):
        out['description'] = og_desc['content']

    price = soup.select_one('meta[property="product:price:amount"], meta[property="og:price:amount"]')
    if price and price.get('content'):
        out['price_text'] = price['content']
        out['price_value'] = to_float_price(price['content'])

    imgs = []
    for tag in soup.select('meta[property="og:image"], meta[name="og:image"]'):
        if tag.get('content'):
            imgs.append(tag['content'])
    if imgs:
        out['images'] = imgs

    return out


def _extract_images_dom(soup: BeautifulSoup) -> List[str]:
    """CSS fallback voor afbeeldingen: pak joy-sourcing product-afbeeldingen."""
    images = []
    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src') or img.get('data-lazy')
        if not src:
            continue
        if 'joy-sourcing.com/product' in src or 'jfsintlpro' in src:
            cleaned = clean_image_url(src)
            if cleaned:
                images.append(cleaned)
    return list(dict.fromkeys(images))


# ---------------------------------------------------------------------------
# Hoofd-scraper
# ---------------------------------------------------------------------------

def scrape_joybuy_product(
    url: str,
    headless: bool = True,
    ean: str = "",
    user_data_dir: Optional[str] = None,
    solve_timeout: int = 150,
) -> Dict[str, Any]:
    """
    Scrape een joybuy.nl productpagina.

    Joybuy (JD.com) heeft een agressieve risk-control / CAPTCHA. De betrouwbaarste
    aanpak is een ZICHTBARE browser (headless=False) met een PERSISTENTE sessie:
    je lost de CAPTCHA dan eenmalig handmatig op, de cookies worden bewaard in
    `user_data_dir`, en volgende runs hergebruiken die sessie.

    Args:
        url: Joybuy.nl product URL
        headless: Of de browser headless moet draaien. Voor joybuy sterk
            aangeraden om dit op False te zetten (echt venster -> CAPTCHA oplosbaar).
        ean: Optionele EAN om mee te geven (joybuy toont deze zelden publiek)
        user_data_dir: Map waar de browsersessie/cookies bewaard worden. Default:
            JOYBUY_PROFILE_DIR env var, anders ./joybuy_profile naast deze module.
        solve_timeout: Max. seconden om (in zichtbare modus) te wachten tot de
            gebruiker een eventuele CAPTCHA heeft opgelost.

    Returns:
        Dict met productdata (zelfde vorm als de andere scrapers)

    Raises:
        ValueError: bij ongeldige URL
        RuntimeError: wanneer de risk-control / CAPTCHA niet gepasseerd kon worden
    """
    parsed = urlparse(url)
    if not parsed.netloc or 'joybuy' not in parsed.netloc:
        raise ValueError("URL moet van joybuy.nl zijn")

    # Persistente sessie-map bepalen
    if user_data_dir is None:
        user_data_dir = os.getenv('JOYBUY_PROFILE_DIR') or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'joybuy_profile'
        )
    os.makedirs(user_data_dir, exist_ok=True)

    with sync_playwright() as p:
        # Persistente context (bewaart cookies/CAPTCHA-oplossing tussen runs)
        context = p.chromium.launch_persistent_context(
            user_data_dir,
            headless=headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ],
            user_agent=(
                'Mozilla/5.0 (X11; Linux x86_64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            locale='nl-NL',
            timezone_id='Europe/Amsterdam',
            viewport={'width': 1366, 'height': 900},
            extra_http_headers={
                'Accept-Language': 'nl-NL,nl;q=0.9,en;q=0.8',
            },
        )
        # Verberg navigator.webdriver
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page: Page = context.pages[0] if context.pages else context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

            # Cookie consent afhandelen (accepteren zodat de pagina laadt)
            for label in ('Alles accepteren', 'Accepteren', 'Accept all', 'Alles afwijzen'):
                try:
                    btn = page.get_by_role('button', name=label)
                    if btn and btn.count() > 0:
                        btn.first.click(timeout=2500)
                        break
                except Exception:
                    continue

            # Wacht op product content / netwerk
            try:
                page.wait_for_load_state('networkidle', timeout=15000)
            except Exception:
                pass
            try:
                page.wait_for_selector('h1, [class*="price"]', state='visible', timeout=8000)
            except Exception:
                pass
            # Scroll om lazy content te triggeren
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
            except Exception:
                pass
            time.sleep(1.5)

            current_url = page.url
            html = page.content()

            # Risk / CAPTCHA detectie
            if _is_risk_page(html, current_url):
                if not headless:
                    # Zichtbaar venster: geef de gebruiker tijd om de CAPTCHA
                    # handmatig op te lossen. We pollen tot de echte pagina laadt.
                    print(
                        "\n[joybuy] CAPTCHA / beveiligingscontrole gedetecteerd.\n"
                        "  -> Los de CAPTCHA op in het geopende browservenster.\n"
                        f"  -> Ik wacht maximaal {solve_timeout} seconden...\n",
                        flush=True,
                    )
                    deadline = time.time() + solve_timeout
                    while time.time() < deadline:
                        time.sleep(3)
                        try:
                            current_url = page.url
                            html = page.content()
                        except Exception:
                            continue
                        if not _is_risk_page(html, current_url):
                            # Sessie is nu geldig (cookies blijven bewaard in user_data_dir)
                            try:
                                page.wait_for_selector(
                                    'h1, [class*="price"]', state='visible', timeout=8000
                                )
                            except Exception:
                                pass
                            time.sleep(1.5)
                            html = page.content()
                            break
                    else:
                        raise RuntimeError(
                            "Joybuy risk-control / CAPTCHA niet binnen de tijd opgelost. "
                            "Probeer opnieuw; de sessie wordt bewaard, dus een volgende "
                            "poging kan direct lukken."
                        )
                else:
                    raise RuntimeError(
                        "Joybuy risk-control / CAPTCHA gedetecteerd (headless). Zet "
                        "HEADLESS=false en draai lokaal op een machine met beeldscherm, "
                        "zodat je de CAPTCHA eenmalig kunt oplossen. De sessie wordt "
                        "daarna bewaard in user_data_dir."
                    )

            soup = BeautifulSoup(html, 'lxml')

            # Gelaagde extractie: JSON-LD -> embedded state -> meta -> DOM
            data_jsonld = _extract_from_jsonld(soup)
            data_state = _extract_embedded_state(page)
            data_meta = _extract_meta(soup)

            def first(*vals):
                for v in vals:
                    if v:
                        return v
                return ""

            title = first(
                data_jsonld.get('title'),
                data_state.get('title'),
                data_meta.get('title'),
                text(['h1', 'h1 span', '[class*="productName"]', '[class*="title"]'], soup),
            )

            brand = first(
                data_jsonld.get('brand'),
                data_state.get('brand'),
                text(['[class*="brand"] a', '[class*="brand"]'], soup),
            )

            description = first(
                data_jsonld.get('description'),
                data_state.get('description'),
                data_meta.get('description'),
                text(['[class*="description"]', '[class*="detail"]', '#detail'], soup),
            )

            # Prijs
            price_text = first(
                data_jsonld.get('price_text'),
                str(data_state.get('price') or ''),
                data_meta.get('price_text'),
                text(['[class*="price"]'], soup),
            )
            price_value = (
                data_jsonld.get('price_value')
                or to_float_price(price_text)
            )

            # Afbeeldingen verzamelen uit alle bronnen, opschonen + dedupe
            raw_images: List[str] = []
            for src in (
                data_jsonld.get('images') or []
            ) + (
                data_state.get('images') or []
            ) + (
                data_meta.get('images') or []
            ):
                cleaned = clean_image_url(src)
                if cleaned:
                    raw_images.append(cleaned)
            raw_images += _extract_images_dom(soup)

            gallery_images = list(dict.fromkeys(raw_images))[:20]
            main_image = gallery_images[0] if gallery_images else ""
            all_images = "\n".join(gallery_images)

            return {
                "source_url": url,
                "title": title,
                "brand": brand,
                "price_text": price_text,
                "price_value": price_value,
                "list_price_text": "",
                "list_price_value": None,
                "ean": re.sub(r'\D', '', ean) if ean else data_jsonld.get('ean', ''),
                "description": description,
                "main_image": main_image,
                "all_images": all_images,
            }

        finally:
            context.close()
