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
print(f"Project: {PROJECT_ID}")

SCOPES = ['https://www.googleapis.com/auth/datastore',
          'https://www.googleapis.com/auth/cloud-platform']
gsa_creds = google.oauth2.service_account.Credentials.from_service_account_info(
    sa_dict, scopes=SCOPES)
gsa_creds.refresh(google.auth.transport.requests.Request())
token = gsa_creds.token

BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/{DB_ID}/documents"

def rest_get(path, params=None):
    url = f"{BASE}/{path}"
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        body = e.read()
        return json.loads(body) if body else {}, e.code

def rest_post(path, body):
    url  = f"{BASE}:runQuery"
    data = json.dumps(body).encode()
    req  = urllib.request.Request(url, data=data, headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        body = e.read()
        return json.loads(body) if body else {}, e.code

# Try 1: Simple GET
print("\n[1] Simple GET users:")
d, s = rest_get('users')
print(f"  Status: {s} | Keys: {list(d.keys())} | Docs: {len(d.get('documents',[]))}")

# Try 2: GET with pageSize
print("\n[2] GET users with pageSize=20:")
d, s = rest_get('users', {'pageSize': 20})
print(f"  Status: {s} | Keys: {list(d.keys())} | Docs: {len(d.get('documents',[]))}")

# Try 3: RunQuery (collectionGroup)
print("\n[3] RunQuery for users collection:")
query = {
    "structuredQuery": {
        "from": [{"collectionId": "users", "allDescendants": False}],
        "limit": 10
    }
}
d, s = rest_post('', query)
print(f"  Status: {s}")
if isinstance(d, list):
    print(f"  Results: {len(d)}")
    for item in d[:3]:
        doc = item.get('document', {})
        print(f"    - {doc.get('name','empty')}")
else:
    print(f"  Response: {d}")

# Try 4: Check if specific UID exists (from app)
print("\n[4] Check known UID pattern:")
# Try to list collections at root
list_url = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/{DB_ID}/documents:listCollectionIds"
req = urllib.request.Request(list_url,
    data=json.dumps({}).encode(),
    headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
    method='POST')
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        result = json.loads(r.read())
        print(f"  Root collections: {result.get('collectionIds', [])}")
except urllib.error.HTTPError as e:
    print(f"  Error: {e.code} {e.read().decode()[:200]}")

print("\nDone")
