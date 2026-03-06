
#-------------------------
#The purpose of the script is to search for discussion assignments completed by a specific
#student determined by user and course id.
#-----------------------------

import requests

# === Required Variables ===
access_token = 'paste token here'
course_id = 00000     # Replace with your Canvas course ID
student_id = 00000    # Replace with the Canvas user ID of the student

# === API Setup ===
base_url = 'paste domain here'  # Replace with your Canvas base URL
headers = {
    'Authorization': f'Bearer {access_token}'
}

# === Step 1: Get All Assignments (Filtered to Graded Discussions) ===
assignments_url = f'{base_url}/api/v1/courses/{course_id}/assignments?per_page=100'
assignments_response = requests.get(assignments_url, headers=headers)

if assignments_response.status_code != 200:
    print(f"Failed to fetch assignments: {assignments_response.status_code} - {assignments_response.text}")
    exit()

assignments = assignments_response.json()
graded_discussions = [a for a in assignments if "discussion_topic" in a.get("submission_types", [])]

print(f"Found {len(graded_discussions)} graded discussion assignments.\n")

# === Step 2: Check Submissions for Each Graded Discussion ===
for assignment in graded_discussions:
    assignment_id = assignment['id']
    assignment_name = assignment['name']

    submission_url = f'{base_url}/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/{student_id}'
    submission_response = requests.get(submission_url, headers=headers)

    if submission_response.status_code != 200:
        print(f"- {assignment_name} (ID: {assignment_id}): Unable to retrieve submission ({submission_response.status_code})")
        continue

    submission = submission_response.json()
    submitted_at = submission.get('submitted_at')
    status = submission.get('workflow_state')
    grade = submission.get('grade')

    if submitted_at:
        print(f"- {assignment_name} (ID: {assignment_id})")
        print(f"  Submitted   : {submitted_at}")
        print(f"  Status      : {status}")
        print(f"  Grade       : {grade}\n")
    else:
        print(f"- {assignment_name} (ID: {assignment_id}): Not submitted.\n")

