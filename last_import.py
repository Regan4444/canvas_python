import requests, json

CANVAS_BASE_URL = "https://grayson.instructure.com"
API_TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"
ACCOUNT_ID = "1"
LAST_IMPORT_ID = 382096

headers = {"Authorization": f"Bearer {API_TOKEN}"}

url = f"{CANVAS_BASE_URL}/api/v1/accounts/{ACCOUNT_ID}/sis_imports/{LAST_IMPORT_ID}"
r = requests.get(url, headers=headers, timeout=60)
r.raise_for_status()
data = r.json()

print("workflow_state:", data.get("workflow_state"))
print("\nDATA BLOCK:")
print(json.dumps(data.get("data", {}), indent=2)[:4000])