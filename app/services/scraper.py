"""
Job Scraper Service
-------------------
Real job scraping using Adzuna API.
Decoupled from startup to ensure server stability.
"""
import os
import logging
from uuid import uuid4
from typing import List, Dict, Any

import httpx

from app.db import SessionLocal
from app.models import JobPost

logger = logging.getLogger(__name__)

# --- Adzuna API Configuration ---
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
ADZUNA_BASE_URL = "https://api.adzuna.com/v1/api/jobs"


def search_adzuna_jobs(query: str, country: str = "us", results_per_page: int = 10) -> List[Dict[str, Any]]:
    """
    Search for jobs using the Adzuna API.
    
    Args:
        query: Search query (e.g., "AI Engineer")
        country: Country code (us, gb, ca, etc.)
        results_per_page: Number of results to fetch
    
    Returns:
        List of job dictionaries ready for database insertion
    """
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        logger.warning("⚠️ Adzuna API credentials not configured. Set ADZUNA_APP_ID and ADZUNA_APP_KEY env vars.")
        return []
    
    url = f"{ADZUNA_BASE_URL}/{country}/search/1"
    
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "what": query,
        "results_per_page": results_per_page,
        "content-type": "application/json",
    }
    
    logger.info(f"🔍 Searching Adzuna for: {query} (country: {country})")
    
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Adzuna API HTTP error: {e.response.status_code} - {e.response.text}")
        return []
    except httpx.RequestError as e:
        logger.error(f"Adzuna API request failed: {e}")
        return []
    except Exception as e:
        logger.error(f"Adzuna API unexpected error: {e}")
        return []
    
    results = data.get("results", [])
    logger.info(f"✅ Adzuna returned {len(results)} jobs")
    
    jobs = []
    for item in results:
        # Extract fields from Adzuna response
        job_id = str(item.get("id", f"adzuna-{uuid4().hex[:8]}"))
        title = item.get("title", "Unknown Role")
        
        # Company is nested
        company_obj = item.get("company", {})
        company = company_obj.get("display_name", "Unknown Company") if isinstance(company_obj, dict) else "Unknown Company"
        
        # Location is nested
        location_obj = item.get("location", {})
        location = location_obj.get("display_name", "Remote") if isinstance(location_obj, dict) else "Remote"
        
        # URL and description
        url = item.get("redirect_url", "")
        description = item.get("description", "")
        
        # Salary info (Adzuna provides min/max)
        salary_min = item.get("salary_min")
        salary_max = item.get("salary_max")
        
        # Category
        category = item.get("category", {})
        category_tag = category.get("tag", "") if isinstance(category, dict) else ""
        
        jobs.append({
            "id": f"adzuna-{job_id}",
            "title": title[:200],
            "company": company[:100],
            "location": location[:100],
            "url": url,
            "description": description[:2000] if description else "",
            "salary_min": salary_min,
            "salary_max": salary_max,
            "is_remote": "remote" in location.lower() or "remote" in title.lower(),
            "source": "Adzuna",
        })
    
    return jobs


def run_scraper(query: str = "AI Engineer", country: str = "us") -> Dict[str, Any]:
    """
    Main scraper function. Fetches jobs from Adzuna and saves to database.
    
    Args:
        query: Search query for jobs (default: "AI Engineer")
        country: Country code (default: "us")
    
    Returns:
        Summary of what was scraped
    """
    logger.info(f"🔍 SCRAPER: Starting job scrape for '{query}'...")
    
    # Fetch jobs from Adzuna
    jobs = search_adzuna_jobs(query, country=country, results_per_page=15)
    
    if not jobs:
        logger.warning("No jobs returned from Adzuna")
        return {
            "status": "success",
            "added": 0,
            "skipped": 0,
            "total_processed": 0,
            "query": query,
            "source": "Adzuna",
        }
    
    # Save to database
    db = SessionLocal()
    added = 0
    skipped = 0
    
    try:
        for job_data in jobs:
            # Check if job already exists by URL or ID
            existing = db.query(JobPost).filter(
                (JobPost.id == job_data["id"]) | 
                (JobPost.url == job_data.get("url"))
            ).first()
            
            if existing:
                logger.debug(f"⏭️ Skipping existing job: {job_data['title']}")
                skipped += 1
                continue
            
            # Create new job
            new_job = JobPost(
                id=job_data["id"],
                title=job_data["title"],
                company=job_data["company"],
                location=job_data.get("location"),
                url=job_data.get("url"),
                description=job_data.get("description"),
                salary_min=job_data.get("salary_min"),
                salary_max=job_data.get("salary_max"),
                is_remote=job_data.get("is_remote", False),
                source=job_data.get("source", "Adzuna"),
            )
            
            db.add(new_job)
            added += 1
            logger.info(f"✅ Added job: {job_data['title']} at {job_data['company']}")
        
        db.commit()
        logger.info(f"🔍 SCRAPER: Complete. Added: {added}, Skipped: {skipped}")
        
        return {
            "status": "success",
            "added": added,
            "skipped": skipped,
            "total_processed": len(jobs),
            "query": query,
            "source": "Adzuna",
        }
        
    except Exception as e:
        logger.error(f"❌ SCRAPER ERROR: {e}")
        db.rollback()
        return {
            "status": "error",
            "error": str(e),
            "added": added,
            "query": query,
        }
    finally:
        db.close()
