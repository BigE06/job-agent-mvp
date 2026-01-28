import sys
import os

# Add project root to sys.path
sys.path.append(os.getcwd())

from app.services.adzuna import fetch_jobs_from_api

print("Testing Adzuna API...")
jobs = fetch_jobs_from_api(query="software developer", location="London")

if jobs:
    print(f"Success! Fetched {len(jobs)} jobs.")
    print("Sample job:", jobs[0]['title'], "at", jobs[0]['company'])
else:
    print("Failed to fetch jobs or no jobs found.")
