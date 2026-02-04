"""
Flask app voor Bol.com scraper
"""
import os
import io
import re
import time
import hashlib
from datetime import datetime
from functools import wraps
from typing import Dict, Any, Optional, List, Tuple
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, jsonify, g
import google.generativeai as genai
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from scraper.printables import scrape_printables_product
from scraper.bol import scrape_bol_product
from scraper.amazon import scrape_amazon_product

load_dotenv()
load_dotenv('.env.local')

# Configure Google AI
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
if GOOGLE_API_KEY:
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
    except Exception as e:
        print(f"Error configuring Google AI: {e}")

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')

# Configuratie
HEADLESS = os.getenv('HEADLESS', 'true').lower() == 'true'
OUTPUT_EXCEL = os.getenv('OUTPUT_EXCEL', 'Export_generic_template_20251004_07 PM052.xlsx')
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', '').rstrip('/')  # optioneel, bv. https://example.com
DATABASE_URL = os.getenv('DATABASE_URL') or 'sqlite:///bol_scraper.db'

# Database setup
engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# Static pad voor afbeeldingen (Flask serveert /static automatisch vanuit deze map)
STATIC_IMAGES_DIR = os.path.join(os.path.dirname(__file__), 'static', 'images', 'products')
os.makedirs(STATIC_IMAGES_DIR, exist_ok=True)

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

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    products = relationship('Product', back_populates='user', cascade='all, delete-orphan')


class Product(Base):
    __tablename__ = 'products'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    platform = Column(String(40), nullable=True)
    source_url = Column(Text, nullable=True)
    title = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    internal_reference = Column(String(200), nullable=True)
    ean = Column(String(100), nullable=True)
    condition = Column(String(50), nullable=True)
    condition_comment = Column(String(255), nullable=True)
    stock = Column(Integer, nullable=True)
    list_price_value = Column(Float, nullable=True)
    delivery_time = Column(String(50), nullable=True)
    delivery_method = Column(String(50), nullable=True)
    for_sale = Column(String(20), nullable=True)
    cost_price = Column(Float, nullable=True)
    shipping_costs = Column(Float, nullable=True)
    commission_percentage = Column(Float, nullable=True)
    commission_fixed = Column(Float, nullable=True)
    commission_amount = Column(Float, nullable=True)
    margin = Column(Float, nullable=True)
    main_image = Column(Text, nullable=True)
    marketplace_participant = Column(String(200), nullable=True)
    all_images = Column(Text, nullable=True)
    is_draft = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship('User', back_populates='products')


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


init_db()


def get_db_session():
    return SessionLocal()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Login vereist'}), 401
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


@app.before_request
def load_current_user():
    g.current_user = None
    user_id = session.get('user_id')
    if not user_id:
        return
    db = get_db_session()
    try:
        g.current_user = db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()


@app.context_processor
def inject_current_user():
    return {'current_user': g.get('current_user')}


def product_to_internal_data(product: Product) -> Dict[str, Any]:
    return {
        'id': product.id,
        'source_url': product.source_url,
        'title': product.title or '',
        'description': product.description or '',
        'internal_reference': product.internal_reference or '',
        'ean': product.ean or '',
        'condition': product.condition or '',
        'condition_comment': product.condition_comment or '',
        'stock': product.stock if product.stock is not None else 69,
        'list_price_value': product.list_price_value,
        'delivery_time': product.delivery_time or '',
        'delivery_method': product.delivery_method or '',
        'for_sale': product.for_sale or 'ja',
        'cost_price': product.cost_price,
        'shipping_costs': product.shipping_costs,
        'commission_percentage': product.commission_percentage,
        'commission_fixed': product.commission_fixed,
        'commission_amount': product.commission_amount,
        'margin': product.margin,
        'main_image': product.main_image or '',
        'marketplace_participant': product.marketplace_participant or '',
        'all_images': product.all_images or '',
    }


def product_to_excel_row(product: Product) -> Dict[str, Any]:
    return {
        'Productnaam': product.title or '',
        'Beschrijving': product.description or '',
        'Interne referentie': product.internal_reference or '',
        'EAN': product.ean or '',
        'Conditie': product.condition or '',
        'Conditie commentaar': product.condition_comment or '',
        'Voorraad': product.stock if product.stock is not None else 69,
        'Prijs': product.list_price_value if product.list_price_value is not None else '',
        'Levertijd': product.delivery_time or '',
        'Afleverwijze': product.delivery_method or '',
        'Te koop': product.for_sale or 'ja',
        'Hoofdafbeelding': product.main_image or '',
        'Marktdeelnemer': product.marketplace_participant or '',
        'Additionele afbeeldingen': product.all_images or ''
    }


def update_product_from_form(product: Product, form_data: Dict[str, str]) -> None:
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
        'Inkoopprijs': 'cost_price',
        'Verzendkosten': 'shipping_costs',
        'Commissie Percentage': 'commission_percentage',
        'Commissie Vast': 'commission_fixed',
        'Bol Commissie': 'commission_amount',
        'Marge': 'margin',
        'Hoofdafbeelding': 'main_image',
        'Marktdeelnemer': 'marketplace_participant',
        'Additionele afbeeldingen': 'all_images'
    }

    for excel_field, internal_field in field_mapping.items():
        if excel_field not in form_data:
            continue
        value = form_data[excel_field].strip()
        if internal_field in [
            'list_price_value',
            'cost_price',
            'shipping_costs',
            'commission_percentage',
            'commission_fixed',
            'commission_amount',
            'margin',
        ]:
            try:
                setattr(product, internal_field, float(value) if value else None)
            except ValueError:
                setattr(product, internal_field, None)
        elif internal_field == 'stock':
            try:
                setattr(product, internal_field, int(value) if value else 69)
            except ValueError:
                setattr(product, internal_field, 69)
        else:
            setattr(product, internal_field, value)

    product.updated_at = datetime.utcnow()


def get_user_product(db, product_id: int) -> Optional[Product]:
    return (
        db.query(Product)
        .filter(Product.id == product_id, Product.user_id == g.current_user.id)
        .first()
    )


def create_draft_product(db, platform: str, source_url: str, product_data: Dict[str, Any], user_id: int) -> Product:
    product = Product(
        user_id=user_id,
        platform=platform,
        source_url=source_url,
        title=product_data.get('title'),
        description=product_data.get('description'),
        internal_reference=product_data.get('internal_reference'),
        ean=product_data.get('ean'),
        condition=product_data.get('condition'),
        condition_comment=product_data.get('condition_comment'),
        stock=product_data.get('stock'),
        list_price_value=product_data.get('list_price_value'),
        delivery_time=product_data.get('delivery_time'),
        delivery_method=product_data.get('delivery_method'),
        for_sale=product_data.get('for_sale'),
        cost_price=product_data.get('cost_price'),
        shipping_costs=product_data.get('shipping_costs'),
        commission_percentage=product_data.get('commission_percentage'),
        commission_fixed=product_data.get('commission_fixed'),
        commission_amount=product_data.get('commission_amount'),
        margin=product_data.get('margin'),
        main_image=product_data.get('main_image'),
        marketplace_participant=product_data.get('marketplace_participant'),
        all_images=product_data.get('all_images'),
        is_draft=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(product)
    db.flush()
    return product


@app.route('/register', methods=['GET', 'POST'])
def register():
    if g.current_user:
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash('Vul gebruikersnaam en wachtwoord in', 'error')
            return redirect(url_for('register'))

        db = get_db_session()
        try:
            existing = db.query(User).filter(User.username == username).first()
            if existing:
                flash('Gebruikersnaam is al in gebruik', 'error')
                return redirect(url_for('register'))
            user = User(
                username=username,
                password_hash=generate_password_hash(password),
            )
            db.add(user)
            db.commit()
            session['user_id'] = user.id
            flash('Account aangemaakt', 'success')
            return redirect(url_for('home'))
        finally:
            db.close()

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.current_user:
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash('Vul gebruikersnaam en wachtwoord in', 'error')
            return redirect(url_for('login'))

        db = get_db_session()
        try:
            user = db.query(User).filter(User.username == username).first()
            if not user or not check_password_hash(user.password_hash, password):
                flash('Ongeldige login', 'error')
                return redirect(url_for('login'))
            session['user_id'] = user.id
            flash('Ingelogd', 'success')
            return redirect(url_for('home'))
        finally:
            db.close()

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))
@app.route('/printables')
@login_required
def printables_index():
    """Printables Scraper hoofdpagina."""
    return render_template('printables_index.html')


@app.route('/printables/scrape', methods=['POST'])
@login_required
def printables_scrape():
    """Start scrape van Printables URL."""
    url = request.form.get('url', '').strip()
    
    if not url:
        flash('Voer een URL in', 'error')
        return redirect(url_for('printables_index'))
    
    if 'printables.com' not in url:
        flash('URL moet van printables.com zijn', 'error')
        return redirect(url_for('printables_index'))
        
    try:
        # Scrape product
        product_data = scrape_printables_product(url, headless=HEADLESS)
        product_data['source_url'] = url
        
        db = get_db_session()
        try:
            product = create_draft_product(db, platform='printables', source_url=url, product_data=product_data, user_id=g.current_user.id)
            new_product_id = product.id

            # Download afbeeldingen naar /static en vervang URLs door serveerbare lokale URLs
            try:
                new_main, new_all = process_images_into_static(
                    product_data.get('main_image', ''),
                    product_data.get('all_images', ''),
                    title=product_data.get('title', ''),
                    ean=f"PR-{int(time.time())}",
                    user_id=g.current_user.id,
                    product_id=new_product_id,
                )
                product.main_image = new_main
                product.all_images = new_all
            except Exception:
                pass
            # ID veiligstellen voordat session sluit/expireert
            session['current_product_id'] = new_product_id
            db.commit()
        finally:
            db.close()

        # Gebruik de BOL edit flow voor nu, want de velden zijn gemapped
        # Maar we moeten wel weten dat we terug naar printables moeten als we cancelen?
        # Voorlopig linken we naar dezelfde edit pagina, maar die post naar /bol/edit...
        # Dat is niet handig. We moeten een /printables/edit hebben of de edit pagina slim maken.
        # Laten we voor consistentie /printables/edit maken.
        
        return redirect(url_for('printables_edit'))
        
    except Exception as e:
        flash(f'Scrape fout: {str(e)}', 'error')
        return redirect(url_for('printables_index'))


@app.route('/printables/edit', methods=['GET', 'POST'])
@login_required
def printables_edit():
    """Formulier voor bewerken van Printables data."""
    product_id = session.get('current_product_id')
    if not product_id:
        flash('Geen data om te bewerken', 'error')
        return redirect(url_for('printables_index'))

    db = get_db_session()
    try:
        product = get_user_product(db, product_id)
        if not product:
            flash('Geen data om te bewerken', 'error')
            return redirect(url_for('printables_index'))

        if request.method == 'POST':
            update_product_from_form(product, request.form)
            db.commit()
            return redirect(url_for('printables_confirm'))

        return render_template('edit.html', data=product_to_internal_data(product), platform='printables')
    finally:
        db.close()


@app.route('/printables/confirm', methods=['GET', 'POST'])
@login_required
def printables_confirm():
    product_id = session.get('current_product_id')
    if not product_id:
        flash('Geen data om te bevestigen', 'error')
        return redirect(url_for('printables_index'))

    db = get_db_session()
    try:
        product = get_user_product(db, product_id)
        if not product:
            flash('Geen data om te bevestigen', 'error')
            return redirect(url_for('printables_index'))

        if request.method == 'POST':
            was_draft = product.is_draft
            product.is_draft = False
            product.updated_at = datetime.utcnow()
            db.commit()
            session.pop('current_product_id', None)
            flash('Product opgeslagen!', 'success')
            return redirect(url_for('printables_index' if was_draft else 'printables_rows'))

        return render_template('confirm.html', data=product_to_internal_data(product), platform='printables')
    finally:
        db.close()


@app.route('/printables/rows')
@login_required
def printables_rows():
    """Overzicht rijen (gedeelde Excel)."""
    # Reuse bol logic but render with platform='printables' for back links
    db = get_db_session()
    try:
        products = (
            db.query(Product)
            .filter(Product.user_id == g.current_user.id, Product.is_draft.is_(False))
            .order_by(Product.created_at.desc())
            .all()
        )
        rows_data = []
        for product in products:
            row = product_to_excel_row(product)
            row['product_id'] = product.id
            rows_data.append(row)

        return render_template('rows.html', rows=rows_data, platform='printables')
    except Exception as e:
        flash(f'Fout: {str(e)}', 'error')
        return redirect(url_for('printables_index'))
    finally:
        db.close()
        
        
@app.route('/printables/edit_row/<int:product_id>')
@login_required
def printables_edit_row(product_id):
    db = get_db_session()
    try:
        product = get_user_product(db, product_id)
        if not product:
            return redirect(url_for('printables_rows'))
        session['current_product_id'] = product.id
        return redirect(url_for('printables_edit'))
    finally:
        db.close()

@app.route('/printables/delete_row/<int:product_id>')
@login_required
def printables_delete_row(product_id):
    db = get_db_session()
    try:
        product = get_user_product(db, product_id)
        if product:
            db.delete(product)
            db.commit()
            flash('Verwijderd', 'success')
        return redirect(url_for('printables_rows'))
    finally:
        db.close()
        
@app.route('/printables/export')
@login_required
def printables_export():
    return bol_export() # Reuse export logic




def validate_bol_url(url: str) -> bool:
    """Valideer of URL van bol.com is."""
    try:
        parsed = urlparse(url)
        return parsed.netloc and 'bol.com' in parsed.netloc
    except:
        return False


def normalize_bol_url(url: str) -> str:
    """Probeer van invoer een geldige bol.com URL te maken.
    - Voegt https:// toe als schema ontbreekt
    - Trimt whitespace
    - Accepteert www.bol.com/... of bol.com/...
    """
    if not url:
        return ''
    raw = url.strip()
    # Pad-only invoer direct mappen naar bol.com
    if raw.startswith('/'):
        return 'https://www.bol.com' + raw
    # Geen schema opgegeven
    if not re.match(r'^https?://', raw, flags=re.IGNORECASE):
        first_token = raw.split('/')[0].lower()
        if '.' in first_token:
            # Lijkt een host (bijv. bol.com/... of www.bol.com/...)
            raw = 'https://' + raw
        else:
            # Lijkt een pad zonder leading slash (bijv. product/123)
            return 'https://www.bol.com/' + raw
    parsed = urlparse(raw)
    # Als nog steeds geen host, behandel het als pad
    if not parsed.netloc and parsed.path:
        return 'https://www.bol.com' + (parsed.path if parsed.path.startswith('/') else ('/' + parsed.path)) + (('?' + parsed.query) if parsed.query else '')
    # Host controle
    host = (parsed.netloc or '').lower()
    if host.endswith('bol.com'):
        return raw
    # Forceer bol.com met behoud van pad en query
    if parsed.path:
        return 'https://www.bol.com' + (parsed.path if parsed.path.startswith('/') else ('/' + parsed.path)) + (('?' + parsed.query) if parsed.query else '')
    return raw


def is_valid_image_source_url(url: str) -> bool:
    """Valideer bron-URL tegen Bol eisen (basis checks; uiteindelijke URL wordt lokaal)."""
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        # Geen shorteners (simpele blacklist)
        host = parsed.netloc.lower()
        if host in { 'bit.ly', 't.ly', 'tinyurl.com', 'goo.gl', 'ow.ly', 'buff.ly' }:
            return False
        return True
    except Exception:
        return False


def guess_extension(content_type: str, fallback: str = '.jpg') -> str:
    ct = (content_type or '').lower()
    if 'jpeg' in ct:
        return '.jpg'
    if 'jpg' in ct:
        return '.jpg'
    if 'png' in ct:
        return '.png'
    return fallback


def sanitize_filename(name: str) -> str:
    """Maak veilige bestandsnaam: geen spaties/rare chars, lowercase."""
    name = name.strip().lower()
    name = name.replace(' ', '-')
    # Alleen a-z0-9-_ .
    name = re.sub(r'[^a-z0-9\-_.]', '', name)
    name = re.sub(r'-{2,}', '-', name)
    name = name.strip('-.')
    return name or 'image'


def build_image_filename(title: str, ean: str, index: int, ext: str, source_url: str) -> str:
    base = sanitize_filename(f"{title}-{ean}" if ean else title)
    # Hash erbij voor uniqueness bij gelijke titels
    url_hash = hashlib.sha1(source_url.encode('utf-8')).hexdigest()[:8]
    filename = f"{base}-{index+1}-{url_hash}{ext}"
    return filename


def download_image_to_static(
    source_url: str,
    title: str,
    ean: str,
    index: int,
    user_id: int,
    product_id: int,
) -> Optional[str]:
    """Download afbeelding en sla op in static, return serveerbare URL (/static/...)."""
    if not is_valid_image_source_url(source_url):
        return None
    try:
        req = Request(source_url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; BolScraper/1.0)'
        })
        with urlopen(req, timeout=20) as resp:
            content_type = resp.headers.get('Content-Type', '')
            if not any(x in (content_type or '').lower() for x in ['image/jpeg', 'image/jpg', 'image/png']):
                return None
            data = resp.read()
            ext = guess_extension(content_type)
    except (HTTPError, URLError, TimeoutError):
        return None
    except Exception:
        return None

    filename = build_image_filename(title, ean, index, ext, source_url)
    product_dir = os.path.join(STATIC_IMAGES_DIR, str(user_id), str(product_id))
    os.makedirs(product_dir, exist_ok=True)
    abs_path = os.path.join(product_dir, filename)
    try:
        with open(abs_path, 'wb') as f:
            f.write(data)
    except Exception:
        return None

    # Bouw publieke/serveerbare URL (zonder spaties, eindigt op .jpg/.png)
    rel_path = f"/static/images/products/{user_id}/{product_id}/{filename}"
    # Gebruik PUBLIC_BASE_URL of fallback naar localhost:5002 (nooit relatieve paden)
    base = PUBLIC_BASE_URL if PUBLIC_BASE_URL else "http://localhost:5002"
    return f"{base}{rel_path}"


def process_images_into_static(
    main_image_url: str,
    all_images_concat: str,
    title: str,
    ean: str,
    user_id: int,
    product_id: int,
) -> Tuple[str, str]:
    """Download hoofd- en additionele afbeeldingen en return lokale URLs (gescheiden door |)."""
    urls: List[str] = []
    if main_image_url:
        urls.append(main_image_url)
    if all_images_concat:
        # Split op zowel | als \n (en eventueel ,)
        # Eerst alles normaliseren naar 1 separator
        cleaned = all_images_concat.replace('|', '\n').replace('\r', '')
        # Splitsen op newline
        raw_urls = cleaned.split('\n')
        
        # Voeg toe aan lijst (strip whitespace en eventuele trailing komma's)
        for u in raw_urls:
            clean_u = u.strip().strip(',')
            if clean_u:
                urls.append(clean_u)

    # Dedupe met behoud van volgorde
    seen = set()
    ordered_urls = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered_urls.append(u)

    stored_urls: List[str] = []
    for i, src in enumerate(ordered_urls):
        stored = download_image_to_static(
            src,
            title=title or 'product',
            ean=ean or '',
            index=i,
            user_id=user_id,
            product_id=product_id,
        )
        if stored:
            stored_urls.append(stored)

    new_main = stored_urls[0] if stored_urls else ''
    # Join met ,\n zoals gevraagd
    new_all = ',\n'.join(stored_urls)
    new_main = stored_urls[0] if stored_urls else ''
    # Join met ,\n zoals gevraagd
    new_all = ',\n'.join(stored_urls)
    return new_main, new_all


def process_images_keep_remote(main_image_url: str, all_images_concat: str) -> Tuple[str, str]:
    """Bewerk URLs (splitsen/opschonen) maar download niets. Return originele URLs."""
    urls: List[str] = []
    if main_image_url:
        urls.append(main_image_url)
    
    if all_images_concat:
        # Split op zowel | als \n (en eventueel ,)
        cleaned = all_images_concat.replace('|', '\n').replace('\r', '')
        raw_urls = cleaned.split('\n')
        
        for u in raw_urls:
            clean_u = u.strip().strip(',')
            if clean_u:
                urls.append(clean_u)

    # Dedupe
    seen = set()
    ordered_urls = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered_urls.append(u)

    new_main = ordered_urls[0] if ordered_urls else ''
    new_all = ',\n'.join(ordered_urls)
    return new_main, new_all



@app.route('/')
@login_required
def home():
    """Nieuwe home pagina met scraper selectie."""
    return render_template('home.html')


@app.route('/bol')
@login_required
def bol_index():
    """Bol.com Scraper hoofdpagina."""
    return render_template('bol_index.html')


@app.route('/bol/scrape', methods=['POST'])
@login_required
def bol_scrape():
    """Start scrape van bol.com URL."""
    incoming = request.form.get('url', '').strip()
    url = normalize_bol_url(incoming)
    
    if not url:
        flash('Voer een URL in', 'error')
        return redirect(url_for('bol_index'))
    
    if not validate_bol_url(url):
        flash('URL moet van bol.com zijn (invoer automatisch proberen te corrigeren is mislukt)', 'error')
        return redirect(url_for('bol_index'))
    
    try:
        # Scrape product
        product_data = scrape_bol_product(url, headless=HEADLESS)
        product_data['source_url'] = url

        # Voeg standaard waarden toe voor nieuwe velden
        product_data['condition'] = 'nieuw'
        product_data['condition_comment'] = ''
        product_data['internal_reference'] = ''
        product_data['stock'] = 69
        product_data['delivery_time'] = ''
        product_data['delivery_method'] = ''
        product_data['for_sale'] = 'ja'
        product_data['marketplace_participant'] = ''

        db = get_db_session()
        try:
            product = create_draft_product(db, platform='bol', source_url=url, product_data=product_data, user_id=g.current_user.id)
            new_product_id = product.id  # Direct opslaan

            # Download afbeeldingen naar /static en vervang URLs door serveerbare lokale URLs
            try:
                new_main, new_all = process_images_into_static(
                    product_data.get('main_image', ''),
                    product_data.get('all_images', ''),
                    title=product_data.get('title', ''),
                    ean=product_data.get('ean', ''),
                    user_id=g.current_user.id,
                    product_id=new_product_id,
                )
                product.main_image = new_main
                product.all_images = new_all
            except Exception:
                # Bij fout: laat originele URLs staan
                pass
            
            # ID veiligstellen
            session['current_product_id'] = new_product_id
            db.commit()
        finally:
            db.close()

        # session['current_product_id'] is already set above
        return redirect(url_for('bol_edit'))

    except Exception as e:
        flash(f'Scrape fout: {str(e)}', 'error')
        return redirect(url_for('bol_index'))


@app.route('/bol/edit', methods=['GET', 'POST'])
@login_required
def bol_edit():
    """Formulier voor bewerken van gescrapete data."""
    product_id = session.get('current_product_id')
    if not product_id:
        flash('Geen data om te bewerken', 'error')
        return redirect(url_for('bol_index'))

    db = get_db_session()
    try:
        product = get_user_product(db, product_id)
        if not product:
            flash('Geen data om te bewerken', 'error')
            return redirect(url_for('bol_index'))

        if request.method == 'POST':
            update_product_from_form(product, request.form)
            db.commit()
            return redirect(url_for('bol_confirm'))

        return render_template('edit.html', data=product_to_internal_data(product), platform='bol')
    finally:
        db.close()


@app.route('/bol/confirm', methods=['GET', 'POST'])
@login_required
def bol_confirm():
    """Bevestigingspagina met data overzicht."""
    product_id = session.get('current_product_id')
    if not product_id:
        flash('Geen data om te bevestigen', 'error')
        return redirect(url_for('bol_index'))

    db = get_db_session()
    try:
        product = get_user_product(db, product_id)
        if not product:
            flash('Geen data om te bevestigen', 'error')
            return redirect(url_for('bol_index'))

        if request.method == 'POST':
            was_draft = product.is_draft
            product.is_draft = False
            product.updated_at = datetime.utcnow()
            db.commit()
            session.pop('current_product_id', None)
            flash('Product opgeslagen!', 'success')
            return redirect(url_for('bol_index' if was_draft else 'bol_rows'))

        return render_template('confirm.html', data=product_to_internal_data(product), platform='bol')
    finally:
        db.close()


@app.route('/bol/rows')
@login_required
def bol_rows():
    """Overzicht van alle opgeslagen rijen."""
    db = get_db_session()
    try:
        products = (
            db.query(Product)
            .filter(Product.user_id == g.current_user.id, Product.is_draft.is_(False))
            .order_by(Product.created_at.desc())
            .all()
        )
        rows_data = []
        for product in products:
            row = product_to_excel_row(product)
            row['product_id'] = product.id
            rows_data.append(row)
        return render_template('rows.html', rows=rows_data)
    except Exception as e:
        print(f"DEBUG: Fout in rows functie: {str(e)}")
        flash(f'Fout bij laden data: {str(e)}', 'error')
        return redirect(url_for('bol_index'))
    finally:
        db.close()


@app.route('/bol/edit_row/<int:product_id>')
@login_required
def bol_edit_row(product_id):
    """Bewerk een bestaande rij."""
    db = get_db_session()
    try:
        product = get_user_product(db, product_id)
        if not product:
            flash('Rij niet gevonden', 'error')
            return redirect(url_for('bol_rows'))
        session['current_product_id'] = product.id
        return redirect(url_for('bol_edit'))
    finally:
        db.close()


@app.route('/bol/delete_row/<int:product_id>')
@login_required
def bol_delete_row(product_id):
    """Verwijder een rij."""
    db = get_db_session()
    try:
        product = get_user_product(db, product_id)
        if not product:
            flash('Rij niet gevonden', 'error')
            return redirect(url_for('bol_rows'))
        db.delete(product)
        db.commit()
        flash('Product verwijderd!', 'success')
        return redirect(url_for('bol_rows'))
    finally:
        db.close()


@app.route('/bol/export')
@login_required
def bol_export():
    """Download Excel bestand."""
    db = get_db_session()
    try:
        products = (
            db.query(Product)
            .filter(Product.user_id == g.current_user.id, Product.is_draft.is_(False))
            .order_by(Product.created_at.desc())
            .all()
        )
        rows = [product_to_excel_row(product) for product in products]
        df_clean = pd.DataFrame(rows, columns=EXCEL_COLUMNS)

        for col in EXCEL_COLUMNS:
            if col not in df_clean.columns:
                df_clean[col] = ''

        df_clean = df_clean.fillna('')

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
        return redirect(url_for('bol_index'))
    finally:
        db.close()


@app.route('/amazon')
@login_required
def amazon_index():
    """Amazon Scraper hoofdpagina."""
    return render_template('amazon_index.html')


@app.route('/amazon/scrape', methods=['POST'])
@login_required
def amazon_scrape():
    """Start scrape van Amazon URL."""
    url = request.form.get('url', '').strip()
    
    if not url:
        flash('Voer een URL in', 'error')
        return redirect(url_for('amazon_index'))
    
    # Simpele validatie
    if 'amazon' not in url:
        flash('URL moet van amazon zijn', 'error')
        return redirect(url_for('amazon_index'))
        
    try:
        # Scrape product
        product_data = scrape_amazon_product(url, headless=HEADLESS)
        product_data['source_url'] = url
        
        # Voeg standaard waarden toe
        product_data['condition'] = 'nieuw'
        product_data['condition_comment'] = ''
        product_data['internal_reference'] = product_data.get('asin', '')
        product_data['stock'] = 69
        product_data['delivery_time'] = ''
        product_data['delivery_method'] = ''
        product_data['for_sale'] = 'ja'
        product_data['marketplace_participant'] = ''
        
        # Amazon specifiek: Scraped prijs is Inkoopprijs
        product_data['cost_price'] = product_data.get('price_value')
        product_data['shipping_costs'] = 6.90
        product_data['list_price_value'] = None # Verkoopprijs is nog te bepalen -> leeg laten of default? User implies "The price that scrapes from amazon can be put directly into the cost price". Usually you then calculate a sell price. 
        # But wait, if 'list_price_value' is used as 'Prijs' (Selling Price) in the edit form, we should probably clear it or set it to a target price?
        # Let's just set cost_price and leave list_price_value (Selling Price) empty or as is (if amazon has a list price, maybe that's the RRP/Adviesprijs).
        # In amazon.py, 'list_price_value' is likely the scratched price (RRP).
        # 'price_value' is the current amazon price.
        
        # Mapping:
        # Amazon Price (price_value) -> Inkoopprijs (cost_price)
        # Amazon List Price (list_price_value) -> Adviesprijs (list_price_value in internal model? Wait. In bol.py mapping: 'list_price_value' maps to 'Prijs' (Selling Price) column in Excel?
        # Let's check `bol_edit` mapping again.
        # 'Prijs': 'list_price_value'. So 'list_price_value' IS the field that ends up in the 'Prijs' column in Excel.
        # If we want the *Selling Price* to be something else, we should set 'list_price_value' to that.
        # If the user says "The price that scrapes... put in cost price", they likely imply:
        # Scraped Amazon Price -> Cost Price.
        # Selling Price -> To be entered by user (or maybe we keep it empty?)
        # Let's set cost_price = price_value.
        # And let's NOT set list_price_value to price_value (which would be selling at cost).
        
        # Let's looking at the code I'm replacing:
        # It doesn't explicitly set list_price_value here, it comes from scrape_amazon_product.
        # scrape_amazon_product likely returns 'price_value' and 'list_price_value'.
        # I should probably overwrite list_price_value to None or keep it as RRP?
        # In the context of "Bol Scraper" (the app name), the Excel 'Prijs' column is the price on BOL.
        # So we probably don't want the Amazon Buy Price in the Bol Sell Price column.
        # So I will wipe list_price_value (Selling Price) so the user is forced/encouraged to enter a margin-based price, 
        # OR I calculate a default sell price?
        # User didn't ask for auto-calc sell price. Just "put amazon price in cost price".
        
        product_data['list_price_value'] = None # Reset selling price so user can calculate it

        db = get_db_session()
        try:
            product = create_draft_product(db, platform='amazon', source_url=url, product_data=product_data, user_id=g.current_user.id)
            new_product_id = product.id

            # Amazon: Sla originele URLs op, download niets lokaal
            try:
                new_main, new_all = process_images_keep_remote(
                    product_data.get('main_image', ''),
                    product_data.get('all_images', '')
                )
                product.main_image = new_main
                product.all_images = new_all
            except Exception:
                pass
            
            # ID veiligstellen
            session['current_product_id'] = new_product_id
            db.commit()
        finally:
            db.close()

        # session['current_product_id'] is already set above
        return redirect(url_for('amazon_edit'))
        
    except Exception as e:
        flash(f'Scrape fout: {str(e)}', 'error')
        return redirect(url_for('amazon_index'))


@app.route('/amazon/edit', methods=['GET', 'POST'])
@login_required
def amazon_edit():
    """Formulier voor bewerken van Amazon data."""
    product_id = session.get('current_product_id')
    if not product_id:
        flash('Geen data om te bewerken', 'error')
        return redirect(url_for('amazon_index'))

    db = get_db_session()
    try:
        product = get_user_product(db, product_id)
        if not product:
            flash('Geen data om te bewerken', 'error')
            return redirect(url_for('amazon_index'))

        if request.method == 'POST':
            update_product_from_form(product, request.form)
            db.commit()
            return redirect(url_for('amazon_confirm'))

        return render_template('edit.html', data=product_to_internal_data(product), platform='amazon')
    finally:
        db.close()


@app.route('/amazon/confirm', methods=['GET', 'POST'])
@login_required
def amazon_confirm():
    product_id = session.get('current_product_id')
    if not product_id:
        flash('Geen data om te bevestigen', 'error')
        return redirect(url_for('amazon_index'))

    db = get_db_session()
    try:
        product = get_user_product(db, product_id)
        if not product:
            flash('Geen data om te bevestigen', 'error')
            return redirect(url_for('amazon_index'))

        if request.method == 'POST':
            was_draft = product.is_draft
            product.is_draft = False
            product.updated_at = datetime.utcnow()
            db.commit()
            session.pop('current_product_id', None)
            flash('Product opgeslagen!', 'success')
            return redirect(url_for('amazon_index' if was_draft else 'amazon_rows'))

        return render_template('confirm.html', data=product_to_internal_data(product), platform='amazon')
    finally:
        db.close()


@app.route('/amazon/rows')
@login_required
def amazon_rows():
    """Overzicht rijen (Amazon)."""
    db = get_db_session()
    try:
        products = (
            db.query(Product)
            .filter(Product.user_id == g.current_user.id, Product.is_draft.is_(False))
            .order_by(Product.created_at.desc())
            .all()
        )
        rows_data = []
        for product in products:
            row = product_to_excel_row(product)
            row['product_id'] = product.id
            rows_data.append(row)
        return render_template('rows.html', rows=rows_data, platform='amazon')
    except Exception as e:
        flash(f'Fout: {str(e)}', 'error')
        return redirect(url_for('amazon_index'))
    finally:
        db.close()


@app.route('/amazon/edit_row/<int:product_id>')
@login_required
def amazon_edit_row(product_id):
    db = get_db_session()
    try:
        product = get_user_product(db, product_id)
        if not product:
            return redirect(url_for('amazon_rows'))
        session['current_product_id'] = product.id
        return redirect(url_for('amazon_edit'))
    finally:
        db.close()


@app.route('/amazon/delete_row/<int:product_id>')
@login_required
def amazon_delete_row(product_id):
    db = get_db_session()
    try:
        product = get_user_product(db, product_id)
        if product:
            db.delete(product)
            db.commit()
            flash('Verwijderd', 'success')
        return redirect(url_for('amazon_rows'))
    finally:
        db.close()


@app.route('/amazon/export')
@login_required
def amazon_export():
    return bol_export()


@app.route('/api/optimize-description', methods=['POST'])
@login_required
def optimize_description():
    """Gebruik Google AI om een betere productbeschrijving te genereren."""
    if not GOOGLE_API_KEY:
        return jsonify({'error': 'Geen Google API key geconfigureerd'}), 500
        
    data = request.get_json()
    title = data.get('title', '')
    current_description = data.get('description', '')
    
    if not title and not current_description:
        return jsonify({'error': 'Geen titel of beschrijving opgegeven'}), 400
        
    try:
        model = genai.GenerativeModel('models/gemini-3-pro-preview')
        
        prompt = f"""
        Schrijf een professionele, verkoopkrachtige productbeschrijving voor Bol.com.
        
        Product Titel: {title}
        Huidige Beschrijving/Info: {current_description}
        
        Richtlijnen:
        - Gebruik makkelijk leesbare paragrafen
        - Gebruik opsommingstekens voor kenmerken (indien van toepassing)
        - Schrijf in het Nederlands
        - Focus op voordelen voor de klant
        - Maak het SEO vriendelijk
        - Geen inleiding of slot, alleen de beschrijving zelf
        - LAAT HET MERK (BRAND NAME) WEG UIT DE TEKST. Beschrijf het product neutraal zonder de merknaam te noemen.
        """
        
        response = model.generate_content(prompt)
        optimized_text = response.text
        
        return jsonify({'result': optimized_text})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/optimize-title', methods=['POST'])
@login_required
def optimize_title():
    """Gebruik Google AI om een betere producttitel te genereren."""
    if not GOOGLE_API_KEY:
        return jsonify({'error': 'Geen Google API key geconfigureerd'}), 500
        
    data = request.get_json()
    current_title = data.get('title', '')
    description = data.get('description', '')
    
    if not current_title and not description:
        return jsonify({'error': 'Geen titel of beschrijving beschikbaar'}), 400
        
    try:
        model = genai.GenerativeModel('models/gemini-3-pro-preview')
        
        prompt = f"""
        Herschrijf de producttitel voor Bol.com volgens exact deze structuur:
        [Serie] - [Productgroep] - [Kenmerk 1] - [Kenmerk 2] - [Kenmerk 3]
        
        Input Titel: {current_title}
        Input Beschrijving: {description}
        
        Richtlijnen:
        - Haal serie en kenmerken uit de input.
        - LAAT DE MERKNAAM WEG. De titel mag GEEN merknaam bevatten.
        - Als een serie niet bestaat, sla die over.
        - Zorg dat het professioneel klinkt.
        - Geen inleiding, alleen de titelsuggestie.
        - Houd het beknopt maar informatief.
        """
        
        response = model.generate_content(prompt)
        optimized_title = response.text.strip()
        
        # Verwijder quotes als die eromheen staan
        if optimized_title.startswith('"') and optimized_title.endswith('"'):
            optimized_title = optimized_title[1:-1]
            
        return jsonify({'result': optimized_title})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    init_db()
    
    # Gebruik 0.0.0.0 voor Docker compatibility
    port = int(os.environ.get('PORT', 5002))
    app.run(debug=True, host='0.0.0.0', port=port)
