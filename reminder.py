import firebase_admin
from firebase_admin import credentials, firestore
import smtplib, os, json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

# Init Firebase Admin
sa_dict = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
cred    = credentials.Certificate(sa_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

# Date setup — Riyadh UTC+3
tz_riyadh  = timezone(timedelta(hours=3))
today      = datetime.now(tz_riyadh).date()
target     = today + timedelta(days=2)
target_str = target.strftime('%Y-%m-%d')
print(f"Checking flights for: {target_str}")

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

for user_doc in db.collection('users').stream():
    uid = user_doc.id

    settings = db.collection('users').doc(uid).collection('data').document('settings').get()
    if not settings.exists:
        continue
    notif_email = settings.to_dict().get('notifEmail', '')
    if not notif_email or '@' not in notif_email:
        continue

    tickets_doc = db.collection('users').doc(uid).collection('data').document('tickets').get()
    if not tickets_doc.exists:
        continue
    tickets = tickets_doc.to_dict().get('tickets', [])

    upcoming = [t for t in tickets
                if t.get('flightDate') == target_str
                and not t.get('missed', False)]

    if not upcoming:
        print(f"No flights for {notif_email}")
        continue

    print(f"Found {len(upcoming)} flight(s) for {notif_email}")

    rows = ''
    for t in upcoming:
        route    = 'RUH → JED' if t.get('ticketType') == 'go' else 'JED → RUH'
        paid_str = 'مدفوع' if t.get('paid') else 'غير مدفوع'
        fn       = t.get('flightNumber') or t.get('pnr') or '—'
        rows += (
            '<tr>'
            f'<td style="padding:12px 16px;border-bottom:1px solid #e5e7eb;font-weight:700">{route}</td>'
            f'<td style="padding:12px 16px;border-bottom:1px solid #e5e7eb">{fmt_date(t.get("flightDate",""))}</td>'
            f'<td style="padding:12px 16px;border-bottom:1px solid #e5e7eb">{fmt_time(t.get("flightTime",""))}</td>'
            f'<td style="padding:12px 16px;border-bottom:1px solid #e5e7eb">{t.get("airline","—")}</td>'
            f'<td style="padding:12px 16px;border-bottom:1px solid #e5e7eb;font-family:monospace">{fn}</td>'
            f'<td style="padding:12px 16px;border-bottom:1px solid #e5e7eb">{t.get("category","—")}</td>'
            f'<td style="padding:12px 16px;border-bottom:1px solid #e5e7eb">{paid_str}</td>'
            '</tr>'
        )

    html = (
        '<div style="font-family:Arial,sans-serif;direction:rtl;max-width:620px;margin:0 auto;background:#f1f5f9;padding:24px;border-radius:16px">'
        '<div style="background:linear-gradient(135deg,#0f1f3d,#1a3a6b);padding:28px;border-radius:12px;text-align:center;margin-bottom:20px">'
        '<div style="font-size:40px">&#9992;</div>'
        '<div style="color:white;font-size:22px;font-weight:900;margin-top:8px">تذكير رحلة قادمة</div>'
        '<div style="color:#93c5fd;font-size:14px;margin-top:6px">رحلاتي RUH &#8596; JED</div>'
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
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(GMAIL_USER, GMAIL_PASS)
            smtp.sendmail(GMAIL_USER, notif_email, msg.as_bytes())
        print(f"Sent to {notif_email}")
        sent += 1
    except Exception as e:
        print(f"Failed to send to {notif_email}: {e}")

print(f"Done — {sent} email(s) sent")
