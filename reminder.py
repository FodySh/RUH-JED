import os, json, urllib.request, urllib.parse
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

PROJECT_ID = 'mytrips-9b054'
API_KEY    = 'AIzaSyBUJMZoN-wZ_1y2OCDTBF6pCXSexNN78t0'
BASE       = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents"

GMAIL_USER = os.environ['GMAIL_USER']
GMAIL_PASS = os.environ['GMAIL_APP_PASSWORD'].replace(' ', '')

def rest_get(path):
    url = f"{BASE}/{path}?key={API_KEY}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {'_error': e.code, '_msg': e.read().decode()[:300]}

def run_query(query):
    url  = f"{BASE}:runQuery?key={API_KEY}"
    req  = urllib.request.Request(url,
        data=json.dumps({'structuredQuery': query}).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return [{'_error': e.code, '_msg': e.read().decode()[:300]}]

def get_val(field):
    if not field: return None
    for t in ['stringValue','booleanValue','integerValue','doubleValue']:
        if t in field: return field[t]
    if 'arrayValue' in field:
        return [get_val(v) for v in field['arrayValue'].get('values', [])]
    if 'mapValue' in field:
        return {k: get_val(v) for k,v in field['mapValue'].get('fields',{}).items()}
    return None

# Date setup
tz_riyadh  = timezone(timedelta(hours=3))
today      = datetime.now(tz_riyadh).date()
target     = today + timedelta(days=2)
target_str = target.strftime('%Y-%m-%d')
print(f"Target date: {target_str}")

# Step 1: Find users via runQuery
print("\nFinding users...")
results = run_query({
    'from': [{'collectionId': 'users', 'allDescendants': False}],
    'limit': 50
})

if isinstance(results, list) and results and '_error' in results[0]:
    print(f"Query error: {results[0]}")
else:
    print(f"Query results: {len(results)}")

# Try direct known path format
print("\nTrying direct collection list...")
data = rest_get('users')
print(f"Users GET: {list(data.keys())[:5]} | docs: {len(data.get('documents',[]))}")
if '_error' in data:
    print(f"Error: {data}")

# Try runQuery with allDescendants to find tickets directly
print("\nSearching all tickets directly...")
results2 = run_query({
    'from': [{'collectionId': 'tickets', 'allDescendants': True}],
    'limit': 5
})
print(f"Tickets query results: {len(results2) if isinstance(results2,list) else results2}")
if isinstance(results2, list):
    for r in results2[:3]:
        doc = r.get('document', {})
        if doc:
            print(f"  Found: {doc.get('name','')}")

# Try runQuery for settings (to find notifEmail)
print("\nSearching settings docs...")
results3 = run_query({
    'from': [{'collectionId': 'settings', 'allDescendants': True}],
    'limit': 10
})
print(f"Settings results: {len(results3) if isinstance(results3,list) else results3}")
if isinstance(results3, list):
    for r in results3[:5]:
        doc = r.get('document', {})
        if doc and doc.get('fields'):
            name = doc.get('name','')
            uid  = name.split('/users/')[-1].split('/')[0] if '/users/' in name else '?'
            fields = doc.get('fields', {})
            email = get_val(fields.get('notifEmail', {}))
            print(f"  UID: {uid[:12]}... | email: {email}")

print("\nDone")
