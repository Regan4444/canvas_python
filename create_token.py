import requests

DOMAIN = "paste domain here"
ADMIN_TOKEN = "paste a working token here"
USER_ID = "paste user ID here for the token you wish to create"

headers = {
    "Authorization": f"Bearer {ADMIN_TOKEN}"
}

data = {
    "purpose": "Canvas Automation Service Account",
    "expires_at": None
}

r = requests.post(
    f"{DOMAIN}/api/v1/users/{USER_ID}/tokens",
    headers=headers,
    data=data
)

print(r.status_code)

print(r.json())
