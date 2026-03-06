import requests
import csv
import datetime

# === CONFIGURATION ===
ACCESS_TOKEN = "paste token here"
BASE_URL = "paste domain here"
COURSE_ID = "41380"  # Replace with your course ID
USER_ID = "21769"    # Replace with the student's Canvas user ID

# === HEADERS ===
headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

# === API ENDPOINT ===
endpoint = f"{BASE_URL}/api/v1/users/{USER_ID}/page_views"

# === OPTIONAL: Date range filtering ===
params = {
    "start_time": "2025-01-01T00:00:00Z",
    "end_time": "2025-12-31T23:59:59Z",
    "per_page": 100
}

# === PAGINATED REQUEST LOOP ===
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
        params = {}  # Clear params for next page request
    else:
        endpoint = None

# === FILTER BY COURSE ID (optional but helpful) ===
filtered_views = [p for p in page_views if f"/courses/{COURSE_ID}" in p.get("url", "")]

# === WRITE TO CSV ===
csv_filename = f"student_{USER_ID}_course_{COURSE_ID}_pageviews.csv"
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

print(f"✅ CSV file saved as: {csv_filename}")

