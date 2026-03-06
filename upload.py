import os
import requests
#---------------------------------
#The purpose of this script is to allow you to upload a file to Canvas "Files"
#---------------------------------

# ----------------------------
# CONFIGURATION
# ----------------------------
CANVAS_BASE = os.getenv("CANVAS_BASE", "paste domain here")
TOKEN       = os.getenv("CANVAS_TOKEN", "paste token here")
COURSE_ID   = os.getenv("COURSE_ID", "000000")
FILE_PATH   = "file.ext"  # path to the file you want to upload
TARGET_FOLDER = "TestFolder"     # Canvas folder name (existing or new)

HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# ----------------------------
# STEP 1 – Request Upload URL
# ----------------------------
filename = os.path.basename(FILE_PATH)
init_url = f"{CANVAS_BASE}/api/v1/courses/{COURSE_ID}/files"

params = {
    "name": filename,
    "parent_folder_path": TARGET_FOLDER,
    "on_duplicate": "overwrite",  # or "rename" to avoid overwriting
}

with open(FILE_PATH, "rb") as f:
    # Get upload URL
    init_resp = requests.post(init_url, headers=HEADERS, params=params)
    init_resp.raise_for_status()
    upload_data = init_resp.json()

    upload_url = upload_data["upload_url"]
    upload_params = upload_data["upload_params"]

    # ----------------------------
    # STEP 2 – Upload File Bytes
    # ----------------------------
    files = {"file": (filename, f, "application/octet-stream")}
    upload_resp = requests.post(upload_url, data=upload_params, files=files)
    upload_resp.raise_for_status()

    # Final JSON returned after upload
    result = upload_resp.json()

print("✅ Upload complete!")
print(f"Filename: {result['display_name']}")
print(f"File ID:  {result['id']}")
print(f"URL:      {result['url']}")

