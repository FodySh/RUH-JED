import os, json, urllib.request, urllib.parse
import google.auth.transport.requests
import google.oauth2.service_account
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

# ── Config ──

PROJECT_ID     = ‘mytrips-9b054’
REMINDER_DAYS  = [1, 3, 5, 7]
AVIATION_PROXY = ‘https://aviation-proxy.shaheenhouse1.workers.dev’
WEATHER_KEY    = ‘d417a56b80d952490926cdf53eaf096f’

sa_dict    = json.loads(os.environ[‘FIREBASE_SERVICE_ACCOUNT’])
GMAIL_USER = os.environ[‘GMAIL_USER’]
GMAIL_PASS = os.environ[‘GMAIL_APP_PASSWORD’].replace(’ ’, ‘’)

USERS_CONFIG = os.environ.get(‘USERS_CONFIG’, ‘[]’)
users_list   = json.loads(USERS_CONFIG)
print(f”Users: {len(users_list)}”)

# ── Firebase Auth ──

SCOPES = [‘https://www.googleapis.com/auth/datastore’,
‘https://www.googleapis.com/auth/cloud-platform’]
gsa_creds = google.oauth2.service_account.Credentials.from_service_account_info(
sa_dict, scopes=SCOPES)
gsa_creds.refresh(google.auth.transport.requests.Request())
token = gsa_creds.token

BASE = f”https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents”

def rest_get(path):
req = urllib.request.Request(f”{BASE}/{path}”,
headers={‘Authorization’: f’Bearer {token}’})
try:
with urllib.request.urlopen(req, timeout=15) as r:
return json.loads(r.read())
except urllib.error.HTTPError as e:
return {’_error’: e.code}

def get_val(field):
if not field: return None
for t in [‘stringValue’,‘booleanValue’,‘integerValue’,‘doubleValue’]:
if t in field: return field[t]
if ‘arrayValue’ in field:
return [get_val(v) for v in field[‘arrayValue’].get(‘values’, [])]
if ‘mapValue’ in field:
return {k: get_val(v) for k,v in field[‘mapValue’].get(‘fields’,{}).items()}
return None

# ── Helpers ──

tz_riyadh   = timezone(timedelta(hours=3))
today       = datetime.now(tz_riyadh).date()
target_dates= [(today + timedelta(days=d)).strftime(’%Y-%m-%d’) for d in REMINDER_DAYS]
print(f”Checking dates: {target_dates}”)

MONTHS_AR = [‘يناير’,‘فبراير’,‘مارس’,‘أبريل’,‘مايو’,‘يونيو’,
‘يوليو’,‘أغسطس’,‘سبتمبر’,‘أكتوبر’,‘نوفمبر’,‘ديسمبر’]

def fmt_date(d):
try:
dt = datetime.strptime(d, ‘%Y-%m-%d’)
return f”{dt.day} {MONTHS_AR[dt.month-1]} {dt.year}”
except: return d or ‘—’

def fmt_time_str(t):
if not t: return ‘—’
try:
h, m = map(int, t.split(’:’))
period = ‘ص’ if h < 12 else ‘م’
h12 = 12 if h==0 else (h if h<=12 else h-12)
return f”{h12}:{str(m).zfill(2)} {period}”
except: return t

def fmt_utc_to_riyadh(iso):
if not iso: return ‘—’
try:
clean = iso.replace(’+00:00’,’’).replace(‘Z’,’’)
dt = datetime.strptime(clean[:16], ‘%Y-%m-%dT%H:%M’) + timedelta(hours=3)
h, m = dt.hour, dt.minute
period = ‘ص’ if h < 12 else ‘م’
h12 = 12 if h==0 else (h if h<=12 else h-12)
return f”{h12}:{str(m).zfill(2)} {period}”
except: return ‘—’

# ── Aviation ──

def fetch_flight(flight_number):
if not flight_number: return None
try:
url = f”{AVIATION_PROXY}?flight={urllib.parse.quote(flight_number)}”
req = urllib.request.Request(url, headers={‘User-Agent’: ‘reminder/1.0’})
with urllib.request.urlopen(req, timeout=10) as r:
data = json.loads(r.read())
if data.get(‘data’):
return data[‘data’][0]
except Exception as e:
print(f”    Aviation error {flight_number}: {e}”)
return None

# ── Weather ──

def fetch_weather(city):
if not city: return None
try:
url = f”http://api.weatherstack.com/current?access_key={WEATHER_KEY}&query={urllib.parse.quote(city)}&units=m”
req = urllib.request.Request(url)
with urllib.request.urlopen(req, timeout=8) as r:
data = json.loads(r.read())
if data.get(‘current’):
c = data[‘current’]
desc  = (c.get(‘weather_descriptions’) or [’’])[0]
temp  = c.get(‘temperature’,’—’)
humid = c.get(‘humidity’,’—’)
wind  = c.get(‘wind_speed’,’—’)
emoji = ‘☀️’
dl = desc.lower()
if ‘cloud’ in dl:  emoji = ‘☁️’
elif ‘rain’ in dl: emoji = ‘🌧’
elif ‘storm’ in dl:emoji = ‘⛈’
elif ‘partly’ in dl:emoji = ‘⛅’
elif ‘fog’ in dl or ‘mist’ in dl: emoji = ‘🌫’
elif ‘sand’ in dl or ‘dust’ in dl: emoji = ‘🌪’
return f”{emoji} {temp}°C · رطوبة {humid}% · رياح {wind}km/h”
except Exception as e:
print(f”    Weather error {city}: {e}”)
return None

# ── Main loop ──

sent = 0

for user in users_list:
uid         = user.get(‘uid’,’’).strip()
notif_email = user.get(‘email’,’’).strip()
print(f”\n— {uid[:16]}… → {notif_email} —”)

```
if not uid or not notif_email or '@' not in notif_email:
    print("  Skipping — missing uid/email")
    continue

tickets_doc = rest_get(f"users/{uid}/data/tickets")
if '_error' in tickets_doc:
    print(f"  Firestore error: {tickets_doc['_error']}")
    continue

raw_arr  = tickets_doc.get('fields',{}).get('tickets',{}).get('arrayValue',{}).get('values',[])
tickets  = [get_val(v) for v in raw_arr]
upcoming = sorted(
    [t for t in tickets
     if isinstance(t, dict)
     and t.get('flightDate') in target_dates
     and not t.get('missed', False)],
    key=lambda t: t.get('flightDate','')
)
print(f"  Tickets: {len(tickets)} total, {len(upcoming)} upcoming")
if not upcoming: continue

# ── Build table rows ──
table_rows = ''
for t in upcoming:
    days_left  = (datetime.strptime(t['flightDate'],'%Y-%m-%d').date() - today).days
    days_label = 'اليوم 🔴' if days_left==0 else 'غداً 🟡' if days_left==1 else f'بعد {days_left} أيام'
    route      = 'جدة JED' if t.get('ticketType')=='go' else 'الرياض RUH'
    dep_city   = 'Riyadh' if t.get('ticketType')=='go' else 'Jeddah'
    arr_city   = 'Jeddah' if t.get('ticketType')=='go' else 'Riyadh'
    fn         = t.get('flightNumber') or '—'
    pnr        = t.get('pnr') or '—'
    airline    = t.get('airline') or '—'
    flight_time= fmt_time_str(t.get('flightTime',''))

    # Live aviation data
    gate = '—'
    dep_actual = ''
    if t.get('flightNumber'):
        print(f"    Fetching {t['flightNumber']}...")
        av = fetch_flight(t['flightNumber'])
        if av:
            gate = av.get('departure',{}).get('gate') or '—'
            actual_iso = av.get('departure',{}).get('actual')
            if actual_iso:
                dep_actual = fmt_utc_to_riyadh(actual_iso)

    # Weather for arrival city
    weather_str = fetch_weather(arr_city) or '—'

    # Row color alternation handled by nth-child in table
    dep_time_cell = dep_actual if dep_actual else flight_time

    table_rows += f"""
    <tr>
      <td style="padding:14px 16px;border-bottom:1px solid #e5e7eb;font-weight:800;color:#1e3a5f;white-space:nowrap">
        {"🛫" if t.get('ticketType')=='go' else "🛬"} {route}
      </td>
      <td style="padding:14px 16px;border-bottom:1px solid #e5e7eb;white-space:nowrap">
        {fmt_date(t.get('flightDate',''))}
        <div style="font-size:11px;color:#6b7280;margin-top:2px">{dep_time_cell}</div>
      </td>
      <td style="padding:14px 16px;border-bottom:1px solid #e5e7eb;text-align:center">
        <span style="background:{"#fee2e2" if days_left==0 else "#fef9c3" if days_left==1 else "#ede9fe"};
                     color:{"#b91c1c" if days_left==0 else "#a16207" if days_left==1 else "#6d28d9"};
                     padding:4px 10px;border-radius:20px;font-size:12px;font-weight:700;white-space:nowrap">
          {days_label}
        </span>
      </td>
      <td style="padding:14px 16px;border-bottom:1px solid #e5e7eb;font-family:monospace;font-weight:700;color:#1d4ed8">
        {fn}
      </td>
      <td style="padding:14px 16px;border-bottom:1px solid #e5e7eb;font-family:monospace;color:#374151">
        {pnr}
      </td>
      <td style="padding:14px 16px;border-bottom:1px solid #e5e7eb;color:#374151">
        {airline}
      </td>
      <td style="padding:14px 16px;border-bottom:1px solid #e5e7eb;text-align:center;font-weight:700;color:#0f766e">
        {"🚪 " + gate if gate != "—" else "—"}
      </td>
      <td style="padding:14px 16px;border-bottom:1px solid #e5e7eb;font-size:12px;color:#374151">
        {weather_str}
      </td>
    </tr>"""

# nearest flight for subject/summary
next_t     = upcoming[0]
next_days  = (datetime.strptime(next_t['flightDate'],'%Y-%m-%d').date() - today).days
next_route = 'جدة' if next_t.get('ticketType')=='go' else 'الرياض'
next_date  = fmt_date(next_t.get('flightDate',''))

# ── HTML Email ──
# Google Calendar structured data hint for smart suggestions
# Using schema.org EventReminder markup helps Gmail surface action buttons
first_fn   = next_t.get('flightNumber','')
first_date = next_t.get('flightDate','')
first_time = next_t.get('flightTime','00:00')

html = f"""<!DOCTYPE html>
```

<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<script type="application/ld+json">
{{
  "@context": "http://schema.org",
  "@type": "EventReservation",
  "reservationNumber": "{next_t.get('pnr','') or first_fn}",
  "reservationStatus": "http://schema.org/ReservationConfirmed",
  "underName": {{
    "@type": "Person",
    "name": "المسافر"
  }},
  "reservationFor": {{
    "@type": "Flight",
    "flightNumber": "{first_fn}",
    "airline": {{
      "@type": "Airline",
      "name": "{next_t.get('airline','')}",
      "iataCode": "{next_t.get('airline','')}"
    }},
    "departureAirport": {{
      "@type": "Airport",
      "name": "{'King Khalid International Airport' if next_t.get('ticketType')=='go' else 'King Abdulaziz International Airport'}",
      "iataCode": "{'RUH' if next_t.get('ticketType')=='go' else 'JED'}"
    }},
    "arrivalAirport": {{
      "@type": "Airport",
      "name": "{'King Abdulaziz International Airport' if next_t.get('ticketType')=='go' else 'King Khalid International Airport'}",
      "iataCode": "{'JED' if next_t.get('ticketType')=='go' else 'RUH'}"
    }},
    "departureTime": "{first_date}T{first_time}:00+03:00",
    "arrivalTime": "{first_date}T{first_time}:00+03:00"
  }}
}}
</script>
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,sans-serif;direction:rtl">
<div style="max-width:700px;margin:0 auto;padding:24px">

  <!-- Header -->

  <div style="background:linear-gradient(135deg,#0f1f3d,#1a3a6b);padding:32px;border-radius:16px 16px 0 0;text-align:center">
    <div style="font-size:42px;margin-bottom:8px">✈</div>
    <div style="color:white;font-size:24px;font-weight:900">تذكير رحلة قادمة</div>
    <div style="color:#93c5fd;font-size:14px;margin-top:6px">رحلاتي RUH ↔ JED</div>
  </div>

  <!-- Alert banner -->

  <div style="background:{'#fef2f2' if next_days==0 else '#fefce8' if next_days==1 else '#eff6ff'};
              border-right:4px solid {'#ef4444' if next_days==0 else '#f59e0b' if next_days==1 else '#3b82f6'};
              padding:16px 20px;font-size:15px;font-weight:700;
              color:{'#991b1b' if next_days==0 else '#92400e' if next_days==1 else '#1e3a5f'}">
    {'🔴 رحلتك اليوم!' if next_days==0 else '🟡 رحلتك غداً!' if next_days==1 else f'✈ رحلتك إلى {next_route} بعد {next_days} أيام — {next_date}'}
  </div>

  <!-- Table -->

  <div style="background:white;border-radius:0 0 16px 16px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08)">
    <div style="padding:20px 20px 0;font-size:13px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px">
      تفاصيل الرحلات القادمة ({len(upcoming)} {"رحلة" if len(upcoming)==1 else "رحلات"})
    </div>
    <div style="overflow-x:auto;padding:12px">
      <table style="width:100%;border-collapse:collapse;font-size:13px;min-width:600px">
        <thead>
          <tr style="background:#1e3a5f;color:white">
            <th style="padding:12px 16px;text-align:right;font-weight:700;white-space:nowrap">الوصول إلى</th>
            <th style="padding:12px 16px;text-align:right;font-weight:700;white-space:nowrap">التاريخ والوقت</th>
            <th style="padding:12px 16px;text-align:center;font-weight:700;white-space:nowrap">المتبقي</th>
            <th style="padding:12px 16px;text-align:right;font-weight:700;white-space:nowrap">رقم الرحلة</th>
            <th style="padding:12px 16px;text-align:right;font-weight:700;white-space:nowrap">PNR</th>
            <th style="padding:12px 16px;text-align:right;font-weight:700;white-space:nowrap">الخط</th>
            <th style="padding:12px 16px;text-align:center;font-weight:700;white-space:nowrap">البوابة</th>
            <th style="padding:12px 16px;text-align:right;font-weight:700;white-space:nowrap">طقس الوصول</th>
          </tr>
        </thead>
        <tbody>
          {table_rows}
        </tbody>
      </table>
    </div>

```
<!-- Footer note -->
<div style="padding:16px 20px;background:#f8fafc;border-top:1px solid #e5e7eb;font-size:12px;color:#6b7280;text-align:center">
  💡 تأكد من حجزك وتجهيز حقائبك — رحلة موفقة! &nbsp;|&nbsp;
  <a href="https://fodysh.github.io/RUH-JED/" style="color:#3b82f6;text-decoration:none">فتح التطبيق</a>
</div>
```

  </div>

  <div style="text-align:center;font-size:11px;color:#94a3b8;margin-top:16px">
    رحلاتي RUH JED — تذكير تلقائي · 
    <a href="https://fodysh.github.io/RUH-JED/" style="color:#94a3b8">إيقاف التذكيرات</a>
  </div>
</div>
</body>
</html>"""

```
msg = MIMEMultipart('alternative')
msg['Subject'] = f"✈ تذكير رحلة {'اليوم' if next_days==0 else 'غداً' if next_days==1 else f'بعد {next_days} أيام'} — {next_route} {next_date}"
msg['From']    = GMAIL_USER
msg['To']      = notif_email
# Plain text fallback for Gmail smart suggestions
plain = f"تذكير: لديك رحلة إلى {next_route} بتاريخ {next_date}. رقم الرحلة: {next_t.get('flightNumber','—')} · PNR: {next_t.get('pnr','—')}"
msg.attach(MIMEText(plain, 'plain', 'utf-8'))
msg.attach(MIMEText(html,  'html',  'utf-8'))

try:
    print(f"  Sending to {notif_email}...")
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_PASS)
        smtp.sendmail(GMAIL_USER, notif_email, msg.as_bytes())
    print(f"  ✅ Sent!")
    sent += 1
except Exception as e:
    print(f"  ❌ Email error: {e}")
```

print(f”\nDone — {sent} email(s) sent”)