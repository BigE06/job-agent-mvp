import requests
import uuid

# --- CONFIGURATION ---
ADZUNA_APP_ID = "71988e68"
ADZUNA_APP_KEY = "f9bcf3789cf15740c9fb68504d536b5d"
BASE_URL = "https://api.adzuna.com/v1/api/jobs/gb/search/1"
# ---------------------

def fetch_jobs_from_api(query="software developer", location="remote"):
    """
    Fetches jobs from Adzuna and maps them to our DB schema.
    """
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "results_per_page": 5,
        "what": query,
        "where": location,
        "content-type": "application/json"
    }

    try:
        response = requests.get(BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()
        
        mapped_jobs = []
        for item in data.get('results', []):
            # Adzuna returns 'id' as integer, we treat as string
            mapped_jobs.append({
                "id": str(item.get('id')),
                "title": item.get('title'),
                "company": item.get('company', {}).get('display_name'),
                "url": item.get('redirect_url'),
                "description": item.get('description'),
                "status": "new"
            })
        return mapped_jobs
    except Exception as e:
        print(f"Adzuna API Error: {e}")
        return []
