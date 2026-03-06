import requests

DOMAIN = "paste domain here"
ADMIN_TOKEN = "paste token here".strip()
AUTO_USER_ID = 00000  # Canvas ID of the automation user

url = f"{DOMAIN}/api/v1/users/{AUTO_USER_ID}/tokens"
params = {"access_token": ADMIN_TOKEN}  # <-- sends token in URL

data = {
    "token[purpose]": "Canvas Automation Service Token",
    # "token[expires_at]": "2026-12-31T23:59:59Z",  # optional
}

r = requests.post(url, params=params, data=data, timeout=30)
print(r.status_code)

print(r.text[:1000])
