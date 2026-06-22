"""
Unit tests voor de joybuy scraper (pure parsing/cleaning logica).

Deze tests raken het netwerk niet — ze valideren de prijs-, afbeeldings-,
risk-detectie- en structured-data-extractie functies met synthetische input.

Run: pytest tests/test_joybuy.py
"""
import os
import sys

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'bol_scraper', 'scraper'))
import joybuy as jb  # noqa: E402


# --------------------------------------------------------------------------- #
# Prijs parsing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("€ 1.234,56", 1234.56),   # NL: punt=duizendtal, komma=decimaal
    ("49,99", 49.99),          # NL decimaal
    ("1,234.56", 1234.56),     # EN: komma=duizendtal, punt=decimaal
    ("89", 89.0),              # geheel getal
    ("", None),                # leeg
    ("geen prijs", None),      # geen cijfers
])
def test_to_float_price(raw, expected):
    assert jb.to_float_price(raw) == expected


# --------------------------------------------------------------------------- #
# Afbeeldings-URL opschonen
# --------------------------------------------------------------------------- #
def test_clean_image_strips_webp_and_upsizes():
    u = ("https://images3.joy-sourcing.com/product/s32x32_jfsintlpro-000-com/"
         "t1/4294967296/8192000/6207371322136/557/6a32a63fEabd6158c/"
         "4c765c6ab87a3a67.png.webp")
    assert jb.clean_image_url(u) == (
        "https://images3.joy-sourcing.com/product/s800x800_jfsintlpro-000-com/"
        "t1/4294967296/8192000/6207371322136/557/6a32a63fEabd6158c/"
        "4c765c6ab87a3a67.png")


def test_clean_image_protocol_relative():
    assert jb.clean_image_url("//x.com/a/s64x64_b/img.jpg") == \
        "https://x.com/a/s800x800_b/img.jpg"


def test_clean_image_strips_query():
    assert jb.clean_image_url("https://x.com/img.jpg?w=100") == "https://x.com/img.jpg"


def test_clean_image_rejects_webp_only():
    # Na het strippen van .webp blijft er geen jpg/png over -> None
    assert jb.clean_image_url("https://x.com/img.webp") is None


# --------------------------------------------------------------------------- #
# Risk / CAPTCHA detectie
# --------------------------------------------------------------------------- #
def test_risk_page_by_url():
    assert jb._is_risk_page("<html>ok</html>",
                            "https://www.joybuy.nl/user/risk/pic?x=1") is True


def test_risk_page_by_text():
    assert jb._is_risk_page("...Veiligheidscontrole...",
                            "https://www.joybuy.nl/dp/x") is True


def test_risk_page_normal():
    assert jb._is_risk_page("<h1>Product</h1>",
                            "https://www.joybuy.nl/dp/x") is False


# --------------------------------------------------------------------------- #
# JSON-LD extractie
# --------------------------------------------------------------------------- #
def test_extract_from_jsonld():
    html = '''<html><head>
    <script type="application/ld+json">
    {"@type":"Product","name":"Ochama 5-laags stellingkast","description":"Stalen opbergrek",
     "brand":{"@type":"Brand","name":"Ochama"},"gtin13":"8785342541375",
     "image":["https://images3.joy-sourcing.com/product/s64x64_a/b/c/d/e/f/g.png.webp"],
     "offers":{"@type":"Offer","price":"59.99","priceCurrency":"EUR"}}
    </script></head><body></body></html>'''
    d = jb._extract_from_jsonld(BeautifulSoup(html, 'lxml'))
    assert d['title'] == "Ochama 5-laags stellingkast"
    assert d['brand'] == "Ochama"
    assert d['ean'] == "8785342541375"
    assert d['price_value'] == 59.99
    assert len(d['images']) == 1


# --------------------------------------------------------------------------- #
# Meta / OpenGraph extractie
# --------------------------------------------------------------------------- #
def test_extract_meta():
    html = '''<html><head>
    <meta property="og:title" content="Ochama Shelf">
    <meta property="og:description" content="Steel rack">
    <meta property="product:price:amount" content="59,99">
    <meta property="og:image" content="https://images3.joy-sourcing.com/product/s96x96_a/b/c/d/e/f/h.jpg">
    </head></html>'''
    m = jb._extract_meta(BeautifulSoup(html, 'lxml'))
    assert m['title'] == "Ochama Shelf"
    assert m['price_value'] == 59.99
    assert len(m['images']) == 1


# --------------------------------------------------------------------------- #
# DOM afbeeldings-fallback
# --------------------------------------------------------------------------- #
def test_extract_images_dom_filters_joy_sourcing():
    html = ('<img src="https://images3.joy-sourcing.com/product/s32x32_a/b/c/d/e/f/i.png.webp">'
            '<img src="https://other.com/x.jpg">')
    imgs = jb._extract_images_dom(BeautifulSoup(html, 'lxml'))
    assert imgs == ["https://images3.joy-sourcing.com/product/s800x800_a/b/c/d/e/f/i.png"]


# --------------------------------------------------------------------------- #
# URL validatie
# --------------------------------------------------------------------------- #
def test_invalid_url_raises():
    with pytest.raises(ValueError):
        jb.scrape_joybuy_product("https://www.amazon.nl/dp/x")
