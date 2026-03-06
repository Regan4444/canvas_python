import requests
DOMAIN = "https://grayson.instructure.com"
ADMIN_TOKEN = "4480~zG7VyXmWACG4enVUEAFCHrvakP7BNyyANzXExAQeU8n9wHz4aQPyhHwncJwuBEZn".strip()

# Test with Authorization header
r1 = requests.get(f"{DOMAIN}/api/v1/users/self",
                  headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
                  timeout=30)
print("header auth:", r1.status_code, r1.text[:120])

# Test with query param
r2 = requests.get(f"{DOMAIN}/api/v1/users/self",
                  params={"access_token": ADMIN_TOKEN},
                  timeout=30)
print("query auth :", r2.status_code, r2.text[:120])