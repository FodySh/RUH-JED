import os, json, urllib.request
import google.auth.transport.requests
import google.oauth2.service_account
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

# ── Config ──
PROJECT_ID   = 'mytrips-9b054'
REMINDER_DAYS = [1, 3, 5, 7]
AVIATION_PROXY = 'https://aviation-proxy.shaheenhouse1.workers.dev'

sa_dict    = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
GMAIL_USER = os.environ['GMAIL_USER']
GMAIL_PASS = os.environ['GMAIL_APP_PASSWORD'].replace(' ', '')

USERS_CONFIG = os.environ.get('USERS_CONFIG', '[]')
users_list   = json.loads(USERS_CONFIG)
print(f"Users from config: {len(users_list)}")
for u in users_list:
    print(f"  - {u.get('uid','')[:16]}... → {u.get('email','')}")

# ── Firebase Auth ──
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
        return {'_error': e.code}

def get_val(field):
    if not field: return None
    for t in ['stringValue','booleanValue','integerValue','doubleValue']:
        if t in field: return field[t]
    if 'arrayValue' in field:
        return [get_val(v) for v in field['arrayValue'].get('values', [])]
    if 'mapValue' in field:
        return {k: get_val(v) for k,v in field['mapValue'].get('fields',{}).items()}
    return None

# ── Aviation Stack ──
def fetch_flight_info(flight_number):
    """Fetch live flight data from AviationStack via Worker"""
    if not flight_number:
        return None
    try:
        url = f"{AVIATION_PROXY}?flight={urllib.parse.quote(flight_number)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'reminder-bot/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        if data.get('data') and len(data['data']) > 0:
            return data['data'][0]
    except Exception as e:
        print(f"    Aviation fetch error for {flight_number}: {e}")
    return None

def fmt_aviation_time(iso):
    """Convert UTC ISO to Riyadh time (UTC+3)"""
    if not iso:
        return '—'
    try:
        # Parse ISO with or without timezone
        iso_clean = iso.replace('+00:00', '').replace('Z', '')
        dt = datetime.strptime(iso_clean[:16], '%Y-%m-%dT%H:%M')
        dt_riyadh = dt + timedelta(hours=3)
        h, m = dt_riyadh.hour, dt_riyadh.minute
        period = 'ص' if h < 12 else 'م'
        h12 = 12 if h == 0 else (h if h <= 12 else h - 12)
        return f"{h12}:{str(m).zfill(2)} {period}"
    except:
        return iso[:16] if iso else '—'

import urllib.parse

# ── Dates ──
tz_riyadh    = timezone(timedelta(hours=3))
today        = datetime.now(tz_riyadh).date()
target_dates = [(today + timedelta(days=d)).strftime('%Y-%m-%d') for d in REMINDER_DAYS]
print(f"Checking dates: {target_dates}")

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
        h12    = 12 if h==0 else (h if h<=12 else h-12)
        return f"{h12}:{str(m).zfill(2)} {period}"
    except: return t

sent = 0

for user in users_list:
    uid         = user.get('uid', '').strip()
    notif_email = user.get('email', '').strip()

    print(f"\n--- User: {uid[:16]}... | Email: {notif_email} ---")

    if not uid or not notif_email or '@' not in notif_email:
        print("  Missing uid or email — skipping")
        continue

    tickets_doc = rest_get(f"users/{uid}/data/tickets")
    if '_error' in tickets_doc:
        print(f"  Tickets error: {tickets_doc.get('_error')}")
        continue

    t_fields  = tickets_doc.get('fields', {})
    t_arr_raw = t_fields.get('tickets', {}).get('arrayValue', {}).get('values', [])
    tickets   = [get_val(v) for v in t_arr_raw]
    print(f"  Total tickets: {len(tickets)}")

    upcoming = [t for t in tickets
                if isinstance(t, dict)
                and t.get('flightDate') in target_dates
                and not t.get('missed', False)]
    upcoming.sort(key=lambda t: t.get('flightDate', ''))
    print(f"  Upcoming in next {max(REMINDER_DAYS)} days: {len(upcoming)}")

    if not upcoming:
        continue

    rows = ''
    for t in upcoming:
        route      = 'RUH → JED 🛫' if t.get('ticketType') == 'go' else 'JED → RUH 🛬'
        paid_str   = 'مدفوع ✅' if t.get('paid') else 'غير مدفوع ⏳'
        paid_color = '#10b981' if t.get('paid') else '#f43f5e'
        fn         = t.get('flightNumber') or '—'
        pnr        = t.get('pnr') or '—'
        days_left  = (datetime.strptime(t['flightDate'], '%Y-%m-%d').date() - today).days
        days_label = 'اليوم 🔴' if days_left == 0 else 'غداً 🟡' if days_left == 1 else f'بعد {days_left} أيام'
        transport  = t.get('transport', 0) or 0
        total      = (t.get('ticketPrice', 0) or 0) + transport

        # ── Fetch live aviation data ──
        av = None
        if t.get('flightNumber'):
            print(f"    Fetching aviation data for {t['flightNumber']}...")
            av = fetch_flight_info(t['flightNumber'])

        # Build aviation info block
        if av:
            dep = av.get('departure', {})
            arr = av.get('arrival', {})
            status_map = {
                'scheduled': ('في الموعد', '#10b981'),
                'active':    ('في الجو الآن', '#3b82f6'),
                'landed':    ('هبطت', '#6366f1'),
                'cancelled': ('ملغاة', '#f43f5e'),
                'diverted':  ('حُوِّلت', '#f59e0b'),
            }
            st_label, st_color = status_map.get(av.get('flight_status', ''), ('—', '#64748b'))

            dep_sched  = fmt_aviation_time(dep.get('scheduled'))
            dep_actual = fmt_aviation_time(dep.get('actual') or dep.get('estimated'))
            arr_sched  = fmt_aviation_time(arr.get('scheduled'))
            arr_actual = fmt_aviation_time(arr.get('actual') or arr.get('estimated'))
            dep_delay  = dep.get('delay')
            arr_delay  = arr.get('delay')
            dep_gate   = dep.get('gate') or '—'
            dep_term   = dep.get('terminal') or '—'
            arr_term   = arr.get('terminal') or '—'
            dep_airport = dep.get('airport') or dep.get('iata') or '—'
            arr_airport = arr.get('airport') or arr.get('iata') or '—'

            av_block = f"""
            <tr>
              <td colspan="2" style="padding:0 12px 12px">
                <div style="background:#f0f9ff;border-radius:10px;padding:14px;border-right:4px solid {st_color}">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
                    <span style="font-size:13px;font-weight:900;font-family:monospace">{av.get('flight',{}).get('iata', fn)}</span>
                    <span style="background:{st_color}22;color:{st_color};padding:3px 10px;border-radius:20px;font-size:12px;font-weight:700">{st_label}</span>
                  </div>
                  <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;font-size:12px">
                    <div style="background:white;border-radius:8px;padding:10px;border-right:3px solid #f59e0b">
                      <div style="color:#f59e0b;font-weight:800;margin-bottom:6px">🛫 إقلاع</div>
                      <div><span style="color:#6b7280">مجدول:</span> <strong>{dep_sched}</strong></div>
                      {"<div style='color:#10b981'><strong>فعلي: " + dep_actual + "</strong></div>" if dep.get('actual') else ""}
                      {"<div style='color:#f59e0b'>⏱ تأخير " + str(dep_delay) + " د</div>" if dep_delay else ""}
                      <div style="margin-top:4px;color:#6b7280">
                        {"🏢 T" + dep_term + " " if dep_term != "—" else ""}
                        {"🚪 " + dep_gate + " " if dep_gate != "—" else ""}
                        {"📍 " + dep_airport}
                      </div>
                    </div>
                    <div style="background:white;border-radius:8px;padding:10px;border-right:3px solid #06b6d4">
                      <div style="color:#06b6d4;font-weight:800;margin-bottom:6px">🛬 وصول</div>
                      <div><span style="color:#6b7280">مجدول:</span> <strong>{arr_sched}</strong></div>
                      {"<div style='color:#10b981'><strong>فعلي: " + arr_actual + "</strong></div>" if arr.get('actual') else ""}
                      {"<div style='color:#f59e0b'>⏱ تأخير " + str(arr_delay) + " د</div>" if arr_delay else ""}
                      <div style="margin-top:4px;color:#6b7280">
                        {"🏢 T" + arr_term + " " if arr_term != "—" else ""}
                        {"📍 " + arr_airport}
                      </div>
                    </div>
                  </div>
                </div>
              </td>
            </tr>"""
        else:
            av_block = ''

        rows += f"""
        <tr style="background:#f8fafc">
          <td style="padding:14px 12px;border-bottom:1px solid #e5e7eb">
            <div style="font-weight:800;font-size:14px;margin-bottom:4px">{route}</div>
            <div style="font-size:13px;color:#374151">{fmt_date(t.get('flightDate',''))}</div>
            <div style="font-size:12px;color:#6b7280;margin-top:2px">{t.get('airline','—')}</div>
          </td>
          <td style="padding:14px 12px;border-bottom:1px solid #e5e7eb">
            <div style="display:flex;flex-direction:column;gap:4px">
              <span style="background:#ede9fe;color:#6d28d9;padding:3px 8px;border-radius:20px;font-size:12px;font-weight:700;width:fit-content">{days_label}</span>
              <div style="font-size:13px"><strong>⏰ {fmt_time(t.get('flightTime',''))}</strong></div>
              <div style="font-size:12px;font-family:monospace;color:#374151">✈ {fn} &nbsp; 🎫 {pnr}</div>
              <div style="font-size:12px;color:{paid_color};font-weight:700">{paid_str}</div>
              {"<div style='font-size:12px;color:#6b7280'>💰 " + str(int(total)) + " ريال</div>" if total else ""}
              {"<div style='font-size:12px;color:#6b7280'>🚗 " + t.get('transport').__str__() + " ريال مواصلات</div>" if transport else ""}
              {"<div style='font-size:12px;color:#6b7280'>💳 " + t.get('paidBy','') + "</div>" if t.get('paidBy') else ""}
              {"<div style='font-size:12px;color:#6b7280'>📅 " + t.get('salaryMonth','') + "</div>" if t.get('salaryMonth') else ""}
            </div>
          </td>
        </tr>
        {av_block}"""

    html = f"""
    <div style="font-family:Arial,sans-serif;direction:rtl;max-width:640px;margin:0 auto;background:#f1f5f9;padding:24px;border-radius:16px">
      <div style="background:linear-gradient(135deg,#0f1f3d,#1a3a6b);padding:28px;border-radius:12px;text-align:center;margin-bottom:20px">
        <div style="font-size:40px">✈</div>
        <div style="color:white;font-size:22px;font-weight:900;margin-top:8px">تذكير رحلات قادمة</div>
        <div style="color:#93c5fd;font-size:14px;margin-top:6px">رحلاتي RUH ↔ JED</div>
      </div>
      <div style="background:white;border-radius:12px;padding:20px;margin-bottom:16px">
        <div style="font-size:16px;font-weight:800;color:#1e3a5f;margin-bottom:16px">لديك {len(upcoming)} رحلة قادمة</div>
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          {rows}
        </table>
      </div>
      <div style="background:#dbeafe;border-radius:10px;padding:14px;font-size:13px;color:#1e40af;margin-bottom:16px">
        💡 تأكد من حجزك وتجهيز حقائبك — رحلة موفقة!
      </div>
      <div style="text-align:center;font-size:11px;color:#94a3b8">رحلاتي RUH JED — تذكير تلقائي</div>
    </div>"""

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
        print(f"  ✅ Sent!")
        sent += 1
    except Exception as e:
        print(f"  ❌ Email error: {e}")

print(f"\nDone — {sent} email(s) sent")
