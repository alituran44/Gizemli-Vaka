"""
Mobil uygulama için JSON API katmanı (v1).

Bu modül, mevcut oturum (çerez) tabanlı web uygulamasının yanına token (JWT)
tabanlı bir REST API ekler. Native (Swift/Kotlin) uygulamalar bu uçlara
`Authorization: Bearer <token>` başlığıyla bağlanır.

main.py'nin EN SONUNDA `from api import register_api; register_api(app)` ile
kaydedilir; bu sayede tüm modeller/yardımcılar import sırasında hazırdır.
"""
import os
import sys
import datetime as _dt
from functools import wraps

import jwt
import requests
from flask import Blueprint, request, jsonify, g, redirect, session, abort, send_from_directory, make_response
from werkzeug.security import generate_password_hash, check_password_hash

api_bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')

ACCESS_TOKEN_DAYS = 30
REFRESH_TOKEN_DAYS = 180

# Bu isimler register_api() içinde, ana modül (main.py) tam yüklendikten sonra
# bağlanır. Böylece `python main.py` ile çalışırken oluşan circular import
# (api -> main -> api) sorunu yaşanmaz.
app = None
db = None
User = Case = CaseFile = Suspect = Hint = Purchase = GameProgress = None
DIFFICULTY_POINTS = None
get_payment_settings = None
personalize_case_html = None
UPLOAD_FOLDER = 'static/uploads'


# ----------------------------------------------------------------------------
# Yardımcılar
# ----------------------------------------------------------------------------
def _secret():
    # Ayrı bir API anahtarı tanımlıysa onu kullan (web oturum gizli anahtarından
    # bağımsız). Yoksa Flask secret_key'e düş.
    return os.environ.get('API_JWT_SECRET') or app.secret_key


def _make_token(user, kind='access'):
    now = _dt.datetime.utcnow()
    days = ACCESS_TOKEN_DAYS if kind == 'access' else REFRESH_TOKEN_DAYS
    payload = {
        'uid': user.id,
        'username': user.username,
        'type': kind,
        'iat': now,
        'exp': now + _dt.timedelta(days=days),
    }
    return jwt.encode(payload, _secret(), algorithm='HS256')


def _decode_token(token):
    return jwt.decode(token, _secret(), algorithms=['HS256'])


def _bearer_user():
    """Authorization başlığındaki token'dan kullanıcıyı çözer (yoksa None)."""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    try:
        data = _decode_token(auth.split(' ', 1)[1].strip())
        if data.get('type') != 'access':
            return None
        return db.session.get(User, data.get('uid'))
    except Exception:
        return None


def token_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = _bearer_user()
        if not user:
            return jsonify({'error': 'unauthorized', 'message': 'Geçerli bir giriş token\'ı gerekli.'}), 401
        g.api_user = user
        return f(*args, **kwargs)
    return wrapper


def optional_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        g.api_user = _bearer_user()
        return f(*args, **kwargs)
    return wrapper


def _lang():
    lang = (request.args.get('lang') or '').lower()
    if lang in ('en', 'tr'):
        return lang
    al = (request.headers.get('Accept-Language') or '').lower()
    return 'en' if al.startswith('en') else 'tr'


def _loc(obj, field, lang):
    if lang == 'en':
        v = getattr(obj, field + '_en', None)
        if v:
            return v
    return getattr(obj, field, None)


def _abs(path):
    return request.url_root.rstrip('/') + path


def _display_name(user):
    return (user.screen_name or user.first_name or user.username) if user else 'Dedektif'


def _require_owned(case_id):
    """Sahiplik yoksa 403 JSON döndürür, varsa None döndürür."""
    if not user_owns_case(g.api_user, case_id):
        return jsonify({'error': 'locked', 'message': 'Bu vakayı satın almanız gerekiyor.'}), 403
    return None


def user_owns_case(user, case_id):
    if not user:
        return False
    if case_id in (user.unlocked_cases or '').split(','):
        return True
    return Purchase.query.filter_by(user_id=user.id, case_id=case_id, is_paid=True).first() is not None


def _user_json(user):
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'screen_name': user.screen_name,
        'score': user.score or 0,
    }


def _case_brief(case, user, lang):
    return {
        'id': case.id,
        'title': _loc(case, 'title', lang),
        'description': _loc(case, 'description', lang),
        'price': case.price,
        'old_price': case.old_price,
        'discount_rate': case.discount_rate,
        'difficulty': case.difficulty,
        'game_type': case.game_type,
        'image_url': _abs(f"/static/uploads/{case.id}/{case.image}") if case.image else None,
        'owned': user_owns_case(user, case.id),
    }


def _evidence_json(f, owned):
    data = {
        'id': f.id,
        'display_name': f.display_name or f.filename,
        'category': f.category,
        'sub_category': f.sub_category,
        'file_ext': f.file_ext,
        'youtube_link': f.youtube_link,
    }
    if owned:
        if f.filename:
            data['content_url'] = _abs(f"/api/v1/evidence/{f.id}/content")
    return data


def _case_full(case, user, lang):
    owned = user_owns_case(user, case.id)
    data = _case_brief(case, user, lang)
    data['suspects'] = [{'id': s.id, 'name': s.name} for s in case.suspects]
    data['evidence'] = [_evidence_json(f, owned) for f in case.files]
    data['success_message'] = _loc(case, 'success_message', lang) if owned else None
    return data


# ----------------------------------------------------------------------------
# Kimlik doğrulama
# ----------------------------------------------------------------------------
@api_bp.route('/auth/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    if not username or not email or not password:
        return jsonify({'error': 'missing_fields', 'message': 'Kullanıcı adı, e-posta ve şifre zorunludur.'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'username_taken', 'message': 'Bu kullanıcı adı zaten kullanılıyor.'}), 409
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'email_taken', 'message': 'Bu e-posta adresi zaten kayıtlı.'}), 409
    user = User(username=username, email=email, password=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()
    return jsonify({
        'access_token': _make_token(user, 'access'),
        'refresh_token': _make_token(user, 'refresh'),
        'user': _user_json(user),
    }), 201


@api_bp.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    login_input = (data.get('login') or data.get('username') or data.get('email') or '').strip()
    password = data.get('password') or ''
    if not login_input or not password:
        return jsonify({'error': 'missing_fields', 'message': 'Giriş bilgisi ve şifre zorunludur.'}), 400
    user = User.query.filter_by(username=login_input).first() or \
        User.query.filter_by(email=login_input.lower()).first()
    if not user or not check_password_hash(user.password, password):
        return jsonify({'error': 'invalid_credentials', 'message': 'Giriş başarısız. Bilgileri kontrol edin.'}), 401
    return jsonify({
        'access_token': _make_token(user, 'access'),
        'refresh_token': _make_token(user, 'refresh'),
        'user': _user_json(user),
    })


@api_bp.route('/auth/google', methods=['POST'])
def google_login():
    """Native uygulama Google SDK ile aldığı id_token'ı buraya gönderir."""
    data = request.get_json(silent=True) or {}
    id_token = data.get('id_token') or ''
    if not id_token:
        return jsonify({'error': 'missing_id_token', 'message': 'Google id_token zorunludur.'}), 400
    try:
        resp = requests.get('https://oauth2.googleapis.com/tokeninfo', params={'id_token': id_token}, timeout=15)
        info = resp.json() if resp.status_code == 200 else {}
    except Exception:
        info = {}
    email = (info.get('email') or '').lower()
    if not email or info.get('email_verified') in ('false', False):
        return jsonify({'error': 'invalid_token', 'message': 'Google kimliği doğrulanamadı.'}), 401
    allowed = {os.environ.get('GOOGLE_OAUTH_CLIENT_ID', '')}
    extra = os.environ.get('API_GOOGLE_CLIENT_IDS', '')
    allowed |= {c.strip() for c in extra.split(',') if c.strip()}
    allowed.discard('')
    if allowed and info.get('aud') not in allowed:
        return jsonify({'error': 'invalid_audience', 'message': 'Google istemci kimliği tanınmadı.'}), 401

    user = User.query.filter_by(email=email).first()
    if not user:
        base = email.split('@')[0]
        username = base
        counter = 1
        while User.query.filter_by(username=username).first():
            username = f"{base}{counter}"
            counter += 1
        user = User(
            username=username,
            email=email,
            password=generate_password_hash(os.urandom(24).hex()),
            first_name=info.get('given_name'),
            last_name=info.get('family_name'),
        )
        db.session.add(user)
        db.session.commit()
    return jsonify({
        'access_token': _make_token(user, 'access'),
        'refresh_token': _make_token(user, 'refresh'),
        'user': _user_json(user),
    })


@api_bp.route('/auth/refresh', methods=['POST'])
def refresh():
    data = request.get_json(silent=True) or {}
    rt = data.get('refresh_token') or ''
    try:
        payload = _decode_token(rt)
        if payload.get('type') != 'refresh':
            raise ValueError('wrong type')
        user = db.session.get(User, payload.get('uid'))
        if not user:
            raise ValueError('no user')
    except Exception:
        return jsonify({'error': 'invalid_refresh', 'message': 'Yenileme token\'ı geçersiz.'}), 401
    return jsonify({'access_token': _make_token(user, 'access')})


@api_bp.route('/auth/me', methods=['GET'])
@token_required
def me():
    return jsonify({'user': _user_json(g.api_user)})


# ----------------------------------------------------------------------------
# Vakalar
# ----------------------------------------------------------------------------
@api_bp.route('/cases', methods=['GET'])
@optional_auth
def list_cases():
    lang = _lang()
    cases = Case.query.filter_by(is_active=True).all()
    return jsonify({'cases': [_case_brief(c, g.api_user, lang) for c in cases]})


@api_bp.route('/cases/<case_id>', methods=['GET'])
@optional_auth
def case_detail(case_id):
    lang = _lang()
    case = Case.query.get(case_id)
    if not case or (not case.is_active):
        return jsonify({'error': 'not_found', 'message': 'Vaka bulunamadı.'}), 404
    return jsonify({'case': _case_full(case, g.api_user, lang)})


@api_bp.route('/cases/<case_id>/evidence', methods=['GET'])
@token_required
def case_evidence(case_id):
    case = Case.query.get(case_id)
    if not case:
        return jsonify({'error': 'not_found', 'message': 'Vaka bulunamadı.'}), 404
    if not user_owns_case(g.api_user, case_id):
        return jsonify({'error': 'locked', 'message': 'Bu vakayı satın almanız gerekiyor.'}), 403
    return jsonify({'evidence': [_evidence_json(f, True) for f in case.files]})


@api_bp.route('/evidence/<int:file_id>/content', methods=['GET'])
@token_required
def evidence_content(file_id):
    f = CaseFile.query.get(file_id)
    if not f:
        return jsonify({'error': 'not_found', 'message': 'Delil bulunamadı.'}), 404
    if not user_owns_case(g.api_user, f.case_id):
        return jsonify({'error': 'locked', 'message': 'Bu delile erişim için vakayı satın almalısınız.'}), 403
    uploads_root = os.path.realpath(UPLOAD_FOLDER)
    file_path = os.path.realpath(os.path.join(UPLOAD_FOLDER, f.case_id, f.filename))
    if os.path.commonpath([uploads_root, file_path]) != uploads_root or not os.path.isfile(file_path):
        return jsonify({'error': 'file_missing', 'message': 'Dosya bulunamadı.'}), 404
    ext = (f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else '')
    if ext in ('html', 'htm'):
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as fh:
            content = personalize_case_html(fh.read(), _display_name(g.api_user), f.case_id)
        resp = make_response(content)
        resp.headers['Content-Type'] = 'text/html; charset=utf-8'
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp
    return send_from_directory(os.path.dirname(file_path), os.path.basename(file_path))


# ----------------------------------------------------------------------------
# İpuçları
# ----------------------------------------------------------------------------
@api_bp.route('/cases/<case_id>/hints', methods=['GET'])
@token_required
def case_hints(case_id):
    locked = _require_owned(case_id)
    if locked:
        return locked
    lang = _lang()
    now = _dt.datetime.utcnow()
    user = g.api_user
    unlocked = (user.unlocked_hints or '').split(',')
    out = []
    hints = Hint.query.filter_by(case_id=case_id, is_active=True).order_by(Hint.show_datetime).all()
    for h in hints:
        is_unlocked = str(h.id) in unlocked
        time_released = h.show_datetime is not None and now >= h.show_datetime
        available = is_unlocked or time_released
        out.append({
            'id': h.id,
            'unlock_price': h.unlock_price,
            'show_datetime': h.show_datetime.isoformat() if h.show_datetime else None,
            'time_released': time_released,
            'unlocked': is_unlocked,
            'available': available,
            'hint_text': _loc(h, 'hint_text', lang) if available else None,
            'hint_file_url': _abs(f"/vaka/{case_id}/dosya/{h.hint_file}") if (available and h.hint_file) else None,
        })
    return jsonify({'hints': out})


@api_bp.route('/hints/<int:hint_id>/use', methods=['POST'])
@token_required
def use_hint(hint_id):
    """Süresi gelmiş (ücretsiz) bir ipucunu kullanır; puan kırması uygular."""
    user = g.api_user
    hint = Hint.query.get(hint_id)
    if not hint:
        return jsonify({'error': 'not_found', 'message': 'İpucu bulunamadı.'}), 404
    locked = _require_owned(hint.case_id)
    if locked:
        return locked
    now = _dt.datetime.utcnow()
    unlocked = (user.unlocked_hints or '').split(',')
    time_released = hint.show_datetime is not None and now >= hint.show_datetime
    if str(hint_id) not in unlocked and not time_released:
        return jsonify({'error': 'payment_required', 'message': 'Bu ipucu henüz açılmadı. Satın alın veya zamanını bekleyin.'}), 402
    progress = GameProgress.query.filter_by(user_id=user.id, case_id=hint.case_id).first()
    if not progress:
        progress = GameProgress(user_id=user.id, case_id=hint.case_id)
        db.session.add(progress)
    if progress.is_solved:
        return jsonify({'error': 'already_solved', 'message': 'Vaka zaten çözülmüş.'}), 400
    progress.hints_used = (progress.hints_used or 0) + 1
    db.session.commit()
    lang = _lang()
    return jsonify({
        'hint_text': _loc(hint, 'hint_text', lang),
        'hints_used': progress.hints_used,
    })


# ----------------------------------------------------------------------------
# Rapor gönderme
# ----------------------------------------------------------------------------
@api_bp.route('/cases/<case_id>/report-suspect', methods=['POST'])
@token_required
def report_suspect(case_id):
    """Klasik şüpheli seçimi ile çözüm denemesi."""
    data = request.get_json(silent=True) or {}
    suspect_id = data.get('suspect_id')
    suspect = Suspect.query.get(suspect_id)
    case = Case.query.get(case_id)
    user = g.api_user
    if not case:
        return jsonify({'error': 'not_found', 'message': 'Vaka bulunamadı.'}), 404
    locked = _require_owned(case_id)
    if locked:
        return locked
    if suspect and suspect.is_culprit and suspect.case_id == case_id:
        points_map = {"Zor": 100, "Orta": 75, "Kolay": 50}
        vaka_puani = points_map.get(case.difficulty, 75)
        if case not in user.solved_cases_list:
            user.solved_cases_list.append(case)
            user.score = (user.score or 0) + vaka_puani
            db.session.commit()
            msg = f"Tebrikler! Katili buldunuz ve {vaka_puani} puan kazandınız!"
        else:
            msg = "Tebrikler! Katili tekrar buldunuz (Puan daha önce alınmıştı)."
        return jsonify({'status': 'success', 'correct': True, 'message': msg,
                        'success_message': _loc(case, 'success_message', _lang())})
    return jsonify({'status': 'fail', 'correct': False, 'message': 'Yanlış Şüpheli! Kanıtları tekrar inceleyin.'})


@api_bp.route('/cases/<case_id>/report-text', methods=['POST'])
@token_required
def report_text(case_id):
    """Serbest metin (suçlu adı + açıklama) ile çözüm denemesi. Web ile aynı kurallar."""
    data = request.get_json(silent=True) or {}
    culprit_text = (data.get('culprit_text') or '').strip().lower()
    explanation_text = (data.get('explanation_text') or '').strip().lower()
    elapsed_seconds = data.get('elapsed_seconds')
    if not culprit_text:
        return jsonify({'error': 'missing_culprit', 'message': 'Suçlu adı zorunludur.'}), 400
    user = g.api_user
    case = Case.query.get(case_id)
    if not case:
        return jsonify({'error': 'not_found', 'message': 'Vaka bulunamadı.'}), 404
    locked = _require_owned(case_id)
    if locked:
        return locked

    progress = GameProgress.query.filter_by(user_id=user.id, case_id=case_id).first()
    if not progress:
        progress = GameProgress(user_id=user.id, case_id=case_id, attempts_used=0, hints_used=0)
        db.session.add(progress)
    if progress.attempts_used is None:
        progress.attempts_used = 0
    if progress.hints_used is None:
        progress.hints_used = 0

    if progress.is_solved:
        progress.attempts_used = 0
        progress.hints_used = 0
        progress.is_solved = False
        progress.is_failed = False
        progress.points_earned = 0

    if progress.is_failed and progress.last_attempt_time:
        wait_time = progress.last_attempt_time + _dt.timedelta(hours=3)
        if _dt.datetime.utcnow() < wait_time:
            return jsonify({'success': False, 'message': '3 saat sonra tekrar deneyin.',
                            'wait_until': wait_time.isoformat()})
        progress.attempts_used = 0
        progress.is_failed = False
        progress.hints_used = 0

    if progress.attempts_used >= 2:
        return jsonify({'success': False, 'message': 'Tahmin hakkınız kalmadı.', 'attempts_remaining': 0})

    progress.attempts_used += 1
    progress.last_attempt_time = _dt.datetime.utcnow()

    culprit_keywords = [k.strip().lower() for k in (case.culprit_keywords or '').split(',') if k.strip()]
    explanation_keywords = [k.strip().lower() for k in (case.explanation_keywords or '').split(',') if k.strip()]
    culprit_match = any(kw in culprit_text for kw in culprit_keywords)
    explanation_match = True
    if explanation_keywords:
        explanation_match = any(kw in explanation_text for kw in explanation_keywords)
    is_correct = culprit_match and explanation_match

    if is_correct:
        base_points = DIFFICULTY_POINTS.get(case.difficulty, 200)
        final_points = base_points
        final_points -= base_points * (progress.hints_used * 0.03)
        if progress.attempts_used == 2:
            final_points -= base_points * 0.25
        final_points = max(0, round(final_points, 1))
        progress.points_earned = final_points
        progress.is_solved = True
        if elapsed_seconds is not None:
            try:
                progress.play_time_seconds = int(elapsed_seconds)
            except (TypeError, ValueError):
                pass
        user.score = (user.score or 0) + final_points
        db.session.commit()
        return jsonify({'success': True, 'correct': True, 'message': 'Tebrikler! Davayı çözdünüz!',
                        'points_earned': final_points, 'base_points': base_points,
                        'hints_used': progress.hints_used, 'attempt_number': progress.attempts_used,
                        'success_message': _loc(case, 'success_message', _lang())})
    attempts_remaining = 2 - progress.attempts_used
    if attempts_remaining > 0:
        db.session.commit()
        feedback = 'Yanlış tahmin!'
        if not culprit_match:
            feedback += ' Suçlu adını kontrol edin.'
        elif not explanation_match:
            feedback += ' Açıklamanızı geliştirin.'
        return jsonify({'success': True, 'correct': False,
                        'message': f'{feedback} {attempts_remaining} hakkınız kaldı.',
                        'attempts_remaining': attempts_remaining})
    base_points = DIFFICULTY_POINTS.get(case.difficulty, 200)
    penalty_points = base_points * 0.50
    progress.is_failed = True
    progress.points_earned = -penalty_points
    user.score = max(0, (user.score or 0) - penalty_points)
    db.session.commit()
    wait_time = _dt.datetime.utcnow() + _dt.timedelta(hours=3)
    return jsonify({'success': True, 'correct': False,
                    'message': '2 hakkınızı da kullandınız. 3 saat sonra tekrar deneyin.',
                    'attempts_remaining': 0, 'penalty_points': penalty_points,
                    'wait_until': wait_time.isoformat()})


# ----------------------------------------------------------------------------
# Profil / kullanıcının vakaları
# ----------------------------------------------------------------------------
@api_bp.route('/me/cases', methods=['GET'])
@token_required
def my_cases():
    lang = _lang()
    user = g.api_user
    owned_ids = set((user.unlocked_cases or '').split(','))
    for p in Purchase.query.filter_by(user_id=user.id, is_paid=True).all():
        owned_ids.add(p.case_id)
    owned_ids.discard('')
    out = []
    for cid in owned_ids:
        case = Case.query.get(cid)
        if not case:
            continue
        progress = GameProgress.query.filter_by(user_id=user.id, case_id=cid).first()
        brief = _case_brief(case, user, lang)
        brief['progress'] = {
            'is_solved': bool(progress.is_solved) if progress else False,
            'attempts_used': (progress.attempts_used or 0) if progress else 0,
            'hints_used': (progress.hints_used or 0) if progress else 0,
            'points_earned': (progress.points_earned or 0) if progress else 0,
        }
        out.append(brief)
    return jsonify({'cases': out})


# ----------------------------------------------------------------------------
# Ödeme (mobil): mevcut web 3D Secure akışını WebView içinde açma köprüsü
# ----------------------------------------------------------------------------
@api_bp.route('/payments/methods', methods=['GET'])
@optional_auth
def payment_methods():
    s = get_payment_settings()
    return jsonify({'methods': {
        'iyzico': s.get('iyzico_enabled') == '1',
        'havale': s.get('havale_enabled') == '1',
        'param': s.get('param_enabled') == '1',
        'paynkolay': s.get('paynkolay_enabled') == '1',
    }})


@api_bp.route('/payments/checkout', methods=['POST'])
@token_required
def payment_checkout():
    """
    Native uygulama bu uca (Bearer token ile) istek atar; tek kullanımlık,
    kısa ömürlü (5 dk) bir 'bridge' token içeren WebView URL'i alır.
    Bridge token yalnızca ödeme köprüsünde geçerlidir; API erişimi sağlamaz.
    """
    data = request.get_json(silent=True) or {}
    case_id = (data.get('case_id') or '').strip()
    user = g.api_user
    now = _dt.datetime.utcnow()
    bridge = jwt.encode({
        'uid': user.id,
        'type': 'payment_bridge',
        'case_id': case_id,
        'iat': now,
        'exp': now + _dt.timedelta(minutes=5),
    }, _secret(), algorithm='HS256')
    url = _abs('/api/v1/payments/start') + f"?bt={bridge}"
    return jsonify({'checkout_url': url, 'expires_in': 300})


@api_bp.route('/payments/start', methods=['GET'])
def payment_start():
    """
    /payments/checkout'tan alınan tek kullanımlık bridge token ile çağrılır.
    Sunucu oturumu kurulur ve mevcut web ödeme akışına (3D Secure) yönlendirilir.
    Ödeme bitince uygulama /api/v1/me/cases ile durumu kontrol edebilir.
    """
    bt = request.args.get('bt', '')
    try:
        payload = _decode_token(bt)
        if payload.get('type') != 'payment_bridge':
            raise ValueError('type')
        user = db.session.get(User, payload.get('uid'))
        if not user:
            raise ValueError('user')
    except Exception:
        abort(401)
    case_id = payload.get('case_id') or ''
    session['user_id'] = user.id
    session['username'] = user.username
    if case_id and Case.query.get(case_id):
        return redirect(f"/payment/select/{case_id}")
    return redirect("/cases")


def register_api(flask_app):
    """main.py tarafından çağrılır: ana modül nesnelerini bağlar, CORS + blueprint kaydı."""
    global app, db, User, Case, CaseFile, Suspect, Hint, Purchase, GameProgress
    global DIFFICULTY_POINTS, get_payment_settings, personalize_case_html, UPLOAD_FOLDER
    m = sys.modules.get(flask_app.import_name) or sys.modules.get('main') or sys.modules.get('__main__')
    app = flask_app
    db = m.db
    User, Case, CaseFile, Suspect = m.User, m.Case, m.CaseFile, m.Suspect
    Hint, Purchase, GameProgress = m.Hint, m.Purchase, m.GameProgress
    DIFFICULTY_POINTS = m.DIFFICULTY_POINTS
    get_payment_settings = m.get_payment_settings
    personalize_case_html = m.personalize_case_html
    UPLOAD_FOLDER = m.UPLOAD_FOLDER
    try:
        from flask_cors import CORS
        CORS(flask_app, resources={r"/api/*": {"origins": "*"}},
             supports_credentials=False,
             allow_headers=["Authorization", "Content-Type"],
             methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
    except Exception as exc:  # pragma: no cover
        print(f"[api] flask-cors kurulamadı/uygulanamadı: {exc}")
    flask_app.register_blueprint(api_bp)
    print("[api] /api/v1 mobil API katmanı kaydedildi.")
