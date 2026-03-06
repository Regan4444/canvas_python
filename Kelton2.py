import requests
import csv

# === CONFIGURATION ===
ACCESS_TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"
BASE_URL = "https://grayson.instructure.com/"
COURSE_ID = "41183"
USER_ID = "64732"

# === FILTER SETTINGS ===
item_filter = ["pages", "assignments", "quizzes"]  # ← Filter for these path segments

# === HEADERS ===
headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

# === API ENDPOINT ===
endpoint = f"{BASE_URL}/api/v1/users/{USER_ID}/page_views"

# === OPTIONAL DATE RANGE ===
params = {
    "start_time": "2025-01-01T00:00:00Z",
    "end_time": "2025-12-31T23:59:59Z",
    "per_page": 100
}

# === GET PAGE VIEWS ===
page_views = []
while endpoint:
    response = requests.get(endpoint, headers=headers, params=params)
    if response.status_code != 200:
        print("Error:", response.status_code, response.text)
        break
    data = response.json()
    page_views.extend(data)
    if 'next' in response.links:
        endpoint = response.links['next']['url']
        params = {}
    else:
        endpoint = None

# === FILTER PAGE VIEWS BY COURSE AND ITEM TYPE ===
filtered_views = []
for view in page_views:
    url = view.get("url", "")
    if f"/courses/{COURSE_ID}" in url and any(f"/{item}/" in url for item in item_filter):
        filtered_views.append(view)

# === WRITE TO CSV ===
csv_filename = f"filtered_pageviews_{USER_ID}_{COURSE_ID}.csv"
with open(csv_filename, mode='w', newline='', encoding='utf-8') as file:
    writer = csv.writer(file)
    writer.writerow([
        "Timestamp", "URL", "Page Title", "Interaction Seconds", "User Agent", "Context Type"
    ])
    for view in filtered_views:
        writer.writerow([
            view.get("created_at"),
            view.get("url"),
            view.get("title", ""),
            view.get("interaction_seconds", 0),
            view.get("user_agent", ""),
            view.get("context_type", "")
        ])

print(f"✅ Filtered CSV file saved as: {csv_filename}")
