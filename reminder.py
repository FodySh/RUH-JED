import os, json, urllib.request
import google.auth.transport.requests
import google.oauth2.service_account
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

sa_dict   = json.loads(os.environ['FIREBASE_SERVICE_ACCOUNT'])
PROJECT_ID = sa_dict.get('project_id')
print(f"Project: {PROJECT_ID}")

SCOPES = ['https://www.googleapis.com/auth/datastore',
          'https://www.googleapis.com/auth/cloud-platform']
gsa_creds = google.oauth2.service_account.Credentials.from_service_account_info(
    sa_dict, scopes=SCOPES)
gsa_creds.refresh(google.auth.transport.requests.Request())
token = gsa_creds.token

def rest_get(url):
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b'{}'), e.code

# Step 1: list all databases
print("\n--- Listing all Firestore databases ---")
data, status = rest_get(
    f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases"
)
print(f"Status: {status}")
dbs = data.get('databases', [])
print(f"Databases found: {len(dbs)}")
for db in dbs:
    print(f"  - {db.get('name')} | type: {db.get('type')} | location: {db.get('locationId')}")

# Step 2: try each database
for db in dbs:
    db_id = db['name'].split('/')[-1]
    print(f"\n--- Testing database: {db_id} ---")
    url   = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/{db_id}/documents/users"
    data2, status2 = rest_get(url)
    print(f"  Status: {status2}")
    print(f"  Keys: {list(data2.keys())}")
    docs = data2.get('documents', [])
    print(f"  Documents: {len(docs)}")
    if docs:
        print(f"  First doc: {docs[0].get('name','')}")

print("\nDone")
