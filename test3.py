import requests

DOMAIN = "paste domain here"
TOKEN = "paste token here"

         

headers = {"Authorization": f"Bearer {TOKEN}"}
r = requests.get(f"{DOMAIN}/api/v1/users/self", headers=headers)
print(r.status_code)
print(r.text[:500])


