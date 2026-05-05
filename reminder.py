import os, json, urllib.request, urllib.parse
import google.auth.transport.requests
import google.oauth2.service_account
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

sa_dict    = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
PROJECT_ID = sa_dict.get('project_id')
DB_ID      = '(default)'
BASE       = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/{DB_ID}/documents"

SCOPES = ['https://www.googleapis.com/auth/datastore',
          'https://www.googleapis.com/auth/cloud-platform']
gsa_creds = google.oauth2.service_account.Credentials.from_service_account_info(
    sa_dict, scopes=SCOPES)
gsa_creds.refresh(google.auth.transport.requests.Request())
token = gsa_creds.token
print(f"Project: {PROJECT_ID} ✅")

def rest_get(path):
    req = urllib.request.Request(f"{BASE}/{path}",
        headers={'Authorization': f'Bearer {token}'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {'_error': e.code, '_msg': e.read().decode()[:200]}

def run_query(parent, query):
    url  = f"{BASE}/{parent}:runQuery"
    req  = urllib.request.Request(url,
        data=json.dumps({'structuredQuery': query}).encode(),
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return [{'_error': e.code, '_msg': e.read().decode()[:300]}]

def list_collection_ids(parent_path):
    url = f"{BASE}/{parent_path}:listCollectionIds" if parent_path else f"{BASE}:listCollectionIds"
    req = urllib.request.Request(url,
        data=json.dumps({}).encode(),
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()).get('collectionIds', [])
    except urllib.error.HTTPError as e:
        return [f"error:{e.code}"]

def get_field_value(field):
    if not field: return None
    for ftype in ['stringValue','booleanValue','integerValue','doubleValue','nullValue']:
        if ftype in field:
            return field[ftype]
    if 'arrayValue' in field:
        return [get_field_value(v) for v in field['arrayValue'].get('values', [])]
    if 'mapValue' in field:
        return {k: get_field_value(v) for k,v in field['mapValue'].get('fields',{}).items()}
    return None

# Step 1: Find all UIDs via runQuery
print("\n[1] Finding users via runQuery...")
results = run_query('', {
    'from': [{'collectionId': 'users', 'allDescendants': False}],
    'limit': 50
})
uids = []
for r in results:
    doc = r.get('document', {})
    name = doc.get('name', '')
    if name:
        uid = name.split('/')[-1]
        uids.append(uid)
        print(f"  Found UID: {uid[:16]}...")

print(f"Total UIDs: {len(uids)}")

# Date setup
tz_riyadh  = timezone(timedelta(hours=3))
today      = datetime.now(tz_riyadh).date()
target     = today + timedelta(days=2)
target_str = target.strftime('%Y-%m-%d')
print(f"Target date: {target_str}")

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
        h, m = map(int, t.split(':'))
        period = 'ص' if h < 12 else 'م'
        h12    = 12 if h == 0 else (h if h <= 12 else h - 12)
        return f"{h12}:{str(m).zfill(2)} {period}"
    except:
        return t

sent = 0

for uid in uids:
    print(f"\n--- User: {uid[:16]}... ---")

    # Get subcollections under this user
    sub_cols = list_collection_ids(f"users/{uid}")
    print(f"  Subcollections: {sub_cols}")

    # Get settings
    settings = rest_get(f"users/{uid}/data/settings")
    if '_error' in settings:
        # Try direct fields approach
        print(f"  Settings error: {settings.get('_error')} — trying data collection...")
        data_col = rest_get(f"users/{uid}/data")
        print(f"  Data collection: {list(data_col.keys())[:5]}")
        continue

    fields = settings.get('fields', {})
    notif_email = get_field_value(fields.get('notifEmail', {})) or ''
    print(f"  Email: '{notif_email}'")

    if not notif_email or '@' not in str(notif_email):
        # Try listCollectionIds to find correct path
        data_docs = rest_get(f"users/{uid}/data")
        docs_list = data_docs.get('documents', [])
        print(f"  Data docs: {[d.get('name','').split('/')[-1] for d in docs_list]}")
        continue

    # Get tickets
    tickets_doc = rest_get(f"users/{uid}/data/tickets")
    if '_error' in tickets_doc:
        print(f"  Tickets error: {tickets_doc.get('_error')}")
        continue

    t_fields  = tickets_doc.get('fields', {})
    t_arr_raw = t_fields.get('tickets', {}).get('arrayValue', {}).get('values', [])
    tickets   = [get_field_value(v) for v in t_arr_raw]
    print(f"  Tickets: {len(tickets)}")

    upcoming = [t for t in tickets
                if isinstance(t, dict)
                and t.get('flightDate') == target_str
                and not t.get('missed', False)]
    print(f"  Upcoming ({target_str}): {len(upcoming)}")

    if not upcoming:
        continue

    # Build & send email
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
        '<div style="font-family:Arial,sans-serif;direction:rtl;max-width:620px;'
        'margin:0 auto;background:#f1f5f9;padding:24px;border-radius:16px">'
        '<div style="background:linear-gradient(135deg,#0f1f3d,#1a3a6b);padding:28px;'
        'border-radius:12px;text-align:center;margin-bottom:20px">'
        '<div style="font-size:40px">&#9992;</div>'
        '<div style="color:white;font-size:22px;font-weight:900;margin-top:8px">تذكير رحلة قادمة</div>'
        '<div style="color:#93c5fd;font-size:14px;margin-top:6px">رحلاتي RUH JED</div>'
        '</div>'
        '<div style="background:white;border-radius:12px;padding:20px;margin-bottom:16px">'
        f'<div style="font-size:16px;font-weight:800;color:#1e3a5f;margin-bottom:16px">'
        f'لديك {len(upcoming)} رحلة بعد يومين — {fmt_date(target_str)}</div>'
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
        '<div style="background:#dbeafe;border-radius:10px;padding:14px;'
        'font-size:13px;color:#1e40af;margin-bottom:16px">'
        'تأكد من حجزك وتجهيز حقائبك — رحلة موفقة!</div>'
        '<div style="text-align:center;font-size:11px;color:#94a3b8">'
        'رحلاتي RUH JED — تذكير تلقائي</div></div>'
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
