import requests

DOMAIN = "https://grayson.instructure.com"
ADMIN_TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU".strip()
AUTO_USER_ID = 70952  # Canvas user ID for the automation account

headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}

url = f"{DOMAIN}/api/v1/users/{AUTO_USER_ID}/tokens"

data = {
    "token[purpose]": "Canvas Automation Service Token",
    # "token[expires_at]": "2026-12-31T23:59:59Z",  # optional
}

r = requests.post(url, headers=headers, data=data, timeout=30)
print("status:", r.status_code)
print("body:", r.text[:1200])