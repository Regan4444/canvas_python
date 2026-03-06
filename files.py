import requests

DOMAIN = "https://grayson.instructure.com"
ADMIN_TOKEN = "4480~PturLY3URL2MCx9vzthmHUU488c4XDEcKRkU27mzUXPGT4M9uP2HmGZ6K79xTzC7".strip()
AUTO_USER_ID = 70952  # Canvas ID of the automation user

url = f"{DOMAIN}/api/v1/users/{AUTO_USER_ID}/tokens"
params = {"access_token": ADMIN_TOKEN}  # <-- sends token in URL

data = {
    "token[purpose]": "Canvas Automation Service Token",
    # "token[expires_at]": "2026-12-31T23:59:59Z",  # optional
}

r = requests.post(url, params=params, data=data, timeout=30)
print(r.status_code)
print(r.text[:1000])