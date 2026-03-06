#-------------------------------
#The purpose of this script is to add the iDesign template wrapper to pages in
#a Canvas course.  To use it, enter the course id as given below and run the script.
#The script will add the water mark as well as the colors required by the iDesign template.
#-------------------------------


import os
import time
import requests

# ----------------------------
# CONFIGURATION
# ----------------------------
CANVAS_BASE = os.getenv("CANVAS_BASE", "https://grayson.instructure.com")
TOKEN       = os.getenv("CANVAS_TOKEN", "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU")
COURSE_ID   = os.getenv("COURSE_ID", "46246")

HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# ----------------------------
# HELPER FUNCTIONS
# ----------------------------

def paged(url, params=None):
    """Generator for paginated GET requests"""
    while url:
        r = requests.get(url, headers=HEADERS, params=params)
        r.raise_for_status()
        for item in r.json():
            yield item
        next_link = None
        if 'link' in r.headers:
            for part in r.headers['link'].split(','):
                if 'rel="next"' in part:
                    next_link = part.split(';')[0].strip()[1:-1]
        url = next_link
        params = None

def list_pages(course_id):
    url = f"{CANVAS_BASE}/api/v1/courses/{course_id}/pages"
    return paged(url, params={"per_page": 100})

def get_page(course_id, page_url):
    url = f"{CANVAS_BASE}/api/v1/courses/{course_id}/pages/{page_url}"
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return r.json()

def update_page(course_id, page_url, new_body):
    url = f"{CANVAS_BASE}/api/v1/courses/{course_id}/pages/{page_url}"
    data = {"wiki_page[body]": new_body}
    r = requests.put(url, headers=HEADERS, data=data)
    r.raise_for_status()
    return r.json()

def wrap_page(html):
    """Wraps entire page body in <div class="grayson-page-wrapper"> ... </div>"""
    if not html:
        html = ""
    trimmed = html.strip()
    # Avoid double-wrapping if it’s already wrapped
    if trimmed.startswith('<div class="grayson-page-wrapper"') and trimmed.endswith("</div>"):
        return html, False
    new_html = f'<div class="grayson-page-wrapper">\n{trimmed}\n</div>'
    return new_html, True

# ----------------------------
# MAIN PROCESS
# ----------------------------

updated = 0
skipped = 0
unpublished = 0

for p in list_pages(COURSE_ID):
    if not p.get("published", False):
        unpublished += 1
        continue  # ✅ skip unpublished pages

    slug = p["url"]
    detail = get_page(COURSE_ID, slug)
    body = detail.get("body", "")
    new_body, changed = wrap_page(body)

    if not changed:
        skipped += 1
        continue

    update_page(COURSE_ID, slug, new_body)
    updated += 1
    print(f"✔ Wrapped: {p['title']}")
    time.sleep(0.25)  # Gentle rate limit

print(f"\n✅ Done.")
print(f"   Updated pages:     {updated}")
print(f"   Skipped (already): {skipped}")
print(f"   Unpublished:       {unpublished}")
