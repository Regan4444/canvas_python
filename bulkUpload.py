import os
import glob
import mimetypes
import requests
from pathlib import Path
#-----------------------------
#The purpose of the script is to allow the user to upload multiple files from a PC to the Canvas 
#file folder.
#-----------------------------



# ----------------------------
# CONFIG
# ----------------------------
CANVAS_BASE = os.getenv("CANVAS_BASE", "paste domain here")
TOKEN       = os.getenv("CANVAS_TOKEN", "paste token here")
COURSE_ID   = os.getenv("COURSE_ID", "paste course id here")

# Local files to upload:
LOCAL_DIR   = r"./to_upload"      # folder containing the files
GLOB_MASK   = "*.*"               # change to "*.png" or "*.pdf" etc if you want
# Or: FILES = ["banner.jpg", "syllabus.pdf"]  # you can use an explicit list instead

# Canvas destination folder (created if needed)
TARGET_FOLDER = "Course Content"  # subfolders allowed
ON_DUPLICATE  = "overwrite"               # "overwrite" or "rename"

HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# ----------------------------
# HELPERS
# ----------------------------
def start_upload(course_id, filename, parent_folder_path):
    """
    Step 1: Ask Canvas for an upload URL for this file.
    Canvas will return 'upload_url' and 'upload_params' (usually an S3 presigned post).
    """
    init_url = f"{CANVAS_BASE}/api/v1/courses/{course_id}/files"
    params = {
        "name": filename,
        "parent_folder_path": parent_folder_path,
        "on_duplicate": ON_DUPLICATE,
    }
    r = requests.post(init_url, headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json()  # contains upload_url, upload_params

def complete_upload(upload_url, upload_params, filepath):
    """
    Step 2: POST the actual file bytes to the returned upload_url.
    Returns the final file JSON (with id, url, display_name, etc.).
    """
    filename = os.path.basename(filepath)
    mime, _ = mimetypes.guess_type(filename)
    if not mime:
        mime = "application/octet-stream"
    with open(filepath, "rb") as f:
        files = {"file": (filename, f, mime)}
        r = requests.post(upload_url, data=upload_params, files=files)
    r.raise_for_status()
    return r.json()

def upload_one_file(course_id, filepath, parent_folder_path):
    """
    Uploads a single file and returns (filepath, result_json).
    """
    init = start_upload(course_id, os.path.basename(filepath), parent_folder_path)
    result = complete_upload(init["upload_url"], init["upload_params"], filepath)
    return filepath, result

# ----------------------------
# MAIN
# ----------------------------
def main():
    # Build the list of local files
    local_files = sorted(Path(LOCAL_DIR).glob(GLOB_MASK))
    if not local_files:
        print(f"❌ No files found in {LOCAL_DIR!r} matching {GLOB_MASK!r}.")
        return

    print(f"📤 Uploading {len(local_files)} file(s) to /files/{TARGET_FOLDER} in course {COURSE_ID}...\n")

    successes = []
    failures = []

    for p in local_files:
        try:
            src, result = upload_one_file(COURSE_ID, str(p), TARGET_FOLDER)
            successes.append((src, result))
            print(f"  ✔ {p.name}  →  id={result['id']}")
        except requests.HTTPError as e:
            failures.append((str(p), str(e)))
            print(f"  ✖ {p.name}  →  {e}")

    # ------------------------
    # SUMMARY
    # ------------------------
    print("\n================ SUMMARY ================")
    print(f"Uploaded OK: {len(successes)}")
    for src, res in successes:
        file_id   = res["id"]
        disp_name = res.get("display_name") or Path(src).name
        # Handy Canvas-relative links for embedding/links inside pages:
        preview = f"/courses/{COURSE_ID}/files/{file_id}/preview"
        download = f"/courses/{COURSE_ID}/files/{file_id}/download"
        print(f" - {disp_name}  (id {file_id})")
        print(f"   preview:  {preview}")
        print(f"   download: {download}")

    if failures:
        print(f"\nFailed: {len(failures)}")
        for src, msg in failures:
            print(f" - {src}: {msg}")

if __name__ == "__main__":
    main()

