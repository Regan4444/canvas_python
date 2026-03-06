import requests

# === Required Variables ===
access_token = 'paste token here'
course_id = 00000  # Replace with your Canvas course ID
assignment_id = 000000  # Replace with the assignment ID
student_id = 00000  # Replace with the Canvas user ID of the student

# === API Setup ===
base_url = 'paste domain here'  # Replace with your Canvas base URL
headers = {
    'Authorization': f'Bearer {access_token}'
}

# === API Endpoint ===
url = f'{base_url}/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/{student_id}'

# === API Request ===
response = requests.get(url, headers=headers)

if response.status_code == 200:
    submission = response.json()
    if submission['submitted_at']:
        print(f"Student {student_id} submitted the assignment at: {submission['submitted_at']}")
        print(f"Submission status: {submission['workflow_state']}")
        print(f"Grade: {submission.get('grade')}")
    else:
        print(f"Student {student_id} has NOT submitted the assignment.")
else:
    print(f"Failed to retrieve submission: {response

