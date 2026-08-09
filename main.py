from dotenv import load_dotenv
load_dotenv()
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory, make_response, abort
from flask_sqlalchemy import SQLAlchemy
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_compress import Compress
import werkzeug.formparser
werkzeug.formparser.MultiPartParser.max_form_memory_size = 500 * 1024 * 1024
from datetime import datetime, timedelta
from authlib.integrations.flask_client import OAuth
from PIL import Image
import os
import random
import hashlib
import hmac
import base64
import json
import requests
import qrcode
import uuid
import threading
from io import BytesIO
import zipfile
from bs4 import BeautifulSoup
import re
import shutil
from translations import translations, get_text

def extract_keywords_from_html(file_path):
    """HTML başarı dosyasından anahtar kelimeleri çıkar"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        culprit_keywords = ''
        explanation_keywords = ''
        
        # Yöntem 1: HTML yorumlarından çıkar
        # <!-- SUCLU: melis, derin -->
        # <!-- ACIKLAMA: zehir, kahve -->
        culprit_match = re.search(r'<!--\s*SUCLU:\s*(.+?)\s*-->', content, re.IGNORECASE)
        if culprit_match:
            culprit_keywords = culprit_match.group(1).strip()
        
        explanation_match = re.search(r'<!--\s*ACIKLAMA:\s*(.+?)\s*-->', content, re.IGNORECASE)
        if explanation_match:
            explanation_keywords = explanation_match.group(1).strip()
        
        # Yöntem 2: data-* attributelerinden çıkar
        soup = BeautifulSoup(content, 'html.parser')
        
        culprit_el = soup.find(attrs={'data-culprit-keywords': True})
        if culprit_el:
            culprit_keywords = culprit_el.get('data-culprit-keywords', '')
        
        explanation_el = soup.find(attrs={'data-explanation-keywords': True})
        if explanation_el:
            explanation_keywords = explanation_el.get('data-explanation-keywords', '')
        
        # Yöntem 3: id="culprit-keywords" ve id="explanation-keywords" elementlerinden
        culprit_div = soup.find(id='culprit-keywords')
        if culprit_div:
            culprit_keywords = culprit_div.get_text(strip=True)
        
        explanation_div = soup.find(id='explanation-keywords')
        if explanation_div:
            explanation_keywords = explanation_div.get_text(strip=True)
        
        return culprit_keywords, explanation_keywords
    except Exception as e:
        print(f"Keyword extraction error: {e}")
        return '', ''

def remove_background(image_path, output_path):
    """Remove white/light background from image and make it transparent"""
    try:
        img = Image.open(image_path).convert("RGBA")
        datas = img.getdata()
        new_data = []
        for item in datas:
            # Make white and near-white pixels transparent
            if item[0] > 220 and item[1] > 220 and item[2] > 220:
                new_data.append((255, 255, 255, 0))
            else:
                new_data.append(item)
        img.putdata(new_data)
        img.save(output_path, "PNG")
        return True
    except Exception as e:
        print(f"Background removal error: {e}")
        return False

app = Flask(__name__)
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.environ.get('SESSION_SECRET')
if not app.secret_key:
    if os.environ.get('REPLIT_DEPLOYMENT') == '1' or os.environ.get('IS_PRODUCTION') == '1' or os.environ.get('FLASK_ENV') == 'production':
        raise RuntimeError("SESSION_SECRET ortam değişkeni tanımlı değil — production'da güvenli bir secret key zorunludur.")
    app.secret_key = "dev-only-" + hashlib.sha256(b"gizemli_vaka_dev").hexdigest()

_TR_MONTHS = {
    1: 'Ocak', 2: 'Şubat', 3: 'Mart', 4: 'Nisan',
    5: 'Mayıs', 6: 'Haziran', 7: 'Temmuz', 8: 'Ağustos',
    9: 'Eylül', 10: 'Ekim', 11: 'Kasım', 12: 'Aralık'
}

@app.template_filter('tr_date')
def tr_date_filter(dt):
    if not dt:
        return ''
    return f"{dt.day:02d} {_TR_MONTHS.get(dt.month, '')} {dt.year}"

app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True
Compress(app)


# --- GOOGLE OAUTH AYARLARI ---
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_OAUTH_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# --- DOSYA YÜKLEME AYARLARI ---
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
app.config['MAX_FORM_MEMORY_SIZE'] = 500 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.errorhandler(413)
def too_large(e):
    flash("Dosya çok büyük! Maksimum 500 MB yüklenebilir.")
    return redirect(request.url), 302

def get_case_upload_folder(case_id):
    folder = os.path.join(UPLOAD_FOLDER, str(case_id))
    os.makedirs(folder, exist_ok=True)
    return folder

# --- VERİTABANI AYARLARI ---
import os
database_url = os.environ.get('DATABASE_URL')
if database_url:
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    engine_opts = {
        'pool_pre_ping': True,
        'pool_recycle': 120,
    }
    if database_url.startswith('postgres'):
        engine_opts.update({
            'pool_size': 3,
            'max_overflow': 5,
            'pool_timeout': 30,
            'connect_args': {
                'connect_timeout': 10,
                'options': '-c statement_timeout=30000',
            },
        })
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_opts
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- SUNUCU TARAFI SESSION (OAuth state için güvenilir) ---
app.config['SESSION_TYPE'] = 'sqlalchemy'
app.config['SESSION_SQLALCHEMY'] = db
app.config['SESSION_SQLALCHEMY_TABLE'] = 'flask_sessions'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
flask_session_ext = Session(app)

def export_initial_data():
    """Veritabanındaki TÜM verileri initial_data.json'a kaydet"""
    import json
    data = {}
    
    def model_to_dict(obj):
        return {col.name: getattr(obj, col.name) for col in obj.__table__.columns}
    
    def safe_export(model, name):
        try:
            return [model_to_dict(x) for x in model.query.all()]
        except:
            return []
    
    data['settings'] = safe_export(Settings, 'settings')
    data['pages'] = safe_export(Page, 'pages')
    data['how_to_play_steps'] = safe_export(HowToPlayStep, 'how_to_play_steps')
    data['posts'] = safe_export(Post, 'posts')
    data['blog_comments'] = safe_export(BlogComment, 'blog_comments')
    data['cases'] = safe_export(Case, 'cases')
    data['case_files'] = safe_export(CaseFile, 'case_files')
    data['suspects'] = safe_export(Suspect, 'suspects')
    data['users'] = safe_export(User, 'users')
    data['comments'] = safe_export(Comment, 'comments')
    data['orders'] = safe_export(Order, 'orders')
    data['purchases'] = safe_export(Purchase, 'purchases')
    data['hints'] = safe_export(Hint, 'hints')
    data['subscribers'] = safe_export(Subscriber, 'subscribers')
    data['email_logs'] = safe_export(EmailLog, 'email_logs')
    data['contact_messages'] = safe_export(ContactMessage, 'contact_messages')
    data['partners'] = safe_export(Partner, 'partners')
    data['partner_withdrawals'] = safe_export(PartnerWithdrawal, 'partner_withdrawals')
    data['partner_sales'] = safe_export(PartnerSale, 'partner_sales')
    data['discount_codes'] = safe_export(DiscountCode, 'discount_codes')
    data['suggestions'] = safe_export(Suggestion, 'suggestions')
    data['footer_links'] = safe_export(FooterLink, 'footer_links')
    data['faqs'] = safe_export(FAQ, 'faqs')
    data['game_progress'] = safe_export(GameProgress, 'game_progress')
    data['access_codes'] = safe_export(AccessCode, 'access_codes')
    data['team_purchases'] = safe_export(TeamPurchase, 'team_purchases')
    data['team_members'] = safe_export(TeamMember, 'team_members')
    data['team_messages'] = safe_export(TeamMessage, 'team_messages')
    
    try:
        with open('initial_data.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        print(f"JSON kaydetme hatası: {e}")

# --- YENİ: ÇÖZÜLEN VAKALAR TABLOSU ---
solved_cases = db.Table('solved_cases',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('case_id', db.String(50), db.ForeignKey('case.id'))
)

# --- VERİ MODELLERİ ---
class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(200), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)

class Page(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    content = db.Column(db.Text, nullable=False)

class HowToPlayStep(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_num = db.Column(db.Integer, default=1)
    badge = db.Column(db.String(50), default="ADIM 1")
    badge_en = db.Column(db.String(50), default="STEP 1")
    title = db.Column(db.String(200), nullable=False)
    title_en = db.Column(db.String(200), nullable=True)
    content = db.Column(db.Text, nullable=False)
    content_en = db.Column(db.Text, nullable=True)
    image = db.Column(db.String(200), nullable=True)
    is_active = db.Column(db.Boolean, default=True)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(100), nullable=True)
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)
    blog_comments = db.relationship('BlogComment', backref='post', lazy=True)

class BlogComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CaseIdea(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(50), default='unsolved')
    tags = db.Column(db.Text, nullable=True)
    source_type = db.Column(db.String(50), nullable=True)
    difficulty = db.Column(db.String(20), default='Orta')
    setting = db.Column(db.String(200), nullable=True)
    era = db.Column(db.String(50), nullable=True)
    is_used = db.Column(db.Boolean, default=False)
    case_data_json = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='idea')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Case(db.Model):
    id = db.Column(db.String(50), primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    title_en = db.Column(db.String(100), nullable=True)
    price = db.Column(db.Float, nullable=False)
    image = db.Column(db.String(100), nullable=False)
    video = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    description_en = db.Column(db.Text, nullable=True)
    solution = db.Column(db.String(100), nullable=True, default="emily")
    old_price = db.Column(db.Float, default=0.0)
    discount_rate = db.Column(db.Integer, default=0)
    difficulty = db.Column(db.String(20), default="Orta")
    is_active = db.Column(db.Boolean, default=True)
    report_case_name = db.Column(db.String(100)) 
    report_case_name_en = db.Column(db.String(100))
    report_company = db.Column(db.String(100), default="Soğuk Vaka A.Ş.")
    report_company_en = db.Column(db.String(100), default="Cold Case Inc.")
    success_message = db.Column(db.Text)
    success_message_en = db.Column(db.Text)
    success_file = db.Column(db.String(255), nullable=True)
    police_department = db.Column(db.String(100), default="Stonewood Polis Departmanı")
    police_department_en = db.Column(db.String(100), default="Stonewood Police Dept.")
    report_letter = db.Column(db.Text)
    report_letter_en = db.Column(db.Text)
    commissioner_name = db.Column(db.String(100), default="Başkomiser Morris")
    commissioner_name_en = db.Column(db.String(100), default="Chief Morris")
    warning_text = db.Column(db.Text, default="Lütfen sonucu diğer oyunculara söylemeyin.")
    warning_text_en = db.Column(db.Text, default="Please don't reveal the answer to other players.")
    instructions_text = db.Column(db.Text, default="Tüm kanıtları dikkatle inceleyin ve raporunuzu gönderin.")
    instructions_text_en = db.Column(db.Text, default="Carefully examine all evidence and submit your report.")
    report_greeting = db.Column(db.String(50), default="Şef,")
    report_greeting_en = db.Column(db.String(50), default="Chief,")
    report_intro_text = db.Column(db.Text)
    report_intro_text_en = db.Column(db.Text)
    report_suspect_question = db.Column(db.Text)
    report_suspect_question_en = db.Column(db.Text)
    report_confirmation_text = db.Column(db.Text)
    report_confirmation_text_en = db.Column(db.Text)
    report_signature_name = db.Column(db.String(100), default="Dedektif Ali Turan")
    report_signature_name_en = db.Column(db.String(100), default="Detective Ali Turan")
    demo_enabled = db.Column(db.Boolean, default=False)
    demo_summary = db.Column(db.Text, nullable=True)
    demo_summary_en = db.Column(db.Text, nullable=True)
    game_type = db.Column(db.String(20), default='both')  # 'individual', 'team', 'both'
    culprit_keywords = db.Column(db.Text, nullable=True)  # Virgülle ayrılmış suçlu anahtar kelimeleri
    explanation_keywords = db.Column(db.Text, nullable=True)  # Virgülle ayrılmış açıklama anahtar kelimeleri

    files = db.relationship('CaseFile', backref='case', lazy=True, cascade="all, delete-orphan")
    suspects = db.relationship('Suspect', backref='case', lazy=True, cascade="all, delete-orphan")
    comments = db.relationship('Comment', backref='case', lazy=True, cascade="all, delete-orphan")

class CaseFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(100), nullable=False)
    display_name = db.Column(db.String(100), nullable=True)
    category = db.Column(db.String(50), nullable=False)
    sub_category = db.Column(db.String(50), nullable=True)
    file_ext = db.Column(db.String(10))
    youtube_link = db.Column(db.String(255), nullable=True)
    case_id = db.Column(db.String(50), db.ForeignKey('case.id'), nullable=False)

class Suspect(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    is_culprit = db.Column(db.Boolean, default=False)
    case_id = db.Column(db.String(50), db.ForeignKey('case.id'), nullable=False)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    screen_name = db.Column(db.String(100))
    billing_address = db.Column(db.Text)
    unlocked_cases = db.Column(db.String(500), default="stonewood")
    unlocked_hints = db.Column(db.String(500), default="")
    score = db.Column(db.Integer, default=0)
    reset_token = db.Column(db.String(100), nullable=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)
    solved_cases_list = db.relationship('Case', secondary=solved_cases, backref=db.backref('solvers', lazy='dynamic'))
    orders = db.relationship('Order', backref='owner', lazy=True)
    comments = db.relationship('Comment', backref='user', lazy=True)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    rating = db.Column(db.Integer, default=5)
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)
    approved = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    case_id = db.Column(db.String(50), db.ForeignKey('case.id'), nullable=False)

class CaseNote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    case_id = db.Column(db.String(50), db.ForeignKey('case.id'), nullable=False)
    content = db.Column(db.Text, default='')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

class EncryptedClue(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.String(50), db.ForeignKey('case.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    encrypted_text = db.Column(db.Text, nullable=False)
    cipher_type = db.Column(db.String(30), nullable=False)
    cipher_hint = db.Column(db.Text, nullable=True)
    unlock_instructions = db.Column(db.Text, nullable=True)
    correct_answer = db.Column(db.String(500), nullable=False)
    decrypted_reveal = db.Column(db.Text, nullable=False)
    order_num = db.Column(db.Integer, default=0)

class ClueSolve(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    clue_id = db.Column(db.Integer, db.ForeignKey('encrypted_clue.id'), nullable=False)
    solved_at = db.Column(db.DateTime, default=datetime.utcnow)

class EvidenceFlag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    case_id = db.Column(db.String(50), db.ForeignKey('case.id'), nullable=False)
    file_id = db.Column(db.Integer, db.ForeignKey('case_file.id'), nullable=False)
    flag_color = db.Column(db.String(20), default='red')
    note = db.Column(db.String(300), default='')

class InvestigationBoard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    case_id = db.Column(db.String(50), db.ForeignKey('case.id'), nullable=False)
    state_json = db.Column(db.Text, default='{"cards":[],"connections":[]}')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(20), unique=True, nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default="Tamamlanmış")
    total_price = db.Column(db.Float, nullable=False)
    item_count = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    case_id = db.Column(db.String(50), db.ForeignKey('case.id'), nullable=False)
    amount = db.Column(db.Float, default=0)
    is_paid = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='purchases')
    case = db.relationship('Case', backref='purchases')

class Hint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hint_text = db.Column(db.Text, nullable=False)
    hint_text_en = db.Column(db.Text, nullable=True)
    hint_file = db.Column(db.String(255), nullable=True)
    show_datetime = db.Column(db.DateTime, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    unlock_price = db.Column(db.Float, default=0)
    case_id = db.Column(db.String(50), db.ForeignKey('case.id'), nullable=False)
    case = db.relationship('Case', backref=db.backref('hints', lazy=True, cascade="all, delete-orphan"))

class Subscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    source = db.Column(db.String(50), default='newsletter')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class EmailLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    recipient_type = db.Column(db.String(20), default='all')
    recipient_count = db.Column(db.Integer, default=0)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_by = db.Column(db.String(50), default='admin')

class ContactMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    subject = db.Column(db.String(50), nullable=True)
    message = db.Column(db.Text, nullable=False)
    reply = db.Column(db.Text, nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    is_replied = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    replied_at = db.Column(db.DateTime, nullable=True)

class SitePopup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    popup_type = db.Column(db.String(20), default='info')
    start_date = db.Column(db.DateTime, nullable=True)
    end_date = db.Column(db.DateTime, nullable=True)
    target_audience = db.Column(db.String(20), default='all')
    priority = db.Column(db.Integer, default=0)
    position = db.Column(db.String(20), default='center')
    width = db.Column(db.Integer, default=500)
    height = db.Column(db.Integer, nullable=True)
    overlay_opacity = db.Column(db.Float, default=0.5)
    image_filename = db.Column(db.String(300), nullable=True)
    button_text = db.Column(db.String(100), nullable=True)
    button_url = db.Column(db.String(500), nullable=True)
    link_target = db.Column(db.String(20), default='_self')
    is_active = db.Column(db.Boolean, default=True)
    is_closeable = db.Column(db.Boolean, default=True)
    show_once_per_user = db.Column(db.Boolean, default=False)
    hide_duration = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Partner(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref='partner_profile')
    bio = db.Column(db.Text, nullable=False)
    instagram = db.Column(db.String(100))
    youtube = db.Column(db.String(100))
    tiktok = db.Column(db.String(100))
    twitter = db.Column(db.String(100))
    website = db.Column(db.String(200))
    iban = db.Column(db.String(50))
    iban_name = db.Column(db.String(100))
    commission_rate = db.Column(db.Integer, default=20)
    total_earnings = db.Column(db.Float, default=0)
    pending_earnings = db.Column(db.Float, default=0)
    withdrawn_earnings = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime, nullable=True)
    discount_codes = db.relationship('DiscountCode', backref='partner', lazy=True)

class PartnerWithdrawal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partner.id'), nullable=False)
    partner = db.relationship('Partner', backref='withdrawals')
    amount = db.Column(db.Float, nullable=False)
    iban = db.Column(db.String(50), nullable=False)
    iban_name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)
    admin_note = db.Column(db.Text)
    receipt_file = db.Column(db.String(255), nullable=True)

class PartnerSale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partner.id'), nullable=False)
    partner = db.relationship('Partner', backref='sales')
    discount_code_id = db.Column(db.Integer, db.ForeignKey('discount_code.id'), nullable=False)
    discount_code = db.relationship('DiscountCode', backref='partner_sales')
    case_id = db.Column(db.String(50), db.ForeignKey('case.id'), nullable=False)
    case = db.relationship('Case')
    sale_amount = db.Column(db.Float, nullable=False)
    commission_amount = db.Column(db.Float, nullable=False)
    buyer_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class DiscountCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    discount_percent = db.Column(db.Integer, default=0)
    discount_amount = db.Column(db.Float, default=0)
    case_id = db.Column(db.String(50), db.ForeignKey('case.id'), nullable=True)
    case = db.relationship('Case', backref='discount_codes')
    is_active = db.Column(db.Boolean, default=True)
    usage_limit = db.Column(db.Integer, default=0)
    usage_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partner.id'), nullable=True)

class Dealer(db.Model):
    """Bayi (kafe/firma) — oyun başına satıştan komisyon kazanan iş ortağı."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref='dealer_profile')
    cafe_name = db.Column(db.String(150), nullable=False)
    contact_name = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(150))
    city = db.Column(db.String(80))
    address = db.Column(db.Text)
    iban = db.Column(db.String(50))
    iban_name = db.Column(db.String(100))
    dealer_code = db.Column(db.String(20), unique=True, nullable=False)
    commission_rate = db.Column(db.Integer, default=20)
    total_earnings = db.Column(db.Float, default=0)
    pending_earnings = db.Column(db.Float, default=0)
    withdrawn_earnings = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime, nullable=True)

class DealerQrTemplate(db.Model):
    """Bayinin oluşturduğu QR şablonu — masa bazlı veya kafe geneli."""
    id = db.Column(db.Integer, primary_key=True)
    dealer_id = db.Column(db.Integer, db.ForeignKey('dealer.id'), nullable=False)
    dealer = db.relationship('Dealer', backref=db.backref('qr_templates', lazy=True, cascade="all, delete-orphan"))
    name = db.Column(db.String(120), nullable=False)
    qr_type = db.Column(db.String(20), default='general')  # 'table' | 'general'
    table_number = db.Column(db.String(30), nullable=True)
    token = db.Column(db.String(40), unique=True, nullable=False)
    case_ids = db.Column(db.Text)  # virgülle ayrılmış vaka id listesi (boşsa tüm aktif vakalar)
    is_active = db.Column(db.Boolean, default=True)
    scan_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class DealerSale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dealer_id = db.Column(db.Integer, db.ForeignKey('dealer.id'), nullable=False)
    dealer = db.relationship('Dealer', backref='sales')
    qr_template_id = db.Column(db.Integer, db.ForeignKey('dealer_qr_template.id'), nullable=True)
    qr_template = db.relationship('DealerQrTemplate')
    case_id = db.Column(db.String(50), db.ForeignKey('case.id'), nullable=False)
    case = db.relationship('Case')
    sale_amount = db.Column(db.Float, nullable=False)
    commission_amount = db.Column(db.Float, nullable=False)
    buyer_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class DealerWithdrawal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dealer_id = db.Column(db.Integer, db.ForeignKey('dealer.id'), nullable=False)
    dealer = db.relationship('Dealer', backref='withdrawals')
    amount = db.Column(db.Float, nullable=False)
    iban = db.Column(db.String(50), nullable=False)
    iban_name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)
    admin_note = db.Column(db.Text)
    receipt_file = db.Column(db.String(255), nullable=True)

class Suggestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    suggestion = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class FooterLink(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    column = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(100), nullable=False)
    title_en = db.Column(db.String(100), nullable=True)
    url = db.Column(db.String(200), nullable=False)
    order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)

class FAQ(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(500), nullable=False)
    question_en = db.Column(db.String(500), nullable=True)
    answer = db.Column(db.Text, nullable=False)
    answer_en = db.Column(db.Text, nullable=True)
    order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class GameProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    case_id = db.Column(db.String(50), db.ForeignKey('case.id'), nullable=False)
    attempts_used = db.Column(db.Integer, default=0)
    hints_used = db.Column(db.Integer, default=0)
    points_earned = db.Column(db.Float, default=0)
    is_solved = db.Column(db.Boolean, default=False)
    is_failed = db.Column(db.Boolean, default=False)
    last_attempt_time = db.Column(db.DateTime)
    play_time_seconds = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('game_progress', lazy=True))
    case = db.relationship('Case', backref=db.backref('game_progress', lazy=True))

class AccessCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    case_id = db.Column(db.String(50), db.ForeignKey('case.id'), nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    used_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    platform = db.Column(db.String(50), default='Trendyol')
    sale_price = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    used_at = db.Column(db.DateTime, nullable=True)
    case = db.relationship('Case', backref=db.backref('access_codes', lazy=True))
    used_by = db.relationship('User', backref=db.backref('used_codes', lazy=True))

class TeamPurchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.String(50), db.ForeignKey('case.id'), nullable=False)
    organizer_email = db.Column(db.String(150), nullable=False)
    organizer_name = db.Column(db.String(100), nullable=False)
    team_count = db.Column(db.Integer, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    payment_status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    partner_code = db.Column(db.String(50), nullable=True)
    dealer_code = db.Column(db.String(20), nullable=True)
    dealer_qr_template_id = db.Column(db.Integer, nullable=True)
    case = db.relationship('Case', backref=db.backref('team_purchases', lazy=True))
    members = db.relationship('TeamMember', backref='team_purchase', lazy=True, cascade="all, delete-orphan")

class TeamMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_purchase_id = db.Column(db.Integer, db.ForeignKey('team_purchase.id'), nullable=False)
    team_number = db.Column(db.Integer, nullable=False)
    team_name = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(150), nullable=False)
    access_token = db.Column(db.String(100), unique=True, nullable=False)
    accessed = db.Column(db.Boolean, default=False)
    completed = db.Column(db.Boolean, default=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    play_time_seconds = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class TeamMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_purchase_id = db.Column(db.Integer, db.ForeignKey('team_purchase.id'), nullable=False)
    team_number = db.Column(db.Integer, nullable=False)
    sender_email = db.Column(db.String(150), nullable=False)
    sender_name = db.Column(db.String(100), nullable=True)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    team_purchase = db.relationship('TeamPurchase', backref=db.backref('messages', lazy=True))

# Zorluk puanları
DIFFICULTY_POINTS = {
    'Kolay': 100,
    'Orta': 200,
    'Zor': 300
}

# --- OTOMATİK VERİ KAYDETME ---
@app.after_request
def auto_save_data(response):
    """Veritabanı değişikliklerinden sonra verileri otomatik kaydet"""
    save_paths = ['/admin', '/register', '/checkout', '/payment', '/subscribe', '/team', '/redeem', '/partner']
    if request.method == 'POST' and any(request.path.startswith(p) for p in save_paths):
        try:
            export_initial_data()
        except:
            pass
    return response

@app.after_request
def add_cache_headers(response):
    if request.path.startswith('/static/'):
        if any(request.path.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.ico', '.svg']):
            response.headers['Cache-Control'] = 'public, max-age=604800'
        elif any(request.path.endswith(ext) for ext in ['.css', '.js']):
            response.headers['Cache-Control'] = 'public, max-age=86400'
        elif any(request.path.endswith(ext) for ext in ['.mp4', '.webm', '.ogg']):
            response.headers['Cache-Control'] = 'public, max-age=604800'
    else:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response

# --- GLOBAL VERİ SAĞLAYICI ---
@app.context_processor
def inject_global_data():
    cart = session.get('cart', [])
    lang = session.get('lang', 'tr')
    all_db_settings = Settings.query.all()
    s = {item.key: item.value for item in all_db_settings} if all_db_settings else {}
    nav_menu = []
    for i in range(1, 5):
        main_text = s.get(f'nav{i}_text')
        if main_text:
            subs = []
            for j in range(1, 4):
                sub_text = s.get(f'nav{i}_sub{j}_text')
                if sub_text:
                    subs.append({'text': sub_text, 'url': s.get(f'nav{i}_sub{j}_url', '#')})
            nav_menu.append({'text': main_text, 'url': s.get(f'nav{i}_url', '#'), 'subs': subs})
    currency = session.get('currency', 'TRY')
    rates = {'TRY': 1.0, 'USD': 0.029, 'EUR': 0.027, 'GBP': 0.023}
    symbols = {'TRY': '₺', 'USD': '$', 'EUR': '€', 'GBP': '£'}
    t = translations.get(lang, translations['tr'])
    def import_datetime():
        return datetime.now()
    unread_messages_count = 0
    if session.get('username') == 'admin':
        try:
            unread_messages_count = ContactMessage.query.filter_by(is_read=False).count()
        except Exception:
            pass
    return dict(settings=s, nav_menu=nav_menu, custom_pages=Page.query.all(), cart_count=len(cart), 
                current_user=session.get('username'), current_currency=currency, 
                currency_symbol=symbols.get(currency, '₺'), currency_rate=rates.get(currency, 1.0),
                cases=Case.query.filter_by(is_active=True).all(), lang=lang, t=t, import_datetime=import_datetime,
                unread_messages_count=unread_messages_count)

@app.route('/media/<path:filepath>')
def serve_media(filepath):
    uploads_dir = os.path.join(app.static_folder, 'uploads')
    local_path = os.path.join(uploads_dir, filepath)
    if os.path.exists(local_path):
        directory = os.path.dirname(local_path)
        filename = os.path.basename(local_path)
        return send_from_directory(directory, filename)
    return "File not found", 404


# Words that can follow an officer title but are NOT a person's name (annotation
# labels like "Dedektif Notu", unit names like "Komiser ... Şubesi"). Used as a
# negative lookahead so labels are preserved and only real names are swapped.
_OFFICER_NON_NAME = (
    'Notu', 'Notları', 'Notlar', 'Notunu', 'Not',
    'Değerlendirmesi', 'Değerlendirme', 'Raporu', 'Raporunu', 'Rapor',
    'Analizi', 'Analiz', 'Özeti', 'Özet', 'El', 'Yazısı',
    'Birimi', 'Birim', 'Şubesi', 'Şube', 'Bürosu', 'Büro', 'Büroları',
    'Amirliği', 'Amiri', 'Müdürlüğü', 'Müdürü', 'Müdür',
    'Şefliği', 'Şefi', 'Bölümü', 'Servisi', 'Ekibi', 'Ekip', 'Timi', 'Grubu',
    'Polis', 'Memuru', 'Memur', 'Yorumu', 'Görüşü', 'Görüş',
    'Açıklaması', 'Onayı', 'İmzası', 'Kararı', 'Talimatı',
    'Dosyası', 'Tespiti', 'Gözlemi', 'Soruşturması', 'Soruşturma',
    'Sicil', 'Yardımcısı', 'Yrd', 'Yard',
)

# Officer ranks that prefix the investigating detective's name.
_OFFICER_TITLE_ALT = (
    r'Başkomiser Yardımcısı|Başkomiser|Komiser Yardımcısı|'
    r'Komiser Yrd\.?|Komiser Yard\.?|Komiser|Dedektif'
)
# A 1-3 word proper name (each word starts uppercase, continues lowercase).
_OFFICER_NAME_PAT = r'[A-ZÇĞİÖŞÜ][a-zçğıöşü]+(?:\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü]+){0,2}'
_OFFICER_NON_NAME_ALT = '|'.join(_OFFICER_NON_NAME)

# Bare (untitled) lead-detective names per case — these are the player's on-page
# identity and get swapped for the player's name. Suspects/witnesses are excluded.
_CASE_INVESTIGATOR_NAMES = {
    '104.2 Çanakkale Paradoksu': ['Ali Turan'],
    'colun-muhurlu-haritasi': ['Orhan Demir'],
    'vaka-kopyaci-heykeltiras': ['Orhan Demir'],
}
# Names that must NEVER be replaced (e.g. period/historical figures) — protected
# before any substitution and restored afterwards. colun's 1872 layer features
# Başkomiser Emirhan Yılmaz; the modern player cannot be a detective in 1872.
_CASE_PRESERVE_NAMES = {
    'colun-muhurlu-haritasi': ['Emirhan Yılmaz', 'Emirhan YILMAZ'],
}


def personalize_case_html(html_content, display_name, case_id=None):
    """Swap the investigating-officer / detective identity for the current
    player's display name so each player feels like the detective on the case.

    Only the *investigator* identity is personalized. Suspects, witnesses,
    forensic experts and historical/period figures are left untouched, and
    annotation labels (e.g. "Dedektif Notu", "Başkomiser Notu") are preserved —
    only the name part is ever swapped, never the label."""
    name = (display_name or '').strip() or 'Dedektif'
    # When prefixing the rank "Dedektif", avoid "Dedektif Dedektif" if the player
    # name is missing (anonymous fallback already is "Dedektif").
    titled = name if name.lower().startswith('dedektif') else f'Dedektif {name}'

    # 0) Protect names that must never change (historical/period figures).
    sentinels = {}
    for i, preserved in enumerate(_CASE_PRESERVE_NAMES.get(case_id, [])):
        token = f'\x00KEEP{i}\x00'
        sentinels[token] = preserved
        html_content = re.sub(r'\b' + re.escape(preserved) + r'\b', token, html_content)

    # Callable replacements so a player name containing regex-replacement
    # metacharacters (\1, \g<0>, backslashes) is inserted literally, never
    # interpreted (avoids 500s / corrupted output).
    repl_name = lambda m: name
    repl_memuru = lambda m: f'Soruşturma Memuru: {name}'
    repl_titled = lambda m: titled

    # 1) Explicit "(Adınız)" placeholder -> player's name.
    html_content = re.sub(r'\(\s*Ad[ıi]n[ıi]z\s*\)', repl_name, html_content, flags=re.IGNORECASE)

    # 2) "Soruşturma Memuru: <optional rank> <Name>" -> "Soruşturma Memuru: <name>".
    html_content = re.sub(
        r'Soruşturma\s+Memuru\s*:?\s*'
        r'(?:Komiser Yardımcısı\s+|Komiser Yrd\.?\s+|Başkomiser\s+|Komiser\s+|Dedektif\s+|Memur\s+)?'
        + _OFFICER_NAME_PAT,
        repl_memuru,
        html_content,
    )

    # 3) "<Rank> <Name>" -> "Dedektif <name>", skipping annotation/unit words.
    html_content = re.sub(
        r'(?:' + _OFFICER_TITLE_ALT + r')\s+'
        r'(?!(?:' + _OFFICER_NON_NAME_ALT + r')\b)'
        + _OFFICER_NAME_PAT,
        repl_titled,
        html_content,
    )

    # 4) Per-case bare (untitled) lead-detective names.
    for inv in _CASE_INVESTIGATOR_NAMES.get(case_id, []):
        html_content = re.sub(r'\b' + re.escape(inv) + r'\b', repl_name, html_content)

    # 5) Restore protected names.
    for token, preserved in sentinels.items():
        html_content = html_content.replace(token, preserved)

    return html_content


def _current_player_display_name():
    """Best display name for the logged-in player: screen name, then full name,
    then username, falling back to 'Dedektif'."""
    uid = session.get('user_id')
    if uid:
        u = db.session.get(User, uid)
        if u:
            full_name = ' '.join(filter(None, [u.first_name, u.last_name])).strip()
            chosen = (u.screen_name or '').strip() or full_name or (u.username or '').strip()
            if chosen:
                return chosen
    return (session.get('username') or 'Dedektif')


@app.route('/vaka/<case_id>/dosya/<path:filename>')
def serve_personalized_file(case_id, filename):
    """Serve HTML case files with the investigating-detective identity replaced by
    the current player's display name (so the player feels like the detective)."""
    # Resolve and confine the path to the uploads root (the <path:filename>
    # segment could otherwise contain '..' to escape the case folder).
    uploads_root = os.path.realpath(UPLOAD_FOLDER)
    file_path = os.path.realpath(os.path.join(UPLOAD_FOLDER, case_id, filename))
    if os.path.commonpath([uploads_root, file_path]) != uploads_root:
        abort(404)
    if not os.path.isfile(file_path):
        abort(404)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext in ('html', 'htm'):
        display_name = _current_player_display_name()
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        content = personalize_case_html(content, display_name, case_id)
        response = make_response(content)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response
    directory = os.path.dirname(file_path)
    basename = os.path.basename(file_path)
    return send_from_directory(directory, basename)


# --- PARA BİRİMİ ---
@app.route('/set-currency/<code>')
def set_currency(code):
    if code in ['TRY', 'USD', 'EUR']: session['currency'] = code
    return redirect(request.referrer or url_for('index'))

# --- DİL DEĞİŞTİRME ---
@app.route('/set-lang/<code>')
def set_lang(code):
    if code in ['tr', 'en']: session['lang'] = code
    resp = redirect(request.referrer or url_for('index'))
    return resp

# --- ANA ROTALAR ---
@app.route('/')
def index():
    return render_template('index.html', cases=Case.query.filter_by(is_active=True).all(), posts=Post.query.order_by(Post.date_posted.desc()).limit(5).all())

@app.route('/leaderboard')
def leaderboard():
    from sqlalchemy import exists
    top_users = User.query.filter(
        User.username != 'admin',
        exists().where(Purchase.user_id == User.id)
    ).order_by(User.score.desc()).limit(50).all()
    
    from sqlalchemy import func
    team_rankings = db.session.query(
        TeamMember.team_name,
        TeamPurchase.case_id,
        Case.title,
        Case.title_en,
        func.count(TeamMember.id).label('member_count'),
        func.sum(func.cast(TeamMember.completed, db.Integer)).label('completed_count'),
        func.min(TeamMember.completed_at).label('first_complete'),
        func.max(TeamMember.play_time_seconds).label('max_play_time')
    ).join(TeamPurchase, TeamMember.team_purchase_id == TeamPurchase.id
    ).join(Case, TeamPurchase.case_id == Case.id
    ).filter(TeamPurchase.payment_status == 'completed'
    ).filter(TeamMember.completed == True
    ).group_by(TeamMember.team_name, TeamPurchase.case_id, Case.title, Case.title_en
    ).order_by(func.min(TeamMember.completed_at).desc()
    ).limit(20).all()

    # Bireysel sıralama için en iyi süreleri hesapla
    best_times = db.session.query(
        GameProgress.user_id,
        GameProgress.case_id,
        GameProgress.play_time_seconds
    ).filter(
        GameProgress.is_solved == True,
        GameProgress.play_time_seconds != None
    ).all()
    user_best_time = {}
    for bt in best_times:
        uid = bt.user_id
        if uid not in user_best_time or (bt.play_time_seconds and bt.play_time_seconds < user_best_time[uid]):
            user_best_time[uid] = bt.play_time_seconds
    
    return render_template('leaderboard.html', users=top_users, team_rankings=team_rankings, user_best_time=user_best_time)

@app.route('/subscribe', methods=['POST'])
def subscribe():
    email = request.form.get('email')
    if email:
        existing = Subscriber.query.filter_by(email=email).first()
        if not existing:
            subscriber = Subscriber(email=email, source='newsletter')
            db.session.add(subscriber)
            db.session.commit()
            flash("Bültenimize başarıyla abone oldunuz!", "success")
        else:
            flash("Bu email adresi zaten kayıtlı.", "info")
    return redirect(url_for('index'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter(db.func.lower(User.email) == email).first()
        if user:
            import secrets
            token = secrets.token_urlsafe(32)
            user.reset_token = token
            user.reset_token_expiry = datetime.utcnow() + timedelta(hours=1)
            db.session.commit()
            # Reset bağlantısını oluştur
            base_url = request.host_url.rstrip('/')
            reset_url = f"{base_url}/reset-password/{token}"
            # E-posta HTML içeriği
            html_body = f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#fff;padding:40px;border-radius:12px;">
    <div style="text-align:center;margin-bottom:30px;">
        <h1 style="color:#0C1430;font-size:28px;margin:0;">🔑 Şifre Sıfırlama</h1>
        <p style="color:#888;margin-top:8px;font-size:14px;">Gizemli Vaka</p>
    </div>
    <p style="color:#444;line-height:1.7;">Merhaba <strong>{user.first_name or user.username}</strong>,</p>
    <p style="color:#444;line-height:1.7;">
        Hesabınız için şifre sıfırlama talebinde bulundunuz.
        Aşağıdaki butona tıklayarak yeni şifrenizi belirleyebilirsiniz.
    </p>
    <div style="text-align:center;margin:36px 0;">
        <a href="{reset_url}"
           style="background:#e74c3c;color:#fff;padding:16px 40px;border-radius:30px;
                  text-decoration:none;font-weight:900;font-size:16px;display:inline-block;">
            🔑 Şifremi Sıfırla
        </a>
    </div>
    <div style="background:#fff8e1;border-left:4px solid #FFD700;padding:16px;border-radius:8px;margin:20px 0;">
        <p style="margin:0;color:#555;font-size:13px;">
            ⏰ Bu bağlantı <strong>1 saat</strong> geçerlidir.<br>
            🔒 Eğer bu talebi siz yapmadıysanız bu e-postayı görmezden gelebilirsiniz, şifreniz değişmeyecektir.
        </p>
    </div>
    <p style="color:#aaa;font-size:12px;margin-top:30px;text-align:center;">
        Bağlantıyı kopyalayarak tarayıcınıza da yapıştırabilirsiniz:<br>
        <a href="{reset_url}" style="color:#aaa;word-break:break-all;">{reset_url}</a>
    </p>
</div>"""
            ok, msg = send_smtp_email(
                to_email=user.email,
                subject='🔑 Şifre Sıfırlama — Gizemli Vaka',
                html_body=html_body,
                plain_text=f"Şifrenizi sıfırlamak için şu bağlantıyı kullanın: {reset_url}"
            )
            if not ok:
                # SMTP başarısız — loglayıp kullanıcıya genel mesaj ver
                app.logger.error(f"Password reset email failed: {msg}")
        # Güvenlik: e-posta kayıtlı olsun ya da olmasın aynı mesajı göster
        return render_template('forgot_password.html',
                               sent=True,
                               sent_email=email)
    return render_template('forgot_password.html', sent=False)

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    from datetime import timedelta
    user = User.query.filter_by(reset_token=token).first()
    # Token yoksa veya süresi dolmuşsa
    if not user or not user.reset_token_expiry or user.reset_token_expiry < datetime.utcnow():
        return render_template('reset_password.html', expired=True, success=False)

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('password_confirm', '')
        if len(password) < 8:
            flash('Şifre en az 8 karakter olmalıdır.', 'danger')
            return render_template('reset_password.html', expired=False, success=False)
        if password != confirm:
            flash('Şifreler eşleşmiyor.', 'danger')
            return render_template('reset_password.html', expired=False, success=False)
        user.password = generate_password_hash(password)
        user.reset_token = None
        user.reset_token_expiry = None
        db.session.commit()
        return render_template('reset_password.html', expired=False, success=True)

    return render_template('reset_password.html', expired=False, success=False)

@app.route('/how-to-play')
def how_to_play():
    steps = HowToPlayStep.query.filter_by(is_active=True).order_by(HowToPlayStep.order_num).all()
    return render_template('how_to_play.html', steps=steps)

@app.route('/gift-cards')
def gift_cards():
    cases = Case.query.filter_by(is_active=True).all()
    return render_template('gift_cards.html', cases=cases)

@app.route('/blog')
def blog():
    resp = make_response(render_template('blog.html', posts=Post.query.all()))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip()
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()
        if first_name and last_name and email and subject:
            try:
                msg = ContactMessage(first_name=first_name, last_name=last_name, email=email, subject=subject, message=message)
                db.session.add(msg)
                db.session.commit()
                app.logger.info(f"Contact message saved: from={email} subject={subject}")
                flash("Mesajınız gönderildi. En kısa sürede size döneceğiz.")
                return redirect(url_for('contact'))
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Contact message save error: {e}")
                flash("Mesajınız gönderilemedi, lütfen tekrar deneyin.")
        else:
            flash("Lütfen tüm alanları doldurun.")
    return render_template('contact.html')

@app.route('/suggestion-box', methods=['GET', 'POST'])
def suggestion_box():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        suggestion = request.form.get('suggestion', '').strip()
        if name and email and suggestion:
            s = Suggestion(name=name, email=email, suggestion=suggestion)
            db.session.add(s)
            db.session.commit()
            flash("Oneriniz basariyla gonderildi. Tesekkur ederiz!")
            return redirect(url_for('suggestion_box'))
        else:
            flash("Lutfen tum alanlari doldurun.")
    return render_template('suggestion_box.html')

@app.route('/blog/<int:post_id>')
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    return render_template('post_detail.html', post=post)

@app.route('/blog/<int:post_id>/comment', methods=['POST'])
def add_blog_comment(post_id):
    post = Post.query.get_or_404(post_id)
    comment = BlogComment(
        post_id=post_id,
        name=request.form.get('name'),
        content=request.form.get('comment'),
        approved=False
    )
    db.session.add(comment)
    db.session.commit()
    flash('Yorumunuz gönderildi. Onaylandıktan sonra görünecektir.')
    return redirect(url_for('post_detail', post_id=post_id))

@app.route('/reviews')
def reviews():
    approved_comments = Comment.query.filter_by(approved=True).order_by(Comment.date_posted.desc()).all()
    return render_template('reviews.html', comments=approved_comments)

@app.route('/teams')
def teams():
    team_cases = Case.query.filter(Case.game_type.in_(['team', 'both']), Case.is_active==True).all()
    return render_template('teams.html', cases=team_cases)

@app.route('/team-purchase', methods=['GET', 'POST'])
def team_purchase():
    cases = Case.query.filter(Case.game_type.in_(['team', 'both']), Case.is_active==True).all()
    lang = session.get('lang', 'tr')

    # Ortak ref kodunu URL'den yakala ve session'a kaydet
    ref_param = request.args.get('ref')
    if ref_param:
        discount = DiscountCode.query.filter_by(code=ref_param, is_active=True).first()
        if discount and discount.partner_id:
            session['team_partner_ref'] = ref_param

    if request.method == 'POST':
        case_id = request.form.get('case_id')
        organizer_name = request.form.get('organizer_name', '').strip()
        organizer_email = request.form.get('organizer_email', '').strip()
        try:
            team_count = int(request.form.get('team_count', 1))
        except:
            team_count = 1
        
        import re
        email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
        
        if team_count < 1 or team_count > 20:
            flash('Takım sayısı 1-20 arasında olmalıdır.' if lang == 'tr' else 'Team count must be between 1-20.')
            return redirect(url_for('team_purchase'))
        
        if not organizer_email or not email_pattern.match(organizer_email):
            flash('Geçerli bir e-posta adresi giriniz.' if lang == 'tr' else 'Please enter a valid email address.')
            return redirect(url_for('team_purchase'))
        
        case = Case.query.get_or_404(case_id)
        team_fee = case.price * 0.50
        price_per_team = case.price + team_fee
        total_price = price_per_team * team_count
        
        all_members = []
        for team_num in range(1, team_count + 1):
            team_name = request.form.get(f'team_{team_num}_name', '').strip()
            if not team_name:
                team_name = f"Takım {team_num}" if lang == 'tr' else f"Team {team_num}"
            member_emails = request.form.getlist(f'team_{team_num}_emails[]')
            valid_emails = [e.strip() for e in member_emails if e.strip() and email_pattern.match(e.strip())]
            if len(valid_emails) > 6:
                flash(f'Takım {team_num}: Her takımda en fazla 6 e-posta adresi olabilir.' if lang == 'tr' else f'Team {team_num}: Each team can have at most 6 email addresses.')
                return redirect(url_for('team_purchase'))
            all_members.append((team_num, team_name, valid_emails))
        
        _dealer_ref = session.pop('dealer_ref', None) or {}
        purchase = TeamPurchase(
            case_id=case_id,
            organizer_email=organizer_email,
            organizer_name=organizer_name,
            team_count=team_count,
            total_price=total_price,
            payment_status='pending',
            partner_code=session.pop('team_partner_ref', None),
            dealer_code=_dealer_ref.get('code'),
            dealer_qr_template_id=_dealer_ref.get('qr_template_id')
        )
        db.session.add(purchase)
        db.session.commit()
        
        for team_num, team_name, emails in all_members:
            for email in emails:
                member = TeamMember(
                    team_purchase_id=purchase.id,
                    team_number=team_num,
                    team_name=team_name,
                    email=email,
                    access_token=str(uuid.uuid4())
                )
                db.session.add(member)
        
        db.session.commit()
        return redirect(url_for('team_purchase_payment', purchase_id=purchase.id))
    
    preselect_case = request.args.get('case_id', '')
    return render_template('team_purchase.html', cases=cases, preselect_case=preselect_case)

@app.route('/team-purchase/payment/<int:purchase_id>')
def team_purchase_payment(purchase_id):
    purchase = TeamPurchase.query.get_or_404(purchase_id)
    members_by_team = {i: [] for i in range(1, purchase.team_count + 1)}
    for member in purchase.members:
        if member.team_number not in members_by_team:
            members_by_team[member.team_number] = []
        members_by_team[member.team_number].append(member)
    return render_template('team_purchase_payment.html', purchase=purchase, members_by_team=members_by_team)

@app.route('/team-purchase/complete/<int:purchase_id>', methods=['POST'])
def team_purchase_complete(purchase_id):
    purchase = TeamPurchase.query.get_or_404(purchase_id)
    purchase.payment_status = 'completed'
    db.session.commit()
    record_partner_sale_for_team(purchase)
    record_dealer_sale_for_team(purchase)
    flash('Ödeme başarıyla tamamlandı! Erişim linkleri aşağıda listelenmiştir.' if session.get('lang', 'tr') == 'tr' else 'Payment completed successfully! Access links are listed below.')
    return redirect(url_for('team_purchase_payment', purchase_id=purchase.id))

@app.route('/payment/team/select/<int:purchase_id>')
def payment_team_select(purchase_id):
    purchase = TeamPurchase.query.get_or_404(purchase_id)
    if purchase.payment_status == 'completed':
        return redirect(url_for('team_purchase_payment', purchase_id=purchase.id))
    settings = get_payment_settings()
    iyzico_enabled = settings.get('iyzico_enabled') == '1'
    havale_enabled = settings.get('havale_enabled') == '1'
    param_enabled = settings.get('param_enabled') == '1'
    paynkolay_enabled = settings.get('paynkolay_enabled') == '1'
    return render_template('payment_team_select.html', purchase=purchase, iyzico_enabled=iyzico_enabled, havale_enabled=havale_enabled, param_enabled=param_enabled, paynkolay_enabled=paynkolay_enabled)

@app.route('/payment/team/paynkolay/<int:purchase_id>')
def payment_team_paynkolay(purchase_id):
    purchase = TeamPurchase.query.get_or_404(purchase_id)
    if purchase.payment_status == 'completed':
        return redirect(url_for('team_purchase_payment', purchase_id=purchase.id))
    settings = get_payment_settings()
    if settings.get('paynkolay_enabled') != '1':
        flash("PaynKolay ödeme sistemi aktif değil.")
        return redirect(url_for('payment_team_select', purchase_id=purchase_id))
    return render_template('payment_paynkolay.html', case=None, cart_total=None, hint=None,
                           team_purchase=purchase,
                           form_action=url_for('paynkolay_process_team', purchase_id=purchase.id))

@app.route('/payment/team/paynkolay/process/<int:purchase_id>', methods=['POST'])
def paynkolay_process_team(purchase_id):
    purchase = TeamPurchase.query.get_or_404(purchase_id)
    if purchase.payment_status == 'completed':
        return redirect(url_for('team_purchase_payment', purchase_id=purchase.id))
    settings = get_payment_settings()
    if settings.get('paynkolay_enabled') != '1':
        flash("PaynKolay ödeme sistemi aktif değil.")
        return redirect(url_for('payment_team_select', purchase_id=purchase_id))
    sx = settings.get('paynkolay_token', '')
    merchant_secret = settings.get('paynkolay_secret_key', '')
    rnd_num = random.randint(10000, 99999)
    client_ref = f"GV{rnd_num}T{purchase.id}"
    success_url = url_for('paynkolay_success', _external=True)
    fail_url = url_for('paynkolay_fail', _external=True)
    amount = f"{purchase.total_price:.2f}"
    rnd = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    customer_key = ""
    hash_str = f"{sx}|{client_ref}|{amount}|{success_url}|{fail_url}|{rnd}|{customer_key}|{merchant_secret}"
    hash_val = base64.b64encode(hashlib.sha512(hash_str.encode('utf-8')).digest()).decode()
    card_holder_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if card_holder_ip and ',' in card_holder_ip:
        card_holder_ip = card_holder_ip.split(',')[0].strip()
    import json as json_lib
    pending_data = json_lib.dumps({'type': 'team', 'purchase_id': purchase.id})
    pending_setting = Settings.query.filter_by(key=f'paynkolay_pending_{client_ref}').first()
    if pending_setting:
        pending_setting.value = pending_data
    else:
        db.session.add(Settings(key=f'paynkolay_pending_{client_ref}', value=pending_data))
    db.session.commit()
    card_number = request.form.get('card_number', '').replace(' ', '')
    payload = {
        'sx': sx,
        'clientRefCode': client_ref,
        'successUrl': success_url,
        'failUrl': fail_url,
        'amount': amount,
        'currencyNumber': '949',
        'cardHolderName': request.form.get('card_holder', ''),
        'cardNumber': card_number,
        'month': request.form.get('expire_month', ''),
        'year': request.form.get('expire_year', ''),
        'cvv': request.form.get('cvv', ''),
        'transactionType': 'SALES',
        'installmentNo': '1',
        'use3D': 'true',
        'rnd': rnd,
        'hashDatav2': hash_val,
        'cardHolderIP': card_holder_ip,
        'environment': 'API'
    }
    try:
        api_url = 'https://paynkolay.nkolayislem.com.tr/Vpos/v1/Payment'
        resp = requests.post(api_url, data=payload)
        resp_text = resp.text
        try:
            resp_json = resp.json()
            bank_msg = resp_json.get('BANK_REQUEST_MESSAGE', '')
            if bank_msg:
                clean_html = bank_msg.replace('\\r', '').replace('\\n', '').replace('\r', '').replace('\n', '')
                return clean_html
        except:
            pass
        return resp_text
    except Exception as e:
        flash(f"PaynKolay ödeme hatası: {str(e)}")
        return redirect(url_for('payment_team_select', purchase_id=purchase_id))

@app.route('/payment/team/iyzico/<int:purchase_id>', methods=['POST'])
def payment_team_iyzico(purchase_id):
    purchase = TeamPurchase.query.get_or_404(purchase_id)
    if purchase.payment_status == 'completed':
        return redirect(url_for('team_purchase_payment', purchase_id=purchase.id))
    settings = get_payment_settings()
    if settings.get('iyzico_enabled') != '1':
        flash("iyzico ödeme sistemi aktif değil.")
        return redirect(url_for('payment_team_select', purchase_id=purchase_id))
    api_key = settings.get('iyzico_api_key', '')
    secret_key = settings.get('iyzico_secret_key', '')
    base_url = settings.get('iyzico_base_url', 'https://sandbox-api.iyzipay.com')
    conversation_id = f"GVT{purchase.id}{random.randint(1000,9999)}"
    name_parts = purchase.organizer_name.strip().split(' ', 1)
    buyer_name = name_parts[0] if name_parts else purchase.organizer_name
    buyer_surname = name_parts[1] if len(name_parts) > 1 else "."
    request_data = {
        "locale": "tr",
        "conversationId": conversation_id,
        "price": str(purchase.total_price),
        "paidPrice": str(purchase.total_price),
        "currency": "TRY",
        "basketId": f"BT{purchase.id}",
        "paymentGroup": "PRODUCT",
        "callbackUrl": url_for('iyzico_team_callback', _external=True),
        "enabledInstallments": [1, 2, 3, 6, 9],
        "buyer": {
            "id": f"BYT{purchase.id}",
            "name": buyer_name,
            "surname": buyer_surname,
            "gsmNumber": "+905000000000",
            "email": purchase.organizer_email,
            "identityNumber": "74300864791",
            "registrationAddress": "Adres belirtilmemiş",
            "ip": request.remote_addr,
            "city": "Istanbul",
            "country": "Turkey"
        },
        "shippingAddress": {
            "contactName": purchase.organizer_name,
            "city": "Istanbul",
            "country": "Turkey",
            "address": "Adres belirtilmemiş"
        },
        "billingAddress": {
            "contactName": purchase.organizer_name,
            "city": "Istanbul",
            "country": "Turkey",
            "address": "Adres belirtilmemiş"
        },
        "basketItems": [{
            "id": f"TEAM{purchase.id}",
            "name": f"{purchase.case.title} - Takım Oyunu",
            "category1": "Dijital Urun",
            "itemType": "VIRTUAL",
            "price": str(purchase.total_price)
        }]
    }
    random_string = base64.b64encode(os.urandom(8)).decode()
    string_to_hash = random_string + secret_key
    hash_string = hashlib.sha1(string_to_hash.encode()).hexdigest()
    authorization = f"IYZWS {api_key}:{hash_string}"
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': authorization,
        'x-iyzi-rnd': random_string
    }
    session['pending_team_purchase_id'] = purchase.id
    session['pending_conversation_id'] = conversation_id
    try:
        response = requests.post(f"{base_url}/payment/iyzipos/checkoutform/initialize/auth/ecom",
                                json=request_data, headers=headers)
        result = response.json()
        if result.get('status') == 'success':
            return render_template('payment_iyzico.html', checkout_form_content=result.get('checkoutFormContent'), case=purchase.case)
        else:
            flash(f"iyzico hatası: {result.get('errorMessage', 'Bilinmeyen hata')}")
            return redirect(url_for('payment_team_select', purchase_id=purchase_id))
    except Exception as e:
        flash(f"Ödeme sistemi hatası: {str(e)}")
        return redirect(url_for('payment_team_select', purchase_id=purchase_id))

@app.route('/payment/iyzico/team/callback', methods=['POST'])
def iyzico_team_callback():
    token = request.form.get('token')
    if not token:
        flash("Ödeme doğrulanamadı.")
        return redirect(url_for('index'))
    settings = get_payment_settings()
    api_key = settings.get('iyzico_api_key', '')
    secret_key = settings.get('iyzico_secret_key', '')
    base_url = settings.get('iyzico_base_url', 'https://sandbox-api.iyzipay.com')
    random_string = base64.b64encode(os.urandom(8)).decode()
    string_to_hash = random_string + secret_key
    hash_string = hashlib.sha1(string_to_hash.encode()).hexdigest()
    authorization = f"IYZWS {api_key}:{hash_string}"
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': authorization,
        'x-iyzi-rnd': random_string
    }
    try:
        response = requests.post(f"{base_url}/payment/iyzipos/checkoutform/auth/ecom/detail",
                                json={"locale": "tr", "token": token}, headers=headers)
        result = response.json()
        if result.get('paymentStatus') == 'SUCCESS':
            purchase_id = session.pop('pending_team_purchase_id', None)
            if purchase_id:
                team_purchase = TeamPurchase.query.get(purchase_id)
                if team_purchase:
                    team_purchase.payment_status = 'completed'
                    db.session.commit()
                    record_partner_sale_for_team(team_purchase)
                    record_dealer_sale_for_team(team_purchase)
            flash("Ödeme başarılı! Takım erişim linkleri aktif edildi.")
            if purchase_id:
                return redirect(url_for('team_purchase_payment', purchase_id=purchase_id))
            return redirect(url_for('index'))
        else:
            flash("Ödeme başarısız.")
            purchase_id = session.pop('pending_team_purchase_id', None)
            if purchase_id:
                return redirect(url_for('payment_team_select', purchase_id=purchase_id))
            return redirect(url_for('payment_fail'))
    except Exception as e:
        flash(f"Ödeme doğrulama hatası: {str(e)}")
        purchase_id = session.pop('pending_team_purchase_id', None)
        if purchase_id:
            return redirect(url_for('payment_team_select', purchase_id=purchase_id))
        return redirect(url_for('payment_fail'))

@app.route('/team-access/<access_token>')
def team_access(access_token):
    """Team access entry point - saves token and redirects to login if needed"""
    member = TeamMember.query.filter_by(access_token=access_token).first_or_404()
    purchase = member.team_purchase
    lang = session.get('lang', 'tr')
    
    if purchase.payment_status != 'completed':
        flash('Bu bağlantıya erişmek için ödeme tamamlanmalıdır.' if lang == 'tr' else 'Payment must be completed to access this link.')
        return redirect(url_for('index'))
    
    session['team_token'] = access_token
    
    if 'user_id' not in session:
        flash('Takım oyununa erişmek için lütfen giriş yapın veya kayıt olun.' if lang == 'tr' else 'Please login or register to access the team game.')
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    if user.email.lower() != member.email.lower():
        session.pop('team_token', None)
        flash(f'Bu takım oyununa erişim yetkiniz yok. Oyuna kayıtlı email: {member.email}' if lang == 'tr' else f'You do not have access to this team game. Registered email: {member.email}')
        return redirect(url_for('account'))
    
    session.pop('team_token', None)
    return redirect(url_for('team_play', access_token=access_token))

@app.route('/team-play-solo/<case_id>')
def team_play_solo(case_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    if not user:
        session.clear()
        return redirect(url_for('login'))
    case = Case.query.get_or_404(case_id)
    if session.get('username') == 'admin':
        unlocked = [c.id for c in Case.query.all()]
    else:
        unlocked = [x.strip() for x in user.unlocked_cases.split(',') if x.strip()] if user.unlocked_cases else []
    if case.id not in unlocked:
        flash('Bu vakaya erişiminiz yok.')
        return redirect(url_for('cases'))
    user_email = (user.email or '').lower()
    from sqlalchemy import func
    existing_member = TeamMember.query.join(TeamPurchase).filter(
        TeamPurchase.case_id == case.id,
        func.lower(TeamMember.email) == user_email
    ).first()
    if existing_member:
        return redirect(url_for('team_play', access_token=existing_member.access_token))
    import secrets as sec
    solo_purchase = TeamPurchase(
        case_id=case.id,
        organizer_email=user_email,
        organizer_name=user.username,
        team_count=1,
        total_price=0,
        payment_status='completed'
    )
    db.session.add(solo_purchase)
    db.session.flush()
    solo_member = TeamMember(
        team_purchase_id=solo_purchase.id,
        team_number=1,
        team_name=user.username,
        email=user_email,
        access_token=sec.token_urlsafe(32),
        accessed=True
    )
    db.session.add(solo_member)
    db.session.commit()
    return redirect(url_for('team_play', access_token=solo_member.access_token))

@app.route('/team-play/<access_token>')
def team_play(access_token):
    member = TeamMember.query.filter_by(access_token=access_token).first_or_404()
    purchase = member.team_purchase
    lang = session.get('lang', 'tr')
    
    if purchase.payment_status != 'completed':
        flash('Bu bağlantıya erişmek için ödeme tamamlanmalıdır.' if lang == 'tr' else 'Payment must be completed to access this link.')
        return redirect(url_for('index'))
    
    if 'user_id' not in session:
        session['team_token'] = access_token
        flash('Takım oyununa erişmek için lütfen giriş yapın.' if lang == 'tr' else 'Please login to access the team game.')
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    if user.email.lower() != member.email.lower():
        flash(f'Bu takım oyununa erişim yetkiniz yok. Oyuna kayıtlı email: {member.email}' if lang == 'tr' else f'You do not have access to this team game. Registered email: {member.email}')
        return redirect(url_for('account'))
    
    if not member.accessed:
        member.accessed = True
        db.session.commit()
    
    case = purchase.case
    return render_template('team_play.html', case=case, member=member, purchase=purchase, lang=lang)

@app.route('/team-complete/<access_token>', methods=['POST'])
def team_complete(access_token):
    member = TeamMember.query.filter_by(access_token=access_token).first_or_404()
    purchase = member.team_purchase
    
    if purchase.payment_status != 'completed':
        return jsonify({'error': 'Payment not completed'}), 403
    
    data = request.get_json() or {}
    elapsed_seconds = data.get('elapsed_seconds')
    
    if not member.completed:
        member.completed = True
        member.completed_at = datetime.utcnow()
        if elapsed_seconds is not None:
            member.play_time_seconds = int(elapsed_seconds)
        db.session.commit()
    
    return jsonify({'success': True, 'completed': True})

@app.route('/api/team-chat/send', methods=['POST'])
def team_chat_send():
    data = request.get_json()
    token = data.get('token')
    message_text = data.get('message', '').strip()
    
    if not token or not message_text:
        return jsonify({'error': 'Token and message are required'}), 400
    
    member = TeamMember.query.filter_by(access_token=token).first()
    if not member:
        return jsonify({'error': 'Invalid token'}), 404
    
    purchase = member.team_purchase
    if purchase.payment_status != 'completed':
        return jsonify({'error': 'Payment not completed'}), 403
    
    sender_name = member.team_name or member.email.split('@')[0]
    
    new_message = TeamMessage(
        team_purchase_id=purchase.id,
        team_number=member.team_number,
        sender_email=member.email,
        sender_name=sender_name,
        message=message_text
    )
    db.session.add(new_message)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': {
            'id': new_message.id,
            'sender_name': sender_name,
            'sender_email': member.email,
            'message': message_text,
            'created_at': new_message.created_at.strftime('%H:%M'),
            'is_mine': True
        }
    })

@app.route('/api/assistant-chat', methods=['POST'])
def assistant_chat():
    data = request.get_json() or {}
    message = data.get('message', '').strip()
    history = data.get('history', [])
    lang = session.get('lang', 'tr')
    quiz = data.get('quiz', {})  # {experience, difficulty, caseType}

    if not message:
        return jsonify({'error': 'Mesaj boş'}), 400

    from urllib.parse import quote as _urlencode

    cases_all = Case.query.filter_by(is_active=True).all()
    base_url = request.host_url.rstrip('/')
    cases_dict = {c.id: c for c in cases_all}

    CASE_TYPE_KEYWORDS = {
        'cinayet':    ['cinayet', 'öldür', 'ölüm', 'katil', 'murder', 'kill', 'dead', 'ceset', 'infaz'],
        'murder':     ['cinayet', 'öldür', 'ölüm', 'katil', 'murder', 'kill', 'dead', 'ceset'],
        'hirsizlik':  ['hırsız', 'çalındı', 'çalın', 'theft', 'steal', 'rob', 'dolandır', 'kayıp eser'],
        'theft':      ['hırsız', 'çalındı', 'theft', 'steal', 'rob', 'dolandır'],
        'siber':      ['siber', 'yazılım', 'dijital', 'hack', 'kod', 'program', 'teknoloji', 'akıllı', 'bilgisayar', 'cyber', 'digital', 'software'],
        'cyber':      ['siber', 'yazılım', 'dijital', 'hack', 'kod', 'program', 'teknoloji', 'cyber', 'digital'],
        'sanat':      ['müze', 'eser', 'antika', 'sanat', 'heykel', 'tablo', 'koleksiyon', 'müzesi', 'museum', 'art', 'sculpture', 'artifact'],
        'art':        ['müze', 'eser', 'antika', 'sanat', 'heykel', 'museum', 'art', 'sculpture'],
    }

    def score_case_for_type(c, ctype):
        if ctype in ('all', 'hepsi', ''):
            return 1
        kws = CASE_TYPE_KEYWORDS.get(ctype, [])
        text = ((c.title or '') + ' ' + (c.description or '')).lower()
        return sum(1 for kw in kws if kw in text)

    def pick_case_cards(msg, cdict, quiz_params=None, blimit=3):
        quiz_params = quiz_params or {}
        q_diff = quiz_params.get('difficulty', '')
        q_type = quiz_params.get('caseType', '')
        q_exp  = quiz_params.get('experience', '')
        m = msg.lower()

        # Quiz sonuçları: zorluk + tür filtresi
        if q_diff or q_type:
            pool = list(cdict.values())

            # Deneyime göre zorluk yok sayılırsa exp'den türet
            if not q_diff and q_exp:
                exp_map = {'acemi': 'Kolay', 'beginner': 'Kolay',
                           'gundelik': 'Orta', 'casual': 'Orta',
                           'uzman': 'Zor', 'expert': 'Zor'}
                q_diff = exp_map.get(q_exp, '')

            if q_diff:
                pool = [c for c in pool if (c.difficulty or '') == q_diff] or pool

            if q_type and q_type not in ('all', 'hepsi'):
                scored = [(score_case_for_type(c, q_type), c) for c in pool]
                scored.sort(key=lambda x: -x[0])
                pool = [c for sc, c in scored if sc > 0] or pool

            return [c.id for c in pool[:blimit]]

        # Normal metin tabanlı intent detection
        results = []
        for cid, c in cdict.items():
            title_words = [w for w in c.title.lower().split() if len(w) > 3]
            if any(w in m for w in title_words):
                results.append(cid)
        if results:
            return results[:blimit]

        if any(w in m for w in ['zor', 'hard', 'difficul', 'challeng', 'zorlu']):
            results = [c.id for c in cdict.values() if (c.difficulty or '') == 'Zor'][:blimit]
        elif any(w in m for w in ['kolay', 'easy', 'basit', 'beginner']):
            results = [c.id for c in cdict.values() if (c.difficulty or '') == 'Kolay'][:blimit]
        elif any(w in m for w in ['takım', 'team', 'grup', 'group', 'ekip', 'birlikte', 'together']):
            results = [c.id for c in cdict.values() if c.game_type in ('team', 'both')][:blimit]
        elif any(w in m for w in ['bireysel', 'solo', 'individual', 'yalnız', 'alone']):
            results = [c.id for c in cdict.values() if c.game_type in ('individual', 'both')][:blimit]
        elif any(w in m for w in ['ucuz', 'cheap', 'ekonomik', 'uygun', 'affordable']):
            results = [c.id for c in sorted(cdict.values(), key=lambda x: x.price)][:blimit]
        elif any(w in m for w in ['pahalı', 'expensive', 'premium', 'en iyi', 'best']):
            results = [c.id for c in sorted(cdict.values(), key=lambda x: -x.price)][:blimit]
        elif any(w in m for w in ['dava', 'case', 'listele', 'list', 'göster', 'show', 'hepsi', 'all', 'tüm', 'öner', 'suggest', 'recommend']):
            results = list(cdict.keys())[:blimit]

        if not results:
            results = list(cdict.keys())[:2]
        return results

    selected_ids = pick_case_cards(message, cases_dict, quiz_params=quiz)

    # AI için kısa dava özeti (sadece ilgili davalar)
    case_context = ""
    for cid in selected_ids:
        c = cases_dict[cid]
        difficulty = c.difficulty or 'Orta'
        game_type = 'Bireysel' if c.game_type == 'individual' else ('Takım' if c.game_type == 'team' else 'Bireysel & Takım')
        desc_short = (c.description or '')[:200].replace('\n', ' ')
        case_context += f"• {c.title} | {int(c.price)} TL | {difficulty} | {game_type}\n  {desc_short}\n\n"

    if lang == 'tr':
        system_prompt = f"""Sen Gizemli Vaka dedektiflik platformunun yapay zeka asistanısın. Adın "Dedektif". Samimi, heyecanlı ve gizemli bir sohbet üslubuyla konuşursun.

BAĞLAM (kullanıcıya ne önereceğini bil, ama kendin listeleme):
{case_context}

YAZIM KURALLARI — ÇOK ÖNEMLİ:
- Sadece düz metin ve emoji kullan. HTML kodu, markdown, link YAZMA.
- Dava isimlerini, fiyatlarını veya detaylarını METNE YAZMA — bunlar kart olarak ayrıca gösterilecek.
- Sadece 1-2 cümlelik heyecanlı bir giriş/davet yaz: "Seni bekleyen davalar var!", "Hangisi seni çağırıyor?" gibi.
- Kullanıcı spesifik bir şey sorduysa (fiyat, zorluk, tür) kısa cevap ver.
- Max 2 cümle."""
    else:
        system_prompt = f"""You are the AI detective assistant for Gizemli Vaka mystery platform. Your name is "Detective". You speak in a friendly, exciting, mysterious tone.

CONTEXT (know what to recommend, but do NOT list them yourself):
{case_context}

WRITING RULES — VERY IMPORTANT:
- Plain text and emojis only. NO HTML, NO markdown, NO links.
- Do NOT write case names, prices, or descriptions in your text — these will be shown as visual cards separately.
- Write only 1-2 sentence exciting intro/invitation: "Cases await you!", "Which mystery calls to you?" etc.
- If the user asked something specific (price, difficulty, type), give a short direct answer.
- Max 2 sentences."""

    try:
        from openai_helper import client as gemini_client
        from google.genai import types as gtypes

        contents = []
        for h in history[-10:]:
            role = 'user' if h.get('role') == 'user' else 'model'
            contents.append(gtypes.Content(role=role, parts=[gtypes.Part(text=h.get('content', ''))]))
        contents.append(gtypes.Content(role='user', parts=[gtypes.Part(text=message)]))

        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents,
            config=gtypes.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=400,
                temperature=0.9
            )
        )
        reply = response.text or ('Bir sorun oluştu, lütfen tekrar deneyin.' if lang == 'tr' else 'Something went wrong, please try again.')

        # Kart verilerini oluştur
        case_cards = []
        for cid in selected_ids:
            c = cases_dict[cid]
            case_cards.append({
                'id': c.id,
                'title': c.title,
                'price': int(c.price),
                'old_price': int(c.old_price) if c.old_price and c.old_price > c.price else None,
                'difficulty': c.difficulty or 'Orta',
                'image': c.image,
                'url': f"{base_url}/case/{_urlencode(c.id, safe='')}"
            })

        return jsonify({'reply': reply, 'status': 'ok', 'cases': case_cards})
    except Exception as e:
        print(f"Assistant chat error: {e}")
        msg = 'Bağlantı hatası oluştu, lütfen tekrar deneyin.' if lang == 'tr' else 'Connection error, please try again.'
        return jsonify({'reply': msg, 'status': 'error'})


@app.route('/api/team-chat/messages/<token>')
def team_chat_messages(token):
    last_id = request.args.get('last_id', 0, type=int)
    
    member = TeamMember.query.filter_by(access_token=token).first()
    if not member:
        return jsonify({'error': 'Invalid token'}), 404
    
    purchase = member.team_purchase
    if purchase.payment_status != 'completed':
        return jsonify({'error': 'Payment not completed'}), 403
    
    query = TeamMessage.query.filter_by(
        team_purchase_id=purchase.id,
        team_number=member.team_number
    )
    
    if last_id > 0:
        query = query.filter(TeamMessage.id > last_id)
    
    messages = query.order_by(TeamMessage.created_at.asc()).all()
    
    return jsonify({
        'success': True,
        'messages': [{
            'id': m.id,
            'sender_name': m.sender_name or m.sender_email.split('@')[0],
            'sender_email': m.sender_email,
            'message': m.message,
            'created_at': m.created_at.strftime('%H:%M'),
            'is_mine': m.sender_email == member.email
        } for m in messages]
    })

@app.route('/team-certificate/<access_token>')
def team_certificate(access_token):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas as pdf_canvas
    from reportlab.lib.units import cm
    from flask import Response
    
    member = TeamMember.query.filter_by(access_token=access_token).first_or_404()
    purchase = member.team_purchase
    
    if purchase.payment_status != 'completed' or not member.completed:
        flash('Sertifika almak için davayı tamamlamanız gerekmektedir.' if session.get('lang', 'tr') == 'tr' else 'You must complete the case to get the certificate.')
        return redirect(url_for('team_play', access_token=access_token))
    
    case = purchase.case
    lang = session.get('lang', 'tr')
    
    buffer = BytesIO()
    width, height = landscape(A4)
    c = pdf_canvas.Canvas(buffer, pagesize=landscape(A4))
    
    navy_color = HexColor('#0C1430')
    gold_color = HexColor('#ffc107')
    dark_gold = HexColor('#d4a106')
    
    c.setFillColor(navy_color)
    c.rect(0, 0, width, height, fill=True, stroke=False)
    
    c.setStrokeColor(gold_color)
    c.setLineWidth(8)
    c.rect(30, 30, width - 60, height - 60, fill=False, stroke=True)
    
    c.setStrokeColor(dark_gold)
    c.setLineWidth(3)
    c.rect(45, 45, width - 90, height - 90, fill=False, stroke=True)
    
    c.setFillColor(gold_color)
    c.setFont("Helvetica-Bold", 42)
    title = "KATILIM SERTİFİKASI" if lang == 'tr' else "CERTIFICATE OF PARTICIPATION"
    c.drawCentredString(width / 2, height - 100, title)
    
    c.setFillColor(HexColor('#ffffff'))
    c.setFont("Helvetica", 18)
    subtitle = "Gizemli Vaka Dedektiflik Oyunu" if lang == 'tr' else "Mystery Case Detective Game"
    c.drawCentredString(width / 2, height - 140, subtitle)
    
    c.setStrokeColor(gold_color)
    c.setLineWidth(2)
    c.line(width/2 - 150, height - 160, width/2 + 150, height - 160)
    
    c.setFillColor(HexColor('#e0e0e0'))
    c.setFont("Helvetica", 14)
    awarded_text = "Bu sertifika aşağıdaki kişiye takdim edilmiştir:" if lang == 'tr' else "This certificate is awarded to:"
    c.drawCentredString(width / 2, height - 200, awarded_text)
    
    c.setFillColor(gold_color)
    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(width / 2, height - 240, member.email)
    
    c.setFillColor(HexColor('#ffffff'))
    c.setFont("Helvetica", 16)
    team_label = "Takım:" if lang == 'tr' else "Team:"
    team_name = member.team_name or f"Takım {member.team_number}"
    c.drawCentredString(width / 2, height - 280, f"{team_label} {team_name}")
    
    c.setFont("Helvetica", 16)
    case_label = "Çözülen Vaka:" if lang == 'tr' else "Solved Case:"
    case_title = case.title_en if lang == 'en' and case.title_en else case.title
    c.drawCentredString(width / 2, height - 310, f"{case_label} {case_title}")
    
    completed_date = member.completed_at.strftime('%d.%m.%Y') if member.completed_at else datetime.utcnow().strftime('%d.%m.%Y')
    date_label = "Tamamlanma Tarihi:" if lang == 'tr' else "Completion Date:"
    c.drawCentredString(width / 2, height - 340, f"{date_label} {completed_date}")
    
    c.setFillColor(HexColor('#a0a0a0'))
    c.setFont("Helvetica-Oblique", 12)
    congrats = "Tebrikler! Dedektiflik yeteneklerinizi kanıtladınız." if lang == 'tr' else "Congratulations! You proved your detective skills."
    c.drawCentredString(width / 2, height - 400, congrats)
    
    c.setFillColor(gold_color)
    c.circle(width / 2, 100, 35, fill=True, stroke=False)
    c.setFillColor(navy_color)
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, 95, "✓")
    
    c.setFillColor(HexColor('#888888'))
    c.setFont("Helvetica", 10)
    c.drawCentredString(width / 2, 55, "www.gizemlivaka.com")
    
    c.showPage()
    c.save()
    
    buffer.seek(0)
    
    filename = f"certificate_{member.email.split('@')[0]}_{case.id}.pdf"
    
    return Response(
        buffer.getvalue(),
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@app.route('/sertifika/<case_id>')
def user_certificate(case_id):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas as pdf_canvas
    from flask import Response

    if 'user_id' not in session:
        flash('Sertifika almak için giriş yapmalısınız.')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    case = Case.query.get_or_404(case_id)
    lang = session.get('lang', 'tr')

    # Check if user has solved this case
    progress = GameProgress.query.filter_by(user_id=user.id, case_id=case_id, is_solved=True).first()
    in_solved_list = case in (user.solved_cases_list or [])
    if not progress and not in_solved_list:
        flash('Sertifika almak için önce davayı çözmeniz gerekmektedir.' if lang == 'tr' else 'You must solve the case first to get a certificate.')
        return redirect(url_for('play_case', case_id=case_id))

    buffer = BytesIO()
    width, height = landscape(A4)
    c = pdf_canvas.Canvas(buffer, pagesize=landscape(A4))

    navy_color = HexColor('#0C1430')
    gold_color = HexColor('#ffc107')
    dark_gold = HexColor('#d4a106')
    white_color = HexColor('#ffffff')

    # Background
    c.setFillColor(navy_color)
    c.rect(0, 0, width, height, fill=True, stroke=False)

    # Outer gold border
    c.setStrokeColor(gold_color)
    c.setLineWidth(8)
    c.rect(30, 30, width - 60, height - 60, fill=False, stroke=True)

    # Inner border
    c.setStrokeColor(dark_gold)
    c.setLineWidth(3)
    c.rect(45, 45, width - 90, height - 90, fill=False, stroke=True)

    # Corner decorations
    corner_size = 20
    for x, y in [(30, 30), (width - 30, 30), (30, height - 30), (width - 30, height - 30)]:
        c.setFillColor(gold_color)
        c.circle(x, y, 8, fill=True, stroke=False)

    # Title
    c.setFillColor(gold_color)
    c.setFont("Helvetica-Bold", 44)
    title = "DEDEKTIF SERTIFIKASI" if lang == 'tr' else "DETECTIVE CERTIFICATE"
    c.drawCentredString(width / 2, height - 100, title)

    # Subtitle
    c.setFillColor(white_color)
    c.setFont("Helvetica", 18)
    subtitle = "Gizemli Vaka — Dedektiflik Oyun Platformu" if lang == 'tr' else "Gizemli Vaka — Mystery Game Platform"
    c.drawCentredString(width / 2, height - 135, subtitle)

    # Divider line
    c.setStrokeColor(gold_color)
    c.setLineWidth(2)
    c.line(width / 2 - 200, height - 155, width / 2 + 200, height - 155)

    # Award text
    c.setFillColor(HexColor('#e0e0e0'))
    c.setFont("Helvetica", 14)
    awarded_text = "Bu sertifika aşağıdaki dedektife takdim edilmiştir:" if lang == 'tr' else "This certificate is awarded to the following detective:"
    c.drawCentredString(width / 2, height - 195, awarded_text)

    # Username (big gold)
    c.setFillColor(gold_color)
    c.setFont("Helvetica-Bold", 36)
    c.drawCentredString(width / 2, height - 245, user.username)

    # Decorative line under name
    c.setStrokeColor(dark_gold)
    c.setLineWidth(1.5)
    name_width = min(len(user.username) * 22, 400)
    c.line(width / 2 - name_width / 2, height - 260, width / 2 + name_width / 2, height - 260)

    # Case info
    c.setFillColor(white_color)
    c.setFont("Helvetica", 16)
    case_label = "Çözülen Vaka:" if lang == 'tr' else "Solved Case:"
    case_title = case.title_en if lang == 'en' and case.title_en else case.title
    c.drawCentredString(width / 2, height - 300, f"{case_label}  {case_title}")

    # Difficulty
    diff_label = "Zorluk:" if lang == 'tr' else "Difficulty:"
    difficulty = case.difficulty or 'Orta'
    c.setFont("Helvetica", 14)
    c.drawCentredString(width / 2, height - 328, f"{diff_label}  {difficulty}")

    # Points earned
    points_label = "Kazanılan Puan:" if lang == 'tr' else "Points Earned:"
    points_val = f"{progress.points_earned:.0f}" if progress and progress.points_earned else "-"
    c.drawCentredString(width / 2, height - 352, f"{points_label}  {points_val}")

    # Completion date
    if progress and progress.last_attempt_time:
        completed_date = progress.last_attempt_time.strftime('%d.%m.%Y')
    else:
        completed_date = datetime.utcnow().strftime('%d.%m.%Y')
    date_label = "Tamamlanma Tarihi:" if lang == 'tr' else "Completion Date:"
    c.drawCentredString(width / 2, height - 376, f"{date_label}  {completed_date}")

    # Congratulations text
    c.setFillColor(HexColor('#a0c8ff'))
    c.setFont("Helvetica-Oblique", 13)
    congrats = "Tebrikler! Dedektiflik yeteneklerinizi başarıyla kanıtladınız." if lang == 'tr' else "Congratulations! You have proven your detective skills."
    c.drawCentredString(width / 2, height - 415, congrats)

    # Gold badge / seal
    c.setFillColor(gold_color)
    c.circle(width / 2, 90, 38, fill=True, stroke=False)
    c.setFillColor(dark_gold)
    c.circle(width / 2, 90, 38, fill=False, stroke=True)
    c.setStrokeColor(dark_gold)
    c.setLineWidth(2)
    c.setFillColor(navy_color)
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width / 2, 84, "GV")

    # Website footer
    c.setFillColor(HexColor('#666666'))
    c.setFont("Helvetica", 10)
    c.drawCentredString(width / 2, 48, "www.gizemlivaka.com")

    c.showPage()
    c.save()

    buffer.seek(0)
    safe_username = user.username.replace(' ', '_')
    filename = f"sertifika_{safe_username}_{case_id}.pdf"

    return Response(
        buffer.getvalue(),
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@app.route('/api/case-price/<case_id>')
def get_case_price(case_id):
    case = Case.query.get(case_id)
    if case and case.is_active:
        return jsonify({'price': case.price, 'title': case.title, 'title_en': case.title_en or case.title})
    return jsonify({'error': 'Case not found'}), 404

@app.route('/cases')
def cases():
    ref = request.args.get('ref')
    if ref:
        discount = DiscountCode.query.filter_by(code=ref, is_active=True).first()
        if discount and discount.partner_id:
            session['applied_discount'] = {'code': ref, 'percent': discount.discount_percent}
    all_cases = Case.query.filter(Case.is_active==True).all()
    return render_template('cases.html', cases=all_cases)

@app.route('/case/<case_id>')
def case_detail(case_id):
    ref = request.args.get('ref')
    if ref:
        discount = DiscountCode.query.filter_by(code=ref, is_active=True).first()
        if discount and discount.partner_id:
            if not discount.case_id or discount.case_id == case_id:
                session['applied_discount'] = {'code': ref, 'percent': discount.discount_percent}
    case = Case.query.get_or_404(case_id)
    if not case.is_active and session.get('username') != 'admin':
        abort(404)
    comments = Comment.query.filter_by(case_id=case_id, approved=True).order_by(Comment.date_posted.desc()).all()
    user_already_commented = False
    if 'user_id' in session:
        user_already_commented = Comment.query.filter_by(case_id=case_id, user_id=session['user_id']).first() is not None
    return render_template('case_detail.html', case=case, comments=comments, user_already_commented=user_already_commented)

@app.route('/add-comment/<case_id>', methods=['POST'])
def add_comment(case_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    content = request.form.get('content')
    if content:
        db.session.add(Comment(content=content, rating=int(request.form.get('rating', 5)), user_id=session['user_id'], case_id=case_id))
        db.session.commit()
    return redirect(url_for('case_detail', case_id=case_id))

# --- SEPET VE ÖDEME ---
@app.route('/cart')
def view_cart():
    items = [Case.query.get(cid) for cid in session.get('cart', []) if Case.query.get(cid)]
    all_settings = Settings.query.all()
    settings = {item.key: item.value for item in all_settings} if all_settings else {}
    total = round(sum(i.price for i in items), 2)
    
    applied_discount = session.get('applied_discount')
    discount_amount = 0
    final_total = total
    
    if applied_discount and items:
        discount_case_id = applied_discount.get('case_id')
        applicable_items = items if not discount_case_id else [i for i in items if i.id == discount_case_id]
        applicable_total = sum(i.price for i in applicable_items)
        
        if applied_discount.get('percent', 0) > 0:
            discount_amount = round(applicable_total * applied_discount['percent'] / 100, 2)
        if applied_discount.get('amount', 0) > 0:
            discount_amount += applied_discount['amount']
        
        discount_amount = min(discount_amount, total)
        final_total = round(total - discount_amount, 2)
    
    return render_template('cart.html', items=items, total=total, discount_amount=discount_amount, 
                         final_total=final_total, applied_discount=applied_discount, settings=settings)

@app.route('/add-to-cart/<case_id>')
def add_to_cart(case_id):
    case = Case.query.get(case_id)
    if not case or not case.is_active:
        abort(404)
    cart = session.get('cart', [])
    if case_id not in cart: cart.append(case_id); session['cart'] = cart; session.modified = True
    return redirect(url_for('view_cart'))

@app.route('/remove-from-cart/<int:index>')
def remove_from_cart(index):
    cart = session.get('cart', [])
    if 0 <= index < len(cart): cart.pop(index); session['cart'] = cart; session.modified = True
    return redirect(url_for('view_cart'))

@app.route('/checkout', methods=['GET'])
def checkout():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    cart = session.get('cart', [])
    cart_items = []
    subtotal = 0
    for case_id in cart:
        case = Case.query.get(case_id)
        if case:
            cart_items.append({'case': case})
            subtotal += case.price
    
    discount_amount = 0
    discount_code = None
    if 'applied_discount' in session:
        applied = session['applied_discount']
        discount_code = applied.get('code')
        if applied.get('percent'):
            discount_amount = subtotal * (applied['percent'] / 100)
        elif applied.get('amount'):
            discount_amount = min(applied['amount'], subtotal)
    
    total = subtotal - discount_amount
    settings = get_payment_settings()
    iyzico_enabled = settings.get('iyzico_enabled') == '1'
    havale_enabled = settings.get('havale_enabled') == '1'
    param_enabled = settings.get('param_enabled') == '1'
    return render_template('checkout.html', subtotal=subtotal, total=total, discount_amount=discount_amount,
                         discount_code=discount_code, user=user, cart_items=cart_items, 
                         countries=["Turkiye", "Almanya", "ABD", "Ingiltere", "Fransa"],
                         iyzico_enabled=iyzico_enabled, havale_enabled=havale_enabled, param_enabled=param_enabled)

@app.route('/process-checkout', methods=['POST'])
def process_checkout():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    cart = session.get('cart', [])
    if not cart:
        flash("Sepetiniz bos.")
        return redirect(url_for('view_cart'))
    
    user.first_name = request.form.get('first_name', user.first_name)
    user.last_name = request.form.get('last_name', user.last_name)
    user.billing_address = f"{request.form.get('address', '')}, {request.form.get('city', '')}, {request.form.get('province', '')}"
    db.session.commit()
    
    total = sum(Case.query.get(cid).price for cid in cart if Case.query.get(cid))
    payment_provider = request.form.get('payment_provider', 'iyzico')
    
    session['pending_cart'] = cart
    session['pending_total'] = total
    
    if payment_provider == 'iyzico':
        settings = get_payment_settings()
        if settings.get('iyzico_enabled') != '1':
            flash("iyzico odeme sistemi aktif degil.")
            return redirect(url_for('checkout'))
        return redirect(url_for('payment_iyzico_cart'))
    elif payment_provider == 'havale':
        settings = get_payment_settings()
        if settings.get('havale_enabled') != '1':
            flash("Havale ödeme seçeneği aktif değil.")
            return redirect(url_for('checkout'))
        return redirect(url_for('havale_cart'))
    elif payment_provider == 'param':
        settings = get_payment_settings()
        if settings.get('param_enabled') != '1':
            flash("Param POS odeme sistemi aktif degil.")
            return redirect(url_for('checkout'))
        return redirect(url_for('param_cart'))
    else:
        flash("Gecerli bir odeme yontemi seciniz.")
        return redirect(url_for('checkout'))

# --- ADMİN PANELİ ---
@app.route('/admin/cases')
def admin_cases():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    return render_template('admin/cases.html', cases=Case.query.all(), active_page='cases')

## --- ADMİN: KULLANICI LİSTESİ ---
@app.route('/admin/users')
def admin_users():
    if session.get('username') != 'admin': 
        return redirect(url_for('login'))

    try:
        users = User.query.all()
        # active_page='users' sidebar'daki sarı çizgiyi aktif tutar
        return render_template('admin/admin_users.html', users=users, active_page='users')
    except Exception as e:
        # Eğer hata varsa ekranda ne olduğunu yazdırır (Debug için)
        return f"Hata Oluştu: {str(e)}"

# --- ADMİN: KULLANICI DÜZENLEME ---
@app.route('/admin/user/edit/<int:id>', methods=['POST'])
def admin_edit_user(id):
    if session.get('username') != 'admin': return redirect(url_for('login'))
    user = User.query.get_or_404(id)
    user.username = request.form.get('username')
    user.email = request.form.get('email')
    user.score = int(request.form.get('score', 0))
    
    new_password = request.form.get('new_password')
    if new_password and len(new_password) >= 4:
        user.password = generate_password_hash(new_password)
    
    db.session.commit()
    flash(f"'{user.username}' başarıyla güncellendi.")
    return redirect(url_for('admin_users'))

# --- ADMİN: KULLANICI SİLME ---
@app.route('/admin/user/delete/<int:id>')
def admin_delete_user(id):
    if session.get('username') != 'admin': return redirect(url_for('login'))
    user = User.query.get_or_404(id)
    if user.username == 'admin':
        flash("Hata: Ana yönetici silinemez!")
    else:
        try:
            # İlişkili tüm kayıtları önce sil
            partner_ids = [p.id for p in Partner.query.filter_by(user_id=user.id).all()]
            if partner_ids:
                DiscountCode.query.filter(DiscountCode.partner_id.in_(partner_ids)).delete(synchronize_session=False)
                PartnerSale.query.filter(PartnerSale.partner_id.in_(partner_ids)).delete(synchronize_session=False)
                PartnerWithdrawal.query.filter(PartnerWithdrawal.partner_id.in_(partner_ids)).delete(synchronize_session=False)
            Partner.query.filter_by(user_id=user.id).delete()
            Purchase.query.filter_by(user_id=user.id).delete()
            GameProgress.query.filter_by(user_id=user.id).delete()
            TeamMember.query.filter_by(email=user.email).delete()
            db.session.delete(user)
            db.session.commit()
            flash("Kullanıcı ve tüm ilişkili veriler silindi.")
        except Exception as e:
            db.session.rollback()
            flash(f"Silme hatası: {str(e)}")
    return redirect(url_for('admin_users'))

# --- ADMİN: KULLANICI OYUNLARI YÖNETİMİ ---
@app.route('/admin/user-games/<int:user_id>')
def admin_user_games(user_id):
    if session.get('username') != 'admin': return redirect(url_for('login'))
    user = User.query.get_or_404(user_id)
    
    # Bireysel oyunlar
    individual_purchases = Purchase.query.filter_by(user_id=user.id, is_paid=True).all()
    individual_games = []
    for purchase in individual_purchases:
        case = Case.query.get(purchase.case_id)
        if case:
            progress = GameProgress.query.filter_by(user_id=user.id, case_id=case.id).first()
            individual_games.append((purchase, case, progress))
    
    # Takım oyunları
    team_games = db.session.query(TeamMember, TeamPurchase, Case).join(
        TeamPurchase, TeamMember.team_purchase_id == TeamPurchase.id
    ).join(
        Case, TeamPurchase.case_id == Case.id
    ).filter(
        db.func.lower(TeamMember.email) == user.email.lower(),
        TeamPurchase.payment_status == 'completed'
    ).all()
    
    all_cases = Case.query.order_by(Case.title).all()
    return render_template('admin/user_games.html', user=user, individual_games=individual_games, team_games=team_games, all_cases=all_cases, active_page='users')

@app.route('/admin/user-games/<int:user_id>/toggle-individual/<int:purchase_id>')
def admin_toggle_individual_game(user_id, purchase_id):
    if session.get('username') != 'admin': return redirect(url_for('login'))
    purchase = Purchase.query.get_or_404(purchase_id)
    progress = GameProgress.query.filter_by(user_id=user_id, case_id=purchase.case_id).first()
    if progress:
        progress.is_solved = not progress.is_solved
    else:
        progress = GameProgress(user_id=user_id, case_id=purchase.case_id, is_solved=True)
        db.session.add(progress)
    db.session.commit()
    flash('Oyun durumu güncellendi.')
    return redirect(url_for('admin_user_games', user_id=user_id))

@app.route('/admin/user-games/<int:user_id>/revoke-individual/<int:purchase_id>')
def admin_revoke_individual_game(user_id, purchase_id):
    if session.get('username') != 'admin': return redirect(url_for('login'))
    purchase = Purchase.query.get_or_404(purchase_id)
    db.session.delete(purchase)
    db.session.commit()
    flash('Erişim iptal edildi.')
    return redirect(url_for('admin_user_games', user_id=user_id))

@app.route('/admin/user-games/<int:user_id>/reset-game/<case_id>')
def admin_reset_game(user_id, case_id):
    if session.get('username') != 'admin': return redirect(url_for('login'))
    progress = GameProgress.query.filter_by(user_id=user_id, case_id=case_id).first()
    if progress:
        progress.attempts_used = 0
        progress.hints_used = 0
        progress.points_earned = 0
        progress.is_solved = False
        progress.is_failed = False
        progress.last_attempt_time = None
        db.session.commit()
        flash('Oyun sıfırlandı. Kullanıcı baştan başlayabilir.')
    else:
        flash('İlerleme bulunamadı.')
    return redirect(url_for('admin_user_games', user_id=user_id))

@app.route('/admin/user-games/<int:user_id>/reset-cooldown/<case_id>')
def admin_reset_cooldown(user_id, case_id):
    if session.get('username') != 'admin': return redirect(url_for('login'))
    progress = GameProgress.query.filter_by(user_id=user_id, case_id=case_id).first()
    if progress:
        progress.last_attempt_time = None
        progress.is_failed = False
        db.session.commit()
        flash('Bekleme süresi sıfırlandı. Kullanıcı hemen tekrar deneyebilir.')
    else:
        flash('İlerleme bulunamadı.')
    return redirect(url_for('admin_user_games', user_id=user_id))

@app.route('/admin/user-games/<int:user_id>/toggle-team/<int:member_id>')
def admin_toggle_team_game(user_id, member_id):
    if session.get('username') != 'admin': return redirect(url_for('login'))
    member = TeamMember.query.get_or_404(member_id)
    member.completed = not member.completed
    if member.completed:
        member.completed_at = datetime.utcnow()
    else:
        member.completed_at = None
    db.session.commit()
    flash('Takım oyunu durumu güncellendi.')
    return redirect(url_for('admin_user_games', user_id=user_id))

@app.route('/admin/user-games/<int:user_id>/revoke-team/<int:member_id>')
def admin_revoke_team_game(user_id, member_id):
    if session.get('username') != 'admin': return redirect(url_for('login'))
    member = TeamMember.query.get_or_404(member_id)
    db.session.delete(member)
    db.session.commit()
    flash('Takım erişimi iptal edildi.')
    return redirect(url_for('admin_user_games', user_id=user_id))

@app.route('/admin/user-games/<int:user_id>/add-individual', methods=['POST'])
def admin_add_individual_game(user_id):
    if session.get('username') != 'admin': return redirect(url_for('login'))
    user = User.query.get_or_404(user_id)
    case_id = request.form.get('case_id', '').strip()
    if not case_id:
        flash('Lütfen bir vaka seçin.', 'warning')
        return redirect(url_for('admin_user_games', user_id=user_id))
    case = db.session.get(Case, case_id)
    if not case:
        flash(f'Vaka bulunamadı (ID: {case_id}).', 'danger')
        return redirect(url_for('admin_user_games', user_id=user_id))
    existing = Purchase.query.filter_by(user_id=user_id, case_id=case_id, is_paid=True).first()
    if existing:
        flash(f'"{case.title}" vakası zaten bu kullanıcıya tanımlı.', 'warning')
        return redirect(url_for('admin_user_games', user_id=user_id))
    try:
        purchase = Purchase(
            user_id=user_id,
            case_id=case_id,
            amount=0,
            is_paid=True,
            created_at=datetime.utcnow()
        )
        db.session.add(purchase)
        db.session.commit()
        flash(f'✅ "{case.title}" vakası {user.username} kullanıcısına başarıyla eklendi.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Oyun eklenirken hata oluştu: {str(e)}', 'danger')
    return redirect(url_for('admin_user_games', user_id=user_id))

@app.route('/admin/user-games/<int:user_id>/add-team', methods=['POST'])
def admin_add_team_game(user_id):
    if session.get('username') != 'admin': return redirect(url_for('login'))
    user = User.query.get_or_404(user_id)
    case_id = request.form.get('case_id')
    organizer_name = request.form.get('organizer_name', user.username)
    team_name = request.form.get('team_name', '1. Takım')
    if not case_id:
        flash('Lütfen bir vaka seçin.', 'warning')
        return redirect(url_for('admin_user_games', user_id=user_id))
    case = Case.query.get(case_id)
    if not case:
        flash('Vaka bulunamadı.', 'danger')
        return redirect(url_for('admin_user_games', user_id=user_id))
    import secrets as _secrets
    team_purchase = TeamPurchase(
        case_id=case_id,
        organizer_email=user.email,
        organizer_name=organizer_name,
        team_count=1,
        total_price=0,
        payment_status='completed',
        created_at=datetime.utcnow()
    )
    db.session.add(team_purchase)
    db.session.flush()
    member = TeamMember(
        team_purchase_id=team_purchase.id,
        team_number=1,
        team_name=team_name,
        email=user.email,
        access_token=_secrets.token_urlsafe(32),
        accessed=False,
        completed=False,
        created_at=datetime.utcnow()
    )
    db.session.add(member)
    db.session.commit()
    flash(f'✅ "{case.title}" takım oyunu {user.username} kullanıcısına başarıyla eklendi.', 'success')
    return redirect(url_for('admin_user_games', user_id=user_id))

# --- ADMİN: TÜM AKTİF OYUNLAR ---
@app.route('/admin/active-games')
def admin_active_games():
    if session.get('username') != 'admin': return redirect(url_for('login'))
    
    game_type = request.args.get('type', 'all')
    case_filter = request.args.get('case', '')
    user_filter = request.args.get('user', '')
    
    # Bireysel oyunlar
    individual_query = db.session.query(Purchase, User, Case, GameProgress).join(
        User, Purchase.user_id == User.id
    ).join(
        Case, Purchase.case_id == Case.id
    ).outerjoin(
        GameProgress, db.and_(GameProgress.user_id == Purchase.user_id, GameProgress.case_id == Purchase.case_id)
    ).filter(Purchase.is_paid == True)
    
    if case_filter:
        individual_query = individual_query.filter(Case.id == case_filter)
    if user_filter:
        individual_query = individual_query.filter(User.id == user_filter)
    
    individual_games = individual_query.all() if game_type in ['all', 'individual'] else []
    
    # Takım oyunları
    team_query = db.session.query(TeamMember, TeamPurchase, Case, User).join(
        TeamPurchase, TeamMember.team_purchase_id == TeamPurchase.id
    ).join(
        Case, TeamPurchase.case_id == Case.id
    ).outerjoin(
        User, db.func.lower(TeamMember.email) == db.func.lower(User.email)
    ).filter(TeamPurchase.payment_status == 'completed')
    
    if case_filter:
        team_query = team_query.filter(Case.id == case_filter)
    if user_filter:
        team_query = team_query.filter(User.id == user_filter)
    
    team_games = team_query.all() if game_type in ['all', 'team'] else []
    
    cases = Case.query.filter_by(is_active=True).all()
    users = User.query.all()
    
    team_purchases = TeamPurchase.query.filter_by(payment_status='completed').all()
    
    return render_template('admin/active_games.html', 
                           individual_games=individual_games, 
                           team_games=team_games, 
                           cases=cases, 
                           users=users,
                           team_purchases=team_purchases,
                           game_type=game_type,
                           case_filter=case_filter,
                           user_filter=user_filter,
                           active_page='active_games')

@app.route('/admin/reset-individual-game/<purchase_id>')
def admin_reset_individual_game(purchase_id):
    if session.get('username') != 'admin': return redirect(url_for('login'))
    purchase = Purchase.query.get_or_404(purchase_id)
    progress = GameProgress.query.filter_by(user_id=purchase.user_id, case_id=purchase.case_id).first()
    if progress:
        progress.is_solved = False
        progress.is_failed = False
        progress.attempts_used = 0
        progress.hints_used = 0
        progress.points_earned = 0
        progress.last_attempt_time = None
        db.session.commit()
        flash('Oyun ilerlemesi sıfırlandı.', 'success')
    else:
        flash('İlerleme kaydı bulunamadı.', 'warning')
    return redirect(url_for('admin_active_games'))

@app.route('/admin/delete-individual-game/<purchase_id>')
def admin_delete_individual_game(purchase_id):
    if session.get('username') != 'admin': return redirect(url_for('login'))
    purchase = Purchase.query.get_or_404(purchase_id)
    user = User.query.get(purchase.user_id)
    if user and user.unlocked_cases:
        unlocked = user.unlocked_cases.split(',')
        if purchase.case_id in unlocked:
            unlocked.remove(purchase.case_id)
            user.unlocked_cases = ','.join(unlocked)
    progress = GameProgress.query.filter_by(user_id=purchase.user_id, case_id=purchase.case_id).first()
    if progress:
        db.session.delete(progress)
    db.session.delete(purchase)
    db.session.commit()
    flash('Oyun başarıyla silindi.', 'success')
    return redirect(url_for('admin_active_games'))

@app.route('/admin/reset-team-member/<int:member_id>')
def admin_reset_team_member(member_id):
    if session.get('username') != 'admin': return redirect(url_for('login'))
    member = TeamMember.query.get_or_404(member_id)
    member.completed = False
    member.completed_at = None
    db.session.commit()
    flash('Takım üyesi ilerlemesi sıfırlandı.', 'success')
    return redirect(url_for('admin_active_games'))

@app.route('/admin/edit-team-member/<int:member_id>', methods=['GET', 'POST'])
def admin_edit_team_member(member_id):
    if session.get('username') != 'admin': return redirect(url_for('login'))
    member = TeamMember.query.get_or_404(member_id)
    if request.method == 'POST':
        member.name = request.form.get('name', member.name)
        member.email = request.form.get('email', member.email)
        member.team_name = request.form.get('team_name', member.team_name)
        db.session.commit()
        flash('Takım üyesi güncellendi.', 'success')
        return redirect(url_for('admin_active_games'))
    return render_template('admin/edit_team_member.html', member=member, active_page='active_games')

@app.route('/admin/delete-team-member/<int:member_id>')
def admin_delete_team_member(member_id):
    if session.get('username') != 'admin': return redirect(url_for('login'))
    member = TeamMember.query.get_or_404(member_id)
    db.session.delete(member)
    db.session.commit()
    flash('Takım üyesi silindi.', 'success')
    return redirect(url_for('admin_active_games'))

@app.route('/admin/add-team-member', methods=['POST'])
def admin_add_team_member():
    if session.get('username') != 'admin': return redirect(url_for('login'))
    purchase_id = request.form.get('purchase_id')
    name = request.form.get('name')
    email = request.form.get('email')
    team_number = int(request.form.get('team_number', 1))
    team_name = request.form.get('team_name', '')
    
    if not purchase_id or not name or not email:
        flash('Tüm alanları doldurun.', 'error')
        return redirect(url_for('admin_active_games'))
    
    import secrets
    new_member = TeamMember(
        purchase_id=purchase_id,
        team_purchase_id=purchase_id,
        name=name,
        email=email,
        team_number=team_number,
        team_name=team_name,
        access_token=secrets.token_urlsafe(32)
    )
    db.session.add(new_member)
    db.session.commit()
    flash(f'{name} takıma eklendi.', 'success')
    return redirect(url_for('admin_active_games'))

@app.route('/admin/orders')
def admin_orders():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    tab = request.args.get('tab', 'individual')
    
    # Bireysel satışlar
    orders = Order.query.order_by(Order.date.desc()).all()
    individual_purchases = Purchase.query.filter_by(is_paid=True).order_by(Purchase.created_at.desc()).all()
    
    # Takım satışları
    team_purchases = TeamPurchase.query.filter_by(payment_status='completed').order_by(TeamPurchase.created_at.desc()).all()
    
    # Ortak satışları (PartnerSale modelini kullan)
    affiliate_sales = PartnerSale.query.order_by(PartnerSale.created_at.desc()).all()
    
    # Erişim kodu satışları
    access_code_sales = AccessCode.query.filter_by(is_used=True).order_by(AccessCode.used_at.desc()).all()
    
    # Toplam gelirler
    individual_total = sum([p.amount for p in individual_purchases if p.amount])
    team_total = sum([t.total_price for t in team_purchases if t.total_price])
    affiliate_total = sum([s.sale_amount for s in affiliate_sales if s.sale_amount])
    access_code_total = sum([ac.sale_price or 0 for ac in access_code_sales if hasattr(ac, 'sale_price') and ac.sale_price])
    
    return render_template('admin/admin_orders.html', 
                           orders=orders, 
                           individual_purchases=individual_purchases,
                           team_purchases=team_purchases,
                           affiliate_sales=affiliate_sales,
                           access_code_sales=access_code_sales,
                           individual_total=individual_total,
                           team_total=team_total,
                           affiliate_total=affiliate_total,
                           access_code_total=access_code_total,
                           tab=tab,
                           active_page='orders')

@app.route('/admin/add', methods=['GET', 'POST'])
def admin_add_case():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    if request.method == 'POST':
        case_id_val = request.form.get('id')
        case_folder = get_case_upload_folder(case_id_val)

        img = request.files.get('image')
        img_name = secure_filename(img.filename) if img and img.filename else 'default.jpg'
        if img and img.filename:
            img.save(os.path.join(case_folder, img_name))

        video_value = request.form.get('video') or '#'
        video_file = request.files.get('video_file')
        if video_file and video_file.filename:
            video_name = secure_filename(video_file.filename)
            video_file.save(os.path.join(case_folder, video_name))
            video_value = video_name

        success_file_name = None
        success_file = request.files.get('success_file')
        if success_file and success_file.filename:
            success_file_name = secure_filename(success_file.filename)
            file_path = os.path.join(case_folder, success_file_name)
            success_file.save(file_path)

        report_company_tr = request.form.get('report_company_tr')
        report_company_val = report_company_tr if report_company_tr else request.form.get('report_company')

        new_case = Case(
            id=request.form.get('id'),
            title=request.form.get('title'),
            price=float(request.form.get('price')),
            old_price=float(request.form.get('old_price') or 0.0),
            discount_rate=int(request.form.get('discount_rate') or 0),
            description=request.form.get('description'),
            difficulty=request.form.get('difficulty', 'Orta'),
            game_type=request.form.get('game_type', 'both'),
            report_case_name=request.form.get('report_case_name'),
            report_company=report_company_val,
            success_message=request.form.get('success_message'),
            image=img_name,
            video=video_value,
            police_department=request.form.get('police_department'),
            commissioner_name=request.form.get('commissioner_name'),
            report_letter=request.form.get('report_letter'),
            warning_text=request.form.get('warning_text'),
            instructions_text=request.form.get('instructions_text'),
            demo_enabled=request.form.get('demo_enabled') == 'on',
            demo_summary=request.form.get('demo_summary'),
            report_greeting=request.form.get('report_greeting'),
            report_signature_name=request.form.get('report_signature_name'),
            report_intro_text=request.form.get('report_intro_text'),
            report_suspect_question=request.form.get('report_suspect_question'),
            report_confirmation_text=request.form.get('report_confirmation_text'),
            culprit_keywords=request.form.get('culprit_keywords', ''),
            explanation_keywords=request.form.get('explanation_keywords', ''),
            success_file=success_file_name,
        )
        db.session.add(new_case)
        db.session.flush()

        if success_file_name and success_file_name.lower().endswith(('.html', '.htm')):
            file_path = os.path.join(get_case_upload_folder(new_case.id), success_file_name)
            culprit_kw, explanation_kw = extract_keywords_from_html(file_path)
            if culprit_kw:
                new_case.culprit_keywords = culprit_kw
            if explanation_kw:
                new_case.explanation_keywords = explanation_kw

        suspect_names = request.form.getlist('suspect_names[]')
        culprit_index = int(request.form.get('culprit_index', 0))
        for i, name in enumerate(suspect_names):
            if name.strip():
                suspect = Suspect(
                    name=name.strip(),
                    case_id=new_case.id,
                    is_culprit=(i == culprit_index)
                )
                db.session.add(suspect)
                if i == culprit_index:
                    new_case.solution = name.strip().lower().split()[0] if name.strip() else ''

        file_categories = {
            'cat1': ('Olay Raporları', None),
            'cat2_profil': ('Mağdur Detayları', 'Profil Raporları'),
            'cat2_olayeri': ('Mağdur Detayları', 'Olay Yeri Raporları'),
            'cat2_otopsi': ('Mağdur Detayları', 'Otopsi Raporları'),
            'cat3': ('Şüpheli Profilleri', None),
            'cat4': ('Röportaj Kayıtları', None),
            'cat5': ('Tanık Beyanları', None),
            'cat6_konum': ('Kanıt Arşivi', 'Konum Haritaları'),
            'cat6_mesaj': ('Kanıt Arşivi', 'SMS/Email Kayıtları'),
            'cat6_audio': ('Kanıt Arşivi', 'Ses Dosyaları'),
            'cat6_video': ('Kanıt Arşivi', 'Kamera Görüntüleri'),
            'cat7': ('Diğer Belgeler', None),
        }

        for field_name, (category, sub_category) in file_categories.items():
            files = request.files.getlist(field_name)
            for f in files:
                if f and f.filename:
                    fname = secure_filename(f.filename)
                    f.save(os.path.join(get_case_upload_folder(new_case.id), fname))
                    ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
                    db.session.add(CaseFile(filename=fname, category=category, sub_category=sub_category, file_ext=ext, case_id=new_case.id))

        db.session.commit()
        flash("Vaka başarıyla kaydedildi!")
        return redirect(url_for('admin_cases'))
    return render_template('admin/add_case.html', active_page='add_case')

@app.route('/admin/toggle-case/<case_id>', methods=['POST'])
def admin_toggle_case(case_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    case = Case.query.get_or_404(case_id)
    was_inactive = not case.is_active
    case.is_active = not case.is_active
    db.session.commit()
    try:
        export_initial_data()
    except:
        pass
    status = "aktif" if case.is_active else "pasif"
    flash(f"'{case.title}' vakası {status} yapıldı.", "success")

    # Vaka aktif edildiyse ve abonelere bildir seçildiyse newsletter gönder
    notify = request.form.get('notify_subscribers') == '1'
    if case.is_active and was_inactive and notify:
        import threading
        base_url = request.host_url.rstrip('/')
        def send_bg():
            with app.app_context():
                sent = send_new_case_newsletter(case_id, base_url=base_url)
        t = threading.Thread(target=send_bg, daemon=True)
        t.start()
        flash(f"📧 '{case.title}' için abonelere duyuru e-postası gönderiliyor...", "info")

    return redirect(url_for('admin_cases'))

@app.route('/admin/delete/<id>')
def admin_delete_case(id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    case = Case.query.get_or_404(id)
    db.session.delete(case); db.session.commit()
    flash("Vaka başarıyla silindi."); return redirect(url_for('admin_cases'))

@app.route('/admin/duplicate/<case_id>')
def admin_duplicate_case(case_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    original = Case.query.get_or_404(case_id)
    import time
    base_id = original.id[:35] if len(original.id) > 35 else original.id
    if base_id.endswith('-kopya') or '-kopya-' in base_id:
        base_id = base_id.split('-kopya')[0]
    new_id = base_id + '-kopya-' + str(int(time.time()))[-6:]
    new_case = Case(
        id=new_id,
        title=original.title,
        title_en=original.title_en,
        price=original.price,
        image=original.image,
        video=original.video,
        description=original.description,
        description_en=original.description_en,
        solution=original.solution,
        old_price=original.old_price,
        discount_rate=original.discount_rate,
        difficulty=original.difficulty,
        is_active=False,
        report_case_name=original.report_case_name,
        report_case_name_en=original.report_case_name_en,
        report_company=original.report_company,
        report_company_en=original.report_company_en,
        success_message=original.success_message,
        success_message_en=original.success_message_en,
        success_file=original.success_file,
        police_department=original.police_department,
        police_department_en=original.police_department_en,
        report_letter=original.report_letter,
        report_letter_en=original.report_letter_en,
        commissioner_name=original.commissioner_name,
        commissioner_name_en=original.commissioner_name_en,
        warning_text=original.warning_text,
        warning_text_en=original.warning_text_en,
        instructions_text=original.instructions_text,
        instructions_text_en=original.instructions_text_en,
        report_greeting=original.report_greeting,
        report_greeting_en=original.report_greeting_en,
        report_intro_text=original.report_intro_text,
        report_intro_text_en=original.report_intro_text_en,
        report_suspect_question=original.report_suspect_question,
        report_suspect_question_en=original.report_suspect_question_en,
        report_confirmation_text=original.report_confirmation_text,
        report_confirmation_text_en=original.report_confirmation_text_en,
        report_signature_name=original.report_signature_name,
        report_signature_name_en=original.report_signature_name_en,
        demo_enabled=original.demo_enabled,
        demo_summary=original.demo_summary,
        demo_summary_en=original.demo_summary_en,
        game_type=original.game_type,
        culprit_keywords=original.culprit_keywords,
        explanation_keywords=original.explanation_keywords,
    )
    db.session.add(new_case)
    db.session.flush()
    for suspect in original.suspects:
        db.session.add(Suspect(name=suspect.name, is_culprit=suspect.is_culprit, case_id=new_id))
    for f in original.files:
        db.session.add(CaseFile(filename=f.filename, display_name=f.display_name, category=f.category, sub_category=f.sub_category, file_ext=f.file_ext, youtube_link=f.youtube_link, case_id=new_id))
    src_folder = get_case_upload_folder(original.id)
    dst_folder = get_case_upload_folder(new_id)
    if os.path.exists(src_folder):
        for fname in os.listdir(src_folder):
            src_file = os.path.join(src_folder, fname)
            dst_file = os.path.join(dst_folder, fname)
            if os.path.isfile(src_file):
                shutil.copy2(src_file, dst_file)

    db.session.commit()
    flash("Vaka kopyası oluşturuldu! Şimdi düzenleyebilirsiniz.")
    return redirect(url_for('admin_edit_case', case_id=new_id))

@app.route('/admin/bulk-delete-files', methods=['POST'])
def admin_bulk_delete_files():
    if session.get('username') != 'admin':
        return jsonify({'success': False, 'error': 'Yetkisiz'}), 403
    data = request.get_json()
    file_ids = data.get('file_ids', [])
    deleted = 0
    for fid in file_ids:
        f = CaseFile.query.get(int(fid))
        if f:
            try:
                fp = os.path.join(get_case_upload_folder(f.case_id), f.filename)
                if os.path.exists(fp):
                    os.remove(fp)
            except: pass
            db.session.delete(f)
            deleted += 1
    db.session.commit()
    return jsonify({'success': True, 'deleted': deleted})

@app.route('/admin/delete-file/<int:file_id>')
def admin_delete_file(file_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    file = CaseFile.query.get_or_404(file_id)
    case_id = file.case_id
    try:
        file_path = os.path.join(get_case_upload_folder(file.case_id), file.filename)
        if os.path.exists(file_path):
            os.remove(file_path)
    except: pass
    db.session.delete(file)
    db.session.commit()
    flash("Dosya başarıyla silindi.")
    return redirect(url_for('admin_edit_case', case_id=case_id))

@app.route('/admin/download-file/<int:file_id>')
def admin_download_file(file_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    file = CaseFile.query.get_or_404(file_id)
    return send_from_directory(get_case_upload_folder(file.case_id), file.filename, as_attachment=True)

@app.route('/download-all-files/<case_id>')
def download_all_files(case_id):
    case = Case.query.get_or_404(case_id)
    is_admin = session.get('username') == 'admin'
    is_logged_in = 'user_id' in session
    if not is_admin and not is_logged_in:
        return redirect(url_for('login'))
    case_files = CaseFile.query.filter_by(case_id=case_id).all()
    if not case_files:
        flash('Bu vakada indirilecek dosya bulunamadı.')
        return redirect(request.referrer or url_for('index'))
    buffer = BytesIO()
    case_folder = get_case_upload_folder(case_id)
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for cf in case_files:
            file_path = os.path.join(case_folder, cf.filename)
            if os.path.exists(file_path):
                arcname = cf.display_name or cf.filename
                if not os.path.splitext(arcname)[1]:
                    arcname += os.path.splitext(cf.filename)[1]
                zf.write(file_path, arcname)
    buffer.seek(0)
    safe_title = re.sub(r'[^\w\s-]', '', case.title or case_id).strip().replace(' ', '_')
    from flask import send_file
    return send_file(buffer, mimetype='application/zip', as_attachment=True, download_name=f'{safe_title}_dosyalar.zip')

@app.route('/admin/update-file', methods=['POST'])
def admin_update_file():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    file_id = request.form.get('file_id')
    case_id = request.form.get('case_id')
    file = CaseFile.query.get_or_404(int(file_id))
    file.category = request.form.get('category')
    file.sub_category = request.form.get('sub_category') or None
    file.display_name = request.form.get('display_name') or None
    file.youtube_link = request.form.get('youtube_link') or None
    db.session.commit()
    flash("Dosya bilgileri güncellendi.")
    return redirect(url_for('admin_edit_case', case_id=case_id))

@app.route('/admin/get-html-content/<int:file_id>')
def admin_get_html_content(file_id):
    if session.get('username') != 'admin':
        return jsonify({"error": "Yetkisiz"}), 403
    file = CaseFile.query.get_or_404(file_id)
    if file.file_ext not in ('html', 'htm'):
        return jsonify({"error": "Bu dosya HTML değil"}), 400
    file_path = os.path.join(get_case_upload_folder(file.case_id), file.filename)
    if not os.path.exists(file_path):
        return jsonify({"error": "Dosya bulunamadı"}), 404
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return jsonify({"content": content, "filename": file.filename})

@app.route('/admin/save-html-content/<int:file_id>', methods=['POST'])
def admin_save_html_content(file_id):
    if session.get('username') != 'admin':
        return jsonify({"error": "Yetkisiz"}), 403
    file = CaseFile.query.get_or_404(file_id)
    if file.file_ext not in ('html', 'htm'):
        return jsonify({"error": "Bu dosya HTML değil"}), 400
    data = request.get_json()
    if not data or 'content' not in data:
        return jsonify({"error": "İçerik bulunamadı"}), 400
    file_path = os.path.join(get_case_upload_folder(file.case_id), file.filename)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(data['content'])
    return jsonify({"success": True, "message": "Dosya başarıyla kaydedildi."})

@app.route('/admin/add-hint/<case_id>', methods=['POST'])
def admin_add_hint(case_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    hint_text = request.form.get('hint_text') or ''
    hint_text_en = request.form.get('hint_text_en')
    show_date = request.form.get('show_date')
    show_time = request.form.get('show_time', '00:00')
    unlock_price = float(request.form.get('unlock_price', 0) or 0)
    
    hint_file = request.files.get('hint_file')
    hint_filename = None
    if hint_file and hint_file.filename:
        hint_filename = secure_filename(hint_file.filename)
        hint_file.save(os.path.join(get_case_upload_folder(case_id), hint_filename))
    
    if (hint_text or hint_filename) and show_date:
        show_datetime = datetime.strptime(f"{show_date} {show_time}", "%Y-%m-%d %H:%M")
        new_hint = Hint(
            hint_text=hint_text or 'Dosya ipucu',
            hint_text_en=hint_text_en,
            hint_file=hint_filename,
            show_datetime=show_datetime,
            case_id=case_id,
            unlock_price=unlock_price
        )
        db.session.add(new_hint)
        db.session.commit()
        flash("İpucu başarıyla eklendi.")
    return redirect(url_for('admin_edit_case', case_id=case_id))

@app.route('/admin/delete-hint/<int:hint_id>')
def admin_delete_hint(hint_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    hint = Hint.query.get_or_404(hint_id)
    case_id = hint.case_id
    db.session.delete(hint)
    db.session.commit()
    flash("İpucu başarıyla silindi.")
    return redirect(url_for('admin_edit_case', case_id=case_id))

@app.route('/admin/toggle-hint/<int:hint_id>')
def admin_toggle_hint(hint_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    hint = Hint.query.get_or_404(hint_id)
    hint.is_active = not hint.is_active
    db.session.commit()
    flash("İpucu durumu güncellendi.")
    return redirect(url_for('admin_edit_case', case_id=hint.case_id))

@app.route('/admin/edit-hint/<int:hint_id>', methods=['POST'])
def admin_edit_hint(hint_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    hint = Hint.query.get_or_404(hint_id)
    hint.hint_text = request.form.get('hint_text', hint.hint_text)
    hint.hint_text_en = request.form.get('hint_text_en', hint.hint_text_en)
    show_date = request.form.get('show_date')
    show_time = request.form.get('show_time', '00:00')
    if show_date:
        hint.show_datetime = datetime.strptime(f"{show_date} {show_time}", "%Y-%m-%d %H:%M")
    hint.unlock_price = float(request.form.get('unlock_price', 0) or 0)
    
    if request.form.get('remove_hint_file'):
        if hint.hint_file:
            old_path = os.path.join(get_case_upload_folder(hint.case_id), hint.hint_file)
            if os.path.exists(old_path):
                os.remove(old_path)
            hint.hint_file = None
    
    hint_file = request.files.get('hint_file')
    if hint_file and hint_file.filename:
        hint_filename = secure_filename(hint_file.filename)
        hint_file.save(os.path.join(get_case_upload_folder(hint.case_id), hint_filename))
        hint.hint_file = hint_filename
    
    db.session.commit()
    flash("İpucu başarıyla güncellendi.")
    return redirect(url_for('admin_edit_case', case_id=hint.case_id))

@app.route('/admin/extract-keywords/<case_id>')
def admin_extract_keywords(case_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    case = Case.query.get_or_404(case_id)
    
    if case.success_file:
        file_path = os.path.join(get_case_upload_folder(case_id), case.success_file)
        if os.path.exists(file_path) and case.success_file.lower().endswith(('.html', '.htm')):
            culprit_kw, explanation_kw = extract_keywords_from_html(file_path)
            if culprit_kw:
                case.culprit_keywords = culprit_kw
                flash(f"Suçlu anahtar kelimeleri çekildi: {culprit_kw}")
            else:
                flash("HTML dosyasında suçlu anahtar kelimeleri bulunamadı. <!-- SUCLU: kelime1, kelime2 --> formatında ekleyin.")
            if explanation_kw:
                case.explanation_keywords = explanation_kw
                flash(f"Açıklama anahtar kelimeleri çekildi: {explanation_kw}")
            db.session.commit()
        else:
            flash("Başarı dosyası HTML formatında değil veya bulunamadı.")
    else:
        flash("Başarı dosyası yüklenmemiş.")
    
    return redirect(url_for('admin_edit_case', case_id=case_id))

@app.route('/unlock-hint/<int:hint_id>')
def unlock_hint_early(hint_id):
    if 'user_id' not in session:
        flash("Bu ozellik icin giris yapmaniz gerekiyor.")
        return redirect(url_for('login'))
    hint = Hint.query.get_or_404(hint_id)
    user = User.query.get(session['user_id'])
    unlocked_hints = (user.unlocked_hints or '').split(',')
    if str(hint_id) in unlocked_hints:
        flash("Bu ipucu zaten acilmis.")
        return redirect(url_for('play_case', case_id=hint.case_id))
    session['pending_hint_id'] = hint_id
    settings = get_payment_settings()
    iyzico_enabled = settings.get('iyzico_enabled') == '1'
    havale_enabled = settings.get('havale_enabled') == '1'
    param_enabled = settings.get('param_enabled') == '1'
    return render_template('hint_checkout.html', hint=hint, user=user, 
                         iyzico_enabled=iyzico_enabled, havale_enabled=havale_enabled, param_enabled=param_enabled)

@app.route('/payment/hint/<int:hint_id>', methods=['POST'])
def payment_hint(hint_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    hint = Hint.query.get_or_404(hint_id)
    user = User.query.get(session['user_id'])
    payment_provider = request.form.get('payment_provider', 'iyzico')
    settings = get_payment_settings()
    
    session['pending_hint_id'] = hint_id
    
    if payment_provider == 'havale':
        if settings.get('havale_enabled') != '1':
            flash("Havale ödeme seçeneği aktif değil.")
            return redirect(url_for('play_case', case_id=hint.case_id))
        return redirect(url_for('payment_havale_hint', hint_id=hint_id))
    elif payment_provider == 'iyzico':
        if settings.get('iyzico_enabled') != '1':
            flash("iyzico odeme sistemi aktif degil.")
            return redirect(url_for('play_case', case_id=hint.case_id))
        
        api_key = settings.get('iyzico_api_key', '')
        secret_key = settings.get('iyzico_secret_key', '')
        base_url = settings.get('iyzico_base_url', 'https://sandbox-api.iyzipay.com')
        
        conversation_id = f"HINT{user.id}{hint_id}{random.randint(1000,9999)}"
        
        request_data = {
            "locale": "tr",
            "conversationId": conversation_id,
            "price": str(hint.unlock_price),
            "paidPrice": str(hint.unlock_price),
            "currency": "TRY",
            "basketId": f"BHINT{hint_id}",
            "paymentGroup": "PRODUCT",
            "callbackUrl": url_for('hint_payment_callback', _external=True),
            "enabledInstallments": [1],
            "buyer": {
                "id": f"BY{user.id}",
                "name": user.first_name or user.username,
                "surname": user.last_name or ".",
                "gsmNumber": "+905000000000",
                "email": user.email,
                "identityNumber": "74300864791",
                "registrationAddress": user.billing_address or "Adres",
                "ip": request.remote_addr,
                "city": "Istanbul",
                "country": "Turkey"
            },
            "shippingAddress": {"contactName": user.first_name or user.username, "city": "Istanbul", "country": "Turkey", "address": "Adres"},
            "billingAddress": {"contactName": user.first_name or user.username, "city": "Istanbul", "country": "Turkey", "address": "Adres"},
            "basketItems": [{"id": f"HI{hint_id}", "name": "Ipucu Erken Acma", "category1": "Ipucu", "itemType": "VIRTUAL", "price": str(hint.unlock_price)}]
        }
        
        random_string = base64.b64encode(os.urandom(8)).decode()
        hash_string = hashlib.sha1((random_string + secret_key).encode()).hexdigest()
        authorization = f"IYZWS {api_key}:{hash_string}"
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json', 'Authorization': authorization, 'x-iyzi-rnd': random_string}
        
        try:
            response = requests.post(f"{base_url}/payment/iyzipos/checkoutform/initialize/auth/ecom", json=request_data, headers=headers)
            result = response.json()
            if result.get('status') == 'success':
                return render_template('payment_iyzico.html', checkout_form=result.get('checkoutFormContent'), case=None, hint=hint)
            else:
                flash(f"iyzico hatasi: {result.get('errorMessage', 'Bilinmeyen hata')}")
                return redirect(url_for('play_case', case_id=hint.case_id))
        except Exception as e:
            flash(f"Odeme hatasi: {str(e)}")
            return redirect(url_for('play_case', case_id=hint.case_id))
    elif payment_provider == 'param':
        if settings.get('param_enabled') != '1':
            flash("Param POS odeme sistemi aktif degil.")
            return redirect(url_for('play_case', case_id=hint.case_id))
        return redirect(url_for('param_hint', hint_id=hint_id))
    else:
        flash("Gecerli bir odeme yontemi seciniz.")
        return redirect(url_for('play_case', case_id=hint.case_id))

@app.route('/payment/hint-success')
def hint_payment_success():
    hint_id = session.pop('pending_hint_id', None)
    if hint_id and 'user_id' in session:
        user = User.query.get(session['user_id'])
        hint = Hint.query.get(hint_id)
        unlocked = (user.unlocked_hints or '').split(',')
        if str(hint_id) not in unlocked:
            user.unlocked_hints = f"{user.unlocked_hints},{hint_id}" if user.unlocked_hints else str(hint_id)
            db.session.commit()
        flash("Odeme basarili! Ipucu acildi.")
        return redirect(url_for('play_case', case_id=hint.case_id))
    flash("Odeme basarili!")
    return redirect(url_for('index'))

@app.route('/hint-payment-callback', methods=['POST'])
def hint_payment_callback():
    token = request.form.get('token')
    hint_id = session.get('pending_hint_id')
    if not token or not hint_id:
        flash("Odeme dogrulanamadi.")
        return redirect(url_for('payment_fail'))
    
    settings = get_payment_settings()
    api_key = settings.get('iyzico_api_key', '')
    secret_key = settings.get('iyzico_secret_key', '')
    base_url = settings.get('iyzico_base_url', 'https://sandbox-api.iyzipay.com')
    
    random_string = base64.b64encode(os.urandom(8)).decode()
    hash_string = hashlib.sha1((random_string + secret_key).encode()).hexdigest()
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json', 'Authorization': f"IYZWS {api_key}:{hash_string}", 'x-iyzi-rnd': random_string}
    
    try:
        response = requests.post(f"{base_url}/payment/iyzipos/checkoutform/auth/ecom/detail", json={"locale": "tr", "token": token}, headers=headers)
        result = response.json()
        if result.get('paymentStatus') == 'SUCCESS':
            return redirect(url_for('hint_payment_success'))
        else:
            flash("Odeme basarisiz.")
            return redirect(url_for('payment_fail'))
    except:
        flash("Odeme dogrulama hatasi.")
        return redirect(url_for('payment_fail'))

@app.route('/admin/edit/<case_id>', methods=['GET', 'POST'])
def admin_edit_case(case_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    case = Case.query.get_or_404(case_id)
    
    if request.method == 'POST':
        new_id = request.form.get('new_case_id', '').strip()
        if new_id and new_id != case.id:
            import re
            new_id = re.sub(r'[^a-zA-Z0-9\-_çğıöşüÇĞİÖŞÜ.]', '-', new_id).strip('-')
            existing = Case.query.get(new_id)
            if existing:
                flash("Bu ID zaten başka bir vakada kullanılıyor!")
                return redirect(url_for('admin_edit_case', case_id=case.id))
            old_id = case.id
            try:
                conn = db.session.connection()
                conn.execute(db.text("SET CONSTRAINTS ALL DEFERRED"))
                conn.execute(db.text("UPDATE \"case\" SET id = :new WHERE id = :old"), {"new": new_id, "old": old_id})
                for tbl in ['suspect', 'case_file', 'comment', 'hint', 'purchase', 'game_progress', 'solved_cases', 'access_code', 'team_purchase', 'discount_code', 'partner_sale']:
                    try:
                        conn.execute(db.text(f'UPDATE "{tbl}" SET case_id = :new WHERE case_id = :old'), {"new": new_id, "old": old_id})
                    except Exception:
                        pass
                db.session.commit()
                old_folder = os.path.join(UPLOAD_FOLDER, str(old_id))
                new_folder = os.path.join(UPLOAD_FOLDER, str(new_id))
                if os.path.exists(old_folder) and not os.path.exists(new_folder):
                    os.rename(old_folder, new_folder)
                case = Case.query.get(new_id)
            except Exception as e:
                db.session.rollback()
                flash(f"ID değiştirme hatası: {str(e)}")
                return redirect(url_for('admin_edit_case', case_id=old_id))

        case.title = request.form.get('title')
        case.title_en = request.form.get('title_en')
        case.description = request.form.get('description')
        case.description_en = request.form.get('description_en')
        case.price = float(request.form.get('price'))
        case.old_price = float(request.form.get('old_price') or 0)
        case.discount_rate = int(request.form.get('discount_rate') or 0)
        case.difficulty = request.form.get('difficulty', 'Orta')
        case.report_case_name = request.form.get('report_case_name')
        case.report_case_name_en = request.form.get('report_case_name_en')
        case.report_company = request.form.get('report_company')
        case.report_company_en = request.form.get('report_company_en')
        case.report_greeting = request.form.get('report_greeting')
        case.report_greeting_en = request.form.get('report_greeting_en')
        case.report_intro_text = request.form.get('report_intro_text')
        case.report_intro_text_en = request.form.get('report_intro_text_en')
        case.report_suspect_question = request.form.get('report_suspect_question')
        case.report_suspect_question_en = request.form.get('report_suspect_question_en')
        case.report_confirmation_text = request.form.get('report_confirmation_text')
        case.report_confirmation_text_en = request.form.get('report_confirmation_text_en')
        case.report_signature_name = request.form.get('report_signature_name')
        case.report_signature_name_en = request.form.get('report_signature_name_en')
        case.success_message = request.form.get('success_message')
        case.success_message_en = request.form.get('success_message_en')
        
        if request.form.get('remove_success_file'):
            if case.success_file:
                old_path = os.path.join(get_case_upload_folder(case.id), case.success_file)
                if os.path.exists(old_path):
                    os.remove(old_path)
                case.success_file = None
        
        success_file = request.files.get('success_file')
        if success_file and success_file.filename:
            success_filename = secure_filename(success_file.filename)
            file_path = os.path.join(get_case_upload_folder(case.id), success_filename)
            success_file.save(file_path)
            case.success_file = success_filename
            
            # HTML dosyasından otomatik anahtar kelime çıkar
            if success_filename.lower().endswith(('.html', '.htm')):
                culprit_kw, explanation_kw = extract_keywords_from_html(file_path)
                if culprit_kw:
                    case.culprit_keywords = culprit_kw
                if explanation_kw:
                    case.explanation_keywords = explanation_kw
        
        case.video = request.form.get('video') or '#'
        case.police_department = request.form.get('police_department')
        case.police_department_en = request.form.get('police_department_en')
        case.report_letter = request.form.get('report_letter')
        case.report_letter_en = request.form.get('report_letter_en')
        case.commissioner_name = request.form.get('commissioner_name')
        case.commissioner_name_en = request.form.get('commissioner_name_en')
        case.warning_text = request.form.get('warning_text')
        case.warning_text_en = request.form.get('warning_text_en')
        case.instructions_text = request.form.get('instructions_text')
        case.instructions_text_en = request.form.get('instructions_text_en')
        case.demo_enabled = request.form.get('demo_enabled') == 'on'
        case.demo_summary = request.form.get('demo_summary')
        case.demo_summary_en = request.form.get('demo_summary_en')
        case.game_type = request.form.get('game_type', 'both')
        case.culprit_keywords = request.form.get('culprit_keywords', '')
        case.explanation_keywords = request.form.get('explanation_keywords', '')
        
        img = request.files.get('image')
        if img and img.filename:
            img_name = secure_filename(img.filename)
            img.save(os.path.join(get_case_upload_folder(case.id), img_name))
            case.image = img_name
        
        video_file = request.files.get('video_file')
        if video_file and video_file.filename:
            video_name = secure_filename(video_file.filename)
            video_file.save(os.path.join(get_case_upload_folder(case.id), video_name))
            case.video = video_name
        
        suspect_ids = request.form.getlist('suspect_ids[]')
        suspect_names = request.form.getlist('suspect_names[]')
        new_suspect_names = request.form.getlist('new_suspect_names[]')
        culprit_id = request.form.get('culprit_id')
        
        existing_ids = [s.id for s in case.suspects]
        for sid in existing_ids:
            if str(sid) not in suspect_ids:
                Suspect.query.filter_by(id=sid).delete()
        
        for i, sid in enumerate(suspect_ids):
            suspect = Suspect.query.get(int(sid))
            if suspect and i < len(suspect_names):
                suspect.name = suspect_names[i]
                suspect.is_culprit = (culprit_id == str(sid))
        
        for name in new_suspect_names:
            if name.strip():
                new_suspect = Suspect(name=name.strip(), case_id=case.id, is_culprit=False)
                db.session.add(new_suspect)
        
        file_categories = {
            'cat1': ('Olay Raporları', None),
            'cat2_profil': ('Mağdur Detayları', 'Profil Raporları'),
            'cat2_olayeri': ('Mağdur Detayları', 'Olay Yeri Raporları'),
            'cat2_otopsi': ('Mağdur Detayları', 'Otopsi Raporları'),
            'cat3': ('Şüpheli Profilleri', None),
            'cat4': ('Röportaj Kayıtları', None),
            'cat5': ('Tanık Beyanları', None),
            'cat6_konum': ('Kanıt Arşivi', 'Konum Haritaları'),
            'cat6_mesaj': ('Kanıt Arşivi', 'SMS/Email Kayıtları'),
            'cat6_audio': ('Kanıt Arşivi', 'Ses Dosyaları'),
            'cat6_video': ('Kanıt Arşivi', 'Kamera Görüntüleri'),
            'cat7': ('Diğer Belgeler', None),
        }
        
        for field_name, (category, sub_category) in file_categories.items():
            files = request.files.getlist(field_name)
            for f in files:
                if f and f.filename:
                    fname = secure_filename(f.filename)
                    f.save(os.path.join(get_case_upload_folder(case.id), fname))
                    ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
                    db.session.add(CaseFile(filename=fname, category=category, sub_category=sub_category, file_ext=ext, case_id=case.id))
        
        db.session.commit()
        flash("Vaka başarıyla güncellendi!")
        return redirect(url_for('admin_cases'))
    
    return render_template('admin/edit_case.html', case=case, active_page='cases')

@app.route('/admin/discounts')
def admin_discounts():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    discounts = DiscountCode.query.order_by(DiscountCode.created_at.desc()).all()
    cases = Case.query.all()
    return render_template('admin/discounts.html', discounts=discounts, cases=cases, active_page='discounts')

@app.route('/admin/discount/add', methods=['POST'])
def admin_add_discount():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    code = request.form.get('code', '').strip().upper()
    discount_percent = int(request.form.get('discount_percent', 0) or 0)
    discount_amount = float(request.form.get('discount_amount', 0) or 0)
    case_id = request.form.get('case_id') or None
    usage_limit = int(request.form.get('usage_limit', 0) or 0)
    expires_at = request.form.get('expires_at')
    
    if not code:
        flash("Kod alani bos olamaz.")
        return redirect(url_for('admin_discounts'))
    
    existing = DiscountCode.query.filter_by(code=code).first()
    if existing:
        flash("Bu kod zaten mevcut.")
        return redirect(url_for('admin_discounts'))
    
    discount = DiscountCode(
        code=code,
        discount_percent=discount_percent,
        discount_amount=discount_amount,
        case_id=case_id if case_id else None,
        usage_limit=usage_limit,
        expires_at=datetime.strptime(expires_at, '%Y-%m-%d') if expires_at else None
    )
    db.session.add(discount)
    db.session.commit()
    flash("Indirim kodu eklendi.")
    return redirect(url_for('admin_discounts'))

@app.route('/admin/discount/toggle/<int:discount_id>')
def admin_toggle_discount(discount_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    discount = DiscountCode.query.get_or_404(discount_id)
    discount.is_active = not discount.is_active
    db.session.commit()
    flash("Indirim kodu durumu guncellendi.")
    return redirect(url_for('admin_discounts'))

@app.route('/admin/discount/delete/<int:discount_id>')
def admin_delete_discount(discount_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    discount = DiscountCode.query.get_or_404(discount_id)
    db.session.delete(discount)
    db.session.commit()
    flash("Indirim kodu silindi.")
    return redirect(url_for('admin_discounts'))

# --- ADMİN: HOW TO PLAY YÖNETİMİ ---
@app.route('/admin/how-to-play')
def admin_how_to_play():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    steps = HowToPlayStep.query.order_by(HowToPlayStep.order_num).all()
    return render_template('admin/how_to_play.html', steps=steps, active_page='how_to_play')

@app.route('/admin/how-to-play/add', methods=['GET', 'POST'])
def admin_add_how_to_play():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    if request.method == 'POST':
        order_num = int(request.form.get('order_num', 1))
        badge = request.form.get('badge', 'ADIM 1')
        badge_en = request.form.get('badge_en', 'STEP 1')
        title = request.form.get('title', '')
        title_en = request.form.get('title_en', '')
        content = request.form.get('content', '')
        content_en = request.form.get('content_en', '')
        is_active = request.form.get('is_active') == 'on'
        
        image_filename = None
        if 'image' in request.files:
            image = request.files['image']
            if image and image.filename:
                image_filename = secure_filename(image.filename)
                image.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
        
        step = HowToPlayStep(
            order_num=order_num,
            badge=badge,
            badge_en=badge_en,
            title=title,
            title_en=title_en,
            content=content,
            content_en=content_en,
            image=image_filename,
            is_active=is_active
        )
        db.session.add(step)
        db.session.commit()
        flash("Adım başarıyla eklendi.")
        return redirect(url_for('admin_how_to_play'))
    return render_template('admin/how_to_play_form.html', step=None, active_page='how_to_play')

@app.route('/admin/how-to-play/edit/<int:step_id>', methods=['GET', 'POST'])
def admin_edit_how_to_play(step_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    step = HowToPlayStep.query.get_or_404(step_id)
    if request.method == 'POST':
        step.order_num = int(request.form.get('order_num', 1))
        step.badge = request.form.get('badge', 'ADIM 1')
        step.badge_en = request.form.get('badge_en', 'STEP 1')
        step.title = request.form.get('title', '')
        step.title_en = request.form.get('title_en', '')
        step.content = request.form.get('content', '')
        step.content_en = request.form.get('content_en', '')
        step.is_active = request.form.get('is_active') == 'on'
        
        if 'image' in request.files:
            image = request.files['image']
            if image and image.filename:
                image_filename = secure_filename(image.filename)
                image.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
                step.image = image_filename
        
        db.session.commit()
        flash("Adım başarıyla güncellendi.")
        return redirect(url_for('admin_how_to_play'))
    return render_template('admin/how_to_play_form.html', step=step, active_page='how_to_play')

@app.route('/admin/how-to-play/delete/<int:step_id>')
def admin_delete_how_to_play(step_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    step = HowToPlayStep.query.get_or_404(step_id)
    db.session.delete(step)
    db.session.commit()
    flash("Adım başarıyla silindi.")
    return redirect(url_for('admin_how_to_play'))

@app.route('/admin/how-to-play/toggle/<int:step_id>')
def admin_toggle_how_to_play(step_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    step = HowToPlayStep.query.get_or_404(step_id)
    step.is_active = not step.is_active
    db.session.commit()
    flash("Adım durumu güncellendi.")
    return redirect(url_for('admin_how_to_play'))

@app.route('/apply-discount', methods=['POST'])
def apply_discount():
    code = request.form.get('discount_code', '').strip().upper()
    if not code:
        flash("Lutfen bir indirim kodu girin.")
        return redirect(url_for('view_cart'))
    
    discount = DiscountCode.query.filter_by(code=code, is_active=True).first()
    if not discount:
        flash("Gecersiz veya suresi dolmus indirim kodu.")
        return redirect(url_for('view_cart'))
    
    if discount.expires_at and discount.expires_at < datetime.utcnow():
        flash("Bu indirim kodunun suresi dolmus.")
        return redirect(url_for('view_cart'))
    
    if discount.usage_limit > 0 and discount.usage_count >= discount.usage_limit:
        flash("Bu indirim kodu kullanim limitine ulasmis.")
        return redirect(url_for('view_cart'))
    
    session['applied_discount'] = {
        'id': discount.id,
        'code': discount.code,
        'percent': discount.discount_percent,
        'amount': discount.discount_amount,
        'case_id': discount.case_id
    }
    flash(f"Indirim kodu '{code}' uygulandi!")
    return redirect(url_for('view_cart'))

@app.route('/remove-discount')
def remove_discount():
    session.pop('applied_discount', None)
    flash("Indirim kodu kaldirildi.")
    return redirect(url_for('view_cart'))

@app.route('/admin/messages')
def admin_messages():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    messages = ContactMessage.query.order_by(ContactMessage.created_at.desc()).all()
    return render_template('admin/messages.html', messages=messages)

@app.route('/admin/message/<int:msg_id>', methods=['GET', 'POST'])
def admin_message_detail(msg_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    msg = ContactMessage.query.get_or_404(msg_id)
    if not msg.is_read:
        msg.is_read = True
        db.session.commit()
    if request.method == 'POST':
        reply = request.form.get('reply', '').strip()
        if reply:
            msg.reply = reply
            msg.is_replied = True
            msg.replied_at = datetime.utcnow()
            db.session.commit()
            flash("Cevap kaydedildi.")
            return redirect(url_for('admin_messages'))
    return render_template('admin/message_detail.html', msg=msg)

@app.route('/admin/message/delete/<int:msg_id>')
def admin_delete_message(msg_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    msg = ContactMessage.query.get_or_404(msg_id)
    db.session.delete(msg)
    db.session.commit()
    flash("Mesaj silindi.")
    return redirect(url_for('admin_messages'))

@app.route('/admin/messages/bulk-delete', methods=['POST'])
def admin_bulk_delete_messages():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    scope = request.form.get('scope', 'selected')
    if scope == 'all':
        deleted = ContactMessage.query.delete(synchronize_session=False)
    elif scope == 'read':
        deleted = ContactMessage.query.filter_by(is_read=True).delete(synchronize_session=False)
    else:
        ids = [int(i) for i in request.form.getlist('msg_ids') if i.isdigit()]
        deleted = 0
        if ids:
            deleted = ContactMessage.query.filter(ContactMessage.id.in_(ids)).delete(synchronize_session=False)
    db.session.commit()
    flash(f"{deleted} mesaj silindi.")
    return redirect(url_for('admin_messages'))

@app.route('/admin/settings', defaults={'section': 'news'}, methods=['GET', 'POST'])
@app.route('/admin/settings/<section>', methods=['GET', 'POST'])
def admin_settings(section):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    
    # Handle add_page POST first
    if section == 'add_page' and request.method == 'POST':
        title = request.form.get('page_title', '').strip()
        content = request.form.get('page_content', '')
        if title:
            slug = title.lower().replace(' ', '-').replace('ı', 'i').replace('ğ', 'g').replace('ü', 'u').replace('ş', 's').replace('ö', 'o').replace('ç', 'c')
            slug = ''.join(c for c in slug if c.isalnum() or c == '-')
            existing = Page.query.filter_by(slug=slug).first()
            if existing:
                slug = f"{slug}-{Page.query.count() + 1}"
            new_page = Page(title=title, slug=slug, content=content)
            db.session.add(new_page)
            db.session.commit()
            flash("Sayfa başarıyla oluşturuldu!")
            return redirect(url_for('admin_settings', section='pages'))
    
    # Handle edit_page POST
    if section == 'edit_page' and request.method == 'POST':
        page_id = request.args.get('page_id')
        if page_id:
            page = Page.query.get(page_id)
            if page:
                page.title = request.form.get('page_title', '').strip()
                page.content = request.form.get('page_content', '')
                db.session.commit()
                flash("Sayfa güncellendi!")
                return redirect(url_for('admin_settings', section='pages'))
    
    if request.method == 'POST':
        # Handle file uploads (logo)
        logo_file = request.files.get('logo_img')
        if logo_file and logo_file.filename:
            filename = secure_filename(logo_file.filename)
            base_name = os.path.splitext(filename)[0]
            # Save original first
            original_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            logo_file.save(original_path)
            
            # Remove background and save as PNG
            output_filename = f"{base_name}_transparent.png"
            output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)
            if remove_background(original_path, output_path):
                # Save transparent version filename to settings
                item = Settings.query.filter_by(key='logo_img').first()
                if item: item.value = output_filename
                else: db.session.add(Settings(key='logo_img', value=output_filename))
                flash("Logo yüklendi ve arka planı kaldırıldı!")
            else:
                # If background removal fails, use original
                item = Settings.query.filter_by(key='logo_img').first()
                if item: item.value = filename
                else: db.session.add(Settings(key='logo_img', value=filename))
        
        # Handle other form fields
        for key, value in request.form.items():
            # smtp_pass: boş bırakılırsa mevcut değeri koru
            if key == 'smtp_pass' and not value.strip():
                continue
            item = Settings.query.filter_by(key=key).first()
            if item: item.value = value
            else: db.session.add(Settings(key=key, value=value))
        # Checkbox'lar: form'da yoksa 0 olarak kaydet
        for checkbox_key in ['smtp_use_tls', 'smtp_use_ssl']:
            if checkbox_key not in request.form:
                item = Settings.query.filter_by(key=checkbox_key).first()
                if item: item.value = '0'
                else: db.session.add(Settings(key=checkbox_key, value='0'))
        db.session.commit()
        flash("Ayarlar güncellendi.")
        return redirect(url_for('admin_settings', section=section))
    
    # Get all settings for display
    all_settings = Settings.query.all()
    settings_dict = {s.key: s.value for s in all_settings}
    faqs = FAQ.query.order_by(FAQ.order).all() if section == 'faq' else []
    pages = Page.query.all() if section == 'pages' else []
    
    # Get page for editing
    edit_page = None
    if section == 'edit_page':
        page_id = request.args.get('page_id')
        if page_id:
            edit_page = Page.query.get(page_id)
    
    return render_template('admin/settings.html', section=section, settings=settings_dict, faqs=faqs, pages=pages, edit_page=edit_page, active_page='settings')

@app.route('/admin/upload-promo-video', methods=['POST'])
def upload_promo_video():
    if session.get('username') != 'admin':
        return jsonify({'error': 'Yetkisiz'}), 403
    
    video_file = request.files.get('promo_video_file')
    cover_file = request.files.get('promo_cover_file')
    
    if video_file and video_file.filename:
        video_filename = secure_filename(video_file.filename)
        video_path = os.path.join(app.config['UPLOAD_FOLDER'], video_filename)
        old_video = Settings.query.filter_by(key='promo_video').first()
        if old_video and old_video.value:
            old_path = os.path.join(app.config['UPLOAD_FOLDER'], old_video.value)
            if os.path.exists(old_path):
                os.remove(old_path)
        video_file.save(video_path)
        item = Settings.query.filter_by(key='promo_video').first()
        if item: item.value = video_filename
        else: db.session.add(Settings(key='promo_video', value=video_filename))
    
    if cover_file and cover_file.filename:
        cover_filename = secure_filename(cover_file.filename)
        cover_path = os.path.join(app.config['UPLOAD_FOLDER'], cover_filename)
        old_cover = Settings.query.filter_by(key='promo_cover').first()
        if old_cover and old_cover.value:
            old_path = os.path.join(app.config['UPLOAD_FOLDER'], old_cover.value)
            if os.path.exists(old_path):
                os.remove(old_path)
        cover_file.save(cover_path)
        item = Settings.query.filter_by(key='promo_cover').first()
        if item: item.value = cover_filename
        else: db.session.add(Settings(key='promo_cover', value=cover_filename))
    
    title = request.form.get('promo_title', '')
    desc = request.form.get('promo_description', '')
    for k, v in [('promo_title', title), ('promo_description', desc)]:
        item = Settings.query.filter_by(key=k).first()
        if item: item.value = v
        else: db.session.add(Settings(key=k, value=v))
    
    db.session.commit()
    return jsonify({'success': True, 'message': 'Tanıtım videosu güncellendi!'})

@app.route('/admin/promo-video/delete')
def delete_promo_video():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    item = Settings.query.filter_by(key='promo_video').first()
    if item and item.value:
        video_path = os.path.join(app.config['UPLOAD_FOLDER'], item.value)
        if os.path.exists(video_path):
            os.remove(video_path)
        item.value = ''
        db.session.commit()
        flash("Tanıtım videosu silindi.")
    return redirect(url_for('admin_settings', section='promo_video'))

@app.route('/admin/page/delete/<int:id>')
def delete_page(id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    page = Page.query.get_or_404(id)
    db.session.delete(page)
    db.session.commit()
    flash("Sayfa silindi.")
    return redirect(url_for('admin_settings', section='pages'))

@app.route('/p/<slug>')
def view_page(slug):
    page = Page.query.filter_by(slug=slug).first_or_404()
    return render_template('page.html', page=page)

# --- BLOG YÖNETİMİ ---
@app.route('/admin/posts')
def admin_posts():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    return render_template('admin/posts.html', posts=Post.query.all(), active_page='posts')

@app.route('/admin/post/add', methods=['GET', 'POST'])
def admin_add_post():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    if request.method == 'POST':
        img = request.files.get('image')
        img_name = secure_filename(img.filename) if img else None
        if img: img.save(os.path.join(app.config['UPLOAD_FOLDER'], img_name))
        db.session.add(Post(title=request.form.get('title'), content=request.form.get('content'), image=img_name))
        db.session.commit(); flash("Blog yazısı yayınlandı!"); return redirect(url_for('admin_posts'))
    return render_template('admin/add_post.html', active_page='posts')

@app.route('/admin/post/delete/<int:id>')
def admin_delete_post(id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    post = Post.query.get_or_404(id)
    db.session.delete(post); db.session.commit()
    return redirect(url_for('admin_posts'))

# --- YORUM YÖNETİMİ ---
@app.route('/admin/reviews')
def admin_reviews():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    comments = Comment.query.order_by(Comment.date_posted.desc()).all()
    blog_comments = BlogComment.query.order_by(BlogComment.created_at.desc()).all()
    return render_template('admin/reviews.html', comments=comments, blog_comments=blog_comments, active_page='reviews')

@app.route('/admin/review/approve/<int:id>')
def admin_approve_review(id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    comment = Comment.query.get_or_404(id)
    comment.approved = True
    db.session.commit()
    flash("Yorum onaylandı!")
    return redirect(url_for('admin_reviews'))

@app.route('/admin/review/reject/<int:id>')
def admin_reject_review(id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    comment = Comment.query.get_or_404(id)
    comment.approved = False
    db.session.commit()
    flash("Yorum onayı kaldırıldı!")
    return redirect(url_for('admin_reviews'))

@app.route('/admin/review/delete/<int:id>')
def admin_delete_review(id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    comment = Comment.query.get_or_404(id)
    db.session.delete(comment)
    db.session.commit()
    flash("Yorum silindi!")
    return redirect(url_for('admin_reviews'))

@app.route('/admin/blog-comment/approve/<int:id>')
def admin_approve_blog_comment(id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    comment = BlogComment.query.get_or_404(id)
    comment.approved = True
    db.session.commit()
    flash("Blog yorumu onaylandı!")
    return redirect(url_for('admin_reviews'))

@app.route('/admin/blog-comment/delete/<int:id>')
def admin_delete_blog_comment(id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    comment = BlogComment.query.get_or_404(id)
    db.session.delete(comment)
    db.session.commit()
    flash("Blog yorumu silindi!")
    return redirect(url_for('admin_reviews'))

@app.route('/admin/review/edit', methods=['POST'])
def admin_edit_review():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    comment_id = request.form.get('comment_id')
    content = request.form.get('content')
    rating = request.form.get('rating', type=int)
    comment = Comment.query.get_or_404(comment_id)
    comment.content = content
    comment.rating = rating
    db.session.commit()
    flash("Yorum guncellendi!")
    return redirect(url_for('admin_reviews'))

# --- ABONELİK YÖNETİMİ ---
@app.route('/admin/subscribers')
def admin_subscribers():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    subscribers = Subscriber.query.order_by(Subscriber.created_at.desc()).all()
    users = User.query.filter(User.username != 'admin').order_by(User.id.desc()).all()
    email_logs = EmailLog.query.order_by(EmailLog.sent_at.desc()).limit(20).all()
    all_cases = Case.query.order_by(Case.title).all()
    return render_template('admin/subscribers.html', subscribers=subscribers, users=users, email_logs=email_logs, all_cases=all_cases, active_page='subscribers')

@app.route('/admin/subscribers/delete/<int:id>')
def delete_subscriber(id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    subscriber = Subscriber.query.get_or_404(id)
    db.session.delete(subscriber)
    db.session.commit()
    flash("Abone silindi!", "success")
    return redirect(url_for('admin_subscribers'))

@app.route('/admin/subscribers/toggle/<int:id>')
def toggle_subscriber(id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    subscriber = Subscriber.query.get_or_404(id)
    subscriber.is_active = not subscriber.is_active
    db.session.commit()
    flash("Abone durumu güncellendi!", "success")
    return redirect(url_for('admin_subscribers'))

def get_smtp_settings():
    """SMTP ayarlarını DB'den okur, yoksa env var'a fallback yapar"""
    all_settings = Settings.query.all()
    s = {item.key: item.value for item in all_settings} if all_settings else {}
    smtp_host = s.get('smtp_host') or os.environ.get('SMTP_HOST', '')
    smtp_port_str = s.get('smtp_port') or os.environ.get('SMTP_PORT', '587')
    smtp_user = s.get('smtp_user') or os.environ.get('SMTP_USER', '')
    smtp_pass = s.get('smtp_pass') or os.environ.get('SMTP_PASS', '')
    from_email = s.get('smtp_from_email') or os.environ.get('FROM_EMAIL', smtp_user)
    use_tls = s.get('smtp_use_tls', '1') == '1'
    use_ssl = s.get('smtp_use_ssl', '0') == '1'
    try:
        smtp_port = int(smtp_port_str)
    except (ValueError, TypeError):
        smtp_port = 587
    return {
        'host': smtp_host, 'port': smtp_port, 'user': smtp_user,
        'pass': smtp_pass, 'from': from_email, 'tls': use_tls, 'ssl': use_ssl
    }

def send_smtp_email(to_email, subject, html_body, plain_text=''):
    """Tek bir adrese SMTP ile email gönderir"""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    import ssl as ssl_lib
    cfg = get_smtp_settings()
    if not cfg['host'] or not cfg['user'] or not cfg['pass']:
        return False, "SMTP ayarları eksik"
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"Gizemli Vaka <{cfg['from']}>"
        msg['To'] = to_email
        if plain_text:
            msg.attach(MIMEText(plain_text, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        if cfg['ssl']:
            context = ssl_lib.create_default_context()
            server = smtplib.SMTP_SSL(cfg['host'], cfg['port'], context=context)
        else:
            server = smtplib.SMTP(cfg['host'], cfg['port'])
            if cfg['tls']:
                server.starttls()
        server.login(cfg['user'], cfg['pass'])
        server.sendmail(cfg['from'], to_email, msg.as_string())
        server.quit()
        return True, "Gönderildi"
    except Exception as e:
        return False, str(e)

def send_new_case_newsletter(case_id, base_url='https://gizemlivaka.com'):
    """Yeni/aktif edilen vaka için güzel HTML bülten emaili gönderir"""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    case = Case.query.get(case_id)
    if not case:
        return 0

    cfg = get_smtp_settings()
    smtp_host = cfg['host']
    smtp_port = cfg['port']
    smtp_user = cfg['user']
    smtp_pass = cfg['pass']
    from_email = cfg['from']

    if not smtp_host or not smtp_user or not smtp_pass:
        return 0

    subscribers = Subscriber.query.filter_by(is_active=True).all()
    users = User.query.filter(User.username != 'admin').all()
    recipient_emails = list(set([s.email for s in subscribers] + [u.email for u in users]))

    if not recipient_emails:
        return 0

    difficulty_colors = {'Kolay': '#2ecc71', 'Orta': '#3498db', 'Zor': '#e74c3c'}
    difficulty_color = difficulty_colors.get(case.difficulty or 'Orta', '#3498db')

    case_image_url = f"{base_url}/static/uploads/{case.id}/{case.image}" if case.image else ''
    case_url = f"{base_url}/case/{case.id}"

    price_html = ''
    if case.old_price and case.old_price > case.price:
        price_html = f'''
        <span style="text-decoration:line-through;color:#999;font-size:16px;">{int(case.old_price)} TL</span>
        &nbsp;<span style="background:#e74c3c;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold;">%{case.discount_rate} İNDİRİM</span>
        <br><span style="font-size:32px;font-weight:900;color:#FFD700;">{int(case.price)} TL</span>
        '''
    else:
        price_html = f'<span style="font-size:32px;font-weight:900;color:#FFD700;">{int(case.price)} TL</span>'

    subject = f"🔍 Yeni Vaka Açıldı: {case.title} | Gizemli Vaka"

    html_body = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{case.title}</title>
</head>
<body style="margin:0;padding:0;background-color:#0a0e1a;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#0a0e1a;">
    <tr><td align="center" style="padding:30px 15px;">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background-color:#0C1430;border-radius:16px;overflow:hidden;border:1px solid #1e2d5a;">

        <!-- HEADER -->
        <tr>
          <td style="background:linear-gradient(135deg,#0C1430 0%,#1a2550 100%);padding:30px;text-align:center;border-bottom:2px solid #FFD700;">
            <div style="display:inline-flex;align-items:center;gap:10px;">
              <span style="font-size:28px;">🔍</span>
              <span style="font-size:26px;font-weight:900;color:#FFD700;letter-spacing:2px;">GİZEMLİ VAKA</span>
            </div>
            <p style="color:#8899bb;margin:8px 0 0;font-size:13px;letter-spacing:1px;">DEDEKTIF PLATFORMU</p>
          </td>
        </tr>

        <!-- BREAKING NEWS BANNER -->
        <tr>
          <td style="background:linear-gradient(90deg,#c0392b,#e74c3c,#c0392b);padding:12px;text-align:center;">
            <span style="color:#fff;font-weight:900;font-size:13px;letter-spacing:3px;">⚠ YENİ VAKA AÇILDI ⚠</span>
          </td>
        </tr>

        <!-- CASE IMAGE -->
        {"<tr><td style='padding:0;'><img src='" + case_image_url + "' width='600' style='width:100%;max-width:600px;height:280px;object-fit:cover;display:block;' alt='" + case.title + "'></td></tr>" if case_image_url else ""}

        <!-- CASE TITLE -->
        <tr>
          <td style="padding:30px 35px 15px;text-align:center;">
            <span style="background:{difficulty_color};color:#fff;padding:4px 14px;border-radius:20px;font-size:12px;font-weight:bold;letter-spacing:1px;">{case.difficulty or 'Orta'}</span>
            <h1 style="color:#ffffff;font-size:28px;font-weight:900;margin:15px 0 8px;line-height:1.2;">
              {case.title}
            </h1>
            <div style="width:60px;height:3px;background:#FFD700;margin:0 auto 20px;border-radius:2px;"></div>
          </td>
        </tr>

        <!-- DESCRIPTION -->
        <tr>
          <td style="padding:0 35px 25px;">
            <p style="color:#aab8d4;font-size:15px;line-height:1.7;margin:0;text-align:center;">
              {(case.description or '')[:300]}{"..." if len(case.description or '') > 300 else ""}
            </p>
          </td>
        </tr>

        <!-- CLUE BOX -->
        <tr>
          <td style="padding:0 35px 25px;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,#111d3d,#162040);border-radius:12px;border:1px solid #2a3d6e;overflow:hidden;">
              <tr>
                <td style="padding:20px 25px;">
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td style="text-align:center;padding:0 10px;">
                        <div style="font-size:24px;">🕵️</div>
                        <div style="color:#8899bb;font-size:11px;margin-top:4px;">KATEGORİ</div>
                        <div style="color:#fff;font-weight:bold;font-size:13px;margin-top:2px;">{"Bireysel" if case.game_type == "individual" else "Takım" if case.game_type == "team" else "Her İkisi"}</div>
                      </td>
                      <td style="text-align:center;padding:0 10px;border-left:1px solid #2a3d6e;">
                        <div style="font-size:24px;">⭐</div>
                        <div style="color:#8899bb;font-size:11px;margin-top:4px;">ZORLUK</div>
                        <div style="color:{difficulty_color};font-weight:bold;font-size:13px;margin-top:2px;">{case.difficulty or 'Orta'}</div>
                      </td>
                      <td style="text-align:center;padding:0 10px;border-left:1px solid #2a3d6e;">
                        <div style="font-size:24px;">💰</div>
                        <div style="color:#8899bb;font-size:11px;margin-top:4px;">FİYAT</div>
                        <div style="color:#FFD700;font-weight:bold;font-size:14px;margin-top:2px;">{int(case.price)} TL</div>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- PRICE & CTA -->
        <tr>
          <td style="padding:0 35px 35px;text-align:center;">
            <div style="margin-bottom:20px;">{price_html}</div>
            <a href="{case_url}" style="display:inline-block;background:linear-gradient(135deg,#FFD700,#f0a500);color:#0C1430;text-decoration:none;font-weight:900;font-size:16px;padding:16px 45px;border-radius:50px;letter-spacing:1px;box-shadow:0 6px 25px rgba(255,215,0,0.4);">
              🔍 DAVAYII İNCELE &amp; SATIN AL
            </a>
            <p style="color:#556688;font-size:12px;margin-top:15px;">Vakaları çözerek dedektif sıralamanda yüksel!</p>
          </td>
        </tr>

        <!-- HOW IT WORKS -->
        <tr>
          <td style="padding:0 35px 30px;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#080d1e;border-radius:10px;overflow:hidden;">
              <tr><td style="padding:15px 20px;border-bottom:1px solid #1e2d5a;">
                <span style="color:#FFD700;font-weight:bold;font-size:12px;letter-spacing:2px;">NASIL OYNANIR?</span>
              </td></tr>
              <tr><td style="padding:15px 20px;">
                <table cellpadding="0" cellspacing="0">
                  <tr><td style="padding:5px 0;color:#8899bb;font-size:13px;">📄 &nbsp;Kanıtları incele, dosyaları analiz et</td></tr>
                  <tr><td style="padding:5px 0;color:#8899bb;font-size:13px;">🧩 &nbsp;İpuçlarını bir araya getir</td></tr>
                  <tr><td style="padding:5px 0;color:#8899bb;font-size:13px;">✍️ &nbsp;Dedektif raporunu yaz</td></tr>
                  <tr><td style="padding:5px 0;color:#8899bb;font-size:13px;">🏆 &nbsp;Sıralamalarda yüksel!</td></tr>
                </table>
              </td></tr>
            </table>
          </td>
        </tr>

        <!-- FOOTER -->
        <tr>
          <td style="background:#070c1a;padding:25px 35px;text-align:center;border-top:1px solid #1e2d5a;">
            <p style="color:#556688;font-size:12px;margin:0 0 8px;">© 2025 Gizemli Vaka - Türkiye'nin En Büyük Dedektiflik Platformu</p>
            <p style="color:#3a4d6e;font-size:11px;margin:0;">Bu bülteni almak istemiyorsanız <a href="{base_url}/unsubscribe" style="color:#556688;text-decoration:underline;">buraya tıklayın</a>.</p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    plain_text = f"Yeni Vaka Açıldı: {case.title}\n\n{case.description or ''}\n\nFiyat: {int(case.price)} TL\n\nDetaylar için: {case_url}"

    sent_count = 0
    try:
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        for recipient in recipient_emails:
            try:
                msg = MIMEMultipart('alternative')
                msg['Subject'] = subject
                msg['From'] = f"Gizemli Vaka <{from_email}>"
                msg['To'] = recipient
                msg.attach(MIMEText(plain_text, 'plain', 'utf-8'))
                msg.attach(MIMEText(html_body, 'html', 'utf-8'))
                server.sendmail(from_email, recipient, msg.as_string())
                sent_count += 1
            except Exception as e:
                print(f"Email gönderim hatası ({recipient}): {e}")
        server.quit()
    except Exception as e:
        print(f"SMTP bağlantı hatası: {e}")
        return 0

    try:
        email_log = EmailLog(
            subject=subject,
            content=f"[VAKA DUYURUSU: {case.id}] {case.title}",
            recipient_type='all',
            recipient_count=sent_count,
            sent_by='system'
        )
        db.session.add(email_log)
        db.session.commit()
    except Exception:
        pass

    return sent_count


@app.route('/admin/send-case-announcement/<case_id>', methods=['POST'])
def admin_send_case_announcement(case_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    case = Case.query.get_or_404(case_id)
    try:
        base_url = request.host_url.rstrip('/')
        sent = send_new_case_newsletter(case.id, base_url=base_url)
        if sent > 0:
            flash(f"✅ '{case.title}' duyurusu {sent} kişiye başarıyla gönderildi!", "success")
        else:
            flash("⚠️ Email gönderilmedi. SMTP ayarlarınızı kontrol edin.", "warning")
    except Exception as e:
        flash(f"Hata: {str(e)}", "error")
    return redirect(url_for('admin_cases'))


@app.route('/admin/send-email', methods=['POST'])
def admin_send_email():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    
    recipient_type = request.form.get('recipient_type', 'all')
    subject = request.form.get('subject', '')
    content = request.form.get('content', '')
    individual_email = request.form.get('individual_email', '')
    
    if not subject or not content:
        flash("Konu ve içerik gereklidir!", "error")
        return redirect(url_for('admin_subscribers'))
    
    recipients = []
    
    if recipient_type == 'individual' and individual_email:
        recipients = [individual_email]
    elif recipient_type == 'subscribers':
        subscribers = Subscriber.query.filter_by(is_active=True).all()
        recipients = [s.email for s in subscribers]
    elif recipient_type == 'users':
        users = User.query.filter(User.username != 'admin').all()
        recipients = [u.email for u in users]
    else:
        subscribers = Subscriber.query.filter_by(is_active=True).all()
        users = User.query.filter(User.username != 'admin').all()
        recipient_emails = set([s.email for s in subscribers] + [u.email for u in users])
        recipients = list(recipient_emails)
    
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    cfg = get_smtp_settings()
    smtp_host = cfg['host']
    smtp_port = cfg['port']
    smtp_user = cfg['user']
    smtp_pass = cfg['pass']
    from_email = cfg['from']

    sent_count = 0

    if smtp_host and smtp_user and smtp_pass:
        try:
            import ssl as ssl_lib
            if cfg['ssl']:
                context = ssl_lib.create_default_context()
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, context=context)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port)
                if cfg['tls']:
                    server.starttls()
            server.login(smtp_user, smtp_pass)

            for recipient in recipients:
                try:
                    msg = MIMEMultipart('alternative')
                    msg['Subject'] = subject
                    msg['From'] = f"Gizemli Vaka <{from_email}>"
                    msg['To'] = recipient
                    html_content = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:30px 15px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.1);">
<tr><td style="background:linear-gradient(135deg,#0C1430,#1a2550);padding:25px;text-align:center;border-bottom:3px solid #FFD700;">
<span style="font-size:24px;font-weight:900;color:#FFD700;letter-spacing:2px;">🔍 GİZEMLİ VAKA</span>
</td></tr>
<tr><td style="padding:35px;">{content}</td></tr>
<tr><td style="background:#f8f8f8;padding:15px;text-align:center;font-size:12px;color:#999;border-top:1px solid #eee;">
Bu e-postayı almak istemiyorsanız, lütfen bizimle iletişime geçin.
<br><a href="https://gizemlivaka.com" style="color:#0C1430;">gizemlivaka.com</a>
</td></tr>
</table></td></tr></table>
</body></html>"""
                    msg.attach(MIMEText(content, 'plain', 'utf-8'))
                    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
                    server.sendmail(from_email, recipient, msg.as_string())
                    sent_count += 1
                except Exception as e:
                    print(f"Error sending to {recipient}: {e}")

            server.quit()
        except Exception as e:
            flash(f"SMTP bağlantı hatası: {str(e)}", "error")
            return redirect(url_for('admin_subscribers'))
    else:
        flash("SMTP ayarları yapılandırılmamış. E-posta Ayarları bölümünden SMTP bilgilerinizi girin.", "warning")
        sent_count = 0
    
    email_log = EmailLog(
        subject=subject,
        content=content,
        recipient_type=recipient_type,
        recipient_count=sent_count,
        sent_by='admin'
    )
    db.session.add(email_log)
    db.session.commit()
    
    flash(f"{sent_count} kişiye email gönderildi!", "success")
    return redirect(url_for('admin_subscribers'))

# --- SMTP TEST ---
@app.route('/admin/test-smtp', methods=['POST'])
def admin_test_smtp():
    if session.get('username') != 'admin':
        return jsonify({'success': False, 'message': 'Yetkisiz'}), 403
    test_email = request.form.get('test_email', '').strip()
    if not test_email:
        return jsonify({'success': False, 'message': 'Test e-posta adresi gerekli'})

    import smtplib, ssl as ssl_lib
    cfg = get_smtp_settings()

    # Tanılama modu: adım adım test et
    diagnostics = []
    try:
        # 1. Bağlantı
        diagnostics.append(f"Bağlanıyor: {cfg['host']}:{cfg['port']} ({'SSL' if cfg['ssl'] else 'TLS' if cfg['tls'] else 'Düz'})")
        if cfg['ssl']:
            ctx = ssl_lib.create_default_context()
            server = smtplib.SMTP_SSL(cfg['host'], cfg['port'], context=ctx, timeout=10)
        else:
            server = smtplib.SMTP(cfg['host'], cfg['port'], timeout=10)
            server.ehlo()
            if cfg['tls']:
                server.starttls()
                server.ehlo()
        diagnostics.append("✓ Sunucuya bağlanıldı")

        # 2. Giriş
        diagnostics.append(f"Giriş yapılıyor: {cfg['user']}")
        server.login(cfg['user'], cfg['pass'])
        diagnostics.append("✓ Giriş başarılı")

        # 3. Gönder
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        msg = MIMEMultipart('alternative')
        msg['Subject'] = '✅ Gizemli Vaka — SMTP Test E-postası'
        msg['From'] = f"Gizemli Vaka <{cfg['from']}>"
        msg['To'] = test_email
        html = """<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:30px 15px;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#fff;border-radius:12px;overflow:hidden;">
<tr><td style="background:linear-gradient(135deg,#0C1430,#1a2550);padding:25px;text-align:center;border-bottom:3px solid #FFD700;">
<span style="font-size:24px;font-weight:900;color:#FFD700;letter-spacing:2px;">🔍 GİZEMLİ VAKA</span></td></tr>
<tr><td style="padding:35px;text-align:center;">
<h2 style="color:#0C1430;">✅ SMTP Bağlantısı Başarılı!</h2>
<p style="color:#555;">Bu bir test e-postasıdır. SMTP ayarlarınız doğru şekilde yapılandırılmış.</p>
</td></tr>
<tr><td style="background:#f8f8f8;padding:15px;text-align:center;font-size:12px;color:#999;">
gizemlivaka.com — Admin SMTP Test</td></tr>
</table></td></tr></table></body></html>"""
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        server.sendmail(cfg['from'], test_email, msg.as_string())
        server.quit()
        diagnostics.append(f"✓ E-posta gönderildi → {test_email}")
        return jsonify({'success': True, 'message': ' | '.join(diagnostics)})

    except smtplib.SMTPAuthenticationError as e:
        step = next((d for d in reversed(diagnostics) if d.startswith('✓')), 'Başlangıç')
        return jsonify({'success': False, 'message':
            f"Kimlik doğrulama hatası: {e.smtp_code} {e.smtp_error.decode('utf-8', errors='replace')} | "
            f"Son başarılı adım: {step} | "
            f"Kontrol: kullanıcı adı tam e-posta mı? ({cfg['user']}) | "
            f"inbox.eu → Ayarlar → Güvenlik → SMTP erişimi etkin mi?"})
    except smtplib.SMTPConnectError as e:
        return jsonify({'success': False, 'message':
            f"Bağlantı kurulamadı: {cfg['host']}:{cfg['port']} — {e} | "
            f"Farklı port/protokol deneyin: 465/SSL veya 587/TLS"})
    except smtplib.SMTPException as e:
        return jsonify({'success': False, 'message': f"SMTP hatası: {e} | Adımlar: {' → '.join(diagnostics)}"})
    except Exception as e:
        return jsonify({'success': False, 'message': f"Hata: {type(e).__name__}: {e} | Adımlar: {' → '.join(diagnostics)}"})


# --- MAIL ŞABLON ÖNİZLEME ---
def get_mail_template_html(template_type, base_url='https://gizemlivaka.com'):
    """Belirtilen şablon tipine göre HTML döndürür"""
    header = f"""<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#0C1430;border-radius:16px 16px 0 0;overflow:hidden;">
<tr><td style="background:linear-gradient(135deg,#0C1430,#1a2550);padding:28px;text-align:center;border-bottom:3px solid #FFD700;">
<span style="font-size:22px;font-weight:900;color:#FFD700;letter-spacing:2px;">🔍 GİZEMLİ VAKA</span>
<p style="color:#8899bb;margin:5px 0 0;font-size:12px;letter-spacing:1px;">DEDEKTİF PLATFORMU</p>
</td></tr></table>"""
    footer = f"""<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#f0f2f5;border-radius:0 0 16px 16px;">
<tr><td style="padding:20px;text-align:center;font-size:12px;color:#888;">
<p style="margin:0;">© Gizemli Vaka — <a href="{base_url}" style="color:#0C1430;text-decoration:none;">gizemlivaka.com</a></p>
<p style="margin:5px 0 0;">Bu e-postayı almak istemiyorsanız <a href="#" style="color:#c00;">buradan çıkabilirsiniz</a>.</p>
</td></tr></table>"""
    body_style = "max-width:600px;width:100%;background:#fff;padding:35px;"

    templates = {
        'welcome': {
            'subject': '🔍 Gizemli Vaka\'ya Hoş Geldiniz!',
            'body': f"""<table width="600" cellpadding="0" cellspacing="0" style="{body_style}">
<tr><td>
<h2 style="color:#0C1430;margin-top:0;">Hoş Geldin, Dedektif! 🎉</h2>
<p style="color:#444;line-height:1.7;">Gizemli Vaka ailesine katıldığın için çok mutluyuz! Artık gerçekçi kurgu cinayet davalarını çözmeye hazırsın.</p>
<p style="color:#444;line-height:1.7;">Platform üzerinde yüzlerce delil dosyası, sesli ifadeler, video kayıtları ve daha fazlası seni bekliyor.</p>
<div style="text-align:center;margin:30px 0;">
<a href="{base_url}/cases" style="background:#FFD700;color:#0C1430;padding:14px 36px;border-radius:30px;text-decoration:none;font-weight:900;font-size:15px;display:inline-block;">🔍 Davaları Keşfet</a>
</div>
<p style="color:#777;font-size:13px;">Herhangi bir sorunuz olursa bize ulaşmaktan çekinmeyin.</p>
<p style="color:#0C1430;font-weight:bold;">İyi soruşturmalar! 🕵️</p>
</td></tr></table>"""
        },
        'order_confirm': {
            'subject': '✅ Siparişiniz Onaylandı — Gizemli Vaka',
            'body': f"""<table width="600" cellpadding="0" cellspacing="0" style="{body_style}">
<tr><td>
<h2 style="color:#0C1430;margin-top:0;">Siparişiniz Onaylandı! ✅</h2>
<p style="color:#444;line-height:1.7;">Ödemeniz başarıyla alındı. Dava dosyanıza hemen erişebilirsiniz.</p>
<div style="background:#f8f9fa;border-left:4px solid #FFD700;padding:20px;border-radius:8px;margin:20px 0;">
<p style="margin:0;color:#0C1430;font-weight:bold;">📁 Dava Adı: <span style="color:#555;">[Dava Başlığı]</span></p>
<p style="margin:8px 0 0;color:#0C1430;font-weight:bold;">💰 Ödenen Tutar: <span style="color:#555;">[Tutar] TL</span></p>
<p style="margin:8px 0 0;color:#0C1430;font-weight:bold;">📅 Tarih: <span style="color:#555;">[Tarih]</span></p>
</div>
<div style="text-align:center;margin:30px 0;">
<a href="{base_url}/my-cases" style="background:#FFD700;color:#0C1430;padding:14px 36px;border-radius:30px;text-decoration:none;font-weight:900;font-size:15px;display:inline-block;">🕵️ Davayı Çözmeye Başla</a>
</div>
</td></tr></table>"""
        },
        'password_reset': {
            'subject': '🔑 Şifre Sıfırlama — Gizemli Vaka',
            'body': f"""<table width="600" cellpadding="0" cellspacing="0" style="{body_style}">
<tr><td>
<h2 style="color:#0C1430;margin-top:0;">Şifre Sıfırlama Talebi 🔑</h2>
<p style="color:#444;line-height:1.7;">Hesabınız için şifre sıfırlama talebinde bulundunuz. Aşağıdaki bağlantıya tıklayarak yeni şifrenizi belirleyebilirsiniz.</p>
<div style="text-align:center;margin:30px 0;">
<a href="#" style="background:#e74c3c;color:#fff;padding:14px 36px;border-radius:30px;text-decoration:none;font-weight:900;font-size:15px;display:inline-block;">🔑 Şifremi Sıfırla</a>
</div>
<p style="color:#888;font-size:13px;">Bu bağlantı 24 saat geçerlidir. Eğer bu talebi siz yapmadıysanız bu e-postayı görmezden gelebilirsiniz.</p>
</td></tr></table>"""
        },
        'comment_approved': {
            'subject': '✅ Yorumunuz Onaylandı — Gizemli Vaka',
            'body': f"""<table width="600" cellpadding="0" cellspacing="0" style="{body_style}">
<tr><td>
<h2 style="color:#0C1430;margin-top:0;">Yorumunuz Yayında! ✅</h2>
<p style="color:#444;line-height:1.7;">Gizemli Vaka hakkında yazdığınız yorum onaylandı ve sitemizde yayına alındı. Katkınız için teşekkür ederiz!</p>
<div style="background:#f0fff4;border-left:4px solid #2ecc71;padding:20px;border-radius:8px;margin:20px 0;">
<p style="margin:0;color:#555;font-style:italic;">"[Yorum içeriği burada görünecek]"</p>
</div>
<div style="text-align:center;margin:30px 0;">
<a href="{base_url}/reviews" style="background:#FFD700;color:#0C1430;padding:14px 36px;border-radius:30px;text-decoration:none;font-weight:900;font-size:15px;display:inline-block;">Yorumları Gör</a>
</div>
</td></tr></table>"""
        },
        'comment_rejected': {
            'subject': 'ℹ️ Yorumunuz Hakkında — Gizemli Vaka',
            'body': f"""<table width="600" cellpadding="0" cellspacing="0" style="{body_style}">
<tr><td>
<h2 style="color:#0C1430;margin-top:0;">Yorumunuz Değerlendirme Sonucu</h2>
<p style="color:#444;line-height:1.7;">Maalesef yorumunuz platform kurallarımıza uymadığı için yayına alınamamıştır. Daha fazla bilgi için bizimle iletişime geçebilirsiniz.</p>
<div style="text-align:center;margin:30px 0;">
<a href="{base_url}/contact" style="background:#0C1430;color:#FFD700;padding:14px 36px;border-radius:30px;text-decoration:none;font-weight:900;font-size:15px;display:inline-block;">İletişime Geç</a>
</div>
</td></tr></table>"""
        },
        'new_sale': {
            'subject': '💰 Yeni Satış Bildirimi — Gizemli Vaka',
            'body': f"""<table width="600" cellpadding="0" cellspacing="0" style="{body_style}">
<tr><td>
<h2 style="color:#0C1430;margin-top:0;">Yeni Satış! 💰</h2>
<div style="background:#fff8e1;border-left:4px solid #FFD700;padding:20px;border-radius:8px;margin:20px 0;">
<p style="margin:0;color:#0C1430;font-weight:bold;">👤 Müşteri: <span style="color:#555;">[Kullanıcı Adı]</span></p>
<p style="margin:8px 0 0;color:#0C1430;font-weight:bold;">📁 Ürün: <span style="color:#555;">[Dava Adı]</span></p>
<p style="margin:8px 0 0;color:#0C1430;font-weight:bold;">💰 Tutar: <span style="color:#2ecc71;font-size:18px;">[Tutar] TL</span></p>
<p style="margin:8px 0 0;color:#0C1430;font-weight:bold;">📅 Tarih: <span style="color:#555;">[Tarih]</span></p>
</div>
<div style="text-align:center;margin:30px 0;">
<a href="{base_url}/admin" style="background:#FFD700;color:#0C1430;padding:14px 36px;border-radius:30px;text-decoration:none;font-weight:900;font-size:15px;display:inline-block;">Admin Paneline Git</a>
</div>
</td></tr></table>"""
        },
        'case_announce': {
            'subject': '🔍 Yeni Vaka Açıldı — Gizemli Vaka',
            'body': f"""<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#0C1430;overflow:hidden;">
<tr><td style="background:linear-gradient(90deg,#c0392b,#e74c3c);padding:12px;text-align:center;">
<span style="color:#fff;font-weight:900;font-size:13px;letter-spacing:3px;">⚠ YENİ VAKA AÇILDI ⚠</span></td></tr>
<tr><td style="padding:30px;text-align:center;">
<span style="background:#3498db;color:#fff;padding:4px 14px;border-radius:20px;font-size:12px;font-weight:bold;">ORTA</span>
<h1 style="color:#fff;font-size:26px;font-weight:900;margin:15px 0 8px;">[Dava Başlığı]</h1>
<p style="color:#aab8d4;font-size:14px;line-height:1.7;">[Dava açıklaması buraya gelecek...]</p>
</td></tr>
<tr><td style="background:#fff;padding:30px;text-align:center;">
<a href="{base_url}/cases" style="background:#FFD700;color:#0C1430;padding:14px 36px;border-radius:30px;text-decoration:none;font-weight:900;font-size:15px;display:inline-block;">🕵️ Davayı İncele</a>
</td></tr></table>"""
        },
    }
    tpl = templates.get(template_type, templates['welcome'])
    wrapper = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#e8ecf1;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#e8ecf1;padding:30px 15px;">
<tr><td align="center">
{header}
{tpl['body']}
{footer}
</td></tr></table></body></html>"""
    return wrapper, tpl['subject']


@app.route('/admin/mail-template-preview/<template_type>')
def admin_mail_template_preview(template_type):
    if session.get('username') != 'admin':
        return redirect(url_for('index'))
    base_url = request.host_url.rstrip('/')
    html, subject = get_mail_template_html(template_type, base_url)
    return html


@app.route('/admin/mail-templates')
def admin_mail_templates():
    if session.get('username') != 'admin':
        return redirect(url_for('index'))
    template_types = [
        {'key': 'welcome', 'name': 'Hoş Geldin', 'desc': 'Yeni kayıt olan kullanıcı için hoş geldin e-postası'},
        {'key': 'order_confirm', 'name': 'Sipariş Onayı', 'desc': 'Sipariş sonrası ödeme onayı'},
        {'key': 'password_reset', 'name': 'Şifre Sıfırlama', 'desc': 'Şifre sıfırlama bağlantısı'},
        {'key': 'comment_approved', 'name': 'Yorum Onaylandı', 'desc': 'Yorum onayı bildirimi'},
        {'key': 'comment_rejected', 'name': 'Yorum Reddedildi', 'desc': 'Yorum reddi bildirimi'},
        {'key': 'new_sale', 'name': 'Yeni Satış', 'desc': 'Admin için yeni satış bildirimi'},
        {'key': 'case_announce', 'name': 'Vaka Duyurusu', 'desc': 'Yeni vaka açılışı bülteni'},
    ]
    selected = request.args.get('type', 'welcome')
    return render_template('admin/mail_templates.html', template_types=template_types, selected=selected, active_page='settings')


@app.route('/admin/send-test-template', methods=['POST'])
def admin_send_test_template():
    if session.get('username') != 'admin':
        return jsonify({'success': False, 'message': 'Yetkisiz'}), 403
    test_email = request.form.get('test_email', '').strip()
    template_type = request.form.get('template_type', 'welcome')
    if not test_email:
        return jsonify({'success': False, 'message': 'E-posta adresi gerekli'})
    base_url = request.host_url.rstrip('/')
    html, subject = get_mail_template_html(template_type, base_url)
    ok, msg = send_smtp_email(test_email, subject, html)
    return jsonify({'success': ok, 'message': msg})


# --- POPUP YÖNETİMİ ---
POPUP_IMG_FOLDER = os.path.join('static', 'uploads', 'popups')
os.makedirs(POPUP_IMG_FOLDER, exist_ok=True)

@app.route('/admin/popups')
def admin_popups():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    popups = SitePopup.query.order_by(SitePopup.priority.desc(), SitePopup.created_at.desc()).all()
    return render_template('admin/popups.html', popups=popups, active_page='settings')


@app.route('/admin/popups/create', methods=['GET', 'POST'])
def admin_popup_create():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    if request.method == 'POST':
        image_filename = None
        img_file = request.files.get('image_file')
        if img_file and img_file.filename:
            ext = os.path.splitext(secure_filename(img_file.filename))[1].lower()
            if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                fname = f"popup_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}{ext}"
                img_file.save(os.path.join(POPUP_IMG_FOLDER, fname))
                image_filename = fname

        start_date_str = request.form.get('start_date', '').strip()
        end_date_str = request.form.get('end_date', '').strip()
        start_date = datetime.fromisoformat(start_date_str) if start_date_str else None
        end_date = datetime.fromisoformat(end_date_str) if end_date_str else None

        height_str = request.form.get('height', '').strip()
        hide_dur_str = request.form.get('hide_duration', '').strip()
        try:
            overlay = float(request.form.get('overlay_opacity', '0.5'))
        except ValueError:
            overlay = 0.5

        popup = SitePopup(
            title=request.form.get('title', '').strip(),
            message=request.form.get('message', ''),
            popup_type=request.form.get('popup_type', 'info'),
            start_date=start_date,
            end_date=end_date,
            target_audience=request.form.get('target_audience', 'all'),
            priority=int(request.form.get('priority', 0) or 0),
            position=request.form.get('position', 'center'),
            width=int(request.form.get('width', 500) or 500),
            height=int(height_str) if height_str else None,
            overlay_opacity=overlay,
            image_filename=image_filename,
            button_text=request.form.get('button_text', '').strip() or None,
            button_url=request.form.get('button_url', '').strip() or None,
            link_target=request.form.get('link_target', '_self'),
            is_active='is_active' in request.form,
            is_closeable='is_closeable' in request.form,
            show_once_per_user='show_once_per_user' in request.form,
            hide_duration=int(hide_dur_str) if hide_dur_str else None,
        )
        db.session.add(popup)
        db.session.commit()
        flash("Pop-up başarıyla oluşturuldu!", "success")
        return redirect(url_for('admin_popups'))
    return render_template('admin/popups.html', popup=None, mode='create', popups=SitePopup.query.order_by(SitePopup.created_at.desc()).all(), active_page='settings')


@app.route('/admin/popups/<int:popup_id>/edit', methods=['GET', 'POST'])
def admin_popup_edit(popup_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    popup = SitePopup.query.get_or_404(popup_id)
    if request.method == 'POST':
        img_file = request.files.get('image_file')
        if img_file and img_file.filename:
            ext = os.path.splitext(secure_filename(img_file.filename))[1].lower()
            if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                if popup.image_filename:
                    old_path = os.path.join(POPUP_IMG_FOLDER, popup.image_filename)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                fname = f"popup_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}{ext}"
                img_file.save(os.path.join(POPUP_IMG_FOLDER, fname))
                popup.image_filename = fname

        start_date_str = request.form.get('start_date', '').strip()
        end_date_str = request.form.get('end_date', '').strip()
        height_str = request.form.get('height', '').strip()
        hide_dur_str = request.form.get('hide_duration', '').strip()
        try:
            overlay = float(request.form.get('overlay_opacity', '0.5'))
        except ValueError:
            overlay = 0.5

        popup.title = request.form.get('title', '').strip()
        popup.message = request.form.get('message', '')
        popup.popup_type = request.form.get('popup_type', 'info')
        popup.start_date = datetime.fromisoformat(start_date_str) if start_date_str else None
        popup.end_date = datetime.fromisoformat(end_date_str) if end_date_str else None
        popup.target_audience = request.form.get('target_audience', 'all')
        popup.priority = int(request.form.get('priority', 0) or 0)
        popup.position = request.form.get('position', 'center')
        popup.width = int(request.form.get('width', 500) or 500)
        popup.height = int(height_str) if height_str else None
        popup.overlay_opacity = overlay
        popup.button_text = request.form.get('button_text', '').strip() or None
        popup.button_url = request.form.get('button_url', '').strip() or None
        popup.link_target = request.form.get('link_target', '_self')
        popup.is_active = 'is_active' in request.form
        popup.is_closeable = 'is_closeable' in request.form
        popup.show_once_per_user = 'show_once_per_user' in request.form
        popup.hide_duration = int(hide_dur_str) if hide_dur_str else None
        db.session.commit()
        flash("Pop-up güncellendi!", "success")
        return redirect(url_for('admin_popups'))
    return render_template('admin/popups.html', popup=popup, mode='edit', popups=SitePopup.query.order_by(SitePopup.created_at.desc()).all(), active_page='settings')


@app.route('/admin/popups/<int:popup_id>/delete', methods=['POST'])
def admin_popup_delete(popup_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    popup = SitePopup.query.get_or_404(popup_id)
    if popup.image_filename:
        old_path = os.path.join(POPUP_IMG_FOLDER, popup.image_filename)
        if os.path.exists(old_path):
            os.remove(old_path)
    db.session.delete(popup)
    db.session.commit()
    flash("Pop-up silindi.", "success")
    return redirect(url_for('admin_popups'))


@app.route('/admin/popups/<int:popup_id>/toggle', methods=['POST'])
def admin_popup_toggle(popup_id):
    if session.get('username') != 'admin': return jsonify({'error': 'Yetkisiz'}), 403
    popup = SitePopup.query.get_or_404(popup_id)
    popup.is_active = not popup.is_active
    db.session.commit()
    return jsonify({'is_active': popup.is_active})


@app.route('/api/active-popup')
def api_active_popup():
    """Frontend için aktif popup döndürür"""
    now = datetime.utcnow()
    query = SitePopup.query.filter_by(is_active=True)
    popups = query.order_by(SitePopup.priority.desc()).all()
    result = []
    for p in popups:
        if p.start_date and p.start_date > now:
            continue
        if p.end_date and p.end_date < now:
            continue
        img_url = f"/static/uploads/popups/{p.image_filename}" if p.image_filename else None
        result.append({
            'id': p.id,
            'title': p.title,
            'message': p.message,
            'type': p.popup_type,
            'position': p.position,
            'width': p.width,
            'height': p.height,
            'overlay_opacity': p.overlay_opacity,
            'image_url': img_url,
            'button_text': p.button_text,
            'button_url': p.button_url,
            'link_target': p.link_target,
            'is_closeable': p.is_closeable,
            'show_once': p.show_once_per_user,
            'hide_duration': p.hide_duration,
        })
    return jsonify(result[:1])


# --- ORTAKLIK YÖNETİMİ ---
@app.route('/admin/partners')
def admin_partners():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    partners = Partner.query.order_by(Partner.created_at.desc()).all()
    partner_filter = request.args.get('partner_id')
    if partner_filter:
        sales = PartnerSale.query.filter_by(partner_id=int(partner_filter)).order_by(PartnerSale.created_at.desc()).all()
    else:
        sales = PartnerSale.query.order_by(PartnerSale.created_at.desc()).limit(50).all()
    return render_template('admin/partners.html', partners=partners, sales=sales, selected_partner=partner_filter, active_page='partners')

@app.route('/admin/partner/<int:partner_id>')
def admin_partner_detail(partner_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    partner = Partner.query.get_or_404(partner_id)
    sales = PartnerSale.query.filter_by(partner_id=partner_id).order_by(PartnerSale.created_at.desc()).all()
    return render_template('admin/partner_detail.html', partner=partner, sales=sales, active_page='partners')

@app.route('/admin/partner/approve/<int:partner_id>')
def admin_approve_partner(partner_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    partner = Partner.query.get_or_404(partner_id)
    partner.status = 'approved'
    partner.approved_at = datetime.utcnow()
    db.session.commit()
    flash('Ortak onaylandı!')
    return redirect(url_for('admin_partners'))

@app.route('/admin/partner/reject/<int:partner_id>')
def admin_reject_partner(partner_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    partner = Partner.query.get_or_404(partner_id)
    partner.status = 'rejected'
    db.session.commit()
    flash('Ortak reddedildi!')
    return redirect(url_for('admin_partners'))

@app.route('/admin/partner/update-commission/<int:partner_id>', methods=['POST'])
def admin_update_commission(partner_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    partner = Partner.query.get_or_404(partner_id)
    partner.commission_rate = int(request.form.get('commission_rate', 10))
    db.session.commit()
    flash('Komisyon oranı güncellendi!')
    return redirect(url_for('admin_partner_detail', partner_id=partner_id))

@app.route('/admin/partner/<int:partner_id>/edit', methods=['POST'])
def admin_edit_partner(partner_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    partner = Partner.query.get_or_404(partner_id)
    partner.commission_rate = int(request.form.get('commission_rate', partner.commission_rate))
    partner.status = request.form.get('status', partner.status)
    partner.iban = request.form.get('iban', partner.iban)
    partner.iban_name = request.form.get('iban_name', partner.iban_name)
    db.session.commit()
    flash('Ortak bilgileri güncellendi!')
    return redirect(url_for('admin_partners'))

@app.route('/admin/partner/<int:partner_id>/delete', methods=['POST'])
def admin_delete_partner(partner_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    partner = Partner.query.get_or_404(partner_id)
    PartnerSale.query.filter_by(partner_id=partner_id).delete()
    PartnerWithdrawal.query.filter_by(partner_id=partner_id).delete()
    DiscountCode.query.filter_by(partner_id=partner_id).delete()
    db.session.delete(partner)
    db.session.commit()
    flash('Ortak silindi!')
    return redirect(url_for('admin_partners'))

@app.route('/admin/partner/<int:partner_id>/pay', methods=['POST'])
def admin_partner_pay(partner_id):
    if session.get('username') != 'admin': 
        return redirect(url_for('index'))
    
    partner = Partner.query.get_or_404(partner_id)
    amount = float(request.form.get('amount', 0))
    receipt_file = request.files.get('receipt')
    
    if amount <= 0 or amount > partner.pending_earnings:
        flash('Geçersiz ödeme tutarı!')
        return redirect(url_for('admin_partner_detail', partner_id=partner_id))
    
    receipt_path = None
    if receipt_file and receipt_file.filename:
        os.makedirs('static/receipts', exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = secure_filename(f"{partner_id}_{timestamp}_{receipt_file.filename}")
        receipt_path = f"receipts/{filename}"
        receipt_file.save(os.path.join('static', receipt_path))
    
    partner.pending_earnings -= amount
    partner.withdrawn_earnings += amount
    
    withdrawal = PartnerWithdrawal(
        partner_id=partner_id,
        amount=amount,
        iban=partner.iban or '',
        iban_name=partner.iban_name or '',
        status='completed',
        processed_at=datetime.utcnow(),
        receipt_file=receipt_path
    )
    db.session.add(withdrawal)
    db.session.commit()
    
    flash(f'₺{amount:.2f} ödeme başarıyla yapıldı!')
    return redirect(url_for('admin_partner_detail', partner_id=partner_id))

@app.route('/admin/bayiler')
def admin_dealers():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    dealers = Dealer.query.order_by(Dealer.created_at.desc()).all()
    dealer_filter = request.args.get('dealer_id')
    if dealer_filter:
        sales = DealerSale.query.filter_by(dealer_id=int(dealer_filter)).order_by(DealerSale.created_at.desc()).all()
    else:
        sales = DealerSale.query.order_by(DealerSale.created_at.desc()).limit(50).all()
    return render_template('admin/dealers.html', dealers=dealers, sales=sales, selected_dealer=dealer_filter, active_page='dealers')

@app.route('/admin/bayi/<int:dealer_id>')
def admin_dealer_detail(dealer_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    dealer = Dealer.query.get_or_404(dealer_id)
    sales = DealerSale.query.filter_by(dealer_id=dealer_id).order_by(DealerSale.created_at.desc()).all()
    templates = DealerQrTemplate.query.filter_by(dealer_id=dealer_id).order_by(DealerQrTemplate.created_at.desc()).all()
    return render_template('admin/dealer_detail.html', dealer=dealer, sales=sales, templates=templates, active_page='dealers')

@app.route('/admin/bayi/approve/<int:dealer_id>')
def admin_approve_dealer(dealer_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    dealer = Dealer.query.get_or_404(dealer_id)
    dealer.status = 'approved'
    dealer.approved_at = datetime.utcnow()
    db.session.commit()
    flash('Bayi onaylandı!')
    return redirect(url_for('admin_dealers'))

@app.route('/admin/bayi/reject/<int:dealer_id>')
def admin_reject_dealer(dealer_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    dealer = Dealer.query.get_or_404(dealer_id)
    dealer.status = 'rejected'
    db.session.commit()
    flash('Bayi reddedildi!')
    return redirect(url_for('admin_dealers'))

@app.route('/admin/bayi/<int:dealer_id>/edit', methods=['POST'])
def admin_edit_dealer(dealer_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    dealer = Dealer.query.get_or_404(dealer_id)
    try:
        dealer.commission_rate = int(request.form.get('commission_rate', dealer.commission_rate))
    except (TypeError, ValueError):
        pass
    dealer.status = request.form.get('status', dealer.status)
    dealer.cafe_name = request.form.get('cafe_name', dealer.cafe_name)
    dealer.contact_name = request.form.get('contact_name', dealer.contact_name)
    dealer.phone = request.form.get('phone', dealer.phone)
    dealer.city = request.form.get('city', dealer.city)
    dealer.iban = request.form.get('iban', dealer.iban)
    dealer.iban_name = request.form.get('iban_name', dealer.iban_name)
    db.session.commit()
    flash('Bayi bilgileri güncellendi!')
    return redirect(url_for('admin_dealer_detail', dealer_id=dealer_id))

@app.route('/admin/bayi/<int:dealer_id>/delete', methods=['POST'])
def admin_delete_dealer(dealer_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    dealer = Dealer.query.get_or_404(dealer_id)
    DealerSale.query.filter_by(dealer_id=dealer_id).delete()
    DealerWithdrawal.query.filter_by(dealer_id=dealer_id).delete()
    DealerQrTemplate.query.filter_by(dealer_id=dealer_id).delete()
    db.session.delete(dealer)
    db.session.commit()
    flash('Bayi silindi!')
    return redirect(url_for('admin_dealers'))

@app.route('/admin/bayi/<int:dealer_id>/pay', methods=['POST'])
def admin_dealer_pay(dealer_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    dealer = Dealer.query.get_or_404(dealer_id)
    try:
        amount = float(request.form.get('amount', 0))
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0 or amount > dealer.pending_earnings:
        flash('Geçersiz ödeme tutarı!')
        return redirect(url_for('admin_dealer_detail', dealer_id=dealer_id))
    receipt_file = request.files.get('receipt')
    receipt_path = None
    if receipt_file and receipt_file.filename:
        os.makedirs('static/receipts', exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = secure_filename(f"dealer_{dealer_id}_{timestamp}_{receipt_file.filename}")
        receipt_path = f"receipts/{filename}"
        receipt_file.save(os.path.join('static', receipt_path))
    dealer.pending_earnings -= amount
    dealer.withdrawn_earnings += amount
    withdrawal = DealerWithdrawal(
        dealer_id=dealer_id,
        amount=amount,
        iban=dealer.iban or '',
        iban_name=dealer.iban_name or '',
        status='completed',
        processed_at=datetime.utcnow(),
        receipt_file=receipt_path
    )
    db.session.add(withdrawal)
    db.session.commit()
    flash(f'₺{amount:.2f} ödeme başarıyla yapıldı!')
    return redirect(url_for('admin_dealer_detail', dealer_id=dealer_id))

@app.route('/admin/withdrawals')
def admin_withdrawals():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    withdrawals = PartnerWithdrawal.query.order_by(PartnerWithdrawal.created_at.desc()).all()
    return render_template('admin/withdrawals.html', withdrawals=withdrawals, active_page='partners')

@app.route('/admin/withdrawal/process/<int:withdrawal_id>', methods=['POST'])
def admin_process_withdrawal(withdrawal_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    withdrawal = PartnerWithdrawal.query.get_or_404(withdrawal_id)
    action = request.form.get('action')
    note = request.form.get('note', '')
    if action == 'approve':
        withdrawal.status = 'completed'
        withdrawal.processed_at = datetime.utcnow()
        withdrawal.admin_note = note
        withdrawal.partner.pending_earnings -= withdrawal.amount
        withdrawal.partner.withdrawn_earnings += withdrawal.amount
        receipt = request.files.get('receipt')
        if receipt and receipt.filename:
            import os
            receipts_dir = os.path.join('static', 'receipts')
            os.makedirs(receipts_dir, exist_ok=True)
            filename = f"withdrawal_{withdrawal.id}_{int(datetime.utcnow().timestamp())}_{receipt.filename}"
            filepath = os.path.join(receipts_dir, filename)
            receipt.save(filepath)
            withdrawal.receipt_file = filepath
        flash('Ödeme onaylandı!')
    elif action == 'reject':
        withdrawal.status = 'rejected'
        withdrawal.processed_at = datetime.utcnow()
        withdrawal.admin_note = note
        flash('Ödeme reddedildi!')
    db.session.commit()
    return redirect(url_for('admin_withdrawals'))

# --- DEDEKTİF AKADEMİSİ ---
@app.route('/dedektif-akademisi')
def dedektif_akademisi():
    from sqlalchemy import func
    kolay = Case.query.filter_by(is_active=True, difficulty='Kolay').order_by(func.random()).limit(3).all()
    orta = Case.query.filter_by(is_active=True, difficulty='Orta').order_by(func.random()).limit(3).all()
    zor = Case.query.filter_by(is_active=True, difficulty='Zor').order_by(func.random()).limit(3).all()
    return render_template('akademi.html', kolay_vakalar=kolay, orta_vakalar=orta, zor_vakalar=zor)

# --- DEDEKTİF AKADEMİSİ MAKALELER ---
@app.route('/dedektif-akademisi/<slug>')
def akademi_makale(slug):
    from akademi_data import ARTICLES
    article = ARTICLES.get(slug)
    if not article:
        abort(404)
    return render_template('akademi_makale.html', article=article, current_slug=slug)

# --- HAKKIMIZDA ---
@app.route('/about')
def about():
    return render_template('about.html')

# --- FAQ YÖNETİMİ ---
@app.route('/faq')
def faq():
    faqs = FAQ.query.filter_by(is_active=True).order_by(FAQ.order).all()
    return render_template('faq.html', faqs=faqs)

@app.route('/privacy-policy')
def privacy_policy():
    return render_template('legal/privacy_policy.html')

@app.route('/terms-conditions')
def terms_conditions():
    return render_template('legal/terms_conditions.html')

@app.route('/distance-sales')
def distance_sales():
    return render_template('legal/distance_sales.html')

@app.route('/kvkk')
def kvkk():
    return render_template('legal/kvkk.html')

@app.route('/admin/faq')
def admin_faq():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    faqs = FAQ.query.order_by(FAQ.order).all()
    return render_template('admin/faq.html', faqs=faqs, active_page='settings')

@app.route('/admin/faq/add', methods=['GET', 'POST'])
def admin_add_faq():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    if request.method == 'POST':
        faq = FAQ(
            question=request.form.get('question'),
            question_en=request.form.get('question_en'),
            answer=request.form.get('answer'),
            answer_en=request.form.get('answer_en'),
            order=int(request.form.get('order', 0)),
            is_active=request.form.get('is_active') == '1'
        )
        db.session.add(faq)
        db.session.commit()
        flash("Soru başarıyla eklendi!")
        return redirect(url_for('admin_settings', section='faq'))
    return render_template('admin/faq_form.html', faq=None, active_page='settings')

@app.route('/admin/faq/edit/<int:faq_id>', methods=['GET', 'POST'])
def admin_edit_faq(faq_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    faq = FAQ.query.get_or_404(faq_id)
    if request.method == 'POST':
        faq.question = request.form.get('question')
        faq.question_en = request.form.get('question_en')
        faq.answer = request.form.get('answer')
        faq.answer_en = request.form.get('answer_en')
        faq.order = int(request.form.get('order', 0))
        faq.is_active = request.form.get('is_active') == '1'
        db.session.commit()
        flash("Soru başarıyla güncellendi!")
        return redirect(url_for('admin_settings', section='faq'))
    return render_template('admin/faq_form.html', faq=faq, active_page='settings')

@app.route('/admin/faq/delete/<int:faq_id>')
def admin_delete_faq(faq_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    faq = FAQ.query.get_or_404(faq_id)
    db.session.delete(faq)
    db.session.commit()
    flash("Soru silindi!")
    return redirect(url_for('admin_settings', section='faq'))

@app.route('/admin/faq/toggle/<int:faq_id>')
def admin_toggle_faq(faq_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    faq = FAQ.query.get_or_404(faq_id)
    faq.is_active = not faq.is_active
    db.session.commit()
    flash("Soru durumu güncellendi!")
    return redirect(url_for('admin_settings', section='faq'))

# --- VAKA KÜTÜPHANESİ ---
@app.route('/admin/vaka-kutuphanesi')
def admin_case_library():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    ideas = CaseIdea.query.order_by(CaseIdea.created_at.desc()).all()
    return render_template('admin/vaka_kutuphanesi.html', ideas=ideas, active_page='case_library')

@app.route('/admin/vaka-kutuphanesi/kesfet', methods=['POST'])
def admin_discover_cases():
    if session.get('username') != 'admin': return jsonify({'error': 'Yetkisiz'}), 403
    from openai_helper import discover_case_ideas
    category = request.json.get('category', 'all')
    ideas = discover_case_ideas(category)
    saved = []
    for idea in ideas:
        existing = CaseIdea.query.filter_by(title=idea.get('title', '')).first()
        if not existing:
            extra = {}
            for k in ['victim_brief', 'suspect_count', 'key_evidence', 'crime_type']:
                if idea.get(k):
                    extra[k] = idea[k]
            ci = CaseIdea(
                title=idea.get('title', ''),
                description=idea.get('description', ''),
                category=idea.get('category', 'unsolved'),
                tags=','.join(idea.get('tags', [])) if isinstance(idea.get('tags'), list) else idea.get('tags', ''),
                source_type=idea.get('source_type', ''),
                difficulty=idea.get('difficulty', 'Orta'),
                setting=idea.get('setting', ''),
                era=idea.get('era', 'modern'),
                case_data_json=json.dumps(extra, ensure_ascii=False) if extra else None
            )
            db.session.add(ci)
            saved.append(idea)
    db.session.commit()
    return jsonify({'ideas': saved, 'count': len(saved)})

@app.route('/admin/vaka-kutuphanesi/yenile', methods=['POST'])
def admin_refresh_ideas():
    if session.get('username') != 'admin': return jsonify({'error': 'Yetkisiz'}), 403
    from openai_helper import discover_case_ideas
    # Delete all pending (unused) ideas to make room for fresh ones
    CaseIdea.query.filter_by(status='idea').delete()
    db.session.commit()
    category = request.json.get('category', 'all') if request.json else 'all'
    ideas = discover_case_ideas(category)
    saved = []
    for idea in ideas:
        existing = CaseIdea.query.filter_by(title=idea.get('title', '')).first()
        if not existing:
            extra = {}
            for k in ['victim_brief', 'suspect_count', 'key_evidence', 'crime_type']:
                if idea.get(k):
                    extra[k] = idea[k]
            ci = CaseIdea(
                title=idea.get('title', ''),
                description=idea.get('description', ''),
                category=idea.get('category', 'unsolved'),
                tags=','.join(idea.get('tags', [])) if isinstance(idea.get('tags'), list) else idea.get('tags', ''),
                source_type=idea.get('source_type', ''),
                difficulty=idea.get('difficulty', 'Orta'),
                setting=idea.get('setting', ''),
                era=idea.get('era', 'modern'),
                case_data_json=json.dumps(extra, ensure_ascii=False) if extra else None
            )
            db.session.add(ci)
            saved.append(idea)
    db.session.commit()
    return jsonify({'ideas': saved, 'count': len(saved)})

@app.route('/admin/vaka-kutuphanesi/ara', methods=['POST'])
def admin_search_cases():
    if session.get('username') != 'admin': return jsonify({'error': 'Yetkisiz'}), 403
    from openai_helper import search_case_ideas
    query = request.json.get('query', '')
    if not query:
        return jsonify({'ideas': [], 'count': 0})
    ideas = search_case_ideas(query)
    saved = []
    for idea in ideas:
        existing = CaseIdea.query.filter_by(title=idea.get('title', '')).first()
        if not existing:
            extra = {}
            for k in ['victim_brief', 'suspect_count', 'key_evidence', 'crime_type']:
                if idea.get(k):
                    extra[k] = idea[k]
            ci = CaseIdea(
                title=idea.get('title', ''),
                description=idea.get('description', ''),
                category=idea.get('category', 'unsolved'),
                tags=','.join(idea.get('tags', [])) if isinstance(idea.get('tags'), list) else idea.get('tags', ''),
                source_type=idea.get('source_type', ''),
                difficulty=idea.get('difficulty', 'Orta'),
                setting=idea.get('setting', ''),
                era=idea.get('era', 'modern'),
                case_data_json=json.dumps(extra, ensure_ascii=False) if extra else None
            )
            db.session.add(ci)
            saved.append(idea)
    db.session.commit()
    return jsonify({'ideas': saved, 'count': len(saved)})

@app.route('/admin/vaka-kutuphanesi/sil/<int:idea_id>', methods=['POST'])
def admin_delete_idea(idea_id):
    if session.get('username') != 'admin': return jsonify({'error': 'Yetkisiz'}), 403
    idea = CaseIdea.query.get_or_404(idea_id)
    db.session.delete(idea)
    db.session.commit()
    return jsonify({'success': True})

case_generation_progress = {}

def _background_generate_case(app, idea_id):
    with app.app_context():
        from openai_helper import generate_case_content, generate_evidence_html, generate_success_file, generate_evidence_image, generate_evidence_audio
        progress = case_generation_progress[idea_id]
        idea = CaseIdea.query.get(idea_id)
        if not idea:
            progress['status'] = 'error'
            progress['error'] = 'Fikir bulunamadı'
            return

        try:
            db.session.execute(db.text("SELECT setval('suspect_id_seq', (SELECT COALESCE(MAX(id), 0) FROM suspect) + 1, false)"))
            db.session.commit()
            progress['step'] = 'Senaryo yazılıyor...'
            progress['percent'] = 5
            case_data = generate_case_content(idea.title, idea.description, idea.setting, idea.difficulty)
            if not case_data:
                progress['status'] = 'error'
                progress['error'] = 'Vaka içeriği oluşturulamadı'
                idea.status = 'idea'
                db.session.commit()
                return

            progress['step'] = 'Senaryo hazır, dosyalar oluşturuluyor...'
            progress['percent'] = 15

            idea.case_data_json = json.dumps(case_data, ensure_ascii=False)
            idea.status = 'generating'
            db.session.commit()

            case_id = case_data.get('case_id', '').replace(' ', '-')
            if not case_id:
                case_id = idea.title.replace(' ', '-').replace(':', '').replace("'", '')[:50]
            case_id = re.sub(r'[^\w\-]', '', case_id)

            existing_case = Case.query.get(case_id)
            if existing_case:
                case_id = case_id + '-' + str(random.randint(100, 999))

            upload_folder = os.path.join('static', 'uploads', case_id)
            os.makedirs(upload_folder, exist_ok=True)

            suspects_data = case_data.get('suspects', [])
            evidence_files = case_data.get('evidence_files', [])
            solution = case_data.get('solution', {})

            culprit_names = solution.get('culprit_names', [])
            if not culprit_names and solution.get('culprit_name'):
                culprit_names = [solution['culprit_name']]
            first_culprit = culprit_names[0].split()[0].lower() if culprit_names else ''

            new_case = Case(
                id=case_id,
                title=case_data.get('title', idea.title),
                price=149.0,
                image='placeholder.png',
                video='',
                description=case_data.get('description', idea.description),
                difficulty=idea.difficulty or 'Orta',
                solution=first_culprit,
                culprit_keywords=case_data.get('culprit_keywords', ''),
                explanation_keywords=case_data.get('explanation_keywords', ''),
                police_department=case_data.get('police_department', 'Emniyet Müdürlüğü'),
                commissioner_name=case_data.get('commissioner_name', 'Başkomiser'),
                is_active=False,
                game_type='both',
                success_message=solution.get('explanation', ''),
                report_case_name=case_data.get('title', idea.title),
                report_company='Soğuk Vaka A.Ş.',
                report_letter=case_data.get('report_letter', ''),
                report_greeting=case_data.get('report_greeting', 'Şef,'),
                report_intro_text=case_data.get('report_intro_text', ''),
                report_suspect_question=case_data.get('report_suspect_question', ''),
                report_confirmation_text=case_data.get('report_confirmation_text', ''),
                report_signature_name=case_data.get('commissioner_name', 'Başkomiser'),
                warning_text=case_data.get('warning_text', 'Lütfen sonucu diğer oyunculara söylemeyin.'),
                instructions_text=case_data.get('instructions_text', 'Tüm kanıtları dikkatle inceleyin ve raporunuzu gönderin.')
            )
            db.session.add(new_case)
            db.session.flush()

            # Generate cover image
            progress['step'] = 'Kapak fotoğrafı oluşturuluyor...'
            progress['percent'] = 10
            try:
                from openai_helper import generate_case_cover_image
                cover_bytes = generate_case_cover_image(case_data)
                if cover_bytes:
                    cover_name = 'cover.png'
                    cover_path = os.path.join(upload_folder, cover_name)
                    with open(cover_path, 'wb') as f:
                        f.write(cover_bytes)
                    new_case.image = cover_name
                    db.session.commit()
                    progress['step'] = 'Kapak fotoğrafı hazır, dosyalar oluşturuluyor...'
            except Exception as e:
                print(f"Kapak fotoğrafı hatası: {e}")

            for s in suspects_data:
                suspect = Suspect(
                    case_id=case_id,
                    name=s.get('name', ''),
                    is_culprit=s.get('is_culprit', False)
                )
                db.session.add(suspect)
            db.session.flush()

            generated_files = []
            failed_files = []
            total_files = len(evidence_files) + 1
            for idx, ef in enumerate(evidence_files):
                file_type = ef.get('file_type', 'html')
                filename = ef.get('filename', 'Belge').replace(' ', '_')
                filename = re.sub(r'[^\w\-.]', '_', filename)

                for old_ext in ['.html', '.jpg', '.jpeg', '.png', '.mp3', '.wav', '.ogg']:
                    if filename.lower().endswith(old_ext):
                        filename = filename[:len(filename)-len(old_ext)]
                        break

                if file_type == 'image':
                    filename = filename + '.png'
                    file_ext = 'png'
                elif file_type == 'audio':
                    filename = filename + '.mp3'
                    file_ext = 'mp3'
                else:
                    filename = filename + '.html'
                    file_ext = 'html'

                display = ef.get('display_name', filename.rsplit('.', 1)[0].replace('_', ' '))
                type_label = {'image': 'Fotoğraf', 'audio': 'Ses kaydı', 'html': 'Belge'}.get(file_type, 'Belge')
                progress['step'] = f'{type_label} üretiliyor: {display} ({idx+1}/{total_files})'
                progress['percent'] = 15 + int((idx / total_files) * 80)
                progress['current_file'] = display
                progress['files_done'] = idx
                progress['files_total'] = total_files

                try:
                    filepath = os.path.join(upload_folder, filename)
                    file_generated = False

                    if file_type == 'image':
                        img_bytes = generate_evidence_image(case_data, ef)
                        if img_bytes:
                            with open(filepath, 'wb') as f:
                                f.write(img_bytes)
                            file_generated = True
                    elif file_type == 'audio':
                        audio_bytes = generate_evidence_audio(case_data, ef)
                        if audio_bytes:
                            with open(filepath, 'wb') as f:
                                f.write(audio_bytes)
                            file_generated = True
                    else:
                        html_content = generate_evidence_html(case_data, ef)
                        if html_content:
                            with open(filepath, 'w', encoding='utf-8') as f:
                                f.write(html_content)
                            file_generated = True

                    if file_generated:
                        cf = CaseFile(
                            filename=filename,
                            display_name=display,
                            category=ef.get('category', 'Diğer Belgeler'),
                            file_ext=file_ext,
                            case_id=case_id
                        )
                        db.session.add(cf)
                        db.session.commit()
                        generated_files.append(filename)
                    else:
                        failed_files.append(filename)
                except Exception as e:
                    print(f"Dosya oluşturma hatası ({filename}): {e}")
                    failed_files.append(filename)
                    try:
                        db.session.rollback()
                    except:
                        pass

            progress['step'] = 'Başarı dosyası oluşturuluyor...'
            progress['percent'] = 95
            try:
                for s in case_data.get('suspects', []):
                    for cn in case_data.get('solution', {}).get('culprit_names', []):
                        if cn.lower() in s.get('name', '').lower() or s.get('name', '').lower() in cn.lower():
                            s['is_culprit'] = True
                success_html = generate_success_file(case_data)
                if success_html:
                    success_path = os.path.join(upload_folder, 'Basari_Dosyasi.html')
                    with open(success_path, 'w', encoding='utf-8') as f:
                        f.write(success_html)
                    generated_files.append('Basari_Dosyasi.html')
                    new_case = db.session.get(Case, case_id)
                    if new_case:
                        new_case.success_file = 'Basari_Dosyasi.html'
                        db.session.commit()
            except Exception as e:
                print(f"Başarı dosyası hatası: {e}")

            idea.status = 'completed'
            idea.is_used = True
            db.session.commit()

            progress['status'] = 'completed'
            progress['percent'] = 100
            progress['step'] = 'Tamamlandı!'
            progress['case_id'] = case_id
            progress['title'] = new_case.title
            progress['files_generated'] = len(generated_files)
            progress['files_failed'] = len(failed_files)
            progress['edit_url'] = f'/admin/edit/{case_id}'

        except Exception as e:
            print(f"Vaka oluşturma hatası: {e}")
            progress['status'] = 'error'
            progress['error'] = str(e)
            try:
                db.session.rollback()
                idea = CaseIdea.query.get(idea_id)
                if idea:
                    idea.status = 'idea'
                    db.session.commit()
            except Exception as e2:
                print(f"Durum sıfırlama hatası: {e2}")
                try:
                    db.session.rollback()
                except:
                    pass


@app.route('/admin/vaka-kutuphanesi/olustur/<int:idea_id>', methods=['POST'])
def admin_generate_case(idea_id):
    if session.get('username') != 'admin': return jsonify({'error': 'Yetkisiz'}), 403
    idea = CaseIdea.query.get_or_404(idea_id)

    if idea_id in case_generation_progress and case_generation_progress[idea_id].get('status') == 'running':
        return jsonify({'error': 'Bu vaka zaten üretiliyor'}), 400

    case_generation_progress[idea_id] = {
        'status': 'running',
        'step': 'Başlatılıyor...',
        'percent': 0,
        'files_done': 0,
        'files_total': 0,
        'current_file': '',
    }

    idea.status = 'generating'
    db.session.commit()

    thread = threading.Thread(target=_background_generate_case, args=(app, idea_id))
    thread.daemon = True
    thread.start()

    return jsonify({'success': True, 'message': 'Vaka oluşturma başlatıldı'})


@app.route('/admin/vaka-kutuphanesi/progress/<int:idea_id>')
def admin_case_progress(idea_id):
    if session.get('username') != 'admin': return jsonify({'error': 'Yetkisiz'}), 403
    progress = case_generation_progress.get(idea_id)
    if not progress:
        idea = CaseIdea.query.get(idea_id)
        if idea and idea.status == 'completed':
            return jsonify({'status': 'completed', 'percent': 100, 'step': 'Tamamlandı!'})
        return jsonify({'status': 'idle', 'percent': 0})
    return jsonify(progress)

# --- ORTAKLIK SAYFASI ---
@app.route('/partner')
def partner():
    all_settings = Settings.query.all()
    settings_dict = {s.key: s.value for s in all_settings}
    return render_template('partner.html',
        partner_title=settings_dict.get('partner_title', 'Ortaklık Programımıza Katılın'),
        partner_title_en=settings_dict.get('partner_title_en', 'Join Our Partnership Program'),
        partner_description=settings_dict.get('partner_description', 'Gizem ve gerçek suç öykülerine olan tutkumuzu paylaşan yayıncılarla ortaklık kurmaktan heyecan duyuyoruz.'),
        partner_description_en=settings_dict.get('partner_description_en', 'We are excited to partner with publishers who share our passion for mystery and true crime stories.'),
        partner_commission=settings_dict.get('partner_commission', '%20'),
        partner_cookie_days=settings_dict.get('partner_cookie_days', '30'),
        partner_signup_url=settings_dict.get('partner_signup_url', ''),
        partner_button_text=settings_dict.get('partner_button_text', 'Hemen Kayıt Olun!'),
        partner_button_text_en=settings_dict.get('partner_button_text_en', 'Sign Up Now!'),
        partner_faq1_tr=settings_dict.get('partner_faq1_tr', 'Kitlenize benzersiz dedektiflik oyunları tanıtırken her satıştan komisyon kazanın.'),
        partner_faq1_en=settings_dict.get('partner_faq1_en', 'Earn commission on every sale while promoting unique detective games to your audience.'),
        partner_faq2_tr=settings_dict.get('partner_faq2_tr', 'Kayıt olun, benzersiz linkinizi alın, paylaşın ve linkiniz üzerinden yapılan her satın almadan komisyon kazanın.'),
        partner_faq2_en=settings_dict.get('partner_faq2_en', 'Sign up, get your unique link, share it, and earn commission on every purchase made through your link.'),
        partner_faq3_tr=settings_dict.get('partner_faq3_tr', 'Her satışın komisyon oranı kadarını kazanırsınız. Ne kadar çok tanıtırsanız, o kadar çok kazanırsınız!'),
        partner_faq3_en=settings_dict.get('partner_faq3_en', 'You earn the commission rate of every sale. The more you promote, the more you earn!'),
        partner_faq4_tr=settings_dict.get('partner_faq4_tr', 'Ödemeler, iş ortağı platformumuz aracılığıyla aylık olarak yapılır.'),
        partner_faq4_en=settings_dict.get('partner_faq4_en', 'Payments are made monthly through our partner platform.'),
        partner_faq5_tr=settings_dict.get('partner_faq5_tr', 'Minimum ödeme eşikleri için lütfen iş ortağı platformumuzu kontrol edin.'),
        partner_faq5_en=settings_dict.get('partner_faq5_en', 'Please check our partner platform for minimum payout thresholds.'),
        partner_faq6_tr=settings_dict.get('partner_faq6_tr', 'Evet! Gizem oyunları, gerçek suç hikayeleri veya eğlenceyle ilgilenen bir kitleye sahip herkes katılabilir.'),
        partner_faq6_en=settings_dict.get('partner_faq6_en', 'Yes! Anyone with an audience interested in mystery games, true crime, or entertainment can join.')
    )

# --- OYUN PANELİ ---
@app.route('/active-cases')
def active_cases():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    if not user:
        session.clear()
        return redirect(url_for('login'))
    
    # Bireysel oyunlar
    if session.get('username') == 'admin':
        unlocked = [c.id for c in Case.query.all()]
    else:
        unlocked = [x.strip() for x in user.unlocked_cases.split(',') if x.strip()] if user.unlocked_cases else []
    
    from sqlalchemy import func
    user_email = (user.email or '').lower()
    
    all_accessed_cases = {}
    for case in Case.query.all():
        if case.id in unlocked:
            progress = GameProgress.query.filter_by(user_id=user.id, case_id=case.id).first()
            all_accessed_cases[case.id] = {
                'case': case,
                'completed': progress.is_solved if progress else False,
                'has_individual': True,
                'team_member': None,
                'team_purchase': None
            }
    
    # Purchase tablosunu da kontrol et (hesabım sayfasıyla tutarlılık için)
    if session.get('username') != 'admin':
        for purchase in Purchase.query.filter_by(user_id=user.id, is_paid=True).all():
            case = Case.query.get(purchase.case_id)
            if case and case.id not in all_accessed_cases:
                progress = GameProgress.query.filter_by(user_id=user.id, case_id=case.id).first()
                all_accessed_cases[case.id] = {
                    'case': case,
                    'completed': progress.is_solved if progress else False,
                    'has_individual': True,
                    'team_member': None,
                    'team_purchase': None
                }
    
    team_members = TeamMember.query.filter(func.lower(TeamMember.email) == user_email).all() if user_email else []
    for member in team_members:
        purchase = TeamPurchase.query.get(member.team_purchase_id)
        if purchase and purchase.payment_status == 'completed':
            case = Case.query.get(purchase.case_id)
            if case:
                if case.id in all_accessed_cases:
                    all_accessed_cases[case.id]['team_member'] = member
                    all_accessed_cases[case.id]['team_purchase'] = purchase
                else:
                    all_accessed_cases[case.id] = {
                        'case': case,
                        'completed': member.completed if member.completed else False,
                        'has_individual': False,
                        'team_member': member,
                        'team_purchase': purchase
                    }
    
    individual_cases = []
    team_games = []
    for cid, info in all_accessed_cases.items():
        case = info['case']
        if case.game_type in ('individual', 'both'):
            individual_cases.append({
                'case': case,
                'completed': info['completed']
            })
        if case.game_type in ('team', 'both'):
            team_games.append({
                'member': info['team_member'],
                'purchase': info['team_purchase'],
                'case': case,
                'completed': info['completed'],
                'from_individual': info['team_member'] is None
            })

    organized_purchases = []
    if user.email:
        organized_purchases = TeamPurchase.query.filter(
            db.func.lower(TeamPurchase.organizer_email) == user.email.lower(),
            TeamPurchase.payment_status == 'completed'
        ).order_by(TeamPurchase.created_at.desc()).all()

    return render_template('active_cases.html', 
                          individual_cases=individual_cases,
                          team_games=team_games,
                          organized_purchases=organized_purchases,
                          cases=Case.query.filter_by(is_active=True).all(), 
                          unlocked_list=unlocked)

def _parse_person_name(filename):
    import re as _re
    name = _re.sub(r'\.[^.]+$', '', filename)
    for prefix in ['Tanik_', 'Sorgu_', 'Ifade_']:
        if name.lower().startswith(prefix.lower()):
            name = name[len(prefix):]
            break
    parts = name.split('_')
    if parts and parts[0].lower() in ['dr', 'prof', 'av', 'op']:
        return ' '.join(parts[:3])
    return ' '.join(parts[:2]) if len(parts) >= 2 else name

def _get_board_people(case_id):
    witness_files = CaseFile.query.filter_by(case_id=case_id, category='Tanık Beyanları').all()
    board_witnesses = [{'id': f.id, 'name': _parse_person_name(f.filename)} for f in witness_files]
    victim_files = CaseFile.query.filter_by(case_id=case_id, category='Mağdur Detayları').filter(
        CaseFile.filename.ilike('Maktul_%')).all()
    board_victims = [{'id': f.id, 'name': f.display_name or 'Mağdur'} for f in victim_files[:1]]
    return board_witnesses, board_victims

@app.route('/play/<case_id>')
def play_case(case_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    case = Case.query.get_or_404(case_id)
    if not case.is_active and session.get('username') != 'admin':
        abort(404)
    uid = session['user_id']
    user_already_commented = Comment.query.filter_by(case_id=case_id, user_id=uid).first() is not None
    encrypted_clues = EncryptedClue.query.filter_by(case_id=case_id).order_by(EncryptedClue.order_num).all()
    solved_clue_ids = [s.clue_id for s in ClueSolve.query.filter_by(user_id=uid).filter(
        ClueSolve.clue_id.in_([c.id for c in encrypted_clues])).all()] if encrypted_clues else []
    user_flags = {f.file_id: {'color': f.flag_color, 'note': f.note}
                  for f in EvidenceFlag.query.filter_by(user_id=uid, case_id=case_id).all()}
    user_note = CaseNote.query.filter_by(user_id=uid, case_id=case_id).first()
    board_witnesses, board_victims = _get_board_people(case_id)
    return render_template('play_case.html', case=case, files=case.files, suspects=case.suspects,
                           demo_mode=False, user_already_commented=user_already_commented,
                           encrypted_clues=encrypted_clues, solved_clue_ids=solved_clue_ids,
                           user_flags=user_flags, user_note=user_note,
                           board_witnesses=board_witnesses, board_victims=board_victims)

@app.route('/add-comment-ajax/<case_id>', methods=['POST'])
def add_comment_ajax(case_id):
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Giriş yapmalısınız.'})
    already = Comment.query.filter_by(case_id=case_id, user_id=session['user_id']).first()
    if already:
        return jsonify({'status': 'error', 'message': 'Bu vaka için zaten yorum yaptınız.'})
    content = request.form.get('content', '').strip()
    rating = int(request.form.get('rating', 5))
    if not content:
        return jsonify({'status': 'error', 'message': 'Yorum boş bırakılamaz.'})
    if not (1 <= rating <= 5):
        rating = 5
    db.session.add(Comment(content=content, rating=rating, user_id=session['user_id'], case_id=case_id))
    db.session.commit()
    return jsonify({'status': 'success', 'message': 'Yorumunuz alındı, incelendikten sonra yayınlanacaktır.'})

# --- İNTERAKTİF OYUN API'LERİ ---

@app.route('/api/note/<case_id>', methods=['GET', 'POST'])
def case_note_api(case_id):
    if 'user_id' not in session:
        return jsonify({'status': 'error'})
    uid = session['user_id']
    note = CaseNote.query.filter_by(user_id=uid, case_id=case_id).first()
    if request.method == 'GET':
        return jsonify({'content': note.content if note else ''})
    content = (request.json or {}).get('content', '')
    if note:
        note.content = content
        note.updated_at = datetime.utcnow()
    else:
        note = CaseNote(user_id=uid, case_id=case_id, content=content)
        db.session.add(note)
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/check-cipher/<int:clue_id>', methods=['POST'])
def check_cipher(clue_id):
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Giriş yapın'})
    uid = session['user_id']
    clue = EncryptedClue.query.get_or_404(clue_id)
    already = ClueSolve.query.filter_by(user_id=uid, clue_id=clue_id).first()
    if already:
        return jsonify({'status': 'already', 'reveal': clue.decrypted_reveal})
    answer = request.form.get('answer', '').strip().lower()
    valid = [x.strip().lower() for x in clue.correct_answer.split('|')]
    if answer in valid:
        db.session.add(ClueSolve(user_id=uid, clue_id=clue_id))
        db.session.commit()
        return jsonify({'status': 'correct', 'reveal': clue.decrypted_reveal})
    return jsonify({'status': 'wrong', 'message': 'Yanlış! Tekrar deneyin.'})

@app.route('/api/flag-evidence', methods=['POST'])
def flag_evidence():
    if 'user_id' not in session:
        return jsonify({'status': 'error'})
    uid = session['user_id']
    data = request.json or {}
    file_id = int(data.get('file_id', 0))
    case_id = data.get('case_id', '')
    flag_color = data.get('flag_color', 'red')
    note_text = data.get('note', '')
    existing = EvidenceFlag.query.filter_by(user_id=uid, file_id=file_id).first()
    if existing:
        if flag_color == 'remove':
            db.session.delete(existing)
        else:
            existing.flag_color = flag_color
            existing.note = note_text
    else:
        if flag_color != 'remove':
            db.session.add(EvidenceFlag(user_id=uid, case_id=case_id, file_id=file_id,
                                        flag_color=flag_color, note=note_text))
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/interrogate/<case_id>/<int:suspect_id>', methods=['POST'])
def interrogate_suspect(case_id, suspect_id):
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Giriş yapın'})
    question = (request.json or {}).get('question', '').strip()
    if not question:
        return jsonify({'status': 'error', 'message': 'Soru boş'})
    suspect = Suspect.query.get_or_404(suspect_id)
    case = Case.query.get_or_404(case_id)
    guilty_note = ('Suçlusun ama bunu asla kabul etme; kendini savun, yalan söyle veya konuyu saptır.'
                   if suspect.is_culprit else 'Massumsun; şüphe altında olduğun için sinirli veya endişelisin.')
    system_prompt = (
        f"Sen '{case.title}' cinayet vakasındaki şüpheli '{suspect.name}' isimli kişisin.\n"
        f"Vaka: {(case.description or '')[:400]}\n"
        f"Durum: {guilty_note}\n"
        "Dedektif sana sorular soruyor. Karaktere uygun, gerçekçi, kısa (2-3 cümle) cevaplar ver. "
        "Türkçe cevap ver. Hiçbir zaman yapay zeka olduğunu söyleme."
    )
    try:
        from openai_helper import client as gemini_client
        from google.genai import types as gtypes
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[gtypes.Content(role='user', parts=[gtypes.Part(text=question)])],
            config=gtypes.GenerateContentConfig(
                system_instruction=system_prompt, max_output_tokens=200, temperature=0.88)
        )
        return jsonify({'status': 'ok', 'reply': response.text or 'Cevap vermek istemiyorum.'})
    except Exception:
        return jsonify({'status': 'error', 'message': 'AI şu an yanıt veremiyor.'})

@app.route('/api/assistant/<case_id>', methods=['POST'])
def case_assistant(case_id):
    """Vaka çözüm istasyonunda kullanıcıya yol gösteren yapay zeka rehberi.
    Delilleri incelemeye, ipuçlarını düzenlemeye ve doğru soruları sormaya
    yardım eder; ancak katili/çözümü ASLA açıklamaz veya ima etmez."""
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Giriş yapın'})
    data = request.json or {}
    question = (data.get('question') or '').strip()
    history = data.get('history') or []
    if not question:
        return jsonify({'status': 'error', 'message': 'Soru boş'})
    case = Case.query.get_or_404(case_id)
    lang = session.get('lang', 'tr')

    # Bağlam: başlık, özet, deliller (belge metinleri kısaltılmış), şüpheli adları,
    # kullanıcının erişebildiği ipuçları. Çözümü ele veren alanlar (culprit_keywords,
    # explanation_keywords, is_culprit, ipucu cevapları) BİLİNÇLİ olarak dışarıda bırakıldı.
    ev_lines, total = [], 0
    for f in case.files:
        name = f.display_name or f.filename or 'Belge'
        cat = f.category or ''
        snippet = ''
        try:
            if f.filename and f.filename.lower().endswith(('.html', '.htm', '.txt')) and total < 6000:
                path = os.path.join(UPLOAD_FOLDER, case_id, f.filename)
                if os.path.isfile(path):
                    with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                        raw = fh.read()
                    text = re.sub(r'<[^>]+>', ' ', raw)
                    text = re.sub(r'\s+', ' ', text).strip()
                    snippet = text[:600]
                    total += len(snippet)
        except Exception:
            snippet = ''
        ev_lines.append(f"- {name} ({cat}): {snippet}" if snippet else f"- {name} ({cat})")

    suspect_names = ', '.join(s.name for s in case.suspects) or 'Belirtilmemiş'

    now = datetime.utcnow()
    user = User.query.get(session['user_id'])
    unlocked = (user.unlocked_hints or '').split(',') if user else []
    hint_lines = []
    for h in Hint.query.filter_by(case_id=case_id, is_active=True).order_by(Hint.show_datetime).all():
        released = h.show_datetime is not None and now >= h.show_datetime
        if str(h.id) in unlocked or released:
            if h.hint_text:
                hint_lines.append(f"- {h.hint_text}")

    guard = (
        "Sen 'Dedektif Asistanı'sın; bir cinayet soruşturmasında dedektife (kullanıcıya) "
        "yol gösteren deneyimli, sakin ve mantıklı bir rehbersin.\n"
        f"VAKA: {case.title}\n"
        f"ÖZET: {(case.description or '')[:600]}\n"
        f"ŞÜPHELİLER: {suspect_names}\n"
        "DELİLLER:\n" + "\n".join(ev_lines[:20]) + "\n"
    )
    if hint_lines:
        guard += "KULLANICININ AÇTIĞI İPUÇLARI:\n" + "\n".join(hint_lines[:10]) + "\n"
    guard += (
        "\nGÖREVİN:\n"
        "- Kullanıcının doğru soruları sormasına yardım et; hangi delili neden incelemesi gerektiğini göster.\n"
        "- Belgeleri (evrakları) detaylı yorumlamasına, çelişkileri ve gözden kaçan ayrıntıları fark etmesine yardım et.\n"
        "- İpuçlarını ve notlarını düzenlemesine, mantıklı bir soruşturma sırası izlemesine rehberlik et.\n"
        "- Kısa, net ve anlaşılır cevap ver (en fazla 4-5 cümle).\n\n"
        "KESİN YASAKLAR (çok önemli):\n"
        "- ASLA katilin/suçlunun kim olduğunu söyleme veya ima etme.\n"
        "- ASLA vakanın çözümünü, nihai cevabını veya olayın nasıl gerçekleştiğinin tam açıklamasını verme.\n"
        "- Kullanıcı 'katil X mi?' gibi doğrudan sorarsa doğrulama veya yalanlama; onu kendi çıkarımını yapmaya yönlendir.\n"
        "- Doğrudan sonuca götürecek kestirme yanıtlar verme; yalnızca düşünmeyi ve incelemeyi kolaylaştır.\n"
        "- Yapay zeka olduğunu belirtme; deneyimli bir soruşturma rehberi gibi davran."
    )
    if lang == 'en':
        guard += "\n(Kullanıcının mesajları İngilizce ise İngilizce, Türkçe ise Türkçe cevap ver.)"

    try:
        from openai_helper import client as gemini_client
        from google.genai import types as gtypes
        contents = []
        for m in history[-8:]:
            role = 'model' if m.get('role') == 'assistant' else 'user'
            txt = (m.get('text') or '')[:500]
            if txt:
                contents.append(gtypes.Content(role=role, parts=[gtypes.Part(text=txt)]))
        contents.append(gtypes.Content(role='user', parts=[gtypes.Part(text=question)]))
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents,
            config=gtypes.GenerateContentConfig(
                system_instruction=guard, max_output_tokens=400, temperature=0.6)
        )
        reply = response.text or 'Şu an yardımcı olamıyorum.'

        # Deterministik güvenlik ağı: modelin prompt'a rağmen çözümü sızdırmasını engelle.
        # Katil anahtar kelimeleri, açıklama anahtar kelimeleri ve suçlunun adı yanıtta
        # geçiyorsa cevabı güvenli bir yönlendirmeyle değiştir.
        low = reply.lower()
        spoilers = []
        for field in (case.culprit_keywords, case.explanation_keywords):
            if field:
                spoilers += [k.strip().lower() for k in field.split(',')]
        for s in case.suspects:
            if s.is_culprit and s.name:
                spoilers.append(s.name.strip().lower())
        spoilers = [k for k in spoilers if len(k) >= 4]
        if any(k in low for k in spoilers):
            reply = ("Bu konuda sana doğrudan bir cevap veremem — katili senin bulman gerekiyor. "
                     "İstersen delilleri hangi sırayla incelemen gerektiğini veya hangi çelişkilere "
                     "odaklanabileceğini birlikte konuşabiliriz.")

        return jsonify({'status': 'ok', 'reply': reply})
    except Exception:
        return jsonify({'status': 'error', 'message': 'Asistan şu an yanıt veremiyor.'})

@app.route('/api/board/<case_id>', methods=['GET', 'POST'])
def board_api(case_id):
    if 'user_id' not in session:
        return jsonify({'cards': [], 'connections': []})
    uid = session['user_id']
    board = InvestigationBoard.query.filter_by(user_id=uid, case_id=case_id).first()
    if request.method == 'GET':
        import json as _json
        state = _json.loads(board.state_json) if board else {'cards': [], 'connections': []}
        return jsonify(state)
    import json as _json
    state_str = _json.dumps(request.json or {})
    if board:
        board.state_json = state_str
        board.updated_at = datetime.utcnow()
    else:
        board = InvestigationBoard(user_id=uid, case_id=case_id, state_json=state_str)
        db.session.add(board)
    db.session.commit()
    return jsonify({'status': 'ok'})

# --- ADMİN: ŞİFRELİ MESAJ YÖNETİMİ ---

@app.route('/admin/case/<case_id>/encrypted-clues')
def admin_encrypted_clues(case_id):
    if session.get('username') != 'admin': abort(403)
    case = Case.query.get_or_404(case_id)
    clues = EncryptedClue.query.filter_by(case_id=case_id).order_by(EncryptedClue.order_num).all()
    return render_template('admin/encrypted_clues.html', case=case, clues=clues, active_page='cases')

@app.route('/admin/case/<case_id>/encrypted-clues/add', methods=['POST'])
def admin_add_encrypted_clue(case_id):
    if session.get('username') != 'admin': abort(403)
    clue = EncryptedClue(
        case_id=case_id,
        title=request.form.get('title', ''),
        encrypted_text=request.form.get('encrypted_text', ''),
        cipher_type=request.form.get('cipher_type', 'caesar'),
        cipher_hint=request.form.get('cipher_hint', ''),
        unlock_instructions=request.form.get('unlock_instructions', ''),
        correct_answer=request.form.get('correct_answer', ''),
        decrypted_reveal=request.form.get('decrypted_reveal', ''),
        order_num=int(request.form.get('order_num') or 0)
    )
    db.session.add(clue)
    db.session.commit()
    flash('Şifreli mesaj eklendi.')
    return redirect(url_for('admin_encrypted_clues', case_id=case_id))

@app.route('/admin/encrypted-clue/<int:clue_id>/edit', methods=['POST'])
def admin_edit_encrypted_clue(clue_id):
    if session.get('username') != 'admin': abort(403)
    clue = EncryptedClue.query.get_or_404(clue_id)
    clue.title = request.form.get('title', clue.title)
    clue.encrypted_text = request.form.get('encrypted_text', clue.encrypted_text)
    clue.cipher_type = request.form.get('cipher_type', clue.cipher_type)
    clue.cipher_hint = request.form.get('cipher_hint', clue.cipher_hint)
    clue.unlock_instructions = request.form.get('unlock_instructions', clue.unlock_instructions)
    clue.correct_answer = request.form.get('correct_answer', clue.correct_answer)
    clue.decrypted_reveal = request.form.get('decrypted_reveal', clue.decrypted_reveal)
    clue.order_num = int(request.form.get('order_num') or clue.order_num)
    db.session.commit()
    flash('Şifreli mesaj güncellendi.')
    return redirect(url_for('admin_encrypted_clues', case_id=clue.case_id))

@app.route('/admin/encrypted-clue/<int:clue_id>/delete', methods=['POST'])
def admin_delete_encrypted_clue(clue_id):
    if session.get('username') != 'admin': abort(403)
    clue = EncryptedClue.query.get_or_404(clue_id)
    case_id = clue.case_id
    ClueSolve.query.filter_by(clue_id=clue_id).delete()
    db.session.delete(clue)
    db.session.commit()
    flash('Şifreli mesaj silindi.')
    return redirect(url_for('admin_encrypted_clues', case_id=case_id))

@app.route('/demo/<case_id>')
def demo_case(case_id):
    case = Case.query.get_or_404(case_id)
    if not case.is_active and session.get('username') != 'admin':
        abort(404)
    if not case.demo_enabled:
        flash('Bu vaka için demo modu aktif değil.')
        return redirect(url_for('case_detail', case_id=case_id))
    
    currency = session.get('currency', 'TRY')
    rates = {'TRY': 1, 'USD': 0.028, 'EUR': 0.026, 'GBP': 0.023}
    symbols = {'TRY': '₺', 'USD': '$', 'EUR': '€', 'GBP': '£'}
    
    board_witnesses, board_victims = _get_board_people(case_id)
    return render_template('play_case.html', case=case, files=case.files, suspects=case.suspects, demo_mode=True,
                         currency_rate=rates.get(currency, 1), currency_symbol=symbols.get(currency, '₺'),
                         board_witnesses=board_witnesses, board_victims=board_victims)

@app.route('/check-report/<case_id>', methods=['POST'])
def check_report(case_id):
    if 'user_id' not in session: return jsonify({"status": "fail", "message": "Giriş yapmalısınız."})
    s_id = request.form.get('suspect_id')
    suspect = Suspect.query.get(s_id)
    case = Case.query.get(case_id)
    user = User.query.get(session['user_id'])

    if suspect and suspect.is_culprit:
        points_map = {"Zor": 100, "Orta": 75, "Kolay": 50}
        vaka_puani = points_map.get(case.difficulty, 75)
        if case not in user.solved_cases_list:
            user.solved_cases_list.append(case)
            user.score += vaka_puani
            db.session.commit()
            msg = f"Tebrikler! Katili buldunuz ve {vaka_puani} puan kazandınız!"
        else:
            msg = "Tebrikler! Katili tekrar buldunuz (Puan daha önce alınmıştı)."
        return jsonify({"status": "success", "message": msg, "html": case.success_message})
    return jsonify({"status": "fail", "message": "Yanlış Şüpheli! Kanıtları tekrar inceleyin."})

# --- KİMLİK DOĞRULAMA ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_input = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=login_input).first()
        if not user:
            user = User.query.filter_by(email=login_input).first()
        if user and check_password_hash(user.password, password):
            session['user_id'], session['username'] = user.id, user.username
            # Bekleyen erişim kodu varsa işle
            if 'pending_code' in session:
                return redirect(url_for('process_pending_code'))
            # Bekleyen takım token'ı varsa yönlendir
            if 'team_token' in session:
                team_token = session['team_token']
                return redirect(url_for('team_access', access_token=team_token))
            return redirect(url_for('admin_cases' if user.username == 'admin' else 'active_cases'))
        flash("Giriş başarısız! Bilgileri kontrol edin.")
    return render_template('login.html')

# --- GOOGLE OAUTH GİRİŞ ---
@app.route('/auth/google')
def google_login():
    redirect_uri = "https://gizemlivaka.com/auth/google/callback"
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/google/callback')
def google_callback():
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')
        if not user_info:
            user_info = google.get('https://openidconnect.googleapis.com/v1/userinfo').json()
        
        email = user_info.get('email')
        name = user_info.get('name', email.split('@')[0])
        
        user = User.query.filter_by(email=email).first()
        if not user:
            username = email.split('@')[0]
            base_username = username
            counter = 1
            while User.query.filter_by(username=username).first():
                username = f"{base_username}{counter}"
                counter += 1
            
            user = User(
                username=username,
                email=email,
                password=generate_password_hash(os.urandom(24).hex())
            )
            db.session.add(user)
            db.session.commit()
        
        session['user_id'] = user.id
        session['username'] = user.username
        # Bekleyen takım token'ı varsa yönlendir
        if 'team_token' in session:
            team_token = session['team_token']
            flash(f"Hoş geldiniz, {user.username}! Takım oyununa yönlendiriliyorsunuz.")
            return redirect(url_for('team_access', access_token=team_token))
        flash(f"Hoş geldiniz, {user.username}!")
        return redirect(url_for('active_cases'))
    except Exception as e:
        print(f"Google OAuth Error: {e}")
        flash(f"Google ile giriş başarısız oldu: {str(e)}")
        return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash("Bu kullanıcı adı zaten kullanılıyor.")
            return render_template('register.html')
        if User.query.filter_by(email=email).first():
            flash("Bu e-posta adresi zaten kayıtlı.")
            return render_template('register.html')
        
        try:
            hashed_pw = generate_password_hash(password)
            new_user = User(username=username, email=email, password=hashed_pw)
            db.session.add(new_user)
            db.session.commit()
            # Kayıt sonrası otomatik giriş yap
            session['user_id'] = new_user.id
            session['username'] = new_user.username
            # Bekleyen takım token'ı varsa yönlendir
            if 'team_token' in session:
                team_token = session['team_token']
                flash("Kayıt başarılı! Takım oyununa yönlendiriliyorsunuz.")
                return redirect(url_for('team_access', access_token=team_token))
            flash("Kayıt başarılı!")
            return redirect(url_for('active_cases'))
        except Exception as e:
            db.session.rollback()
            flash("Kayıt sırasında bir hata oluştu.")
            return render_template('register.html')
    return render_template('register.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('index'))

@app.route('/account', defaults={'section': 'dashboard'})
@app.route('/account/<section>')
def account(section):
    if 'user_id' not in session: return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    if not user:
        session.clear()
        return redirect(url_for('login'))
    orders = Order.query.filter_by(user_id=user.id).all()
    
    all_user_cases = {}
    
    individual_purchases = Purchase.query.filter_by(user_id=user.id, is_paid=True).all()
    for purchase in individual_purchases:
        case = Case.query.get(purchase.case_id)
        if case:
            progress = GameProgress.query.filter_by(user_id=user.id, case_id=case.id).first()
            all_user_cases[case.id] = {
                'purchase': purchase,
                'case': case,
                'progress': progress,
                'team_member': None,
                'team_purchase': None
            }
    
    if user.email:
        team_results = db.session.query(TeamMember, TeamPurchase, Case).join(
            TeamPurchase, TeamMember.team_purchase_id == TeamPurchase.id
        ).join(
            Case, TeamPurchase.case_id == Case.id
        ).filter(
            db.func.lower(TeamMember.email) == user.email.lower(),
            TeamPurchase.payment_status == 'completed'
        ).all()
        for member, tp, case in team_results:
            if case.id in all_user_cases:
                all_user_cases[case.id]['team_member'] = member
                all_user_cases[case.id]['team_purchase'] = tp
            else:
                progress = GameProgress.query.filter_by(user_id=user.id, case_id=case.id).first()
                all_user_cases[case.id] = {
                    'purchase': None,
                    'case': case,
                    'progress': progress,
                    'team_member': member,
                    'team_purchase': tp
                }
    
    individual_games = []
    team_games = []
    for cid, info in all_user_cases.items():
        case = info['case']
        if case.game_type in ('individual', 'both'):
            individual_games.append((info['purchase'], case, info['progress']))
        if case.game_type in ('team', 'both'):
            if info['team_member']:
                team_games.append((info['team_member'], info['team_purchase'], case))
            else:
                team_games.append((None, None, case))
    
    organized_purchases = []
    if user.email:
        organized_purchases = TeamPurchase.query.filter(
            db.func.lower(TeamPurchase.organizer_email) == user.email.lower(),
            TeamPurchase.payment_status == 'completed'
        ).order_by(TeamPurchase.created_at.desc()).all()

    return render_template('account.html', user=user, section=section, orders=orders, 
                          team_games=team_games, individual_games=individual_games,
                          organized_purchases=organized_purchases)

# --- TAKIM ÜYESİ EKLEME / KALDIRMA ---
@app.route('/team-manage/add-member', methods=['POST'])
def team_manage_add_member():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    purchase_id = request.form.get('purchase_id', type=int)
    team_number = request.form.get('team_number', type=int)
    email = request.form.get('email', '').strip().lower()
    lang = session.get('lang', 'tr')

    purchase = TeamPurchase.query.get_or_404(purchase_id)

    if purchase.organizer_email.lower() != (user.email or '').lower() and session.get('username') != 'admin':
        flash('Bu işlem için yetkiniz yok.' if lang == 'tr' else 'You are not authorized.')
        return redirect(url_for('account'))

    import re
    if not email or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        flash('Geçerli bir e-posta adresi giriniz.' if lang == 'tr' else 'Please enter a valid email.')
        return redirect(url_for('team_purchase_payment', purchase_id=purchase_id))

    team_members = [m for m in purchase.members if m.team_number == team_number]
    if len(team_members) >= 6:
        flash('Bu takımda en fazla 6 üye olabilir.' if lang == 'tr' else 'A team can have at most 6 members.')
        return redirect(url_for('team_purchase_payment', purchase_id=purchase_id))

    existing = next((m for m in purchase.members if m.email.lower() == email), None)
    if existing:
        flash('Bu e-posta bu satın almada zaten kayıtlı.' if lang == 'tr' else 'This email is already registered.')
        return redirect(url_for('team_purchase_payment', purchase_id=purchase_id))

    team_name = team_members[0].team_name if team_members else (f'Takım {team_number}' if lang == 'tr' else f'Team {team_number}')
    import secrets as _sec
    new_member = TeamMember(
        team_purchase_id=purchase.id,
        team_number=team_number,
        team_name=team_name,
        email=email,
        access_token=_sec.token_urlsafe(32)
    )
    db.session.add(new_member)
    db.session.commit()
    flash(f'✅ {email} takıma eklendi.' if lang == 'tr' else f'✅ {email} added to the team.')
    next_page = request.form.get('next', 'payment')
    if next_page == 'my_teams':
        return redirect(url_for('account', section='my_teams'))
    if next_page == 'active_cases':
        return redirect(url_for('active_cases'))
    return redirect(url_for('team_purchase_payment', purchase_id=purchase_id))


@app.route('/team-manage/remove-member/<int:member_id>', methods=['POST'])
def team_manage_remove_member(member_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = db.session.get(User, session['user_id'])
    member = TeamMember.query.get_or_404(member_id)
    purchase = member.team_purchase
    lang = session.get('lang', 'tr')

    if purchase.organizer_email.lower() != (user.email or '').lower() and session.get('username') != 'admin':
        flash('Bu işlem için yetkiniz yok.' if lang == 'tr' else 'You are not authorized.')
        return redirect(url_for('account'))

    if member.accessed or member.completed:
        flash('Oyuna giriş yapmış üye kaldırılamaz.' if lang == 'tr' else 'Cannot remove a member who has already accessed the game.')
        return redirect(url_for('team_purchase_payment', purchase_id=purchase.id))

    purchase_id = purchase.id
    db.session.delete(member)
    db.session.commit()
    flash('Üye kaldırıldı.' if lang == 'tr' else 'Member removed.')
    next_page = request.form.get('next', 'payment')
    if next_page == 'my_teams':
        return redirect(url_for('account', section='my_teams'))
    if next_page == 'active_cases':
        return redirect(url_for('active_cases'))
    return redirect(url_for('team_purchase_payment', purchase_id=purchase_id))


# --- ORTAKLIK SİSTEMİ KULLANICI ROTALARI ---
@app.route('/account/partner')
def account_partner():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    partner = Partner.query.filter_by(user_id=user.id).first()
    cases = Case.query.filter_by(is_active=True).all()
    case_prices = {c.id: c.price for c in cases}
    return render_template('account_partner.html', partner=partner, cases=cases, case_prices=case_prices)

@app.route('/account/partner/apply', methods=['POST'])
def partner_apply():
    if 'user_id' not in session: return redirect(url_for('login'))
    existing = Partner.query.filter_by(user_id=session['user_id']).first()
    if existing:
        flash('Zaten bir ortaklık başvurunuz var.')
        return redirect(url_for('account_partner'))
    first_name = request.form.get('first_name', '').strip()
    last_name = request.form.get('last_name', '').strip()
    full_name = f"{first_name} {last_name}".strip()
    partner = Partner(
        user_id=session['user_id'],
        bio=request.form.get('bio'),
        instagram=request.form.get('instagram', '').strip() or None,
        youtube=request.form.get('youtube', '').strip() or None,
        tiktok=request.form.get('tiktok', '').strip() or None,
        twitter=request.form.get('twitter', '').strip() or None,
        website=request.form.get('website', '').strip() or None,
        iban=request.form.get('iban', '').strip() or None,
        iban_name=full_name or request.form.get('iban_name', '').strip() or None
    )
    db.session.add(partner)
    db.session.commit()
    flash('Ortaklık başvurunuz alındı! Onay bekleyiniz.')
    return redirect(url_for('account_partner'))

@app.route('/account/partner/update-iban', methods=['POST'])
def partner_update_iban():
    if 'user_id' not in session: return redirect(url_for('login'))
    partner = Partner.query.filter_by(user_id=session['user_id']).first()
    if not partner or partner.status != 'approved':
        flash('Erişim yetkiniz yok.')
        return redirect(url_for('account_partner'))
    partner.iban = request.form.get('iban')
    partner.iban_name = request.form.get('iban_name')
    db.session.commit()
    flash('IBAN bilgileriniz güncellendi.')
    return redirect(url_for('account_partner'))

@app.route('/account/partner/update-social', methods=['POST'])
def partner_update_social():
    if 'user_id' not in session: return redirect(url_for('login'))
    partner = Partner.query.filter_by(user_id=session['user_id']).first()
    if not partner or partner.status != 'approved':
        flash('Erişim yetkiniz yok.')
        return redirect(url_for('account_partner'))
    partner.instagram = request.form.get('instagram', '').strip() or None
    partner.youtube   = request.form.get('youtube', '').strip() or None
    partner.tiktok    = request.form.get('tiktok', '').strip() or None
    partner.twitter   = request.form.get('twitter', '').strip() or None
    partner.website   = request.form.get('website', '').strip() or None
    db.session.commit()
    flash('Sosyal medya bilgileriniz güncellendi.')
    return redirect(url_for('account_partner'))

@app.route('/account/partner/create-coupon', methods=['POST'])
def partner_create_coupon():
    if 'user_id' not in session: return redirect(url_for('login'))
    partner = Partner.query.filter_by(user_id=session['user_id']).first()
    if not partner or partner.status != 'approved':
        flash('Erişim yetkiniz yok.')
        return redirect(url_for('account_partner'))
    import random, string
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    discount = DiscountCode(
        code=code,
        discount_percent=0,
        case_id=request.form.get('case_id') or None,
        partner_id=partner.id,
        is_active=True
    )
    db.session.add(discount)
    db.session.commit()
    flash(f'Kupon oluşturuldu: {code}')
    return redirect(url_for('account_partner'))

@app.route('/account/partner/delete-coupon/<int:coupon_id>', methods=['POST'])
def partner_delete_coupon(coupon_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    partner = Partner.query.filter_by(user_id=session['user_id']).first()
    if not partner or partner.status != 'approved':
        flash('Erişim yetkiniz yok.')
        return redirect(url_for('account_partner'))
    discount = DiscountCode.query.get(coupon_id)
    if not discount or discount.partner_id != partner.id:
        flash('Kupon bulunamadı.')
        return redirect(url_for('account_partner'))
    if discount.usage_count > 0:
        flash('Kullanılmış kuponlar silinemez.')
        return redirect(url_for('account_partner'))
    db.session.delete(discount)
    db.session.commit()
    flash('Kupon silindi.')
    return redirect(url_for('account_partner'))

@app.route('/account/partner/withdraw', methods=['POST'])
def partner_withdraw():
    if 'user_id' not in session: return redirect(url_for('login'))
    partner = Partner.query.filter_by(user_id=session['user_id']).first()
    if not partner or partner.status != 'approved':
        flash('Erişim yetkiniz yok.')
        return redirect(url_for('account_partner'))
    amount = float(request.form.get('amount', 0))
    if amount <= 0 or amount > partner.pending_earnings:
        flash('Geçersiz tutar.')
        return redirect(url_for('account_partner'))
    if not partner.iban:
        flash('Önce IBAN bilgilerinizi girin.')
        return redirect(url_for('account_partner'))
    withdrawal = PartnerWithdrawal(
        partner_id=partner.id,
        amount=amount,
        iban=partner.iban,
        iban_name=partner.iban_name
    )
    db.session.add(withdrawal)
    db.session.commit()
    flash('Para çekme talebiniz alındı.')
    return redirect(url_for('account_partner'))

@app.route('/partner/coupon/<code>/qr')
def partner_coupon_qr(code):
    from flask import send_file
    discount = DiscountCode.query.filter_by(code=code).first_or_404()
    base_url = request.url_root.rstrip('/')
    if discount.case_id:
        url = f"{base_url}/case/{discount.case_id}?ref={code}"
    else:
        url = f"{base_url}/?ref={code}"
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0a1929", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return send_file(buffer, mimetype='image/png', download_name=f'kupon_{code}.png')

# ============================================================
# BAYİLİK SİSTEMİ (kafe/firma) — oyun başına komisyon + QR şablonları
# ============================================================
def _generate_dealer_code():
    import random, string
    while True:
        code = 'BY' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not Dealer.query.filter_by(dealer_code=code).first():
            return code

def _generate_qr_token():
    import secrets
    while True:
        token = secrets.token_urlsafe(9)
        if not DealerQrTemplate.query.filter_by(token=token).first():
            return token

@app.route('/bayi')
def account_dealer():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    dealer = Dealer.query.filter_by(user_id=user.id).first()
    cases = Case.query.filter_by(is_active=True).all()
    templates = []
    if dealer and dealer.status == 'approved':
        templates = DealerQrTemplate.query.filter_by(dealer_id=dealer.id).order_by(DealerQrTemplate.created_at.desc()).all()
    return render_template('account_dealer.html', dealer=dealer, cases=cases, templates=templates)

@app.route('/bayi/basvur', methods=['POST'])
def dealer_apply():
    if 'user_id' not in session: return redirect(url_for('login'))
    existing = Dealer.query.filter_by(user_id=session['user_id']).first()
    if existing:
        flash('Zaten bir bayilik başvurunuz var.')
        return redirect(url_for('account_dealer'))
    cafe_name = request.form.get('cafe_name', '').strip()
    if not cafe_name:
        flash('Kafe/firma adı zorunludur.')
        return redirect(url_for('account_dealer'))
    dealer = Dealer(
        user_id=session['user_id'],
        cafe_name=cafe_name,
        contact_name=request.form.get('contact_name', '').strip() or None,
        phone=request.form.get('phone', '').strip() or None,
        email=request.form.get('email', '').strip() or None,
        city=request.form.get('city', '').strip() or None,
        address=request.form.get('address', '').strip() or None,
        iban=request.form.get('iban', '').strip() or None,
        iban_name=request.form.get('iban_name', '').strip() or None,
        dealer_code=_generate_dealer_code()
    )
    db.session.add(dealer)
    db.session.commit()
    flash('Bayilik başvurunuz alındı! Onay bekleyiniz.')
    return redirect(url_for('account_dealer'))

@app.route('/bayi/update-iban', methods=['POST'])
def dealer_update_iban():
    if 'user_id' not in session: return redirect(url_for('login'))
    dealer = Dealer.query.filter_by(user_id=session['user_id']).first()
    if not dealer or dealer.status != 'approved':
        flash('Erişim yetkiniz yok.')
        return redirect(url_for('account_dealer'))
    dealer.iban = request.form.get('iban', '').strip() or None
    dealer.iban_name = request.form.get('iban_name', '').strip() or None
    db.session.commit()
    flash('IBAN bilgileriniz güncellendi.')
    return redirect(url_for('account_dealer'))

@app.route('/bayi/qr/olustur', methods=['POST'])
def dealer_create_qr():
    if 'user_id' not in session: return redirect(url_for('login'))
    dealer = Dealer.query.filter_by(user_id=session['user_id']).first()
    if not dealer or dealer.status != 'approved':
        flash('Erişim yetkiniz yok.')
        return redirect(url_for('account_dealer'))
    name = request.form.get('name', '').strip()
    qr_type = request.form.get('qr_type', 'general')
    if qr_type not in ('table', 'general'):
        qr_type = 'general'
    table_number = request.form.get('table_number', '').strip() or None
    if qr_type == 'general':
        table_number = None
    selected = request.form.getlist('case_ids')
    valid_ids = {c.id for c in Case.query.filter_by(is_active=True).all()}
    selected = [cid for cid in selected if cid in valid_ids]
    case_ids = ','.join(selected) if selected else ''
    if not name:
        name = f"Masa {table_number}" if (qr_type == 'table' and table_number) else f"{dealer.cafe_name} QR"
    template = DealerQrTemplate(
        dealer_id=dealer.id,
        name=name,
        qr_type=qr_type,
        table_number=table_number,
        token=_generate_qr_token(),
        case_ids=case_ids
    )
    db.session.add(template)
    db.session.commit()
    flash('QR şablonu oluşturuldu.')
    return redirect(url_for('account_dealer'))

@app.route('/bayi/qr/<int:template_id>/sil', methods=['POST'])
def dealer_delete_qr(template_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    dealer = Dealer.query.filter_by(user_id=session['user_id']).first()
    if not dealer or dealer.status != 'approved':
        flash('Erişim yetkiniz yok.')
        return redirect(url_for('account_dealer'))
    template = DealerQrTemplate.query.get(template_id)
    if not template or template.dealer_id != dealer.id:
        flash('Şablon bulunamadı.')
        return redirect(url_for('account_dealer'))
    db.session.delete(template)
    db.session.commit()
    flash('QR şablonu silindi.')
    return redirect(url_for('account_dealer'))

@app.route('/bayi/qr/<int:template_id>/indir')
def dealer_qr_download(template_id):
    from flask import send_file
    if 'user_id' not in session: return redirect(url_for('login'))
    dealer = Dealer.query.filter_by(user_id=session['user_id']).first()
    template = DealerQrTemplate.query.get_or_404(template_id)
    if not dealer or template.dealer_id != dealer.id:
        flash('Erişim yetkiniz yok.')
        return redirect(url_for('account_dealer'))
    base_url = request.url_root.rstrip('/')
    url = f"{base_url}/b/{template.token}"
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0a1929", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    safe = ''.join(ch if ch.isalnum() else '_' for ch in template.name)
    return send_file(buffer, mimetype='image/png', download_name=f'qr_{safe}.png')

@app.route('/bayi/odeme-talebi', methods=['POST'])
def dealer_withdraw():
    if 'user_id' not in session: return redirect(url_for('login'))
    dealer = Dealer.query.filter_by(user_id=session['user_id']).first()
    if not dealer or dealer.status != 'approved':
        flash('Erişim yetkiniz yok.')
        return redirect(url_for('account_dealer'))
    try:
        amount = float(request.form.get('amount', 0))
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0 or amount > dealer.pending_earnings:
        flash('Geçersiz tutar.')
        return redirect(url_for('account_dealer'))
    if not dealer.iban:
        flash('Önce IBAN bilgilerinizi girin.')
        return redirect(url_for('account_dealer'))
    withdrawal = DealerWithdrawal(
        dealer_id=dealer.id,
        amount=amount,
        iban=dealer.iban,
        iban_name=dealer.iban_name or dealer.cafe_name
    )
    db.session.add(withdrawal)
    db.session.commit()
    flash('Para çekme talebiniz alındı.')
    return redirect(url_for('account_dealer'))

@app.route('/b/<token>')
def dealer_qr_landing(token):
    template = DealerQrTemplate.query.filter_by(token=token, is_active=True).first_or_404()
    dealer = Dealer.query.get(template.dealer_id)
    if not dealer or dealer.status != 'approved':
        abort(404)
    template.scan_count = (template.scan_count or 0) + 1
    db.session.commit()
    session['dealer_ref'] = {'code': dealer.dealer_code, 'qr_template_id': template.id}
    session.permanent = True
    if template.case_ids:
        ids = [cid for cid in template.case_ids.split(',') if cid]
        cases = Case.query.filter(Case.id.in_(ids), Case.is_active == True).all()
    else:
        cases = Case.query.filter_by(is_active=True).all()
    return render_template('dealer_landing.html', dealer=dealer, template=template, cases=cases)

# --- ÖDEME SİSTEMLERİ ---
def get_payment_settings():
    all_settings = Settings.query.all()
    return {item.key: item.value for item in all_settings} if all_settings else {}

def record_partner_sale(case_id, sale_amount, buyer_user_id=None):
    if 'applied_discount' not in session:
        return
    applied = session.get('applied_discount', {})
    code = applied.get('code')
    if not code:
        return
    discount = DiscountCode.query.filter_by(code=code).first()
    if not discount or not discount.partner_id:
        return
    partner = Partner.query.get(discount.partner_id)
    if not partner or partner.status != 'approved':
        return
    commission_amount = sale_amount * (partner.commission_rate / 100)
    sale = PartnerSale(
        partner_id=partner.id,
        discount_code_id=discount.id,
        case_id=case_id,
        sale_amount=sale_amount,
        commission_amount=commission_amount,
        buyer_user_id=buyer_user_id
    )
    db.session.add(sale)
    partner.total_earnings += commission_amount
    partner.pending_earnings += commission_amount
    discount.usage_count += 1
    db.session.commit()

def record_partner_sale_for_team(team_purchase):
    """Takım satın alımı için ortak satışını kaydet (partner_code alanından)."""
    code = team_purchase.partner_code
    if not code:
        return
    discount = DiscountCode.query.filter_by(code=code, is_active=True).first()
    if not discount or not discount.partner_id:
        return
    partner = Partner.query.get(discount.partner_id)
    if not partner or partner.status != 'approved':
        return
    commission_amount = team_purchase.total_price * (partner.commission_rate / 100)
    sale = PartnerSale(
        partner_id=partner.id,
        discount_code_id=discount.id,
        case_id=team_purchase.case_id,
        sale_amount=team_purchase.total_price,
        commission_amount=commission_amount,
        buyer_user_id=None
    )
    db.session.add(sale)
    partner.total_earnings += commission_amount
    partner.pending_earnings += commission_amount
    discount.usage_count += 1
    # Çift kayıt önlemek için partner_code'u temizle
    team_purchase.partner_code = None
    db.session.commit()

def record_dealer_sale(case_id, sale_amount, buyer_user_id=None):
    """Bayi (kafe) QR'ından gelen satışın komisyonunu kaydeder."""
    ref = session.get('dealer_ref')
    if not ref:
        return
    code = ref.get('code')
    if not code:
        return
    dealer = Dealer.query.filter_by(dealer_code=code).first()
    if not dealer or dealer.status != 'approved':
        return
    qr_template_id = ref.get('qr_template_id')
    commission_amount = sale_amount * (dealer.commission_rate / 100)
    sale = DealerSale(
        dealer_id=dealer.id,
        qr_template_id=qr_template_id,
        case_id=case_id,
        sale_amount=sale_amount,
        commission_amount=commission_amount,
        buyer_user_id=buyer_user_id
    )
    db.session.add(sale)
    dealer.total_earnings += commission_amount
    dealer.pending_earnings += commission_amount
    db.session.commit()

def record_dealer_sale_for_team(team_purchase):
    """Takım satın alımı için bayi komisyonunu kaydeder (dealer_code alanından)."""
    code = team_purchase.dealer_code
    if not code:
        return
    dealer = Dealer.query.filter_by(dealer_code=code).first()
    if not dealer or dealer.status != 'approved':
        return
    commission_amount = team_purchase.total_price * (dealer.commission_rate / 100)
    sale = DealerSale(
        dealer_id=dealer.id,
        qr_template_id=team_purchase.dealer_qr_template_id,
        case_id=team_purchase.case_id,
        sale_amount=team_purchase.total_price,
        commission_amount=commission_amount,
        buyer_user_id=None
    )
    db.session.add(sale)
    dealer.total_earnings += commission_amount
    dealer.pending_earnings += commission_amount
    # Çift kayıt önlemek için dealer_code'u temizle
    team_purchase.dealer_code = None
    db.session.commit()

# ============================================================
# PARAM POS ENTEGRASYONU — SOAP 3D Secure
# ============================================================

def _param_pos_endpoint(settings):
    env = settings.get('param_env', 'test')
    if env == 'prod':
        return 'https://dmz.param.com.tr/turkpos.ws/service_turkpos_prod.asmx'
    return 'https://test-dmz.param.com.tr:4443/turkpos.ws/service_turkpos_test.asmx'

def _param_pos_client_ip():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr) or '127.0.0.1'
    return ip.split(',')[0].strip()

def param_pos_soap_3d_init(settings, kk_sahibi, kk_no, kk_ay, kk_yil, kk_cvc,
                            siparis_id, siparis_aciklama, tutar, success_url, fail_url, ip_adr):
    client_code = settings.get('param_client_code', '')
    username    = settings.get('param_username', '')
    password    = settings.get('param_password', '')
    guid        = settings.get('param_guid', '')
    endpoint    = _param_pos_endpoint(settings)
    tutar_str   = f"{float(tutar):.2f}".replace('.', ',')
    # TurkPos WMD hash: SHA2B64(CLIENT_CODE + GUID + Islem_Tutar + Toplam_Tutar + Siparis_ID + Hata_URL + Basarili_URL)
    hash_text   = client_code + guid + tutar_str + tutar_str + siparis_id + fail_url + success_url
    islem_hash  = base64.b64encode(hashlib.sha256(hash_text.encode('utf-8')).digest()).decode('utf-8')
    ref_url     = request.url_root.rstrip('/')
    soap = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <TP_Islem_Odeme_OnProv_WMD xmlns="https://turkpos.com.tr/">
      <G><CLIENT_CODE>{client_code}</CLIENT_CODE><CLIENT_USERNAME>{username}</CLIENT_USERNAME><CLIENT_PASSWORD>{password}</CLIENT_PASSWORD></G>
      <GUID>{guid}</GUID>
      <KK_Sahibi>{kk_sahibi}</KK_Sahibi><KK_No>{kk_no}</KK_No>
      <KK_SK_Ay>{kk_ay}</KK_SK_Ay><KK_SK_Yil>{kk_yil}</KK_SK_Yil><KK_CVC>{kk_cvc}</KK_CVC>
      <KK_Sahibi_GSM></KK_Sahibi_GSM>
      <Hata_URL>{fail_url}</Hata_URL><Basarili_URL>{success_url}</Basarili_URL>
      <Siparis_ID>{siparis_id}</Siparis_ID><Siparis_Aciklama>{siparis_aciklama}</Siparis_Aciklama>
      <Islem_Tutar>{tutar_str}</Islem_Tutar><Toplam_Tutar>{tutar_str}</Toplam_Tutar>
      <Islem_Hash>{islem_hash}</Islem_Hash>
      <Islem_Guvenlik_Tip>3D</Islem_Guvenlik_Tip><Islem_ID>0</Islem_ID>
      <IPAdr>{ip_adr}</IPAdr><Ref_URL>{ref_url}</Ref_URL>
      <Data1></Data1><Data2></Data2><Data3></Data3><Data4></Data4><Data5></Data5>
      <Taksit>1</Taksit>
    </TP_Islem_Odeme_OnProv_WMD>
  </soap:Body>
</soap:Envelope>"""
    headers = {
        'Content-Type': 'text/xml; charset=utf-8',
        'SOAPAction': '"https://turkpos.com.tr/TP_Islem_Odeme_OnProv_WMD"'
    }
    resp = requests.post(endpoint, data=soap.encode('utf-8'), headers=headers, timeout=30)
    return resp.text

def param_pos_soap_3d_kapa(settings, ucd_md, islem_id):
    client_code = settings.get('param_client_code', '')
    username    = settings.get('param_username', '')
    password    = settings.get('param_password', '')
    guid        = settings.get('param_guid', '')
    endpoint    = _param_pos_endpoint(settings)
    soap = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <TP_Islem_Odeme_OnProv_Kapa xmlns="https://turkpos.com.tr/">
      <G><CLIENT_CODE>{client_code}</CLIENT_CODE><CLIENT_USERNAME>{username}</CLIENT_USERNAME><CLIENT_PASSWORD>{password}</CLIENT_PASSWORD></G>
      <GUID>{guid}</GUID>
      <UCD_MD>{ucd_md}</UCD_MD>
      <Islem_ID>{islem_id}</Islem_ID>
    </TP_Islem_Odeme_OnProv_Kapa>
  </soap:Body>
</soap:Envelope>"""
    headers = {
        'Content-Type': 'text/xml; charset=utf-8',
        'SOAPAction': '"https://turkpos.com.tr/TP_Islem_Odeme_OnProv_Kapa"'
    }
    resp = requests.post(endpoint, data=soap.encode('utf-8'), headers=headers, timeout=30)
    return resp.text

def param_pos_parse(xml_text):
    import re
    def tag(name):
        m = re.search(rf'<{name}[^>]*>(.*?)</{name}>', xml_text, re.DOTALL)
        return m.group(1).strip() if m else ''
    return {
        'Sonuc': tag('Sonuc'), 'Sonuc_Str': tag('Sonuc_Str'),
        'UCD_HTML': tag('UCD_HTML'), 'Islem_ID': tag('Islem_ID'),
        'Siparis_ID': tag('Siparis_ID'),
    }

def _param_pos_process_payment(settings, amount, success_url, fail_url, pending_data, client_ref, fail_redirect):
    import json as jl
    kk_sahibi = request.form.get('card_holder', '')
    kk_no     = request.form.get('card_number', '').replace(' ', '')
    kk_ay     = request.form.get('expire_month', '')
    kk_yil    = request.form.get('expire_year', '')
    kk_cvc    = request.form.get('cvv', '')
    ps = Settings.query.filter_by(key=f'param_pending_{client_ref}').first()
    if ps: ps.value = jl.dumps(pending_data)
    else: db.session.add(Settings(key=f'param_pending_{client_ref}', value=jl.dumps(pending_data)))
    db.session.commit()
    try:
        xml_resp = param_pos_soap_3d_init(
            settings, kk_sahibi, kk_no, kk_ay, kk_yil, kk_cvc,
            client_ref, 'Gizemli Vaka Odeme', amount, success_url, fail_url,
            _param_pos_client_ip()
        )
        result = param_pos_parse(xml_resp)
        try: sonuc = int(result.get('Sonuc', '-1'))
        except: sonuc = -1
        if sonuc > 0:
            ucd_html = result.get('UCD_HTML', '')
            if ucd_html:
                import html as html_lib
                decoded = html_lib.unescape(ucd_html)
                return decoded
            return xml_resp
        else:
            flash(f"Param POS hatası: {result.get('Sonuc_Str', 'Bilinmeyen hata')}")
            return redirect(fail_redirect)
    except Exception as e:
        flash(f"Param POS bağlantı hatası: {str(e)}")
        return redirect(fail_redirect)

# --- Param POS: Tek Vaka ---
@app.route('/payment/param/<case_id>', methods=['GET', 'POST'])
def payment_param(case_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    settings = get_payment_settings()
    if settings.get('param_enabled') != '1':
        flash("Param POS ödeme sistemi aktif değil.")
        return redirect(url_for('payment_select', case_id=case_id))
    case = Case.query.get_or_404(case_id)
    session['pending_case_id'] = case_id
    session['pending_total'] = float(case.price)
    return render_template('payment_param.html', case=case, cart_total=None, hint=None,
                           form_action=url_for('param_process_case', case_id=case_id))

@app.route('/payment/param/<case_id>/process', methods=['POST'])
def param_process_case(case_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    settings = get_payment_settings()
    if settings.get('param_enabled') != '1':
        flash("Param POS ödeme sistemi aktif değil.")
        return redirect(url_for('payment_select', case_id=case_id))
    case = Case.query.get_or_404(case_id)
    user = User.query.get(session['user_id'])
    client_ref = f"GVC{datetime.now().strftime('%f')}{user.id}"
    return _param_pos_process_payment(
        settings, float(case.price),
        url_for('param_success', _external=True),
        url_for('param_fail', _external=True),
        {'type': 'case', 'user_id': user.id, 'case_id': case_id},
        client_ref,
        url_for('payment_select', case_id=case_id)
    )

# --- Param POS: Sepet ---
@app.route('/payment/param-cart', methods=['GET'])
def param_cart():
    if 'user_id' not in session: return redirect(url_for('login'))
    settings = get_payment_settings()
    if settings.get('param_enabled') != '1':
        flash("Param POS ödeme sistemi aktif değil.")
        return redirect(url_for('checkout'))
    cart = session.get('pending_cart', [])
    total = session.get('pending_total', 0)
    if not cart:
        flash("Sepet boş.")
        return redirect(url_for('view_cart'))
    return render_template('payment_param.html', case=None, cart_total=total, hint=None,
                           form_action=url_for('param_process_cart'))

@app.route('/payment/param-cart/process', methods=['POST'])
def param_process_cart():
    if 'user_id' not in session: return redirect(url_for('login'))
    settings = get_payment_settings()
    if settings.get('param_enabled') != '1':
        flash("Param POS ödeme sistemi aktif değil.")
        return redirect(url_for('checkout'))
    cart = session.get('pending_cart', [])
    total = session.get('pending_total', 0)
    if not cart:
        flash("Sepet boş.")
        return redirect(url_for('view_cart'))
    user = User.query.get(session['user_id'])
    client_ref = f"GVT{datetime.now().strftime('%f')}{user.id}"
    return _param_pos_process_payment(
        settings, float(total),
        url_for('param_success', _external=True),
        url_for('param_fail', _external=True),
        {'type': 'cart', 'user_id': user.id, 'cart': cart, 'total': total},
        client_ref,
        url_for('checkout')
    )

# --- Param POS: İpucu ---
@app.route('/payment/param/hint/<int:hint_id>', methods=['GET'])
def param_hint(hint_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    settings = get_payment_settings()
    if settings.get('param_enabled') != '1':
        flash("Param POS ödeme sistemi aktif değil.")
        return redirect(url_for('index'))
    hint = Hint.query.get_or_404(hint_id)
    session['pending_hint_id'] = hint_id
    return render_template('payment_param.html', case=None, cart_total=hint.price if hasattr(hint, 'price') else 0,
                           hint=hint, form_action=url_for('param_process_hint', hint_id=hint_id))

@app.route('/payment/param/hint/<int:hint_id>/process', methods=['POST'])
def param_process_hint(hint_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    settings = get_payment_settings()
    if settings.get('param_enabled') != '1':
        flash("Param POS ödeme sistemi aktif değil.")
        return redirect(url_for('index'))
    hint = Hint.query.get_or_404(hint_id)
    user = User.query.get(session['user_id'])
    price = hint.price if hasattr(hint, 'price') else 0
    client_ref = f"GVH{datetime.now().strftime('%f')}{user.id}"
    return _param_pos_process_payment(
        settings, float(price),
        url_for('param_success', _external=True),
        url_for('param_fail', _external=True),
        {'type': 'hint', 'user_id': user.id, 'hint_id': hint_id},
        client_ref,
        url_for('play_case', case_id=hint.case_id)
    )

# --- Param POS: Takım ---
@app.route('/payment/team/param/<int:purchase_id>', methods=['GET'])
def payment_team_param(purchase_id):
    settings = get_payment_settings()
    if settings.get('param_enabled') != '1':
        flash("Param POS ödeme sistemi aktif değil.")
        return redirect(url_for('payment_team_select', purchase_id=purchase_id))
    purchase = TeamPurchase.query.get_or_404(purchase_id)
    return render_template('payment_param.html', case=None, cart_total=purchase.total_price, hint=None,
                           form_action=url_for('param_process_team', purchase_id=purchase_id))

@app.route('/payment/team/param/process/<int:purchase_id>', methods=['POST'])
def param_process_team(purchase_id):
    settings = get_payment_settings()
    if settings.get('param_enabled') != '1':
        flash("Param POS ödeme sistemi aktif değil.")
        return redirect(url_for('payment_team_select', purchase_id=purchase_id))
    purchase = TeamPurchase.query.get_or_404(purchase_id)
    client_ref = f"GVT2{datetime.now().strftime('%f')}T{purchase_id}"
    return _param_pos_process_payment(
        settings, float(purchase.total_price),
        url_for('param_success', _external=True),
        url_for('param_fail', _external=True),
        {'type': 'team', 'purchase_id': purchase_id},
        client_ref,
        url_for('payment_team_select', purchase_id=purchase_id)
    )

# --- Param POS: Başarı Callback ---
@app.route('/payment/param/success', methods=['GET', 'POST'])
def param_success():
    import json as jl
    data = request.form if request.method == 'POST' else request.args
    ucd_md    = data.get('UCD_MD', '')
    islem_id  = data.get('Islem_ID', '')
    siparis_id = data.get('Siparis_ID', data.get('clientRefCode', ''))
    sonuc     = data.get('Sonuc', data.get('sonuc', ''))
    client_ref = siparis_id
    settings = get_payment_settings()
    # 3D onaylıysa Kapa çağır
    if ucd_md and islem_id:
        try:
            kapa_xml = param_pos_soap_3d_kapa(settings, ucd_md, islem_id)
            kapa_result = param_pos_parse(kapa_xml)
            try: kapa_sonuc = int(kapa_result.get('Sonuc', '-1'))
            except: kapa_sonuc = -1
            if kapa_sonuc <= 0:
                flash(f"Param POS 3D doğrulama hatası: {kapa_result.get('Sonuc_Str', 'Hata')}")
                pending_setting = Settings.query.filter_by(key=f'param_pending_{client_ref}').first()
                if pending_setting: db.session.delete(pending_setting); db.session.commit()
                return redirect(url_for('index'))
        except Exception as e:
            flash(f"Param POS tamamlama hatası: {str(e)}")
            return redirect(url_for('index'))
    pending_setting = Settings.query.filter_by(key=f'param_pending_{client_ref}').first()
    if not pending_setting:
        flash("Ödeme başarılı ancak sipariş bilgisi bulunamadı.")
        return redirect(url_for('index'))
    pending_info = jl.loads(pending_setting.value)
    db.session.delete(pending_setting)
    db.session.commit()
    ptype = pending_info.get('type')
    if ptype == 'team':
        purchase_id = pending_info.get('purchase_id')
        team_purchase = TeamPurchase.query.get(purchase_id)
        if team_purchase:
            team_purchase.payment_status = 'completed'
            db.session.commit()
            record_partner_sale_for_team(team_purchase)
            record_dealer_sale_for_team(team_purchase)
            flash("Ödeme başarılı! Takım erişim linkleri aktif edildi.")
            return redirect(url_for('team_purchase_payment', purchase_id=purchase_id))
        flash("Ödeme başarılı ancak takım bilgisi bulunamadı.")
        return redirect(url_for('index'))
    uid  = pending_info.get('user_id')
    user = User.query.get(uid)
    if not user:
        flash("Ödeme başarılı ancak kullanıcı bulunamadı.")
        return redirect(url_for('index'))
    if ptype == 'hint':
        hint_id = pending_info.get('hint_id')
        hint = Hint.query.get(hint_id)
        if hint:
            unlocked = (user.unlocked_hints or '').split(',')
            if str(hint_id) not in unlocked:
                user.unlocked_hints = f"{user.unlocked_hints},{hint_id}" if user.unlocked_hints else str(hint_id)
                db.session.commit()
            flash("Ödeme başarılı! İpucu açıldı.")
            return redirect(url_for('play_case', case_id=hint.case_id))
    elif ptype == 'cart':
        cart_items = pending_info.get('cart', [])
        cart_total = pending_info.get('total', 0)
        cart_cases = [c for c in (Case.query.get(cid) for cid in cart_items) if c]
        full_total = sum(float(c.price or 0) for c in cart_cases)
        paid_total = float(cart_total or 0) or full_total
        ratio = (paid_total / full_total) if full_total > 0 else 1.0
        for cid in cart_items:
            if cid not in (user.unlocked_cases or '').split(','):
                user.unlocked_cases = f"{user.unlocked_cases},{cid}" if user.unlocked_cases else cid
            c = Case.query.get(cid)
            if c:
                paid_amount = round(float(c.price or 0) * ratio, 2)
                if not Purchase.query.filter_by(user_id=user.id, case_id=cid).first():
                    db.session.add(Purchase(user_id=user.id, case_id=cid, amount=paid_amount, is_paid=True, created_at=datetime.utcnow()))
                record_partner_sale(cid, paid_amount, user.id)
                record_dealer_sale(cid, paid_amount, user.id)
        db.session.commit()
        session.pop('cart', None); session.pop('applied_discount', None); session.pop('pending_total', None)
        session.pop('dealer_ref', None)
        flash("Ödeme başarılı! Vakalar açıldı.")
        return redirect(url_for('active_cases'))
    elif ptype == 'case':
        case_id = pending_info.get('case_id')
        if case_id not in (user.unlocked_cases or '').split(','):
            user.unlocked_cases = f"{user.unlocked_cases},{case_id}" if user.unlocked_cases else case_id
        c = Case.query.get(case_id)
        if c:
            if not Purchase.query.filter_by(user_id=user.id, case_id=case_id).first():
                db.session.add(Purchase(user_id=user.id, case_id=case_id, amount=c.price, is_paid=True, created_at=datetime.utcnow()))
            record_partner_sale(case_id, c.price, user.id)
            record_dealer_sale(case_id, c.price, user.id)
        db.session.commit()
        session.pop('applied_discount', None); session.pop('pending_total', None)
        session.pop('dealer_ref', None)
        flash("Ödeme başarılı! Vaka açıldı.")
        return redirect(url_for('active_cases'))
    flash("Ödeme başarılı.")
    return redirect(url_for('index'))

# --- Param POS: Hata Callback ---
@app.route('/payment/param/fail', methods=['GET', 'POST'])
def param_fail():
    import json as jl
    data = request.form if request.method == 'POST' else request.args
    siparis_id = data.get('Siparis_ID', data.get('clientRefCode', ''))
    hata_msg   = data.get('Sonuc_Str', data.get('ErrMsg', 'Ödeme başarısız'))
    pending_setting = Settings.query.filter_by(key=f'param_pending_{siparis_id}').first()
    if pending_setting:
        try:
            pending_info = jl.loads(pending_setting.value)
            db.session.delete(pending_setting); db.session.commit()
            ptype = pending_info.get('type')
            flash(f"Param POS ödeme başarısız: {hata_msg}")
            if ptype == 'hint':
                hint = Hint.query.get(pending_info.get('hint_id'))
                if hint: return redirect(url_for('play_case', case_id=hint.case_id))
            elif ptype == 'case':
                return redirect(url_for('case_detail', case_id=pending_info.get('case_id')))
            elif ptype == 'team':
                return redirect(url_for('payment_team_select', purchase_id=pending_info.get('purchase_id')))
        except: pass
    flash(f"Param POS ödeme başarısız: {hata_msg}")
    return redirect(url_for('index'))

# ============================================================

@app.route('/payment/select/<case_id>')
def payment_select(case_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    case = Case.query.get_or_404(case_id)
    settings = get_payment_settings()
    iyzico_enabled = settings.get('iyzico_enabled') == '1'
    havale_enabled = settings.get('havale_enabled') == '1'
    param_enabled = settings.get('param_enabled') == '1'
    paynkolay_enabled = settings.get('paynkolay_enabled') == '1'
    return render_template('payment_select.html', case=case, iyzico_enabled=iyzico_enabled, havale_enabled=havale_enabled, param_enabled=param_enabled, paynkolay_enabled=paynkolay_enabled)

@app.route('/payment/havale/<case_id>')
def payment_havale_case(case_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    settings = get_payment_settings()
    if settings.get('havale_enabled') != '1':
        flash("Havale ödeme seçeneği aktif değil.")
        return redirect(url_for('payment_select', case_id=case_id))
    case = Case.query.get_or_404(case_id)
    user = User.query.get(session['user_id'])
    existing_paid = Purchase.query.filter_by(user_id=user.id, case_id=case_id, is_paid=True).first()
    if existing_paid:
        flash("Bu davayı zaten satın aldınız.")
        return redirect(url_for('play_case', case_id=case_id))
    pending = Purchase.query.filter_by(user_id=user.id, case_id=case_id, is_paid=False).first()
    if not pending:
        pending = Purchase(user_id=user.id, case_id=case_id, amount=case.price, is_paid=False)
        db.session.add(pending)
        db.session.commit()
    key = f'havale_case_{pending.id}'
    existing_s = Settings.query.filter_by(key=key).first()
    if existing_s:
        data = json.loads(existing_s.value)
        ref_code = data['ref_code']
    else:
        ref_code = 'GV-' + ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=8))
        db.session.add(Settings(key=key, value=json.dumps({
            'ref_code': ref_code, 'type': 'case', 'user_id': user.id, 'email': user.email,
            'case_id': case_id, 'title': case.title, 'amount': case.price,
            'purchase_id': pending.id, 'created_at': datetime.utcnow().isoformat()
        })))
        db.session.commit()
    return render_template('payment_havale.html',
        havale_iban=settings.get('havale_iban', ''),
        havale_alici_adi=settings.get('havale_alici_adi', ''),
        havale_banka_adi=settings.get('havale_banka_adi', ''),
        amount=case.price, ref_code=ref_code, title=case.title)

@app.route('/payment/havale-cart')
def havale_cart():
    if 'user_id' not in session: return redirect(url_for('login'))
    settings = get_payment_settings()
    if settings.get('havale_enabled') != '1':
        flash("Havale ödeme seçeneği aktif değil.")
        return redirect(url_for('checkout'))
    user = User.query.get(session['user_id'])
    cart = session.get('pending_cart', session.get('cart', []))
    if not cart:
        flash("Sepetiniz boş.")
        return redirect(url_for('view_cart'))
    cases = [Case.query.get(cid) for cid in cart if Case.query.get(cid)]
    total = sum(c.price for c in cases)
    ref_code = 'GV-' + ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=8))
    key = f'havale_cart_{user.id}_{int(datetime.utcnow().timestamp())}'
    db.session.add(Settings(key=key, value=json.dumps({
        'ref_code': ref_code, 'type': 'cart', 'user_id': user.id, 'email': user.email,
        'cart': cart, 'title': ', '.join(c.title for c in cases),
        'amount': total, 'created_at': datetime.utcnow().isoformat()
    })))
    db.session.commit()
    session.pop('pending_cart', None)
    session.pop('cart', None)
    session.modified = True
    return render_template('payment_havale.html',
        havale_iban=settings.get('havale_iban', ''),
        havale_alici_adi=settings.get('havale_alici_adi', ''),
        havale_banka_adi=settings.get('havale_banka_adi', ''),
        amount=total, ref_code=ref_code, title=f"Sepet ({len(cases)} dava)")

@app.route('/payment/team/havale/<int:purchase_id>')
def payment_havale_team(purchase_id):
    settings = get_payment_settings()
    if settings.get('havale_enabled') != '1':
        flash("Havale ödeme seçeneği aktif değil.")
        return redirect(url_for('payment_team_select', purchase_id=purchase_id))
    purchase = TeamPurchase.query.get_or_404(purchase_id)
    if purchase.payment_status == 'completed':
        return redirect(url_for('team_purchase_payment', purchase_id=purchase.id))
    key = f'havale_team_{purchase.id}'
    existing_s = Settings.query.filter_by(key=key).first()
    if existing_s:
        data = json.loads(existing_s.value)
        ref_code = data['ref_code']
    else:
        ref_code = 'GV-' + ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=8))
        purchase.payment_status = 'pending_havale'
        db.session.add(Settings(key=key, value=json.dumps({
            'ref_code': ref_code, 'type': 'team', 'email': purchase.organizer_email,
            'title': f"{purchase.case.title} - {purchase.team_count} Takım",
            'amount': purchase.total_price, 'purchase_id': purchase.id,
            'created_at': datetime.utcnow().isoformat()
        })))
        db.session.commit()
    return render_template('payment_havale.html',
        havale_iban=settings.get('havale_iban', ''),
        havale_alici_adi=settings.get('havale_alici_adi', ''),
        havale_banka_adi=settings.get('havale_banka_adi', ''),
        amount=purchase.total_price, ref_code=ref_code,
        title=f"{purchase.case.title} - Takım Oyunu")

@app.route('/payment/havale/hint/<int:hint_id>')
def payment_havale_hint(hint_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    settings = get_payment_settings()
    hint = Hint.query.get_or_404(hint_id)
    user = User.query.get(session['user_id'])
    ref_code = 'GV-' + ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=8))
    key = f'havale_hint_{hint_id}_{user.id}_{int(datetime.utcnow().timestamp())}'
    db.session.add(Settings(key=key, value=json.dumps({
        'ref_code': ref_code, 'type': 'hint', 'user_id': user.id, 'email': user.email,
        'hint_id': hint_id, 'case_id': hint.case_id,
        'title': f"İpucu #{hint_id}",
        'amount': hint.unlock_price, 'created_at': datetime.utcnow().isoformat()
    })))
    db.session.commit()
    return render_template('payment_havale.html',
        havale_iban=settings.get('havale_iban', ''),
        havale_alici_adi=settings.get('havale_alici_adi', ''),
        havale_banka_adi=settings.get('havale_banka_adi', ''),
        amount=hint.unlock_price, ref_code=ref_code, title=f"İpucu Açma")

@app.route('/admin/havale-transfers')
def admin_havale_transfers():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    all_havale = Settings.query.filter(Settings.key.like('havale_case_%')).all()
    all_havale += Settings.query.filter(Settings.key.like('havale_cart_%')).all()
    all_havale += Settings.query.filter(Settings.key.like('havale_team_%')).all()
    all_havale += Settings.query.filter(Settings.key.like('havale_hint_%')).all()
    transfers = []
    for s in all_havale:
        try:
            d = json.loads(s.value)
            d['key'] = s.key
            transfers.append(d)
        except Exception:
            continue
    transfers.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return render_template('admin/havale_transfers.html', transfers=transfers, active_page='orders')

@app.route('/admin/havale/confirm/<key>')
def admin_confirm_havale(key):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    setting = Settings.query.filter_by(key=key).first_or_404()
    try:
        data = json.loads(setting.value)
    except Exception:
        flash("Transfer verisi okunamadı.")
        return redirect(url_for('admin_havale_transfers'))
    t = data.get('type')
    if t == 'case':
        purchase = Purchase.query.get(data.get('purchase_id'))
        if purchase:
            purchase.is_paid = True
            db.session.delete(setting)
            db.session.commit()
            flash(f"✅ Onaylandı: {data.get('email')} — {data.get('title')}")
        else:
            flash("Purchase kaydı bulunamadı.")
    elif t == 'cart':
        cart = data.get('cart', [])
        user_id = data.get('user_id')
        for cid in cart:
            case_obj = Case.query.get(cid)
            if case_obj and user_id:
                existing = Purchase.query.filter_by(user_id=user_id, case_id=cid, is_paid=True).first()
                if not existing:
                    p = Purchase(user_id=user_id, case_id=cid, amount=case_obj.price, is_paid=True)
                    db.session.add(p)
        order_num = f"HVL{random.randint(100000, 999999)}"
        order = Order(order_number=order_num, status="Tamamlanmış",
                      total_price=data.get('amount', 0), item_count=len(cart), user_id=user_id)
        db.session.add(order)
        db.session.delete(setting)
        db.session.commit()
        flash(f"✅ Onaylandı: {data.get('email')} — {data.get('title')}")
    elif t == 'team':
        purchase = TeamPurchase.query.get(data.get('purchase_id'))
        if purchase:
            purchase.payment_status = 'completed'
            db.session.delete(setting)
            db.session.commit()
            flash(f"✅ Onaylandı: {data.get('email')} — {data.get('title')}")
        else:
            flash("Takım satın alım kaydı bulunamadı.")
    elif t == 'hint':
        hint_id = data.get('hint_id')
        user_id = data.get('user_id')
        hint = Hint.query.get(hint_id)
        user = User.query.get(user_id)
        if hint and user:
            hint.is_active = True
            db.session.delete(setting)
            db.session.commit()
            flash(f"✅ Onaylandı: İpucu #{hint_id} — {data.get('email')}")
        else:
            flash("İpucu veya kullanıcı bulunamadı.")
    else:
        flash("Bilinmeyen transfer türü.")
    return redirect(url_for('admin_havale_transfers'))

@app.route('/admin/havale/reject/<key>')
def admin_reject_havale(key):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    setting = Settings.query.filter_by(key=key).first_or_404()
    try:
        data = json.loads(setting.value)
    except Exception:
        data = {}
    if data.get('type') == 'case':
        purchase = Purchase.query.get(data.get('purchase_id'))
        if purchase and not purchase.is_paid:
            db.session.delete(purchase)
    elif data.get('type') == 'team':
        tp = TeamPurchase.query.get(data.get('purchase_id'))
        if tp and tp.payment_status == 'pending_havale':
            tp.payment_status = 'pending'
    db.session.delete(setting)
    db.session.commit()
    flash(f"❌ Reddedildi: {data.get('ref_code', '')} — {data.get('email', '')}")
    return redirect(url_for('admin_havale_transfers'))

@app.route('/payment/paynkolay/<case_id>', methods=['GET', 'POST'])
def payment_paynkolay(case_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    settings = get_payment_settings()
    if settings.get('paynkolay_enabled') != '1':
        flash("PaynKolay ödeme sistemi aktif değil.")
        return redirect(url_for('payment_select', case_id=case_id))
    case = Case.query.get_or_404(case_id)
    session['pending_case_id'] = case_id
    session['pending_total'] = float(case.price)
    return render_template('payment_paynkolay.html', case=case, cart_total=None, hint=None,
                           form_action=url_for('paynkolay_process_case', case_id=case_id))

@app.route('/payment/paynkolay/process/<case_id>', methods=['POST'])
def paynkolay_process_case(case_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    settings = get_payment_settings()
    if settings.get('paynkolay_enabled') != '1':
        flash("PaynKolay ödeme sistemi aktif değil.")
        return redirect(url_for('payment_select', case_id=case_id))
    case = Case.query.get_or_404(case_id)
    user = User.query.get(session['user_id'])
    session['pending_case_id'] = case_id
    session['pending_total'] = float(case.price)
    sx = settings.get('paynkolay_token', '')
    merchant_secret = settings.get('paynkolay_secret_key', '')
    rnd_num = random.randint(10000,99999)
    client_ref = f"GV{rnd_num}C{user.id}"
    success_url = url_for('paynkolay_success', _external=True)
    fail_url = url_for('paynkolay_fail', _external=True)
    amount = f"{case.price:.2f}"
    rnd = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    customer_key = ""
    hash_str = f"{sx}|{client_ref}|{amount}|{success_url}|{fail_url}|{rnd}|{customer_key}|{merchant_secret}"
    hash_val = base64.b64encode(hashlib.sha512(hash_str.encode('utf-8')).digest()).decode()
    card_holder_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if card_holder_ip and ',' in card_holder_ip:
        card_holder_ip = card_holder_ip.split(',')[0].strip()
    import json as json_lib
    pending_data = json_lib.dumps({'type': 'case', 'user_id': user.id, 'case_id': case_id})
    pending_setting = Settings.query.filter_by(key=f'paynkolay_pending_{client_ref}').first()
    if pending_setting:
        pending_setting.value = pending_data
    else:
        db.session.add(Settings(key=f'paynkolay_pending_{client_ref}', value=pending_data))
    db.session.commit()
    card_number = request.form.get('card_number', '').replace(' ', '')
    payload = {
        'sx': sx,
        'clientRefCode': client_ref,
        'successUrl': success_url,
        'failUrl': fail_url,
        'amount': amount,
        'currencyNumber': '949',
        'cardHolderName': request.form.get('card_holder', ''),
        'cardNumber': card_number,
        'month': request.form.get('expire_month', ''),
        'year': request.form.get('expire_year', ''),
        'cvv': request.form.get('cvv', ''),
        'transactionType': 'SALES',
        'installmentNo': '1',
        'use3D': 'true',
        'rnd': rnd,
        'hashDatav2': hash_val,
        'cardHolderIP': card_holder_ip,
        'environment': 'API'
    }
    try:
        api_url = 'https://paynkolay.nkolayislem.com.tr/Vpos/v1/Payment'
        resp = requests.post(api_url, data=payload)
        resp_text = resp.text
        try:
            resp_json = resp.json()
            bank_msg = resp_json.get('BANK_REQUEST_MESSAGE', '')
            if bank_msg:
                clean_html = bank_msg.replace('\\r', '').replace('\\n', '').replace('\r', '').replace('\n', '')
                return clean_html
        except:
            pass
        return resp_text
    except Exception as e:
        flash(f"PaynKolay ödeme hatası: {str(e)}")
        return redirect(url_for('payment_select', case_id=case_id))

@app.route('/payment/paynkolay-cart')
def paynkolay_cart():
    if 'user_id' not in session: return redirect(url_for('login'))
    settings = get_payment_settings()
    if settings.get('paynkolay_enabled') != '1':
        flash("PaynKolay ödeme sistemi aktif değil.")
        return redirect(url_for('checkout'))
    cart = session.get('pending_cart', [])
    total = session.get('pending_total', 0)
    if not cart:
        flash("Sepet boş.")
        return redirect(url_for('view_cart'))
    return render_template('payment_paynkolay.html', case=None, cart_total=total, hint=None,
                           form_action=url_for('paynkolay_process_cart'))

@app.route('/payment/paynkolay-cart/process', methods=['POST'])
def paynkolay_process_cart():
    if 'user_id' not in session: return redirect(url_for('login'))
    settings = get_payment_settings()
    if settings.get('paynkolay_enabled') != '1':
        flash("PaynKolay ödeme sistemi aktif değil.")
        return redirect(url_for('checkout'))
    cart = session.get('pending_cart', [])
    total = session.get('pending_total', 0)
    if not cart:
        flash("Sepet boş.")
        return redirect(url_for('view_cart'))
    user = User.query.get(session['user_id'])
    sx = settings.get('paynkolay_token', '')
    merchant_secret = settings.get('paynkolay_secret_key', '')
    rnd_num = random.randint(10000,99999)
    client_ref = f"GV{rnd_num}K{user.id}"
    success_url = url_for('paynkolay_success', _external=True)
    fail_url = url_for('paynkolay_fail', _external=True)
    amount = f"{total:.2f}"
    rnd = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    customer_key = ""
    hash_str = f"{sx}|{client_ref}|{amount}|{success_url}|{fail_url}|{rnd}|{customer_key}|{merchant_secret}"
    hash_val = base64.b64encode(hashlib.sha512(hash_str.encode('utf-8')).digest()).decode()
    card_holder_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if card_holder_ip and ',' in card_holder_ip:
        card_holder_ip = card_holder_ip.split(',')[0].strip()
    import json as json_lib
    pending_data = json_lib.dumps({'type': 'cart', 'user_id': user.id, 'cart': cart, 'total': total})
    pending_setting = Settings.query.filter_by(key=f'paynkolay_pending_{client_ref}').first()
    if pending_setting:
        pending_setting.value = pending_data
    else:
        db.session.add(Settings(key=f'paynkolay_pending_{client_ref}', value=pending_data))
    db.session.commit()
    card_number = request.form.get('card_number', '').replace(' ', '')
    payload = {
        'sx': sx,
        'clientRefCode': client_ref,
        'successUrl': success_url,
        'failUrl': fail_url,
        'amount': amount,
        'currencyNumber': '949',
        'cardHolderName': request.form.get('card_holder', ''),
        'cardNumber': card_number,
        'month': request.form.get('expire_month', ''),
        'year': request.form.get('expire_year', ''),
        'cvv': request.form.get('cvv', ''),
        'transactionType': 'SALES',
        'installmentNo': '1',
        'use3D': 'true',
        'rnd': rnd,
        'hashDatav2': hash_val,
        'cardHolderIP': card_holder_ip,
        'environment': 'API'
    }
    try:
        api_url = 'https://paynkolay.nkolayislem.com.tr/Vpos/v1/Payment'
        resp = requests.post(api_url, data=payload)
        resp_text = resp.text
        try:
            resp_json = resp.json()
            bank_msg = resp_json.get('BANK_REQUEST_MESSAGE', '')
            if bank_msg:
                clean_html = bank_msg.replace('\\r', '').replace('\\n', '').replace('\r', '').replace('\n', '')
                return clean_html
        except:
            pass
        return resp_text
    except Exception as e:
        flash(f"PaynKolay ödeme hatası: {str(e)}")
        return redirect(url_for('checkout'))

@app.route('/payment/paynkolay-hint/<int:hint_id>', methods=['GET', 'POST'])
def paynkolay_hint(hint_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    settings = get_payment_settings()
    if settings.get('paynkolay_enabled') != '1':
        flash("PaynKolay ödeme sistemi aktif değil.")
        hint = Hint.query.get_or_404(hint_id)
        return redirect(url_for('play_case', case_id=hint.case_id))
    hint = Hint.query.get_or_404(hint_id)
    session['pending_hint_id'] = hint_id
    return render_template('payment_paynkolay.html', case=None, cart_total=None, hint=hint,
                           form_action=url_for('paynkolay_process_hint', hint_id=hint_id))

@app.route('/payment/paynkolay-hint/<int:hint_id>/process', methods=['POST'])
def paynkolay_process_hint(hint_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    settings = get_payment_settings()
    hint = Hint.query.get_or_404(hint_id)
    if settings.get('paynkolay_enabled') != '1':
        flash("PaynKolay ödeme sistemi aktif değil.")
        return redirect(url_for('play_case', case_id=hint.case_id))
    user = User.query.get(session['user_id'])
    session['pending_hint_id'] = hint_id
    sx = settings.get('paynkolay_token', '')
    merchant_secret = settings.get('paynkolay_secret_key', '')
    rnd_num = random.randint(10000,99999)
    client_ref = f"GV{rnd_num}H{user.id}"
    success_url = url_for('paynkolay_success', _external=True)
    fail_url = url_for('paynkolay_fail', _external=True)
    amount = f"{hint.unlock_price:.2f}"
    rnd = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    customer_key = ""
    hash_str = f"{sx}|{client_ref}|{amount}|{success_url}|{fail_url}|{rnd}|{customer_key}|{merchant_secret}"
    hash_val = base64.b64encode(hashlib.sha512(hash_str.encode('utf-8')).digest()).decode()
    card_holder_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if card_holder_ip and ',' in card_holder_ip:
        card_holder_ip = card_holder_ip.split(',')[0].strip()
    import json as json_lib
    pending_data = json_lib.dumps({'type': 'hint', 'user_id': user.id, 'hint_id': hint_id, 'case_id': hint.case_id})
    pending_setting = Settings.query.filter_by(key=f'paynkolay_pending_{client_ref}').first()
    if pending_setting:
        pending_setting.value = pending_data
    else:
        db.session.add(Settings(key=f'paynkolay_pending_{client_ref}', value=pending_data))
    db.session.commit()
    card_number = request.form.get('card_number', '').replace(' ', '')
    payload = {
        'sx': sx,
        'clientRefCode': client_ref,
        'successUrl': success_url,
        'failUrl': fail_url,
        'amount': amount,
        'currencyNumber': '949',
        'cardHolderName': request.form.get('card_holder', ''),
        'cardNumber': card_number,
        'month': request.form.get('expire_month', ''),
        'year': request.form.get('expire_year', ''),
        'cvv': request.form.get('cvv', ''),
        'transactionType': 'SALES',
        'installmentNo': '1',
        'use3D': 'true',
        'rnd': rnd,
        'hashDatav2': hash_val,
        'cardHolderIP': card_holder_ip,
        'environment': 'API'
    }
    try:
        api_url = 'https://paynkolay.nkolayislem.com.tr/Vpos/v1/Payment'
        resp = requests.post(api_url, data=payload)
        resp_text = resp.text
        try:
            resp_json = resp.json()
            bank_msg = resp_json.get('BANK_REQUEST_MESSAGE', '')
            if bank_msg:
                clean_html = bank_msg.replace('\\r', '').replace('\\n', '').replace('\r', '').replace('\n', '')
                return clean_html
        except:
            pass
        return resp_text
    except Exception as e:
        flash(f"PaynKolay ödeme hatası: {str(e)}")
        return redirect(url_for('play_case', case_id=hint.case_id))

def verify_paynkolay_callback(data):
    """PaynKolay 3D dönüş (callback) sunucu taraflı doğrulaması.
    Başarı için: RESPONSE_CODE == 2, geçerli AUTH_CODE ve hashDataV2 imzasının
    (SHA512 + Base64) merchant secret ile yeniden hesaplanıp eşleşmesi gerekir."""
    settings = get_payment_settings()
    merchant_secret = settings.get('paynkolay_secret_key', '')
    response_code = str(data.get('RESPONSE_CODE', '')).strip()
    auth_code = str(data.get('AUTH_CODE', '')).strip()
    if response_code != '2' or not auth_code or auth_code == '0':
        return False, "Ödeme sağlayıcı onayı doğrulanamadı (RESPONSE_CODE/AUTH_CODE)."
    received_hash = data.get('hashDataV2') or data.get('hashDatav2') or data.get('HASHDATAV2') or ''
    if not merchant_secret or not received_hash:
        return False, "Ödeme doğrulama bilgileri eksik (hashDataV2)."
    hash_str = "|".join([
        str(data.get('MERCHANT_NO', '')),
        str(data.get('REFERENCE_CODE', '')),
        auth_code,
        response_code,
        str(data.get('USE_3D', '')),
        str(data.get('RND', '')),
        str(data.get('INSTALLMENT', '')),
        str(data.get('AUTHORIZATION_AMOUNT', '')),
        str(data.get('CURRENCY_CODE', '')),
        merchant_secret,
    ])
    calculated = base64.b64encode(hashlib.sha512(hash_str.encode('utf-8')).digest()).decode()
    if not hmac.compare_digest(calculated, received_hash):
        return False, "Ödeme imza doğrulaması başarısız (hashDataV2 uyuşmuyor)."
    return True, ""

@app.route('/payment/paynkolay/success', methods=['GET', 'POST'])
def paynkolay_success():
    data = request.form if request.method == 'POST' else request.args
    client_ref = data.get('clientRefCode', '') or data.get('CLIENT_REFERENCE_CODE', '')
    verified, verify_msg = verify_paynkolay_callback(data)
    if not verified:
        app.logger.warning(f"PaynKolay callback dogrulama basarisiz (clientRef={client_ref}): {verify_msg}")
        flash(f"Ödeme doğrulanamadı: {verify_msg} Kartınızdan çekim yapıldıysa lütfen bizimle iletişime geçin.")
        return redirect(url_for('index'))
    import json as json_lib
    try:
        pending_setting = Settings.query.filter_by(key=f'paynkolay_pending_{client_ref}').first() if client_ref else None
        if pending_setting:
            pending_info = json_lib.loads(pending_setting.value)
            db.session.delete(pending_setting)
            db.session.commit()
            ptype = pending_info.get('type')
            if ptype == 'team':
                purchase_id = pending_info.get('purchase_id')
                team_purchase = TeamPurchase.query.get(purchase_id)
                if team_purchase:
                    team_purchase.payment_status = 'completed'
                    db.session.commit()
                    record_partner_sale_for_team(team_purchase)
                    record_dealer_sale_for_team(team_purchase)
                    flash("Ödeme başarılı! Takım erişim linkleri aktif edildi.")
                    return redirect(url_for('team_purchase_payment', purchase_id=purchase_id))
                flash("Ödeme başarılı ancak takım bilgisi bulunamadı.")
                return redirect(url_for('index'))
            uid = pending_info.get('user_id')
            user = User.query.get(uid)
            if not user:
                flash("Ödeme başarılı ancak kullanıcı bulunamadı.")
                return redirect(url_for('index'))
            if ptype == 'hint':
                hint_id = pending_info.get('hint_id')
                hint = Hint.query.get(hint_id)
                if hint:
                    unlocked = (user.unlocked_hints or '').split(',')
                    if str(hint_id) not in unlocked:
                        user.unlocked_hints = f"{user.unlocked_hints},{hint_id}" if user.unlocked_hints else str(hint_id)
                        db.session.commit()
                    flash("Ödeme başarılı! İpucu açıldı.")
                    return redirect(url_for('play_case', case_id=hint.case_id))
            elif ptype == 'cart':
                cart = pending_info.get('cart', [])
                cart_total = pending_info.get('total', 0)
                cart_cases = [c for c in (Case.query.get(cid) for cid in cart) if c]
                full_total = sum(float(c.price or 0) for c in cart_cases)
                paid_total = float(cart_total or 0) or full_total
                ratio = (paid_total / full_total) if full_total > 0 else 1.0
                for cid in cart:
                    if cid not in (user.unlocked_cases or '').split(','):
                        user.unlocked_cases = f"{user.unlocked_cases},{cid}" if user.unlocked_cases else cid
                    case = Case.query.get(cid)
                    if case:
                        paid_amount = round(float(case.price or 0) * ratio, 2)
                        existing_purchase = Purchase.query.filter_by(user_id=user.id, case_id=cid).first()
                        if not existing_purchase:
                            purchase = Purchase(user_id=user.id, case_id=cid, amount=paid_amount, is_paid=True, created_at=datetime.utcnow())
                            db.session.add(purchase)
                        record_partner_sale(cid, paid_amount, user.id)
                        record_dealer_sale(cid, paid_amount, user.id)
                db.session.commit()
                session.pop('cart', None)
                session.pop('applied_discount', None)
                session.pop('dealer_ref', None)
                session.pop('pending_total', None)
                flash("Ödeme başarılı! Vakalar açıldı.")
                return redirect(url_for('active_cases'))
            elif ptype == 'case':
                case_id = pending_info.get('case_id')
                if case_id not in (user.unlocked_cases or '').split(','):
                    user.unlocked_cases = f"{user.unlocked_cases},{case_id}" if user.unlocked_cases else case_id
                case = Case.query.get(case_id)
                if case:
                    existing_purchase = Purchase.query.filter_by(user_id=user.id, case_id=case_id).first()
                    if not existing_purchase:
                        purchase = Purchase(user_id=user.id, case_id=case_id, amount=case.price, is_paid=True, created_at=datetime.utcnow())
                        db.session.add(purchase)
                    record_partner_sale(case_id, case.price, user.id)
                    record_dealer_sale(case_id, case.price, user.id)
                db.session.commit()
                session.pop('applied_discount', None)
                session.pop('dealer_ref', None)
                session.pop('pending_total', None)
                flash("Ödeme başarılı! Vaka açıldı.")
                return redirect(url_for('active_cases'))
        else:
            # Bekleyen ödeme kaydı yoksa (replay / geçersiz referans) erişim AÇILMAZ.
            app.logger.warning(f"PaynKolay callback: bekleyen kayit bulunamadi (clientRef={client_ref}) — erisim acilmadi.")
            flash("Ödeme kaydı bulunamadı. Ödeme yaptıysanız lütfen bizimle iletişime geçin.")
            return redirect(url_for('index'))
    except Exception as e:
        flash(f"Ödeme sonrası işlem hatası: {str(e)}")
    return redirect(url_for('active_cases'))

@app.route('/payment/paynkolay/fail', methods=['GET', 'POST'])
def paynkolay_fail():
    data = request.form if request.method == 'POST' else request.args
    response_msg = data.get('response', data.get('ERROR_MESSAGE', 'Bilinmeyen hata'))
    client_ref = data.get('clientRefCode', '')
    import json as json_lib
    if client_ref:
        pending_setting = Settings.query.filter_by(key=f'paynkolay_pending_{client_ref}').first()
        if pending_setting:
            try:
                pending_info = json_lib.loads(pending_setting.value)
                db.session.delete(pending_setting)
                db.session.commit()
                ptype = pending_info.get('type')
                if ptype == 'hint':
                    hint = Hint.query.get(pending_info.get('hint_id'))
                    if hint:
                        flash(f"PaynKolay ödeme başarısız: {response_msg}")
                        return redirect(url_for('play_case', case_id=hint.case_id))
                elif ptype == 'case':
                    flash(f"PaynKolay ödeme başarısız: {response_msg}")
                    return redirect(url_for('case_detail', case_id=pending_info.get('case_id')))
                elif ptype == 'team':
                    flash(f"PaynKolay ödeme başarısız: {response_msg}")
                    return redirect(url_for('payment_team_select', purchase_id=pending_info.get('purchase_id')))
            except:
                pass
    case_id = session.get('pending_case_id')
    hint_id = session.get('pending_hint_id')
    flash(f"PaynKolay ödeme başarısız: {response_msg}")
    if hint_id:
        hint = Hint.query.get(hint_id)
        if hint:
            return redirect(url_for('play_case', case_id=hint.case_id))
    if case_id:
        return redirect(url_for('payment_select', case_id=case_id))
    return redirect(url_for('index'))

@app.route('/payment/iyzico-cart')
def payment_iyzico_cart():
    if 'user_id' not in session: return redirect(url_for('login'))
    settings = get_payment_settings()
    if settings.get('iyzico_enabled') != '1':
        flash("iyzico odeme sistemi aktif degil."); return redirect(url_for('checkout'))
    
    cart = session.get('pending_cart', [])
    total = session.get('pending_total', 0)
    if not cart:
        flash("Sepet bos."); return redirect(url_for('view_cart'))
    
    user = User.query.get(session['user_id'])
    api_key = settings.get('iyzico_api_key', '')
    secret_key = settings.get('iyzico_secret_key', '')
    base_url = settings.get('iyzico_base_url', 'https://sandbox-api.iyzipay.com')
    
    conversation_id = f"CART{user.id}{random.randint(10000,99999)}"
    
    basket_items = []
    for case_id in cart:
        case = Case.query.get(case_id)
        if case:
            basket_items.append({
                "id": f"BI{case.id}",
                "name": case.title,
                "category1": "Oyun",
                "itemType": "VIRTUAL",
                "price": str(case.price)
            })
    
    request_data = {
        "locale": "tr",
        "conversationId": conversation_id,
        "price": str(total),
        "paidPrice": str(total),
        "currency": "TRY",
        "basketId": f"BCART{user.id}",
        "paymentGroup": "PRODUCT",
        "callbackUrl": url_for('iyzico_cart_callback', _external=True),
        "enabledInstallments": [1, 2, 3, 6, 9],
        "buyer": {
            "id": f"BY{user.id}",
            "name": user.first_name or user.username,
            "surname": user.last_name or ".",
            "gsmNumber": "+905000000000",
            "email": user.email,
            "identityNumber": "74300864791",
            "registrationAddress": user.billing_address or "Adres belirtilmemis",
            "ip": request.remote_addr,
            "city": "Istanbul",
            "country": "Turkey"
        },
        "shippingAddress": {
            "contactName": user.first_name or user.username,
            "city": "Istanbul",
            "country": "Turkey",
            "address": user.billing_address or "Adres"
        },
        "billingAddress": {
            "contactName": user.first_name or user.username,
            "city": "Istanbul",
            "country": "Turkey",
            "address": user.billing_address or "Adres"
        },
        "basketItems": basket_items
    }
    
    random_string = base64.b64encode(os.urandom(8)).decode()
    string_to_hash = random_string + secret_key
    hash_string = hashlib.sha1(string_to_hash.encode()).hexdigest()
    authorization = f"IYZWS {api_key}:{hash_string}"
    
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': authorization,
        'x-iyzi-rnd': random_string
    }
    
    try:
        response = requests.post(f"{base_url}/payment/iyzipos/checkoutform/initialize/auth/ecom",
                                json=request_data, headers=headers)
        result = response.json()
        
        if result.get('status') == 'success':
            session['pending_iyzico_token'] = result.get('token')
            return render_template('payment_iyzico.html', checkout_form=result.get('checkoutFormContent'), case=None, cart_total=total)
        else:
            flash(f"iyzico hatasi: {result.get('errorMessage', 'Bilinmeyen hata')}")
            return redirect(url_for('checkout'))
    except Exception as e:
        flash(f"Odeme sistemi hatasi: {str(e)}")
        return redirect(url_for('checkout'))

@app.route('/payment/cart-success')
def payment_cart_success():
    cart = session.pop('pending_cart', [])
    if cart and 'user_id' in session:
        user = User.query.get(session['user_id'])
        for case_id in cart:
            if case_id not in (user.unlocked_cases or '').split(','):
                user.unlocked_cases = f"{user.unlocked_cases},{case_id}" if user.unlocked_cases else case_id
            case = Case.query.get(case_id)
            if case:
                record_partner_sale(case_id, case.price, user.id)
                record_dealer_sale(case_id, case.price, user.id)
        db.session.commit()
        session.pop('cart', None)
    session.pop('applied_discount', None)
    session.pop('dealer_ref', None)
    flash("Odeme basarili! Vakalar asildi.")
    return redirect(url_for('active_cases'))

@app.route('/iyzico/cart-callback', methods=['POST'])
def iyzico_cart_callback():
    token = request.form.get('token')
    if not token:
        flash("Odeme dogrulanamadi.")
        return redirect(url_for('payment_fail'))
    
    settings = get_payment_settings()
    api_key = settings.get('iyzico_api_key', '')
    secret_key = settings.get('iyzico_secret_key', '')
    base_url = settings.get('iyzico_base_url', 'https://sandbox-api.iyzipay.com')
    
    random_string = base64.b64encode(os.urandom(8)).decode()
    string_to_hash = random_string + secret_key
    hash_string = hashlib.sha1(string_to_hash.encode()).hexdigest()
    authorization = f"IYZWS {api_key}:{hash_string}"
    
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': authorization,
        'x-iyzi-rnd': random_string
    }
    
    try:
        response = requests.post(f"{base_url}/payment/iyzipos/checkoutform/auth/ecom/detail",
                                json={"locale": "tr", "token": token}, headers=headers)
        result = response.json()
        
        if result.get('paymentStatus') == 'SUCCESS':
            return redirect(url_for('payment_cart_success'))
        else:
            flash("Odeme basarisiz.")
            return redirect(url_for('payment_fail'))
    except Exception as e:
        flash(f"Odeme dogrulama hatasi: {str(e)}")
        return redirect(url_for('payment_fail'))

@app.route('/payment/iyzico/<case_id>', methods=['POST'])
def payment_iyzico(case_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    settings = get_payment_settings()
    if settings.get('iyzico_enabled') != '1':
        flash("iyzico ödeme sistemi aktif değil."); return redirect(url_for('index'))
    
    case = Case.query.get_or_404(case_id)
    user = User.query.get(session['user_id'])
    
    api_key = settings.get('iyzico_api_key', '')
    secret_key = settings.get('iyzico_secret_key', '')
    base_url = settings.get('iyzico_base_url', 'https://sandbox-api.iyzipay.com')
    
    conversation_id = f"GV{user.id}{case_id}{random.randint(1000,9999)}"
    
    request_data = {
        "locale": "tr",
        "conversationId": conversation_id,
        "price": str(case.price),
        "paidPrice": str(case.price),
        "currency": "TRY",
        "basketId": f"B{case_id}",
        "paymentGroup": "PRODUCT",
        "callbackUrl": url_for('iyzico_callback', _external=True),
        "enabledInstallments": [1, 2, 3, 6, 9],
        "buyer": {
            "id": f"BY{user.id}",
            "name": user.first_name or user.username,
            "surname": user.last_name or ".",
            "gsmNumber": "+905000000000",
            "email": user.email,
            "identityNumber": "74300864791",
            "registrationAddress": user.billing_address or "Adres belirtilmemiş",
            "ip": request.remote_addr,
            "city": "Istanbul",
            "country": "Turkey"
        },
        "shippingAddress": {
            "contactName": user.first_name or user.username,
            "city": "Istanbul",
            "country": "Turkey",
            "address": user.billing_address or "Adres belirtilmemiş"
        },
        "billingAddress": {
            "contactName": user.first_name or user.username,
            "city": "Istanbul",
            "country": "Turkey",
            "address": user.billing_address or "Adres belirtilmemiş"
        },
        "basketItems": [{
            "id": case_id,
            "name": case.title,
            "category1": "Dijital Urun",
            "itemType": "VIRTUAL",
            "price": str(case.price)
        }]
    }
    
    random_string = base64.b64encode(os.urandom(8)).decode()
    string_to_hash = random_string + secret_key
    hash_string = hashlib.sha1(string_to_hash.encode()).hexdigest()
    authorization = f"IYZWS {api_key}:{hash_string}"
    
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': authorization,
        'x-iyzi-rnd': random_string
    }
    
    session['pending_case_id'] = case_id
    session['pending_conversation_id'] = conversation_id
    
    try:
        response = requests.post(f"{base_url}/payment/iyzipos/checkoutform/initialize/auth/ecom", 
                                json=request_data, headers=headers)
        result = response.json()
        if result.get('status') == 'success':
            return render_template('payment_iyzico.html', checkout_form_content=result.get('checkoutFormContent'), case=case)
        else:
            flash(f"iyzico hatası: {result.get('errorMessage', 'Bilinmeyen hata')}")
            return redirect(url_for('payment_select', case_id=case_id))
    except Exception as e:
        flash(f"Ödeme sistemi hatası: {str(e)}")
        return redirect(url_for('payment_select', case_id=case_id))

@app.route('/payment/iyzico/callback', methods=['POST'])
def iyzico_callback():
    token = request.form.get('token')
    if not token:
        flash("Ödeme doğrulanamadı."); return redirect(url_for('index'))
    
    settings = get_payment_settings()
    api_key = settings.get('iyzico_api_key', '')
    secret_key = settings.get('iyzico_secret_key', '')
    base_url = settings.get('iyzico_base_url', 'https://sandbox-api.iyzipay.com')
    
    random_string = base64.b64encode(os.urandom(8)).decode()
    string_to_hash = random_string + secret_key
    hash_string = hashlib.sha1(string_to_hash.encode()).hexdigest()
    authorization = f"IYZWS {api_key}:{hash_string}"
    
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': authorization,
        'x-iyzi-rnd': random_string
    }
    
    try:
        response = requests.post(f"{base_url}/payment/iyzipos/checkoutform/auth/ecom/detail",
                                json={"locale": "tr", "token": token}, headers=headers)
        result = response.json()
        
        if result.get('paymentStatus') == 'SUCCESS':
            case_id = session.pop('pending_case_id', None)
            if case_id and 'user_id' in session:
                user = User.query.get(session['user_id'])
                if case_id not in (user.unlocked_cases or '').split(','):
                    user.unlocked_cases = f"{user.unlocked_cases},{case_id}" if user.unlocked_cases else case_id
                    db.session.commit()
            flash("Ödeme başarılı! Vaka açıldı.")
            return redirect(url_for('active_cases'))
        else:
            flash("Ödeme başarısız.")
            return redirect(url_for('payment_fail'))
    except Exception as e:
        flash(f"Ödeme doğrulama hatası: {str(e)}")
        return redirect(url_for('payment_fail'))

@app.route('/payment/success')
def payment_success():
    case_id = session.pop('pending_case_id', None)
    if case_id and 'user_id' in session:
        user = User.query.get(session['user_id'])
        case = Case.query.get(case_id)
        if case_id not in (user.unlocked_cases or '').split(','):
            user.unlocked_cases = f"{user.unlocked_cases},{case_id}" if user.unlocked_cases else case_id
            db.session.commit()
        if case:
            record_partner_sale(case_id, case.price, user.id)
            record_dealer_sale(case_id, case.price, user.id)
    session.pop('applied_discount', None)
    session.pop('dealer_ref', None)
    flash("Ödeme başarılı! Vaka açıldı.")
    return redirect(url_for('active_cases'))

@app.route('/payment/fail')
def payment_fail():
    session.pop('pending_case_id', None)
    flash("Ödeme başarısız oldu. Lütfen tekrar deneyin.")
    return redirect(url_for('index'))

# --- PUAN SİSTEMİ API ---
@app.route('/api/game-progress/<case_id>')
def get_game_progress(case_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Giriş yapmalısınız'}), 401
    
    user_id = session['user_id']
    progress = GameProgress.query.filter_by(user_id=user_id, case_id=case_id).first()
    case = Case.query.get(case_id)
    
    if not case:
        return jsonify({'error': 'Vaka bulunamadı'}), 404
    
    base_points = DIFFICULTY_POINTS.get(case.difficulty, 200)
    
    if not progress:
        return jsonify({
            'attempts_used': 0,
            'attempts_remaining': 2,
            'hints_used': 0,
            'is_solved': False,
            'is_failed': False,
            'can_play': True,
            'base_points': base_points,
            'wait_until': None
        })
    
    # Bekleme süresi kontrolü
    wait_until = None
    can_play = True
    
    # Çözülmüşse resetle ve tekrar oynamaya izin ver
    if progress.is_solved:
        progress.attempts_used = 0
        progress.hints_used = 0
        progress.is_solved = False
        progress.is_failed = False
        progress.points_earned = 0
        db.session.commit()
    
    if progress.is_failed and progress.last_attempt_time:
        # 3 saat bekleme (başarısız sonrası)
        wait_time = progress.last_attempt_time + timedelta(hours=3)
        if datetime.utcnow() < wait_time:
            can_play = False
            wait_until = wait_time.isoformat()
        else:
            # 3 saat geçti, resetle
            progress.attempts_used = 0
            progress.is_failed = False
            progress.hints_used = 0
            db.session.commit()
    
    return jsonify({
        'attempts_used': progress.attempts_used,
        'attempts_remaining': max(0, 2 - progress.attempts_used),
        'hints_used': progress.hints_used,
        'is_solved': progress.is_solved,
        'is_failed': progress.is_failed,
        'can_play': can_play,
        'base_points': base_points,
        'points_earned': progress.points_earned,
        'wait_until': wait_until
    })

@app.route('/api/submit-guess', methods=['POST'])
def submit_guess():
    if 'user_id' not in session:
        return jsonify({'error': 'Giriş yapmalısınız'}), 401
    
    data = request.get_json()
    case_id = data.get('case_id')
    suspect_id = data.get('suspect_id')
    elapsed_seconds = data.get('elapsed_seconds')
    
    if not case_id or not suspect_id:
        return jsonify({'error': 'Eksik bilgi'}), 400
    
    user_id = session['user_id']
    user = User.query.get(user_id)
    case = Case.query.get(case_id)
    suspect = Suspect.query.get(suspect_id)
    
    if not case or not suspect:
        return jsonify({'error': 'Vaka veya şüpheli bulunamadı'}), 404
    
    # Mevcut ilerlemeyi al veya oluştur
    progress = GameProgress.query.filter_by(user_id=user_id, case_id=case_id).first()
    if not progress:
        progress = GameProgress(user_id=user_id, case_id=case_id, attempts_used=0, hints_used=0)
        db.session.add(progress)
    
    # None değerleri 0 yap
    if progress.attempts_used is None:
        progress.attempts_used = 0
    if progress.hints_used is None:
        progress.hints_used = 0
    
    # Zaten çözülmüş mü? - Tekrar oynamaya izin ver
    if progress.is_solved:
        # Resetle ve tekrar oynamasına izin ver
        progress.attempts_used = 0
        progress.hints_used = 0
        progress.is_solved = False
        progress.is_failed = False
        progress.points_earned = 0
    
    # Başarısız bekleme kontrolü
    if progress.is_failed and progress.last_attempt_time:
        wait_time = progress.last_attempt_time + timedelta(hours=3)
        if datetime.utcnow() < wait_time:
            return jsonify({
                'success': False,
                'message': '3 saat sonra tekrar deneyin.',
                'wait_until': wait_time.isoformat()
            })
        else:
            # 3 saat geçti, resetle
            progress.attempts_used = 0
            progress.is_failed = False
            progress.hints_used = 0
    
    # Hak kontrolü
    if progress.attempts_used >= 2:
        return jsonify({
            'success': False,
            'message': 'Tahmin hakkınız kalmadı.',
            'attempts_remaining': 0
        })
    
    # Tahmin sayısını artır
    progress.attempts_used += 1
    progress.last_attempt_time = datetime.utcnow()
    
    # Doğru mu?
    if suspect.is_culprit:
        # Puan hesapla
        base_points = DIFFICULTY_POINTS.get(case.difficulty, 200)
        final_points = base_points
        
        # İpucu kesintisi (%3 her ipucu için)
        hint_penalty = progress.hints_used * 0.03
        final_points -= base_points * hint_penalty
        
        # 2. tahminden bilme kesintisi (%25)
        if progress.attempts_used == 2:
            final_points -= base_points * 0.25
        
        final_points = max(0, round(final_points, 1))
        progress.points_earned = final_points
        progress.is_solved = True
        if elapsed_seconds is not None:
            progress.play_time_seconds = int(elapsed_seconds)
        
        # Kullanıcı toplam puanına ekle
        user.score = (user.score or 0) + final_points
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'correct': True,
            'message': 'Tebrikler! Suçluyu buldunuz!',
            'points_earned': final_points,
            'base_points': base_points,
            'hints_used': progress.hints_used,
            'attempt_number': progress.attempts_used
        })
    else:
        # Yanlış tahmin
        attempts_remaining = 2 - progress.attempts_used
        
        if attempts_remaining > 0:
            db.session.commit()
            return jsonify({
                'success': True,
                'correct': False,
                'message': f'Yanlış tahmin! {attempts_remaining} hakkınız kaldı.',
                'attempts_remaining': attempts_remaining
            })
        else:
            # 2 hak da bitti - %50 puan kesintisi
            base_points = DIFFICULTY_POINTS.get(case.difficulty, 200)
            penalty_points = base_points * 0.50
            
            progress.is_failed = True
            progress.points_earned = -penalty_points
            
            # Kullanıcı puanından düş
            user.score = max(0, (user.score or 0) - penalty_points)
            
            db.session.commit()
            
            wait_time = datetime.utcnow() + timedelta(hours=3)
            return jsonify({
                'success': True,
                'correct': False,
                'message': '2 hakkınızı da kullandınız. 3 saat sonra tekrar deneyin.',
                'attempts_remaining': 0,
                'penalty_points': penalty_points,
                'wait_until': wait_time.isoformat()
            })

@app.route('/api/submit-text-report', methods=['POST'])
def submit_text_report():
    if 'user_id' not in session:
        return jsonify({'error': 'Giriş yapmalısınız'}), 401
    
    data = request.get_json()
    case_id = data.get('case_id')
    culprit_text = data.get('culprit_text', '').strip().lower()
    explanation_text = data.get('explanation_text', '').strip().lower()
    elapsed_seconds = data.get('elapsed_seconds')
    
    if not case_id or not culprit_text:
        return jsonify({'error': 'Suçlu adı zorunludur'}), 400
    
    user_id = session['user_id']
    user = User.query.get(user_id)
    case = Case.query.get(case_id)
    
    if not case:
        return jsonify({'error': 'Vaka bulunamadı'}), 404
    
    # Mevcut ilerlemeyi al veya oluştur
    progress = GameProgress.query.filter_by(user_id=user_id, case_id=case_id).first()
    if not progress:
        progress = GameProgress(user_id=user_id, case_id=case_id, attempts_used=0, hints_used=0)
        db.session.add(progress)
    
    if progress.attempts_used is None:
        progress.attempts_used = 0
    if progress.hints_used is None:
        progress.hints_used = 0
    
    # Zaten çözülmüş mü?
    if progress.is_solved:
        progress.attempts_used = 0
        progress.hints_used = 0
        progress.is_solved = False
        progress.is_failed = False
        progress.points_earned = 0
    
    # Başarısız bekleme kontrolü
    if progress.is_failed and progress.last_attempt_time:
        wait_time = progress.last_attempt_time + timedelta(hours=3)
        if datetime.utcnow() < wait_time:
            return jsonify({
                'success': False,
                'message': '3 saat sonra tekrar deneyin.',
                'wait_until': wait_time.isoformat()
            })
        else:
            progress.attempts_used = 0
            progress.is_failed = False
            progress.hints_used = 0
    
    if progress.attempts_used >= 2:
        return jsonify({
            'success': False,
            'message': 'Tahmin hakkınız kalmadı.',
            'attempts_remaining': 0
        })
    
    progress.attempts_used += 1
    progress.last_attempt_time = datetime.utcnow()
    
    # Anahtar kelime kontrolü
    culprit_keywords = [k.strip().lower() for k in (case.culprit_keywords or '').split(',') if k.strip()]
    explanation_keywords = [k.strip().lower() for k in (case.explanation_keywords or '').split(',') if k.strip()]
    
    # Suçlu anahtar kelimesi kontrolü - en az bir eşleşme olmalı
    culprit_match = False
    for kw in culprit_keywords:
        if kw in culprit_text:
            culprit_match = True
            break
    
    # Açıklama anahtar kelimeleri kontrolü (opsiyonel - varsa kontrol et)
    explanation_match = True
    if explanation_keywords:
        explanation_match = False
        for kw in explanation_keywords:
            if kw in explanation_text:
                explanation_match = True
                break
    
    # Her iki kontrol de geçmeli
    is_correct = culprit_match and explanation_match
    
    if is_correct:
        base_points = DIFFICULTY_POINTS.get(case.difficulty, 200)
        final_points = base_points
        
        hint_penalty = progress.hints_used * 0.03
        final_points -= base_points * hint_penalty
        
        if progress.attempts_used == 2:
            final_points -= base_points * 0.25
        
        final_points = max(0, round(final_points, 1))
        progress.points_earned = final_points
        progress.is_solved = True
        if elapsed_seconds is not None:
            progress.play_time_seconds = int(elapsed_seconds)
        
        user.score = (user.score or 0) + final_points
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'correct': True,
            'message': 'Tebrikler! Davayı çözdünüz!',
            'points_earned': final_points,
            'base_points': base_points,
            'hints_used': progress.hints_used,
            'attempt_number': progress.attempts_used
        })
    else:
        attempts_remaining = 2 - progress.attempts_used
        
        if attempts_remaining > 0:
            db.session.commit()
            feedback = 'Yanlış tahmin!'
            if not culprit_match:
                feedback += ' Suçlu adını kontrol edin.'
            elif not explanation_match:
                feedback += ' Açıklamanızı geliştirin.'
            
            return jsonify({
                'success': True,
                'correct': False,
                'message': f'{feedback} {attempts_remaining} hakkınız kaldı.',
                'attempts_remaining': attempts_remaining
            })
        else:
            base_points = DIFFICULTY_POINTS.get(case.difficulty, 200)
            penalty_points = base_points * 0.50
            
            progress.is_failed = True
            progress.points_earned = -penalty_points
            
            user.score = max(0, (user.score or 0) - penalty_points)
            
            db.session.commit()
            
            wait_time = datetime.utcnow() + timedelta(hours=3)
            return jsonify({
                'success': True,
                'correct': False,
                'message': '2 hakkınızı da kullandınız. 3 saat sonra tekrar deneyin.',
                'attempts_remaining': 0,
                'penalty_points': penalty_points,
                'wait_until': wait_time.isoformat()
            })

@app.route('/api/use-hint', methods=['POST'])
def use_hint():
    if 'user_id' not in session:
        return jsonify({'error': 'Giriş yapmalısınız'}), 401
    
    data = request.get_json()
    case_id = data.get('case_id')
    hint_id = data.get('hint_id')
    
    if not case_id:
        return jsonify({'error': 'Vaka ID gerekli'}), 400
    
    user_id = session['user_id']
    
    # Mevcut ilerlemeyi al veya oluştur
    progress = GameProgress.query.filter_by(user_id=user_id, case_id=case_id).first()
    if not progress:
        progress = GameProgress(user_id=user_id, case_id=case_id)
        db.session.add(progress)
    
    # Zaten çözülmüşse ipucu kullanılamaz
    if progress.is_solved:
        return jsonify({'error': 'Vaka zaten çözülmüş'}), 400
    
    progress.hints_used += 1
    db.session.commit()
    
    case = Case.query.get(case_id)
    base_points = DIFFICULTY_POINTS.get(case.difficulty, 200)
    penalty_per_hint = base_points * 0.03
    
    return jsonify({
        'success': True,
        'hints_used': progress.hints_used,
        'penalty_per_hint': penalty_per_hint,
        'total_hint_penalty': progress.hints_used * penalty_per_hint
    })

# --- ADMIN: ERİŞİM KODLARI YÖNETİMİ ---
import random
import string

def generate_access_code():
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=8))

@app.route('/admin/access-codes')
def admin_access_codes():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    codes = AccessCode.query.order_by(AccessCode.created_at.desc()).all()
    cases = Case.query.filter_by(is_active=True).all()
    return render_template('admin/access_codes.html', codes=codes, cases=cases, active_page='access_codes')

@app.route('/admin/access-codes/generate', methods=['POST'])
def admin_generate_codes():
    if session.get('username') != 'admin': return redirect(url_for('index'))
    case_id = request.form.get('case_id')
    count = int(request.form.get('count', 1))
    platform = request.form.get('platform', 'Trendyol')
    sale_price = float(request.form.get('sale_price', 0) or 0)
    
    if not case_id:
        flash('Dava seçmelisiniz.')
        return redirect(url_for('admin_access_codes'))
    
    generated = []
    for _ in range(min(count, 100)):
        code = generate_access_code()
        while AccessCode.query.filter_by(code=code).first():
            code = generate_access_code()
        new_code = AccessCode(code=code, case_id=case_id, platform=platform, sale_price=sale_price)
        db.session.add(new_code)
        generated.append(code)
    
    db.session.commit()
    flash(f'{len(generated)} adet kod oluşturuldu.')
    return redirect(url_for('admin_access_codes'))

@app.route('/admin/access-codes/delete/<int:code_id>')
def admin_delete_access_code(code_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    code = AccessCode.query.get_or_404(code_id)
    db.session.delete(code)
    db.session.commit()
    flash('Kod silindi.')
    return redirect(url_for('admin_access_codes'))

# --- SİPARİŞ DÜZENLEME VE SİLME ---
@app.route('/admin/purchase/<int:purchase_id>/edit', methods=['GET', 'POST'])
def admin_edit_purchase(purchase_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    purchase = Purchase.query.get_or_404(purchase_id)
    cases = Case.query.filter_by(is_active=True).all()
    
    if request.method == 'POST':
        purchase.amount = float(request.form.get('amount', purchase.amount) or 0)
        purchase.is_paid = request.form.get('is_paid') == '1'
        db.session.commit()
        flash('Satış güncellendi.')
        return redirect(url_for('admin_orders', tab='individual'))
    
    return render_template('admin/edit_purchase.html', purchase=purchase, cases=cases, active_page='orders')

@app.route('/admin/purchase/<int:purchase_id>/delete')
def admin_delete_purchase(purchase_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    purchase = Purchase.query.get_or_404(purchase_id)
    
    try:
        GameProgress.query.filter_by(user_id=purchase.user_id, case_id=purchase.case_id).delete()
        db.session.delete(purchase)
        db.session.commit()
        flash('Satış silindi.')
    except Exception as e:
        db.session.rollback()
        flash(f'Silme hatası: {str(e)}')
    return redirect(url_for('admin_orders', tab='individual'))

@app.route('/admin/team-purchase/<int:purchase_id>/edit', methods=['GET', 'POST'])
def admin_edit_team_purchase(purchase_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    tp = TeamPurchase.query.get_or_404(purchase_id)
    cases = Case.query.filter_by(is_active=True).all()
    
    if request.method == 'POST':
        tp.total_amount = float(request.form.get('amount', tp.total_amount))
        tp.payment_status = request.form.get('payment_status', tp.payment_status)
        db.session.commit()
        flash('Takım satışı güncellendi.')
        return redirect(url_for('admin_orders', tab='team'))
    
    return render_template('admin/edit_team_purchase.html', tp=tp, cases=cases, active_page='orders')

@app.route('/admin/team-purchase/<int:purchase_id>/delete')
def admin_delete_team_purchase(purchase_id):
    if session.get('username') != 'admin': return redirect(url_for('index'))
    tp = TeamPurchase.query.get_or_404(purchase_id)
    
    try:
        TeamMessage.query.filter_by(team_purchase_id=tp.id).delete()
        TeamMember.query.filter_by(team_purchase_id=tp.id).delete()
        db.session.delete(tp)
        db.session.commit()
        flash('Takım satışı ve tüm üyeleri silindi.')
    except Exception as e:
        db.session.rollback()
        flash(f'Silme hatası: {str(e)}')
    return redirect(url_for('admin_orders', tab='team'))

# --- KOD GİRİŞ SAYFASI ---
# Bayilerin ornek dava denemesi icin tek kullanimlik OLMAYAN demo kodu
DEMO_ACCESS_CODE = 'GV-ORNEKKF-099'
DEMO_ACCESS_CASE_ID = 'Kusursuz-Vakum'


@app.route('/redeem', methods=['GET', 'POST'])
def redeem_code():
    lang = session.get('lang', 'tr')
    if request.method == 'POST':
        code_input = request.form.get('code', '').strip().upper()
        
        if not code_input:
            flash('Lutfen bir kod girin.' if lang == 'tr' else 'Please enter a code.')
            return redirect(url_for('redeem_code'))
        
        # Demo kodu: tekrar tekrar kullanilabilir, tuketilmez
        if code_input == DEMO_ACCESS_CODE:
            if 'user_id' not in session:
                session['pending_code'] = code_input
                return render_template('redeem_code.html', lang=lang, show_register=True, verified_code=code_input)
            user_id = session['user_id']
            purchase = Purchase.query.filter_by(user_id=user_id, case_id=DEMO_ACCESS_CASE_ID).first()
            if not purchase:
                db.session.add(Purchase(user_id=user_id, case_id=DEMO_ACCESS_CASE_ID, amount=0, is_paid=True))
                db.session.commit()
            flash('Kod basariyla kullanildi! Davaya yonlendiriliyorsunuz.' if lang == 'tr' else 'Code redeemed successfully! Redirecting to case.')
            return redirect(url_for('play_case', case_id=DEMO_ACCESS_CASE_ID))
        
        access_code = AccessCode.query.filter_by(code=code_input).first()
        
        if not access_code:
            flash('Gecersiz kod.' if lang == 'tr' else 'Invalid code.')
            return redirect(url_for('redeem_code'))
        
        if access_code.is_used:
            flash('Bu kod daha once kullanilmis.' if lang == 'tr' else 'This code has already been used.')
            return redirect(url_for('redeem_code'))
        
        # Kullanici giris yapmis mi kontrol et
        if 'user_id' not in session:
            # Kod gecerli, ayni sayfada kayit formu goster
            session['pending_code'] = code_input
            return render_template('redeem_code.html', lang=lang, show_register=True, verified_code=code_input)
        
        # Kodu kullan
        user_id = session['user_id']
        access_code.is_used = True
        access_code.used_by_user_id = user_id
        access_code.used_at = datetime.utcnow()
        
        # Kullaniciya davayi ekle (satin alinmis gibi)
        purchase = Purchase.query.filter_by(user_id=user_id, case_id=access_code.case_id).first()
        if not purchase:
            purchase = Purchase(user_id=user_id, case_id=access_code.case_id, amount=0, is_paid=True)
            db.session.add(purchase)
        
        db.session.commit()
        flash('Kod basariyla kullanildi! Davaya yonlendiriliyorsunuz.' if lang == 'tr' else 'Code redeemed successfully! Redirecting to case.')
        return redirect(url_for('play_case', case_id=access_code.case_id))
    
    return render_template('redeem_code.html', lang=lang, show_register=False)

@app.route('/redeem-register', methods=['POST'])
def redeem_register():
    lang = session.get('lang', 'tr')
    code_input = request.form.get('code', '').strip().upper()
    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    
    # Validasyon
    if not all([code_input, username, email, password]):
        flash('Tum alanlari doldurun.' if lang == 'tr' else 'Please fill all fields.')
        return render_template('redeem_code.html', lang=lang, show_register=True, verified_code=code_input)
    
    is_demo_code = (code_input == DEMO_ACCESS_CODE)
    # Kod kontrolu (demo kodu haric)
    access_code = None
    if not is_demo_code:
        access_code = AccessCode.query.filter_by(code=code_input).first()
        if not access_code or access_code.is_used:
            flash('Gecersiz veya kullanilmis kod.' if lang == 'tr' else 'Invalid or used code.')
            return redirect(url_for('redeem_code'))
    
    # Kullanici adi ve email kontrolu
    if User.query.filter_by(username=username).first():
        flash('Bu kullanici adi zaten kullaniliyor.' if lang == 'tr' else 'Username already exists.')
        return render_template('redeem_code.html', lang=lang, show_register=True, verified_code=code_input)
    
    if User.query.filter_by(email=email).first():
        flash('Bu email zaten kayitli.' if lang == 'tr' else 'Email already registered.')
        return render_template('redeem_code.html', lang=lang, show_register=True, verified_code=code_input)
    
    try:
        # Kullanici olustur
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(username=username, email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.flush()
        
        if is_demo_code:
            target_case_id = DEMO_ACCESS_CASE_ID
        else:
            # Kodu kullan (demo kodu tuketilmez)
            access_code.is_used = True
            access_code.used_by_user_id = new_user.id
            access_code.used_at = datetime.utcnow()
            target_case_id = access_code.case_id
        
        # Satin alma kaydi olustur
        purchase = Purchase(user_id=new_user.id, case_id=target_case_id, amount=0, is_paid=True)
        db.session.add(purchase)
        db.session.commit()
        
        # Oturum ac
        session['user_id'] = new_user.id
        session['username'] = new_user.username
        if 'pending_code' in session:
            session.pop('pending_code')
        
        flash('Hesabiniz olusturuldu! Oyuna yonlendiriliyorsunuz.' if lang == 'tr' else 'Account created! Redirecting to game.')
        return redirect(url_for('play_case', case_id=target_case_id))
    
    except Exception as e:
        db.session.rollback()
        print(f"Redeem register error: {str(e)}")
        flash('Kayit sirasinda bir hata olustu. Lutfen tekrar deneyin.' if lang == 'tr' else 'An error occurred during registration. Please try again.')
        return render_template('redeem_code.html', lang=lang, show_register=True, verified_code=code_input)

# Giriş sonrası bekleyen kodu işle
@app.route('/process-pending-code')
def process_pending_code():
    if 'user_id' not in session or 'pending_code' not in session:
        return redirect(url_for('index'))
    
    code_input = session.pop('pending_code')
    
    # Demo kodu: tuketilmez, her seferinde erisim ver
    if code_input == DEMO_ACCESS_CODE:
        user_id = session['user_id']
        purchase = Purchase.query.filter_by(user_id=user_id, case_id=DEMO_ACCESS_CASE_ID).first()
        if not purchase:
            db.session.add(Purchase(user_id=user_id, case_id=DEMO_ACCESS_CASE_ID, amount=0, is_paid=True))
            db.session.commit()
        flash('Kod başarıyla kullanıldı!')
        return redirect(url_for('play_case', case_id=DEMO_ACCESS_CASE_ID))
    
    access_code = AccessCode.query.filter_by(code=code_input).first()
    
    if access_code and not access_code.is_used:
        user_id = session['user_id']
        access_code.is_used = True
        access_code.used_by_user_id = user_id
        access_code.used_at = datetime.utcnow()
        
        purchase = Purchase.query.filter_by(user_id=user_id, case_id=access_code.case_id).first()
        if not purchase:
            purchase = Purchase(user_id=user_id, case_id=access_code.case_id, amount=0, is_paid=True)
            db.session.add(purchase)
        
        db.session.commit()
        flash('Kod başarıyla kullanıldı!')
        return redirect(url_for('play_case', case_id=access_code.case_id))
    
    return redirect(url_for('index'))

def load_initial_data():
    """initial_data.json'dan eksik verileri senkronize et (her zaman çalışır)"""
    import json
    from datetime import datetime
    
    try:
        with open('initial_data.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print("initial_data.json bulunamadı")
        return
    
    print("Başlangıç verileri senkronize ediliyor...")
    
    def parse_date(val):
        if not val or val == 'None': return None
        try: return datetime.fromisoformat(str(val).replace('Z', '+00:00'))
        except: return None
    
    protected_keys = {'iyzico_api_key', 'iyzico_secret_key', 'havale_iban', 'havale_alici_adi', 'havale_banka_adi',
                       'param_client_code', 'param_username', 'param_password', 'param_guid'}
    for s in data.get('settings', []):
        if s.get('key'):
            existing = Settings.query.filter_by(key=s.get('key')).first()
            if existing:
                if s.get('key') not in protected_keys:
                    existing.value = s.get('value', '')
            else:
                db.session.add(Settings(key=s.get('key'), value=s.get('value', '')))
    db.session.commit()
    
    for p in data.get('pages', []):
        if p.get('id') and not Page.query.get(p.get('id')):
            db.session.add(Page(id=p.get('id'), slug=p.get('slug', ''), title=p.get('title', ''), content=p.get('content', '')))
    db.session.commit()
    
    for h in data.get('how_to_play_steps', []):
        if h.get('id') and not HowToPlayStep.query.get(h.get('id')):
            db.session.add(HowToPlayStep(id=h.get('id'), order_num=h.get('order_num', h.get('step_number', 0)), title=h.get('title', ''),
                content=h.get('content', h.get('description', '')), image=h.get('image', h.get('icon')), title_en=h.get('title_en'), content_en=h.get('content_en', h.get('description_en'))))
    db.session.commit()
    
    for p in data.get('posts', []):
        if p.get('id') and not Post.query.get(p.get('id')):
            db.session.add(Post(id=p.get('id'), title=p.get('title', ''), content=p.get('content', ''),
                image=p.get('image')))
    db.session.commit()
    
    _case_content_fields = [
        'title', 'title_en', 'price', 'image', 'video', 'description', 'description_en',
        'solution', 'old_price', 'discount_rate', 'difficulty', 'is_active', 'game_type',
        'demo_enabled', 'success_file', 'culprit_keywords', 'explanation_keywords',
        'report_case_name', 'report_case_name_en', 'report_company', 'report_company_en',
        'success_message', 'success_message_en', 'police_department', 'police_department_en',
        'report_letter', 'report_letter_en', 'commissioner_name', 'commissioner_name_en',
        'warning_text', 'warning_text_en', 'instructions_text', 'instructions_text_en',
        'report_greeting', 'report_greeting_en', 'report_intro_text', 'report_intro_text_en',
        'report_suspect_question', 'report_suspect_question_en', 'report_confirmation_text',
        'report_confirmation_text_en', 'report_signature_name', 'report_signature_name_en',
        'demo_summary', 'demo_summary_en',
    ]
    for c in data.get('cases', []):
        if not c.get('id'):
            continue
        case = Case.query.get(c.get('id'))
        if not case:
            case = Case(id=c.get('id'))
            db.session.add(case)
        # Her iki durumda da (yeni veya mevcut) içerik alanlarını güncelle
        for field in _case_content_fields:
            if field in c:
                val = c[field]
                if field in ('is_active', 'demo_enabled'):
                    val = bool(val)
                elif field in ('price', 'old_price'):
                    val = float(val) if val is not None else 0.0
                elif field in ('discount_rate',):
                    val = int(val) if val is not None else 0
                setattr(case, field, val)
    db.session.commit()
    
    try:
        expected_files = {}
        seed_case_ids = set()
        for cf in data.get('case_files', []):
            key = (cf.get('filename', ''), cf.get('case_id', ''))
            expected_files[key] = cf
            seed_case_ids.add(cf.get('case_id', ''))
        
        all_db_files = CaseFile.query.all()
        db_file_keys = set()
        for dbf in all_db_files:
            if dbf.case_id not in seed_case_ids:
                continue
            key = (dbf.filename, dbf.case_id)
            if key not in expected_files:
                db.session.delete(dbf)
            else:
                db_file_keys.add(key)
                cf = expected_files[key]
                dbf.display_name = cf.get('display_name')
                dbf.category = cf.get('category', '')
                dbf.sub_category = cf.get('sub_category')
                dbf.file_ext = cf.get('file_ext')
                dbf.youtube_link = cf.get('youtube_link')
        db.session.commit()
        
        added_count = 0
        for key, cf in expected_files.items():
            if key not in db_file_keys:
                try:
                    db.session.add(CaseFile(
                        case_id=cf.get('case_id'),
                        filename=cf.get('filename', ''),
                        display_name=cf.get('display_name'),
                        category=cf.get('category', ''),
                        sub_category=cf.get('sub_category'),
                        file_ext=cf.get('file_ext'),
                        youtube_link=cf.get('youtube_link')
                    ))
                    db.session.commit()
                    added_count += 1
                except Exception as file_err:
                    db.session.rollback()
                    print(f"⚠️ Dosya eklenemedi: {cf.get('filename')}/{cf.get('case_id')}: {file_err}")
        print(f"📁 Dosya senkronizasyonu tamamlandı: {len(expected_files)} toplam, {added_count} yeni eklendi")
    except Exception as e:
        db.session.rollback()
        print(f"⚠️ Dosya senkronizasyon hatası: {e}")
        import traceback
        traceback.print_exc()
    
    for s in data.get('suspects', []):
        if not s.get('id'):
            continue
        suspect = Suspect.query.get(s.get('id'))
        if not suspect:
            suspect = Suspect(id=s.get('id'), case_id=s.get('case_id'))
            db.session.add(suspect)
        suspect.name = s.get('name', '')
        suspect.is_culprit = bool(s.get('is_culprit', 0))
        suspect.case_id = s.get('case_id')
        for f in ['name_en', 'description', 'description_en', 'image']:
            if f in s:
                setattr(suspect, f, s[f])
    db.session.commit()
    
    for u in data.get('users', []):
        if u.get('id') and not User.query.get(u.get('id')):
            user = User(id=u.get('id'), username=u.get('username', ''), email=u.get('email', ''), password=u.get('password', ''),
                first_name=u.get('first_name'), last_name=u.get('last_name'), screen_name=u.get('screen_name'),
                billing_address=u.get('billing_address'))
            db.session.add(user)
    db.session.commit()
    
    for o in data.get('orders', []):
        try:
            if o.get('id') and not Order.query.get(o.get('id')):
                db.session.add(Order(id=o.get('id'), user_id=o.get('user_id'),
                    order_number=o.get('order_number', str(o.get('id', ''))),
                    total_price=o.get('total_price', 0), item_count=o.get('item_count', 1),
                    status=o.get('status', 'Tamamlanmış'), date=parse_date(o.get('created_at') or o.get('date'))))
        except Exception as e:
            db.session.rollback()
            print(f"Order sync error: {e}")
    db.session.commit()
    
    for p in data.get('purchases', []):
        try:
            if p.get('id') and not Purchase.query.get(p.get('id')):
                db.session.add(Purchase(id=p.get('id'), user_id=p.get('user_id'), case_id=p.get('case_id'),
                    amount=p.get('amount', 0), is_paid=bool(p.get('is_paid', 0)), created_at=parse_date(p.get('created_at'))))
        except Exception as e:
            db.session.rollback()
            print(f"Purchase sync error: {e}")
    db.session.commit()
    
    for h in data.get('hints', []):
        if not h.get('id'):
            continue
        hint = Hint.query.get(h.get('id'))
        if not hint:
            hint = Hint(id=h.get('id'), case_id=h.get('case_id'))
            db.session.add(hint)
        hint.hint_text = h.get('hint_text', '')
        hint.hint_text_en = h.get('hint_text_en')
        hint.show_datetime = parse_date(h.get('show_datetime'))
        hint.is_active = bool(h.get('is_active', 1))
        hint.case_id = h.get('case_id')
    db.session.commit()
    
    for s in data.get('subscribers', []):
        if s.get('id') and not Subscriber.query.get(s.get('id')):
            db.session.add(Subscriber(id=s.get('id'), email=s.get('email', ''), name=s.get('name'),
                is_active=bool(s.get('is_active', 1)), subscribed_at=parse_date(s.get('subscribed_at'))))
    db.session.commit()
    
    for p in data.get('partners', []):
        try:
            if p.get('id') and not Partner.query.get(p.get('id')):
                db.session.add(Partner(id=p.get('id'), user_id=p.get('user_id'), bio=p.get('bio', ''),
                    commission_rate=p.get('commission_rate', 20), total_earnings=p.get('total_earnings', 0),
                    pending_earnings=p.get('pending_earnings', 0), status=p.get('status', 'pending'),
                    iban=p.get('iban'), iban_name=p.get('iban_name'), created_at=parse_date(p.get('created_at'))))
        except Exception as e:
            db.session.rollback()
            print(f"Partner sync error: {e}")
    db.session.commit()
    
    for d in data.get('discount_codes', []):
        if d.get('id') and not DiscountCode.query.get(d.get('id')):
            db.session.add(DiscountCode(id=d.get('id'), code=d.get('code', ''), discount_type=d.get('discount_type', 'percent'),
                discount_value=d.get('discount_value', 0), valid_from=parse_date(d.get('valid_from')),
                valid_until=parse_date(d.get('valid_until')), max_uses=d.get('max_uses'), times_used=d.get('times_used', 0),
                is_active=bool(d.get('is_active', 1)), case_id=d.get('case_id')))
    db.session.commit()
    
    for f in data.get('footer_links', []):
        if f.get('id') and not FooterLink.query.get(f.get('id')):
            db.session.add(FooterLink(id=f.get('id'), column=f.get('column', 1), title=f.get('title', ''), url=f.get('url', ''), order=f.get('order', 0)))
    db.session.commit()
    
    for f in data.get('faqs', []):
        if f.get('id') and not FAQ.query.get(f.get('id')):
            db.session.add(FAQ(id=f.get('id'), question=f.get('question', ''), answer=f.get('answer', ''),
                question_en=f.get('question_en'), answer_en=f.get('answer_en'), order=f.get('order', 0)))
    db.session.commit()
    
    for a in data.get('access_codes', []):
        try:
            if a.get('id') and not AccessCode.query.get(a.get('id')):
                db.session.add(AccessCode(id=a.get('id'), code=a.get('code', ''), case_id=a.get('case_id'),
                    platform=a.get('platform', 'Trendyol'), sale_price=a.get('sale_price', 0),
                    is_used=bool(a.get('is_used', 0)), created_at=parse_date(a.get('created_at')),
                    used_at=parse_date(a.get('used_at'))))
        except Exception as e:
            db.session.rollback()
            print(f"AccessCode sync error: {e}")
    db.session.commit()
    
    for t in data.get('team_purchases', []):
        try:
            if t.get('id') and not TeamPurchase.query.get(t.get('id')):
                db.session.add(TeamPurchase(id=t.get('id'), case_id=t.get('case_id'),
                    organizer_email=t.get('organizer_email', ''), organizer_name=t.get('organizer_name', ''),
                    team_count=t.get('team_count', 1), total_price=t.get('total_price', 0),
                    payment_status=t.get('payment_status', 'pending'), created_at=parse_date(t.get('created_at'))))
        except Exception as e:
            db.session.rollback()
            print(f"TeamPurchase sync error: {e}")
    db.session.commit()
    
    for m in data.get('team_members', []):
        try:
            if m.get('id') and not TeamMember.query.get(m.get('id')):
                db.session.add(TeamMember(id=m.get('id'), team_purchase_id=m.get('team_purchase_id'),
                    team_number=m.get('team_number', 1), team_name=m.get('team_name'),
                    email=m.get('email', ''), access_token=m.get('access_token', ''),
                    accessed=bool(m.get('accessed', 0)), completed=bool(m.get('completed', 0)),
                    created_at=parse_date(m.get('created_at'))))
        except Exception as e:
            db.session.rollback()
            print(f"TeamMember sync error: {e}")
    db.session.commit()
    
    print("✅ Tüm veriler başarıyla yüklendi!")

@app.route('/admin/migrate-files')
def admin_migrate_files():
    if session.get('username') != 'admin':
        return redirect(url_for('index'))
    moved = []
    errors = []
    upload_root = app.config['UPLOAD_FOLDER']

    for cf in CaseFile.query.all():
        if cf.filename:
            src = os.path.join(upload_root, cf.filename)
            dst_folder = get_case_upload_folder(cf.case_id)
            dst = os.path.join(dst_folder, cf.filename)
            if os.path.exists(src) and not os.path.exists(dst):
                try:
                    shutil.move(src, dst)
                    moved.append(f"CaseFile: {cf.filename} -> {cf.case_id}/")
                except Exception as e:
                    errors.append(f"CaseFile {cf.filename}: {e}")

    for case in Case.query.all():
        dst_folder = get_case_upload_folder(case.id)
        for field in ['image', 'video', 'success_file']:
            fname = getattr(case, field, None)
            if fname and not fname.startswith('http') and fname != '#':
                src = os.path.join(upload_root, fname)
                dst = os.path.join(dst_folder, fname)
                if os.path.exists(src) and not os.path.exists(dst):
                    try:
                        shutil.move(src, dst)
                        moved.append(f"Case.{field}: {fname} -> {case.id}/")
                    except Exception as e:
                        errors.append(f"Case.{field} {fname}: {e}")

    for hint in Hint.query.all():
        if hint.hint_file:
            src = os.path.join(upload_root, hint.hint_file)
            dst_folder = get_case_upload_folder(hint.case_id)
            dst = os.path.join(dst_folder, hint.hint_file)
            if os.path.exists(src) and not os.path.exists(dst):
                try:
                    shutil.move(src, dst)
                    moved.append(f"Hint: {hint.hint_file} -> {hint.case_id}/")
                except Exception as e:
                    errors.append(f"Hint {hint.hint_file}: {e}")

    return jsonify({"moved": moved, "errors": errors, "total_moved": len(moved), "total_errors": len(errors)})

def cleanup_duplicate_files():
    from sqlalchemy import func
    duplicates = db.session.query(
        CaseFile.filename, CaseFile.case_id, func.min(CaseFile.id).label('keep_id')
    ).group_by(CaseFile.filename, CaseFile.case_id).having(func.count(CaseFile.id) > 1).all()
    
    for dup in duplicates:
        extras = CaseFile.query.filter(
            CaseFile.filename == dup.filename,
            CaseFile.case_id == dup.case_id,
            CaseFile.id != dup.keep_id
        ).all()
        for extra in extras:
            db.session.delete(extra)
    if duplicates:
        db.session.commit()
        print(f"🧹 {len(duplicates)} tekrarlı dosya grubu temizlendi")

def fix_sequences():
    """Tüm tablolardaki PostgreSQL sequence'larını max ID değerine eşitle.
    Veri senkronizasyonu sonrasında sequence bozulmasını önler."""
    tables = [
        'team_purchase', 'team_member', 'purchase', 'partner', 'partner_sale',
        'discount_code', '"user"', 'case_file', 'comment', 'hint', 'game_progress',
        'team_message', 'partner_withdrawal', 'access_code', 'suspect', 'post',
        'page', 'faq', 'settings', 'suggestion', 'contact_message', 'subscriber',
        'case_idea', 'how_to_play_step', 'footer_link', 'blog_comment', 'email_log'
    ]
    for tbl in tables:
        tbl_name = tbl.strip('"')
        try:
            db.session.execute(db.text(
                f"SELECT setval(pg_get_serial_sequence('{tbl_name}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {tbl}), 1))"
            ))
        except Exception:
            db.session.rollback()
    db.session.commit()

def run_auto_migrations():
    """SQLite / PostgreSQL eksik sütun denetimi ve otomatik migration"""
    try:
        engine = db.engine
        inspector = db.inspect(engine)
        tables = inspector.get_table_names()
        
        if 'case' in tables:
            cols = [c['name'] for c in inspector.get_columns('case')]
            with engine.connect() as conn:
                if 'success_file' not in cols:
                    conn.execute(db.text('ALTER TABLE "case" ADD COLUMN success_file VARCHAR(255)'))
                if 'culprit_keywords' not in cols:
                    conn.execute(db.text('ALTER TABLE "case" ADD COLUMN culprit_keywords TEXT'))
                if 'explanation_keywords' not in cols:
                    conn.execute(db.text('ALTER TABLE "case" ADD COLUMN explanation_keywords TEXT'))
                conn.commit()
                
        if 'user' in tables:
            cols = [c['name'] for c in inspector.get_columns('user')]
            with engine.connect() as conn:
                if 'reset_token' not in cols:
                    conn.execute(db.text('ALTER TABLE "user" ADD COLUMN reset_token VARCHAR(100)'))
                if 'reset_token_expiry' not in cols:
                    conn.execute(db.text('ALTER TABLE "user" ADD COLUMN reset_token_expiry TIMESTAMP'))
                conn.commit()

        if 'hint' in tables:
            cols = [c['name'] for c in inspector.get_columns('hint')]
            with engine.connect() as conn:
                if 'hint_file' not in cols:
                    conn.execute(db.text('ALTER TABLE "hint" ADD COLUMN hint_file VARCHAR(255)'))
                conn.commit()

        if 'team_purchase' in tables:
            cols = [c['name'] for c in inspector.get_columns('team_purchase')]
            with engine.connect() as conn:
                if 'partner_code' not in cols:
                    conn.execute(db.text('ALTER TABLE "team_purchase" ADD COLUMN partner_code VARCHAR(50)'))
                if 'dealer_code' not in cols:
                    conn.execute(db.text('ALTER TABLE "team_purchase" ADD COLUMN dealer_code VARCHAR(20)'))
                if 'dealer_qr_template_id' not in cols:
                    conn.execute(db.text('ALTER TABLE "team_purchase" ADD COLUMN dealer_qr_template_id INTEGER'))
                conn.commit()

        if 'team_member' in tables:
            cols = [c['name'] for c in inspector.get_columns('team_member')]
            with engine.connect() as conn:
                if 'play_time_seconds' not in cols:
                    conn.execute(db.text('ALTER TABLE "team_member" ADD COLUMN play_time_seconds INTEGER'))
                conn.commit()
    except Exception as e:
        print(f"Auto-migration uyarısı: {e}")

def initialize_app():
    with app.app_context():
        try:
            run_auto_migrations()
            db.create_all()
            load_initial_data()
            fix_sequences()
            cleanup_duplicate_files()
            if not User.query.filter_by(username="admin").first():
                db.session.add(User(username="admin", email="admin@test.com", password=generate_password_hash("1234")))
                db.session.commit()
            for p in Partner.query.filter(Partner.commission_rate < 20).all():
                p.commission_rate = 20
            db.session.commit()
            # Domain migration: eski gizemlivakalar.com → gizemlivaka.com
            try:
                db.session.execute(db.text(
                    "UPDATE page SET content = REPLACE(content, 'gizemlivakalar.com', 'gizemlivaka.com')"
                ))
                db.session.execute(db.text(
                    "UPDATE page SET title = REPLACE(title, 'gizemlivakalar.com', 'gizemlivaka.com')"
                ))
                db.session.commit()
            except Exception:
                db.session.rollback()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ Başlatma hatası (uygulama çalışmaya devam ediyor): {e}")

@app.before_request
def ensure_db_connection():
    try:
        db.session.execute(db.text('SELECT 1'))
    except Exception:
        db.session.rollback()
        db.session.remove()
        try:
            db.engine.dispose()
        except Exception:
            pass

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    db.session.remove()
    lang = session.get('lang', 'tr')
    if lang == 'en':
        return '<h1>Server Error</h1><p>A temporary error occurred. Please <a href="javascript:location.reload()">refresh the page</a>.</p>', 500
    return '<h1>Sunucu Hatası</h1><p>Geçici bir hata oluştu. Lütfen <a href="javascript:location.reload()">sayfayı yenileyin</a>.</p>', 500

@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session.remove()

@app.after_request
def add_seo_geo_headers(response):
    """SEO & GEO yanıt başlıklarını ekler"""
    response.headers['Link'] = '<https://gizemlivaka.com/llms.txt>; rel="llms-txt"'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

@app.route('/sitemap.xml')
def sitemap():
    from urllib.parse import quote
    from datetime import datetime
    pages = []
    base_url = 'https://gizemlivaka.com'
    today = datetime.now().strftime('%Y-%m-%d')
    static_pages = [
        ('/', 1.0, 'daily'),
        ('/cases', 0.9, 'daily'),
        ('/teams', 0.8, 'weekly'),
        ('/how-to-play', 0.7, 'monthly'),
        ('/about', 0.6, 'monthly'),
        ('/faq', 0.6, 'monthly'),
        ('/blog', 0.7, 'weekly'),
        ('/contact', 0.5, 'monthly'),
        ('/leaderboard', 0.6, 'daily'),
        ('/gift-cards', 0.6, 'monthly'),
        ('/privacy-policy', 0.3, 'yearly'),
        ('/terms-conditions', 0.3, 'yearly'),
        ('/distance-sales', 0.3, 'yearly'),
        ('/kvkk', 0.3, 'yearly'),
    ]
    for url, priority, changefreq in static_pages:
        pages.append(f'  <url>\n    <loc>{base_url}{url}</loc>\n    <lastmod>{today}</lastmod>\n    <changefreq>{changefreq}</changefreq>\n    <priority>{priority}</priority>\n  </url>')
    sitemap_cases = Case.query.filter_by(is_active=True).all()
    for case in sitemap_cases:
        encoded_id = quote(str(case.id), safe='')
        img_xml = ''
        if getattr(case, 'image', None):
            case_img = case.image
            img_url = f"{base_url}/static/uploads/{case.id}/{case_img}" if not case_img.startswith('http') else case_img
            title_escaped = (case.title or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            img_xml = f'\n    <image:image>\n      <image:loc>{img_url}</image:loc>\n      <image:title>{title_escaped}</image:title>\n    </image:image>'
        pages.append(f'  <url>\n    <loc>{base_url}/case/{encoded_id}</loc>\n    <lastmod>{today}</lastmod>\n    <changefreq>weekly</changefreq>\n    <priority>0.9</priority>{img_xml}\n  </url>')
    posts = Post.query.all()
    for post in posts:
        post_date = post.date_posted.strftime('%Y-%m-%d') if post.date_posted else today
        pages.append(f'  <url>\n    <loc>{base_url}/blog/{post.id}</loc>\n    <lastmod>{post_date}</lastmod>\n    <changefreq>monthly</changefreq>\n    <priority>0.6</priority>\n  </url>')
    # Dedektif Akademisi sayfaları
    akademi_slugs = [
        'sorusturma-dusuncesi', 'delil-zinciri', 'ifade-analizi', 'dijital-metadata',
        'adli-isitim', 'cctv-analizi', 'telefon-kayitlari', 'finansal-adli-tip',
        'ag-analizi', 'alibi-denetimi', 'magdurbilim'
    ]
    pages.append(f'  <url>\n    <loc>{base_url}/dedektif-akademisi</loc>\n    <lastmod>{today}</lastmod>\n    <changefreq>weekly</changefreq>\n    <priority>0.8</priority>\n  </url>')
    for slug in akademi_slugs:
        pages.append(f'  <url>\n    <loc>{base_url}/dedektif-akademisi/{slug}</loc>\n    <lastmod>{today}</lastmod>\n    <changefreq>monthly</changefreq>\n    <priority>0.7</priority>\n  </url>')
    pages.append(f'  <url>\n    <loc>{base_url}/reviews</loc>\n    <lastmod>{today}</lastmod>\n    <changefreq>weekly</changefreq>\n    <priority>0.6</priority>\n  </url>')
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'
    xml += '\n'.join(pages)
    xml += '\n</urlset>'
    response = make_response(xml)
    response.headers['Content-Type'] = 'application/xml; charset=utf-8'
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response

@app.route('/robots.txt')
def robots():
    txt = """User-agent: *
Allow: /
Disallow: /admin/
Disallow: /payment/
Disallow: /api/
Disallow: /login
Disallow: /register
Disallow: /account
Disallow: /active-cases
Disallow: /cart
Disallow: /set-lang/
Disallow: /set-currency/
Disallow: /play/
Disallow: /hint-pay/

# --- AI Search Crawlers (explicitly allowed for public content) ---

User-agent: GPTBot
Allow: /
Allow: /cases
Allow: /case/
Allow: /blog/
Allow: /dedektif-akademisi
Allow: /faq
Allow: /about
Allow: /teams
Allow: /reviews
Allow: /llms.txt
Allow: /llms-full.txt
Disallow: /admin/
Disallow: /play/
Disallow: /api/

User-agent: ChatGPT-User
Allow: /

User-agent: OAI-SearchBot
Allow: /
Disallow: /admin/
Disallow: /play/
Disallow: /api/

User-agent: PerplexityBot
Allow: /
Allow: /cases
Allow: /case/
Allow: /blog/
Allow: /dedektif-akademisi
Allow: /faq
Allow: /about
Allow: /teams
Allow: /reviews
Allow: /llms.txt
Allow: /llms-full.txt
Disallow: /admin/
Disallow: /play/
Disallow: /api/

User-agent: ClaudeBot
Allow: /
Disallow: /admin/
Disallow: /play/
Disallow: /api/

User-agent: anthropic-ai
Allow: /
Disallow: /admin/
Disallow: /play/
Disallow: /api/

User-agent: Google-Extended
Allow: /
Disallow: /admin/
Disallow: /play/
Disallow: /api/

User-agent: DeepSeekBot
Allow: /
Disallow: /admin/
Disallow: /play/
Disallow: /api/

User-agent: Applebot
Allow: /
Disallow: /admin/
Disallow: /play/

User-agent: Applebot-Extended
Allow: /
Disallow: /admin/
Disallow: /play/

User-agent: Meta-ExternalAgent
Allow: /
Disallow: /admin/
Disallow: /play/

User-agent: Bytespider
Allow: /
Disallow: /admin/
Disallow: /play/
Disallow: /api/

User-agent: Amazonbot
Allow: /
Disallow: /admin/
Disallow: /play/
Disallow: /api/

User-agent: cohere-ai
Allow: /
Disallow: /admin/
Disallow: /play/
Disallow: /api/

Sitemap: https://gizemlivaka.com/sitemap.xml"""
    response = make_response(txt)
    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    return response

@app.route('/llms.txt')
def llms_txt():
    txt = """# Gizemli Vaka — Türkiye'nin İlk Online Dedektiflik Oyun Platformu

> Gizemli Vaka, kullanıcıların gerçekçi kurgu cinayet dosyalarını tarayıcıdan çözdüğü Türkiye'nin ilk ve en kapsamlı online dedektiflik oyun platformudur.

## Platform Kimliği

Gizemli Vaka (gizemlivaka.com), 2024 yılında Türkiye'de kurulan, tamamen web tarayıcısı üzerinden erişilebilen bir interaktif dedektiflik oyun platformudur. Kullanıcılar kurulum yapmadan, telefondan, tabletten veya bilgisayardan oynayabilir. Platform hem Türkçe hem İngilizce hizmet vermektedir.

- URL: https://gizemlivaka.com
- Kategori: Online oyun, murder mystery, dedektiflik oyunu, kurumsal team building
- Dil: Türkçe (birincil), İngilizce (ikincil)
- Hedef Kitle: 16+ yaş, bireysel oyuncular, kurumsal şirketler, arkadaş grupları
- Ülke: Türkiye (TR)
- Platform türü: Web uygulaması — kurulum gerektirmez

## Gizemli Vaka Nedir?

Gizemli Vaka, oyuncuların kurgusal polis veri tabanlarına erişerek cinayet davalarını çözdüğü bir online dedektiflik deneyimidir. Her dava; PDF belgeler, ses kayıtları, video kanıtlar, otopsi raporları ve şüphe ifadeleri gibi gerçekçi delil dosyaları içerir. Oyuncular bu delilleri analiz ederek katili bulmaya ve yazılı raporlarını göndermeye çalışır.

## Nasıl Oynanır? (Adım Adım)

1. Oyuncu bir dava dosyası satın alır (fiyat aralığı: 149 TL - 299 TL)
2. Kurgusal polis sistemine giriş yapar
3. PDF belgeler, ses kayıtları, video kanıtlar ve görselleri inceler
4. Şüphe profillerini ve tanık ifadelerini değerlendirir
5. İpucu paketi satın alabilir (isteğe bağlı, ek ücret)
6. Yazılı bir rapor göndererek katil adayını bildirir
7. Sistem tahmini kontrol eder; doğruysa puan kazanır, yanlışsa ikinci hak tanınır

## Oyun Modları

- Bireysel Oyun: Tek kişilik dedektiflik deneyimi. Tamamlama süresi: ortalama 2-4 saat.
- Takım Oyunu (Kurumsal): 2 ile 50+ kişiye özel oynanan takım versiyonu. Her katılımcı aynı anda kendi cihazından, benzersiz bir bağlantı linki üzerinden oyuna erişir. Şirket etkinlikleri, team building, doğum günü partileri için tasarlanmıştır. Tüm katılımcılara tamamlama sertifikası verilir.

## Zorluk Seviyeleri

- Kolay: Belirgin ipuçları, az şüphe — 150 puan
- Orta: Karmaşık delil ağı, 3-5 şüphe — 200 puan
- Zor: Yanıltıcı deliller, derin analiz — 300 puan

## Bağlantılar

- Ana Sayfa: https://gizemlivaka.com
- Dava Dosyaları: https://gizemlivaka.com/cases
- Takım Oyunları: https://gizemlivaka.com/teams
- Dedektif Akademisi: https://gizemlivaka.com/dedektif-akademisi
- SSS: https://gizemlivaka.com/faq
- Tam Dokümantasyon: https://gizemlivaka.com/llms-full.txt
"""
    response = make_response(txt)
    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    return response

@app.route('/llms-full.txt')
def llms_full_txt():
    active_cases = Case.query.filter_by(is_active=True).all()
    cases_txt = ""
    for c in active_cases:
        price_val = getattr(c, 'price', 0)
        desc_val = (getattr(c, 'description', '') or '')[:200].replace('\n', ' ').replace('\r', ' ')
        cases_txt += f"- **{c.title}** (Zorluk: {c.difficulty}, Fiyat: {price_val} TL)\n  {desc_val}\n  URL: https://gizemlivaka.com/case/{c.id}\n\n"
    
    txt = f"""# Gizemli Vaka — Tam Platform Dokümantasyonu (LLM Full Version)

Gizemli Vaka (gizemlivaka.com), Türkiye'nin ilk ve lider online dedektiflik platformudur.

## Aktif Dava Kataloğu

{cases_txt}

## Dedektif Akademisi Ders Listesi

1. Soruşturma Düşüncesi: Delilden Teoriye (https://gizemlivaka.com/dedektif-akademisi/sorusturma-dusuncesi)
2. Delil Zinciri ve Yönetimi (https://gizemlivaka.com/dedektif-akademisi/delil-zinciri)
3. İfade Analizi ve Yalan Tespiti (https://gizemlivaka.com/dedektif-akademisi/ifade-analizi)
4. Dijital Metadata ve Adli Analiz (https://gizemlivaka.com/dedektif-akademisi/dijital-metadata)
5. Adli İşitim ve Ses Analizi (https://gizemlivaka.com/dedektif-akademisi/adli-isitim)
6. CCTV Görüntü Analizi (https://gizemlivaka.com/dedektif-akademisi/cctv-analizi)
7. Telefon Kayıtları Soruşturması (https://gizemlivaka.com/dedektif-akademisi/telefon-kayitlari)
8. Finansal Adli Tıp (https://gizemlivaka.com/dedektif-akademisi/finansal-adli-tip)
9. Ağ Analizi ve Bağlantı Haritası (https://gizemlivaka.com/dedektif-akademisi/ag-analizi)
10. Alibi Denetimi (https://gizemlivaka.com/dedektif-akademisi/alibi-denetimi)
11. Mağdurbilim (Viktimoloji) (https://gizemlivaka.com/dedektif-akademisi/magdurbilim)

## İletişim ve Destek
- E-posta: destek@gizemlivaka.com / iletisim@gizemlivaka.com
- Web: https://gizemlivaka.com/contact
"""
    response = make_response(txt)
    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    return response
@app.route('/api/deploy_webhook', methods=['POST'])
def deploy_webhook():
    """GitHub Webhook otomatik dağıtım endpoint'i"""
    secret = os.environ.get('WEBHOOK_SECRET', 'gizemlivaka-auto-deploy-secret-2026')
    signature = request.headers.get('X-Hub-Signature-256')
    
    if secret and signature:
        expected = 'sha256=' + hmac.new(secret.encode('utf-8'), request.data, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return jsonify({'error': 'Unauthorized'}), 401
    elif secret:
        token = request.args.get('token') or (request.json.get('token') if request.is_json else None)
        if token != secret:
            return jsonify({'error': 'Unauthorized token'}), 401

    def _execute_pull_and_restart():
        import subprocess
        try:
            print("🚀 Webhook: Git pull & restart başlatılıyor...")
            subprocess.run(['git', 'pull', 'origin', 'main'], cwd=os.getcwd())
            subprocess.run(['touch', 'main.py'], cwd=os.getcwd())
        except Exception as err:
            print(f"❌ Webhook deploy hatası: {err}")

    threading.Thread(target=_execute_pull_and_restart).start()
    return jsonify({'status': 'success', 'message': 'Deployment triggered'}), 200

initialize_app()

# --- MOBİL UYGULAMA API KATMANI (JSON / token tabanlı) ---
from api import register_api
register_api(app)

if __name__ == '__main__':
    _is_production = os.environ.get('REPLIT_DEPLOYMENT') == '1' or os.environ.get('IS_PRODUCTION') == '1' or os.environ.get('FLASK_ENV') == 'production'
    app.run(host='0.0.0.0', port=5000, debug=not _is_production)