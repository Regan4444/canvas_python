import requests, json

CANVAS_BASE_URL = "https://grayson.instructure.com"
API_TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"
ACCOUNT_ID = "1"
IMPORT_ID = 382096

headers = {"Authorization": f"Bearer {API_TOKEN}"}

url = f"{CANVAS_BASE_URL}/api/v1/accounts/{ACCOUNT_ID}/sis_imports/{IMPORT_ID}"
r = requests.get(url, headers=headers, timeout=60)
r.raise_for_status()
data = r.json()

# These keys vary by instance; print anything that looks like "who did it"
interesting_keys = [
    "user_id", "user", "created_by", "initiated_by", "sis_importer_id",
    "batch_mode", "batch_mode_term", "override_sis_stickiness",
    "diffing_data_set_identifier", "data_set_identifier",
    "attachment", "attachments"
]

print("Top-level keys:", sorted(list(data.keys())))

print("\nPossible 'who initiated' fields:")
for k in ["user_id", "sis_importer_id", "created_by", "initiated_by", "user"]:
    if k in data:
        print(k, "=", data.get(k))

print("\nFull record (first 2000 chars):")
print(json.dumps(data, indent=2)[:2000])