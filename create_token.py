import requests

DOMAIN = "https://grayson.instructure.com"
ADMIN_TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"
USER_ID = "70952"

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