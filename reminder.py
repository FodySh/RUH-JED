# reminder.py – updated 2026-05-16

import os, json, urllib.request, urllib.parse
import google.auth.transport.requests
import google.oauth2.service_account
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

# – Config –

PROJECT_ID     = 'mytrips-9b054'
REMINDER_DAYS  = [1, 3, 5, 7]
AVIATION_PROXY = 'https://aviation-proxy.shaheenhouse1.workers.dev'
WEATHER_KEY    = ‘d417a56b80d952490926cdf53eaf096f’

sa_dict    = json.loads(os.environ[‘FIREBASE_SERVICE_ACCOUNT’])
GMAIL_USER = os.environ[‘GMAIL_USER’]
GMAIL_PASS = os.environ[‘GMAIL_APP_PASSWORD’].replace(’ ’, ‘’)

USERS_CONFIG = os.environ.get(‘USERS_CONFIG’, ‘[]’)
users_list   = json.loads(USERS_CONFIG)
print(’Users: ’ + str(len(users_list)))

# – Firebase Auth –

SCOPES = [
‘https://www.googleapis.com/auth/datastore’,
‘https://www.googleapis.com/auth/cloud-platform’,
]
gsa_creds = google.oauth2.service_account.Credentials.from_service_account_info(
sa_dict, scopes=SCOPES)
gsa_creds.refresh(google.auth.transport.requests.Request())
token = gsa_creds.token

BASE = ‘https://firestore.googleapis.com/v1/projects/’ + PROJECT_ID + ‘/databases/(default)/documents’

def rest_get(path):
req = urllib.request.Request(BASE + ‘/’ + path,
headers={‘Authorization’: ‘Bearer ’ + token})
try:
with urllib.request.urlopen(req, timeout=15) as r:
return json.loads(r.read())
except urllib.error.HTTPError as e:
return {’_error’: e.code}

def get_val(field):
if not field:
return None
for t in [‘stringValue’, ‘booleanValue’, ‘integerValue’, ‘doubleValue’]:
if t in field:
return field[t]
if ‘arrayValue’ in field:
return [get_val(v) for v in field[‘arrayValue’].get(‘values’, [])]
if ‘mapValue’ in field:
return {k: get_val(v) for k, v in field[‘mapValue’].get(‘fields’, {}).items()}
return None

# – Helpers –

tz_riyadh    = timezone(timedelta(hours=3))
today        = datetime.now(tz_riyadh).date()
target_dates = [(today + timedelta(days=d)).strftime(’%Y-%m-%d’) for d in REMINDER_DAYS]
print(’Checking dates: ’ + str(target_dates))

MONTHS_AR = [
‘يناير’, ‘فبراير’, ‘مارس’, ‘أبريل’, ‘مايو’, ‘يونيو’,
‘يوليو’, ‘أغسطس’, ‘سبتمبر’, ‘أكتوبر’, ‘نوفمبر’, ‘ديسمبر’,
]

def fmt_date(d):
try:
dt = datetime.strptime(d, ‘%Y-%m-%d’)
return str(dt.day) + ’ ’ + MONTHS_AR[dt.month - 1] + ’ ’ + str(dt.year)
except Exception:
return d or ‘–’

def fmt_time_str(t):
if not t:
return ‘–’
try:
h, m = map(int, t.split(’:’))
period = ‘ص’ if h < 12 else ‘م’
h12 = 12 if h == 0 else (h if h <= 12 else h - 12)
return str(h12) + ‘:’ + str(m).zfill(2) + ’ ’ + period
except Exception:
return t

def fmt_utc_to_riyadh(iso):
if not iso:
return ‘–’
try:
clean = iso.replace(’+00:00’, ‘’).replace(‘Z’, ‘’)
dt = datetime.strptime(clean[:16], ‘%Y-%m-%dT%H:%M’) + timedelta(hours=3)
h, m = dt.hour, dt.minute
period = ‘ص’ if h < 12 else ‘م’
h12 = 12 if h == 0 else (h if h <= 12 else h - 12)
return str(h12) + ‘:’ + str(m).zfill(2) + ’ ’ + period
except Exception:
return ‘–’

# – Aviation –

def fetch_flight(flight_number):
if not flight_number:
return None
try:
url = AVIATION_PROXY + ‘?flight=’ + urllib.parse.quote(flight_number)
req = urllib.request.Request(url, headers={‘User-Agent’: ‘reminder/1.0’})
with urllib.request.urlopen(req, timeout=10) as r:
data = json.loads(r.read())
if data.get(‘data’):
return data[‘data’][0]
except Exception as e:
print(’    Aviation error ’ + flight_number + ’: ’ + str(e))
return None

# – Weather –

def fetch_weather(city):
if not city:
return None
try:
url = (‘http://api.weatherstack.com/current?access_key=’ + WEATHER_KEY
+ ‘&query=’ + urllib.parse.quote(city) + ‘&units=m’)
with urllib.request.urlopen(url, timeout=8) as r:
data = json.loads(r.read())
if data.get(‘current’):
c    = data[‘current’]
desc = (c.get(‘weather_descriptions’) or [’’])[0]
temp = c.get(‘temperature’, ‘–’)
humid= c.get(‘humidity’, ‘–’)
wind = c.get(‘wind_speed’, ‘–’)
dl   = desc.lower()
emoji = ‘صافي ☀️’
if ‘cloud’ in dl:              emoji = ‘غائم ☁️’
elif ‘rain’ in dl:             emoji = ‘ممطر 🌧’
elif ‘storm’ in dl:            emoji = ‘عاصفة ⛈’
elif ‘partly’ in dl:           emoji = ‘قليل الغيوم ⛅’
elif ‘fog’ in dl or ‘mist’ in dl: emoji = ‘ضبابي 🌫’
elif ‘sand’ in dl or ‘dust’ in dl: emoji = ‘غبار 🌪’
return emoji + ’ ’ + str(temp) + ’C | رطوبة ’ + str(humid) + ‘% | رياح ’ + str(wind) + ‘km/h’
except Exception as e:
print(’    Weather error ’ + city + ’: ’ + str(e))
return None

# – Main loop –

sent = 0

for user in users_list:
uid         = user.get(‘uid’, ‘’).strip()
notif_email = user.get(‘email’, ‘’).strip()
print(’\n— ’ + uid[:16] + ‘… -> ’ + notif_email + ’ —’)

```
if not uid or not notif_email or '@' not in notif_email:
    print('  Skipping -- missing uid/email')
    continue

tickets_doc = rest_get('users/' + uid + '/data/tickets')
if '_error' in tickets_doc:
    print('  Firestore error: ' + str(tickets_doc['_error']))
    continue

raw_arr  = tickets_doc.get('fields', {}).get('tickets', {}).get('arrayValue', {}).get('values', [])
tickets  = [get_val(v) for v in raw_arr]
upcoming = sorted(
    [t for t in tickets
     if isinstance(t, dict)
     and t.get('flightDate') in target_dates
     and not t.get('missed', False)],
    key=lambda t: t.get('flightDate', '')
)
print('  Tickets: ' + str(len(tickets)) + ' total, ' + str(len(upcoming)) + ' upcoming')
if not upcoming:
    continue

# -- Build table rows --
table_rows = ''
for t in upcoming:
    days_left  = (datetime.strptime(t['flightDate'], '%Y-%m-%d').date() - today).days
    if days_left == 0:
        days_label = 'اليوم'
        day_bg     = '#fef2f2'
        day_color  = '#b91c1c'
    elif days_left == 1:
        days_label = 'غداً'
        day_bg     = '#fefce8'
        day_color  = '#a16207'
    else:
        days_label = 'بعد ' + str(days_left) + ' أيام'
        day_bg     = '#ede9fe'
        day_color  = '#6d28d9'

    is_go   = t.get('ticketType') == 'go'
    arr_ar  = 'جدة JED' if is_go else 'الرياض RUH'
    icon    = '🛫' if is_go else '🛬'
    arr_en  = 'Jeddah' if is_go else 'Riyadh'
    fn      = t.get('flightNumber') or '--'
    pnr     = t.get('pnr') or '--'
    airline = t.get('airline') or '--'
    f_time  = fmt_time_str(t.get('flightTime', ''))

    gate       = '--'
    dep_actual = ''
    if t.get('flightNumber'):
        print('    Fetching ' + t['flightNumber'] + '...')
        av = fetch_flight(t['flightNumber'])
        if av:
            gate = av.get('departure', {}).get('gate') or '--'
            actual_iso = av.get('departure', {}).get('actual')
            if actual_iso:
                dep_actual = fmt_utc_to_riyadh(actual_iso)

    weather_str = fetch_weather(arr_en) or '--'
    show_time   = dep_actual if dep_actual else f_time

    table_rows += (
        '<tr>'
        '<td style="padding:12px 14px;border-bottom:1px solid #e5e7eb;font-weight:800;color:#1e3a5f;white-space:nowrap">'
        + icon + ' ' + arr_ar +
        '</td>'
        '<td style="padding:12px 14px;border-bottom:1px solid #e5e7eb;white-space:nowrap">'
        + fmt_date(t.get('flightDate', '')) +
        '<div style="font-size:11px;color:#6b7280;margin-top:2px">' + show_time + '</div>'
        '</td>'
        '<td style="padding:12px 14px;border-bottom:1px solid #e5e7eb;text-align:center">'
        '<span style="background:' + day_bg + ';color:' + day_color + ';padding:3px 10px;border-radius:20px;font-size:12px;font-weight:700;white-space:nowrap">'
        + days_label +
        '</span>'
        '</td>'
        '<td style="padding:12px 14px;border-bottom:1px solid #e5e7eb;font-family:monospace;font-weight:700;color:#1d4ed8">'
        + fn +
        '</td>'
        '<td style="padding:12px 14px;border-bottom:1px solid #e5e7eb;font-family:monospace;color:#374151">'
        + pnr +
        '</td>'
        '<td style="padding:12px 14px;border-bottom:1px solid #e5e7eb;color:#374151">'
        + airline +
        '</td>'
        '<td style="padding:12px 14px;border-bottom:1px solid #e5e7eb;text-align:center;font-weight:700;color:#0f766e">'
        + ('🚪 ' + gate if gate != '--' else '--') +
        '</td>'
        '<td style="padding:12px 14px;border-bottom:1px solid #e5e7eb;font-size:12px;color:#374151">'
        + weather_str +
        '</td>'
        '</tr>'
    )

next_t     = upcoming[0]
next_days  = (datetime.strptime(next_t['flightDate'], '%Y-%m-%d').date() - today).days
next_route = 'جدة' if next_t.get('ticketType') == 'go' else 'الرياض'
next_date  = fmt_date(next_t.get('flightDate', ''))
first_fn   = next_t.get('flightNumber', '')
first_date = next_t.get('flightDate', '')
first_time = next_t.get('flightTime', '00:00')
first_pnr  = next_t.get('pnr', '') or first_fn

if next_days == 0:
    alert_text  = 'رحلتك اليوم!'
    alert_bg    = '#fef2f2'
    alert_border= '#ef4444'
    alert_color = '#991b1b'
    subject_when= 'اليوم'
elif next_days == 1:
    alert_text  = 'رحلتك غداً!'
    alert_bg    = '#fefce8'
    alert_border= '#f59e0b'
    alert_color = '#92400e'
    subject_when= 'غداً'
else:
    alert_text  = 'رحلتك الى ' + next_route + ' بعد ' + str(next_days) + ' ايام -- ' + next_date
    alert_bg    = '#eff6ff'
    alert_border= '#3b82f6'
    alert_color = '#1e3a5f'
    subject_when= 'بعد ' + str(next_days) + ' ايام'

dep_airport_name = 'King Khalid International Airport' if next_t.get('ticketType') == 'go' else 'King Abdulaziz International Airport'
arr_airport_name = 'King Abdulaziz International Airport' if next_t.get('ticketType') == 'go' else 'King Khalid International Airport'
dep_iata = 'RUH' if next_t.get('ticketType') == 'go' else 'JED'
arr_iata = 'JED' if next_t.get('ticketType') == 'go' else 'RUH'

schema = (
    '<script type="application/ld+json">'
    '{"@context":"http://schema.org","@type":"EventReservation",'
    '"reservationNumber":"' + first_pnr + '",'
    '"reservationStatus":"http://schema.org/ReservationConfirmed",'
    '"underName":{"@type":"Person","name":"المسافر"},'
    '"reservationFor":{"@type":"Flight",'
    '"flightNumber":"' + first_fn + '",'
    '"airline":{"@type":"Airline","name":"' + next_t.get('airline', '') + '","iataCode":"' + next_t.get('airline', '') + '"},'
    '"departureAirport":{"@type":"Airport","name":"' + dep_airport_name + '","iataCode":"' + dep_iata + '"},'
    '"arrivalAirport":{"@type":"Airport","name":"' + arr_airport_name + '","iataCode":"' + arr_iata + '"},'
    '"departureTime":"' + first_date + 'T' + first_time + ':00+03:00",'
    '"arrivalTime":"' + first_date + 'T' + first_time + ':00+03:00"}}'
    '</script>'
)

count_label = 'رحلة' if len(upcoming) == 1 else 'رحلات'

html = (
    '<!DOCTYPE html>'
    '<html lang="ar" dir="rtl">'
    '<head><meta charset="UTF-8">' + schema + '</head>'
    '<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,sans-serif;direction:rtl">'
    '<div style="max-width:720px;margin:0 auto;padding:24px">'

    '<div style="background:linear-gradient(135deg,#0f1f3d,#1a3a6b);padding:32px;border-radius:16px 16px 0 0;text-align:center">'
    '<div style="font-size:42px;margin-bottom:8px">✈</div>'
    '<div style="color:white;font-size:24px;font-weight:900">تذكير رحلة قادمة</div>'
    '<div style="color:#93c5fd;font-size:14px;margin-top:6px">رحلاتي RUH - JED</div>'
    '</div>'

    '<div style="background:' + alert_bg + ';border-right:4px solid ' + alert_border + ';'
    'padding:16px 20px;font-size:15px;font-weight:700;color:' + alert_color + '">'
    + alert_text +
    '</div>'

    '<div style="background:white;border-radius:0 0 16px 16px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08)">'
    '<div style="padding:20px 20px 0;font-size:13px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px">'
    'تفاصيل الرحلات القادمة (' + str(len(upcoming)) + ' ' + count_label + ')'
    '</div>'
    '<div style="overflow-x:auto;padding:12px">'
    '<table style="width:100%;border-collapse:collapse;font-size:13px;min-width:620px">'
    '<thead>'
    '<tr style="background:#1e3a5f;color:white">'
    '<th style="padding:12px 14px;text-align:right;font-weight:700;white-space:nowrap">الوصول الى</th>'
    '<th style="padding:12px 14px;text-align:right;font-weight:700;white-space:nowrap">التاريخ والوقت</th>'
    '<th style="padding:12px 14px;text-align:center;font-weight:700;white-space:nowrap">المتبقي</th>'
    '<th style="padding:12px 14px;text-align:right;font-weight:700;white-space:nowrap">رقم الرحلة</th>'
    '<th style="padding:12px 14px;text-align:right;font-weight:700;white-space:nowrap">PNR</th>'
    '<th style="padding:12px 14px;text-align:right;font-weight:700;white-space:nowrap">الخط</th>'
    '<th style="padding:12px 14px;text-align:center;font-weight:700;white-space:nowrap">البوابة</th>'
    '<th style="padding:12px 14px;text-align:right;font-weight:700;white-space:nowrap">طقس الوصول</th>'
    '</tr>'
    '</thead>'
    '<tbody>' + table_rows + '</tbody>'
    '</table>'
    '</div>'

    '<div style="padding:16px 20px;background:#f8fafc;border-top:1px solid #e5e7eb;font-size:12px;color:#6b7280;text-align:center">'
    'رحلة موفقة! | '
    '<a href="https://fodysh.github.io/RUH-JED/" style="color:#3b82f6;text-decoration:none">فتح التطبيق</a>'
    '</div>'
    '</div>'

    '<div style="text-align:center;font-size:11px;color:#94a3b8;margin-top:16px">'
    'رحلاتي RUH JED -- تذكير تلقائي'
    '</div>'
    '</div>'
    '</body></html>'
)

plain = ('تذكير: لديك رحلة الى ' + next_route + ' بتاريخ ' + next_date
         + '. رقم الرحلة: ' + next_t.get('flightNumber', '--')
         + ' - PNR: ' + (next_t.get('pnr') or '--'))

msg = MIMEMultipart('alternative')
msg['Subject'] = 'تذكير رحلة ' + subject_when + ' -- ' + next_route + ' ' + next_date
msg['From']    = GMAIL_USER
msg['To']      = notif_email
msg.attach(MIMEText(plain, 'plain', 'utf-8'))
msg.attach(MIMEText(html,  'html',  'utf-8'))

try:
    print('  Sending to ' + notif_email + '...')
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_PASS)
        smtp.sendmail(GMAIL_USER, notif_email, msg.as_bytes())
    print('  Sent!')
    sent += 1
except Exception as e:
    print('  Email error: ' + str(e))
```

print(’\nDone – ’ + str(sent) + ’ email(s) sent’)