# Import a Classic Quiz's questions into a Classic Question Bank (Canvas)
# 1) pip install requests
# 2) Set BASE and TOKEN
# 3) python ImportQuestions.py

import os, time, zipfile, io, requests

BASE  = "https://grayson.instructure.com"
TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"

COURSE_ID = 43637
QUIZ_ID   = 239874

# If both are set, Canvas gives priority to QUESTION_BANK_ID.
QUESTION_BANK_NAME = "Test Import"
QUESTION_BANK_ID   = 700301   # try None if you want to force name-based bank

S = requests.Session()
S.headers.update({"Authorization": f"Bearer {TOKEN}"})


def _get(url, **kw):
    r = S.get(f"{BASE}{url}", **kw); r.raise_for_status(); return r.json()

def _post(url, **kw):
    r = S.post(f"{BASE}{url}", **kw); r.raise_for_status(); return r.json()

def poll_progress(progress_url, sleep_s=2):
    while True:
        r = S.get(progress_url); r.raise_for_status()
        data = r.json()
        pct   = data.get("completion", 0)
        state = data.get("workflow_state", "")
        print(f"[progress] {pct}% state={state}")
        if pct >= 100 or state in ("completed","failed"):
            if state == "failed":
                raise RuntimeError(f"Progress failed: {data}")
            break
        time.sleep(sleep_s)

def assert_classic_quiz(course_id, quiz_id):
    q  = _get(f"/api/v1/courses/{course_id}/quizzes/{quiz_id}")
    qt = q.get("quiz_type")
    print(f"[quiz] id={quiz_id} title={q.get('title')!r} quiz_type={qt!r}")
    if qt is None:
        print("[warn] quiz_type is None (could be New Quizzes/LTI). Export may be empty.")
    return q

def export_quiz_to_qti(course_id, quiz_id, out_zip="quiz_qti.zip"):
    exp = _post(f"/api/v1/courses/{course_id}/content_exports", json={
        "export_type":"qti",
        "select": {"quizzes":[quiz_id]},
        "skip_notifications": True
    })
    print(f"[export] started id={exp.get('id')}")
    poll_progress(exp["progress_url"])

    er = _get(f"/api/v1/courses/{course_id}/content_exports/{exp['id']}")
    att = er.get("attachment")
    if not att or "url" not in att:
        raise RuntimeError("Export finished but no attachment URL (export may be empty).")

    z = S.get(att["url"]); z.raise_for_status()
    with open(out_zip, "wb") as f: f.write(z.content)
    print(f"[export] saved {out_zip} ({len(z.content)} bytes)")

    # sanity check: look for typical QTI filenames
    try:
        with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
            names = set(zf.namelist())
        print(f"[export] zip entries (first 10): {sorted(list(names))[:10]}")
        if not any(n.lower().endswith(("imsmanifest.xml","assessment.xml","assessment_qti.xml")) for n in names):
            print("[warn] ZIP may not be QTI (no imsmanifest/assessment*.xml).")
    except zipfile.BadZipFile:
        print("[warn] Export is not a valid ZIP.")
    return out_zip

def import_qti_into_bank(course_id, zip_path, bank_name=None, bank_id=None):
    if not os.path.exists(zip_path): raise FileNotFoundError(zip_path)
    settings = {}
    if bank_id:  settings["question_bank_id"]   = int(bank_id)
    elif bank_name: settings["question_bank_name"] = bank_name
    else: settings["question_bank_name"] = "Imported Quiz Items"

    mig = _post(f"/api/v1/courses/{course_id}/content_migrations", json={
        "migration_type":"qti_converter",
        "settings": settings,
        "pre_attachment": {
            "name": os.path.basename(zip_path),
            "size": os.path.getsize(zip_path),
            "content_type":"application/zip"
        }
    })
    mig_id = mig.get("id")
    print(f"[import] migration id={mig_id} created")

    up = mig.get("pre_attachment", {})
    upload_url    = up.get("upload_url")
    upload_params = up.get("upload_params", {})
    if not upload_url: raise RuntimeError("No upload_url from pre_attachment.")
    with open(zip_path, "rb") as f:
        ur = requests.post(upload_url, data=upload_params,
                           files={"file": (os.path.basename(zip_path), f, "application/zip")})
        ur.raise_for_status()
    print("[import] file uploaded; polling…")
    poll_progress(mig["progress_url"], sleep_s=3)

    final = _get(f"/api/v1/courses/{course_id}/content_migrations/{mig_id}")
    print(f"[import] final state={final.get('workflow_state')} issues={final.get('migration_issues_count')}")
    if final.get("migration_issues_count", 0):
        issues = _get(f"/api/v1/courses/{course_id}/content_migrations/{mig_id}/migration_issues")
        for iss in issues:
            print(f"[issue] type={iss.get('issue_type')} status={iss.get('workflow_state')} "
                  f"subject={iss.get('subject')} message={iss.get('description')}")

if __name__ == "__main__":
    assert_classic_quiz(COURSE_ID, QUIZ_ID)
    zip_path = export_quiz_to_qti(COURSE_ID, QUIZ_ID)
    import_qti_into_bank(
        COURSE_ID,
        zip_path,
        bank_name=QUESTION_BANK_NAME if not QUESTION_BANK_ID else None,
        bank_id=QUESTION_BANK_ID
    )
    print(f"[done] import attempted into "
          f"{'bank ID '+str(QUESTION_BANK_ID) if QUESTION_BANK_ID else 'bank '+repr(QUESTION_BANK_NAME)}")
