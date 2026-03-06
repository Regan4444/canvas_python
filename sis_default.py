import requests

CANVAS_BASE_URL = "paste domain here"
API_TOKEN = "paste token here"
ACCOUNT_ID = "1"  # try 1 first

url = f"{CANVAS_BASE_URL}/api/v1/accounts/{ACCOUNT_ID}/sis_imports"
r = requests.get(url, headers={"Authorization": f"Bearer {API_TOKEN}"}, params={"per_page": 5}, timeout=60)

print("URL:", r.url)
print("HTTP:", r.status_code)
print("Content-Type:", r.headers.get("Content-Type"))
print("Body (first 500 chars):")

print(r.text[:500])
