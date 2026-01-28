import requests

ADZUNA_APP_ID = "71988e68"
ADZUNA_APP_KEY = "f9bcf3789cf15740c9fb68504d536b5d"
BASE_URL = "https://api.adzuna.com/v1/api/jobs/gb/search/1"

params = {
    "app_id": ADZUNA_APP_ID,
    "app_key": ADZUNA_APP_KEY,
    "results_per_page": 1,
    "what": "software",
    "content-type": "application/json"
}

try:
    print(f"Requesting {BASE_URL}...")
    response = requests.get(BASE_URL, params=params)
    print(f"Status Code: {response.status_code}")
    print(f"Response Body: {response.text[:500]}") # Print first 500 chars
except Exception as e:
    print(f"Error: {e}")
