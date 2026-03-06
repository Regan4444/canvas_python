import requests

DOMAIN = "https://grayson.instructure.com"
TOKEN = "4480~YmPPBYnTQzPUDt6nnekAwrkm2Ye64MM3KUYUQQ4fyUf6k2kD4zGETfwUMAZR3wzW"

         

headers = {"Authorization": f"Bearer {TOKEN}"}
r = requests.get(f"{DOMAIN}/api/v1/users/self", headers=headers)
print(r.status_code)
print(r.text[:500])

