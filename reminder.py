import firebase_admin
from firebase_admin import credentials, firestore
import smtplib, os, json, urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
import google.auth.transport.requests
import google.oauth2.service_account

print("Loading service account...")
sa_dict = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
print(f"Project ID: {sa_dict.get('project_id')}")
PROJECT_ID = sa_dict.get('project_id')

# Get access token using service account
SCOPES = ['https://www.googleapis.com/auth/datastore',
          'https://www.googleapis.com/auth/cloud-platform']

gsa_creds = google.oauth2.service_account.Credentials.from_service_account_info(
    sa_dict, scopes=SCOPES)
auth_req = google.auth.transport.requests.Request()
gsa_creds.refresh(auth_req)
token = gsa_creds.token
print(f"Access token obtained: {token[:20]}...")

# Use Firestore REST API directly
def firestore_list(collection_path):
    url = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents/{collection_path}"
    req = urllib.request.Request(url, headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {'error': e.code, 'msg': e.read().decode()}

def get_field(fields, key):
    if not fields or key not in fields:
        return None
    f = fields[key]
    return (f.get('stringValue') or f.get('booleanValue') or
            f.get('doubleValue') or f.get('integerValue') or
            f.get('nullValue'))

# List users
print("\nListing users via REST API...")
users_data = firestore_list('users')
print(f"Response keys: {list(users_data.keys())}")

if 'error' in users_data:
    print(f"Error: {users_data}")
    exit(1)

documents = users_data.get('documents', [])
print(f"Users found: {len(documents)}")

# Date setup
tz_riyadh  = timezone(timedelta(hours=3))
today      = datetime.now(tz_riyadh).date()
target     = today + timedelta(days=2)
target_str = target.strftime('%Y-%m-%d')
print(f"\nTarget date: {target_str}")

GMAIL_USER = os.environ['GMAIL_USER']
GMAIL_PASS = os.environ['GMAIL_APP_PASSWORD'].replace(' ', '')

MONTHS_AR = ['يناير','فبراير','مارس','أبريل','مايو','يونيو',
             'يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر']

def fmt_date(d):
    try:
        dt = datetime.strptime(d, '%Y-%m-%d')
        return f"{dt.day} {MONTHS_AR[dt.month-1]} {dt.year}"
    except:
        return d or '—'

def fmt_time(t):
    if not t: return '—'
    try:
        h, m   = map(int, t.split(':'))
        period = 'ص' if h < 12 else 'م'
        h12    = 12 if h == 0 else (h if h <= 12 else h - 12)
        return f"{h12}:{str(m).zfill(2)} {period}"
    except:
        return t

sent = 0

for user_doc in documents:
    uid = user_doc['name'].split('/')[-1]
    print(f"\n--- User: {uid[:12]}... ---")

    # Get settings
    settings_data = firestore_list(f"users/{uid}/data/settings")
    if 'error' in settings_data:
        print(f"  Settings error: {settings_data}")
        continue
    settings_docs = settings_data.get('documents', [])
    if not settings_docs:
        print("  No settings")
        continue

    fields = settings_docs[0].get('fields', {})
    notif_email = get_field(fields, 'notifEmail') or ''
    print(f"  Email: {notif_email}")
    if not notif_email or '@' not in notif_email:
        print("  No valid email")
        continue

    # Get tickets
    tickets_data = firestore_list(f"users/{uid}/data/tickets")
    if 'error' in tickets_data:
        print(f"  Tickets error: {tickets_data}")
        continue
    tickets_docs = tickets_data.get('documents', [])
    if not tickets_docs:
        print("  No tickets")
        continue

    t_fields = tickets_docs[0].get('fields', {})
    tickets_arr = t_fields.get('tickets', {}).get('arrayValue', {}).get('values', [])
    print(f"  Tickets: {len(tickets_arr)}")

    upcoming = []
    for item in tickets_arr:
        t_map = item.get('mapValue', {}).get('fields', {})
        flight_date = get_field(t_map, 'flightDate')
        if flight_date != target_str:
            continue
        if get_field(t_map, 'missed'):
            continue
        upcoming.append({
            'type':     get_field(t_map, 'ticketType') or '',
            'date':     flight_date or '',
            'time':     get_field(t_map, 'flightTime') or '',
            'airline':  get_field(t_map, 'airline') or '—',
            'pnr':      get_field(t_map, 'pnr') or '',
            'flightNo': get_field(t_map, 'flightNumber') or '',
            'category': get_field(t_map, 'category') or '—',
            'paid':     get_field(t_map, 'paid') or False,
        })

    print(f"  Upcoming ({target_str}): {len(upcoming)}")
    if not upcoming:
        continue

    # Build email
    rows = ''
    for t in upcoming:
        route    = 'RUH → JED' if t['type'] == 'go' else 'JED → RUH'
        paid_str = 'مدفوع' if t['paid'] else 'غير مدفوع'
        fn       = t['flightNo'] or t['pnr'] or '—'
        rows += (
            '<tr>'
            f'<td style="padding:12px;border-bottom:1px solid #e5e7eb;font-weight:700">{route}</td>'
            f'<td style="padding:12px;border-bottom:1px solid #e5e7eb">{fmt_date(t["date"])}</td>'
            f'<td style="padding:12px;border-bottom:1px solid #e5e7eb">{fmt_time(t["time"])}</td>'
            f'<td style="padding:12px;border-bottom:1px solid #e5e7eb">{t["airline"]}</td>'
            f'<td style="padding:12px;border-bottom:1px solid #e5e7eb;font-family:monospace">{fn}</td>'
            f'<td style="padding:12px;border-bottom:1px solid #e5e7eb">{t["category"]}</td>'
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
        f'<tbody>{rows}</tbody>'
        '</table></div>'
        '<div style="background:#dbeafe;border-radius:10px;padding:14px;font-size:13px;color:#1e40af;margin-bottom:16px">'
        'تأكد من حجزك وتجهيز حقائبك — رحلة موفقة!'
        '</div>'
        '<div style="text-align:center;font-size:11px;color:#94a3b8">رحلاتي RUH JED — تذكير تلقائي</div>'
        '</div>'
    )

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"تذكير — رحلتك بعد يومين {fmt_date(target_str)}"
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
