import os, json, urllib.request
import google.auth.transport.requests
import google.oauth2.service_account
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

PROJECT_ID = 'mytrips-9b054'
sa_dict    = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])

# Get users from SECRET directly
# Read from env (GitHub Actions variable)
    USERS_CONFIG = os.environ.get('USERS_CONFIG', '[]')
users_list   = json.loads(USERS_CONFIG)
# Format: [{"uid": "xxx", "email": "xxx@gmail.com"}]
print(f"Users from config: {len(users_list)}")

SCOPES = ['https://www.googleapis.com/auth/datastore',
          'https://www.googleapis.com/auth/cloud-platform']
gsa_creds = google.oauth2.service_account.Credentials.from_service_account_info(
    sa_dict, scopes=SCOPES)
gsa_creds.refresh(google.auth.transport.requests.Request())
token = gsa_creds.token

BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents"

def rest_get(path):
    req = urllib.request.Request(f"{BASE}/{path}",
        headers={'Authorization': f'Bearer {token}'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {'_error': e.code, '_msg': e.read().decode()[:200]}

def get_val(field):
    if not field: return None
    for t in ['stringValue','booleanValue','integerValue','doubleValue']:
        if t in field: return field[t]
    if 'arrayValue' in field:
        return [get_val(v) for v in field['arrayValue'].get('values', [])]
    if 'mapValue' in field:
        return {k: get_val(v) for k,v in field['mapValue'].get('fields',{}).items()}
    return None

tz_riyadh  = timezone(timedelta(hours=3))
today      = datetime.now(tz_riyadh).date()

# ── تذكيرات متعددة: اليوم التالي، يومين، 3 أيام، أسبوع ──
REMINDER_DAYS = [1, 2, 3, 7]  # ← غيّر هذه القيم حسب رغبتك
target_dates  = [(today + timedelta(days=d)).strftime('%Y-%m-%d') for d in REMINDER_DAYS]
print(f"Checking dates: {target_dates}")

GMAIL_USER = os.environ['GMAIL_USER']
GMAIL_PASS = os.environ['GMAIL_APP_PASSWORD'].replace(' ', '')

MONTHS_AR = ['يناير','فبراير','مارس','أبريل','مايو','يونيو',
             'يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر']

def fmt_date(d):
    try:
        dt = datetime.strptime(d, '%Y-%m-%d')
        return f"{dt.day} {MONTHS_AR[dt.month-1]} {dt.year}"
    except: return d or '—'

def fmt_time(t):
    if not t: return '—'
    try:
        h, m = map(int, t.split(':'))
        period = 'ص' if h < 12 else 'م'
        h12 = 12 if h==0 else (h if h<=12 else h-12)
        return f"{h12}:{str(m).zfill(2)} {period}"
    except: return t

sent = 0

for user in users_list:
    uid         = user.get('uid', '')
    notif_email = user.get('email', '')
    print(f"\n--- User: {uid[:16]}... | Email: {notif_email} ---")

    if not uid or not notif_email:
        print("  Missing uid or email — skipping")
        continue

    # Get tickets directly
    tickets_doc = rest_get(f"users/{uid}/data/tickets")
    if '_error' in tickets_doc:
        print(f"  Tickets error: {tickets_doc.get('_error')} {tickets_doc.get('_msg','')[:100]}")
        continue

    t_fields  = tickets_doc.get('fields', {})
    t_arr_raw = t_fields.get('tickets', {}).get('arrayValue', {}).get('values', [])
    tickets   = [get_val(v) for v in t_arr_raw]
    print(f"  Total tickets: {len(tickets)}")

    # Check settings for email override
    settings = rest_get(f"users/{uid}/data/settings")
    if '_error' not in settings:
        saved_email = get_val(settings.get('fields',{}).get('notifEmail', {}))
        if saved_email and '@' in str(saved_email):
            notif_email = saved_email
            print(f"  Email from settings: {notif_email}")

    upcoming = [t for t in tickets
                if isinstance(t, dict)
                and t.get('flightDate') in target_dates
                and not t.get('missed', False)]
    # Sort by date
    upcoming.sort(key=lambda t: t.get('flightDate',''))
    print(f"  Upcoming in next {max(REMINDER_DAYS)} days: {len(upcoming)}")

    if not upcoming:
        continue

    rows = ''
    for t in upcoming:
        route    = 'RUH → JED' if t.get('ticketType') == 'go' else 'JED → RUH'
        paid_str = 'مدفوع' if t.get('paid') else 'غير مدفوع'
        fn       = t.get('flightNumber') or t.get('pnr') or '—'
        rows += (
            '<tr>'
            f'<td style="padding:12px;border-bottom:1px solid #e5e7eb;font-weight:700">{route}</td>'
            f'<td style="padding:12px;border-bottom:1px solid #e5e7eb">{fmt_date(t.get("flightDate",""))}</td>'
            f'<td style="padding:12px;border-bottom:1px solid #e5e7eb">{fmt_time(t.get("flightTime",""))}</td>'
            f'<td style="padding:12px;border-bottom:1px solid #e5e7eb">{t.get("airline","—")}</td>'
            f'<td style="padding:12px;border-bottom:1px solid #e5e7eb;font-family:monospace">{fn}</td>'
            f'<td style="padding:12px;border-bottom:1px solid #e5e7eb">{t.get("category","—")}</td>'
            f'<td style="padding:12px;border-bottom:1px solid #e5e7eb">{paid_str}</td>'
            '</tr>'
        )

    html = (
        '<div style="font-family:Arial,sans-serif;direction:rtl;max-width:620px;margin:0 auto;background:#f1f5f9;padding:24px;border-radius:16px">'
        '<div style="background:linear-gradient(135deg,#0f1f3d,#1a3a6b);padding:28px;border-radius:12px;text-align:center;margin-bottom:20px">'
        '<div style="font-size:40px">&#9992;</div>'
        '<div style="color:white;font-size:22px;font-weight:900;margin-top:8px">تذكير رحلة قادمة</div>'
        '<div style="color:#93c5fd;font-size:14px;margin-top:6px">رحلاتي RUH JED</div>'
        '</div>'
        '<div style="background:white;border-radius:12px;padding:20px;margin-bottom:16px">'
        f'<div style="font-size:16px;font-weight:800;color:#1e3a5f;margin-bottom:16px">لديك {len(upcoming)} رحلة بعد يومين — {fmt_date(target_str)}</div>'
        '<table style="width:100%;border-collapse:collapse;font-size:13px">'
        '<thead><tr style="background:#1e3a5f;color:white">'
        '<th style="padding:12px;text-align:right">الرحلة</th>'
        '<th style="padding:12px;text-align:right">التاريخ</th>'
        '<th style="padding:12px;text-align:right">الوقت</th>'
        '<th style="padding:12px;text-align:right">الخط</th>'
        '<th style="padding:12px;text-align:right">رقم الرحلة</th>'
        '<th style="padding:12px;text-align:right">التصنيف</th>'
        '<th style="padding:12px;text-align:right">الدفع</th>'
        '</tr></thead>'
        f'<tbody>{rows}</tbody></table></div>'
        '<div style="background:#dbeafe;border-radius:10px;padding:14px;font-size:13px;color:#1e40af;margin-bottom:16px">'
        'تأكد من حجزك وتجهيز حقائبك — رحلة موفقة!</div>'
        '<div style="text-align:center;font-size:11px;color:#94a3b8">رحلاتي RUH JED — تذكير تلقائي</div>'
        '</div>'
    )

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"✈ تذكير — لديك {len(upcoming)} رحلة قادمة"
    msg['From']    = GMAIL_USER
    msg['To']      = notif_email
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    try:
        print(f"  Sending to {notif_email}...")
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(GMAIL_USER, GMAIL_PASS)
            smtp.sendmail(GMAIL_USER, notif_email, msg.as_bytes())
        print("  ✅ Sent!")
        sent += 1
    except Exception as e:
        print(f"  ❌ Email error: {e}")

print(f"\nDone — {sent} email(s) sent")
