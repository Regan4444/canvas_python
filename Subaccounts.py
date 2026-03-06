#!/usr/bin/env python3
"""
list_canvas_subaccounts_hardcoded.py

Fetches all subaccounts and their SIS IDs from your Canvas domain
and writes them to 'subaccounts.csv'.
"""

import csv
import requests
from urllib.parse import urljoin

# ============================
# 🔧 CONFIGURATION (EDIT THESE)
# ============================
CANVAS_DOMAIN = "paste domain here"  # e.g., "canvas.yourschool.edu"
ACCESS_TOKEN = "paste token here"  #  paste in your access token
ROOT_ACCOUNT_ID = 1   # typically 1 for the main/root account
OUTPUT_FILE = "subaccounts.csv"
# ============================


def get_headers():
    return {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Accept": "application/json"
    }


def get_next_link(link_header):
    """Parse the 'next' pagination link from Canvas Link headers."""
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        if 'rel="next"' in part:
            start = part.find("<")
            end = part.find(">")
            if start != -1 and end != -1:
                return part[start+1:end]
    return None


def fetch_all_subaccounts():
    """Recursively fetch all subaccounts from the root account."""
    base_url = f"https://{CANVAS_DOMAIN}/"
    endpoint = f"/api/v1/accounts/{ROOT_ACCOUNT_ID}/sub_accounts"
    params = {"recursive": "true", "per_page": 100}
    url = urljoin(base_url, endpoint)

    all_accounts = []
    while url:
        response = requests.get(url, headers=get_headers(), params=params if "?" not in url else None)
        if response.status_code != 200:
            raise SystemExit(f"❌ Error {response.status_code}: {response.text}")

        accounts = response.json()
        if not isinstance(accounts, list):
            raise SystemExit("Unexpected JSON response format.")
        all_accounts.extend(accounts)

        next_url = get_next_link(response.headers.get("Link"))
        url = next_url
        params = None  # after first request, use direct pagination URLs

    return all_accounts


def write_csv(accounts):
    """Write account information to a CSV file."""
    fields = ["id", "name", "parent_account_id", "account_number", "sis_account_id", "workflow_state"]
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for a in accounts:
            writer.writerow({
                "id": a.get("id"),
                "name": a.get("name"),
                "parent_account_id": a.get("parent_account_id"),
                "account_number": a.get("account_number"),
                "sis_account_id": a.get("sis_account_id"),
                "workflow_state": a.get("workflow_state"),
            })


def main():
    print(f"📡 Connecting to https://{CANVAS_DOMAIN} ...")
    accounts = fetch_all_subaccounts()
    print(f"✅ Retrieved {len(accounts)} subaccounts.")
    write_csv(accounts)
    print(f"💾 Results saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

