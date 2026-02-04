"""
Job Scraper Service
-------------------
Real job scraping using Adzuna API + Deep Scraping for full descriptions.
"""
import os
import logging
from uuid import uuid4
from typing import List, Dict, Any, Optional

import httpx
from bs4 import BeautifulSoup

from app.db import SessionLocal
from app.models import JobPost

logger = logging.getLogger(__name__)

# --- Adzuna API Configuration ---
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
ADZUNA_BASE_URL = "https://api.adzuna.com/v1/api/jobs"

# --- User Agent for Deep Scraping ---
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def scrape_job_details(url: str) -> Optional[str]:
    """
    Deep scrape a job posting URL to extract the full description text.
    """
    if not url:
        return None
    
    logger.info(f"🔍 Deep scraping: {url[:60]}...")
    
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            html = response.text
    except Exception as e:
        logger.warning(f"Deep scrape failed: {e}")
        return None
    
    soup = BeautifulSoup(html, "html.parser")
    
    for element in soup(["script", "style", "nav", "header", "footer", "aside"]):
        element.decompose()
    
    description_text = ""
    
    selectors = [
        '[data-qa="job-description"]', '.job-description', '#job-description',
        '.content__content', '.posting-page', '.section-wrapper',
        '.job-description-wrapper', 'article', '.job-details', '.job-content', 'main',
    ]
    
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            text = element.get_text(separator='\n', strip=True)
            if len(text) > 200:
                description_text = text
                break
    
    if not description_text or len(description_text) < 200:
        body = soup.find('body')
        if body:
            description_text = body.get_text(separator='\n', strip=True)
    
    if description_text:
        lines = [line.strip() for line in description_text.split('\n') if line.strip()]
        description_text = '\n'.join(lines)
        
        if len(description_text) > 8000:
            description_text = description_text[:8000] + "..."
        
        logger.info(f"✅ Deep scrape success: {len(description_text)} chars")
        return description_text
    
    return None


def search_adzuna_jobs(query: str, location: str = "", country: str = "us", results_per_page: int = 15) -> List[Dict[str, Any]]:
    """
    Search for jobs using the Adzuna API.
    
    Args:
        query: Search query (e.g., "AI Engineer")
        location: Location filter (e.g., "New York", "Remote")
        country: Country code (us, gb, ca, etc.)
        results_per_page: Number of results to fetch
    """
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        logger.warning("⚠️ Adzuna API credentials not configured.")
        return []
    
    # --- DYNAMIC REGION DETECTION ---
    # Check if location indicates UK/GB region
    location_lower = location.lower() if location else ""
    UK_INDICATORS = [
        'london', 'manchester', 'birmingham', 'edinburgh', 'glasgow', 
        'liverpool', 'bristol', 'leeds', 'sheffield', 'newcastle',
        'nottingham', 'cardiff', 'belfast', 'oxford', 'cambridge',
        'uk', 'united kingdom', 'england', 'scotland', 'wales', 'gb'
    ]
    
    detected_country = country  # Default
    for uk_city in UK_INDICATORS:
        if uk_city in location_lower:
            detected_country = "gb"
            print(f"[SEARCH] Switching Region to: GB (detected '{uk_city}' in location)")
            logger.info(f"[SEARCH] Switching Region to: GB (detected '{uk_city}')")
            break
    
    url = f"{ADZUNA_BASE_URL}/{detected_country}/search/1"
    
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "what": query,
        "results_per_page": results_per_page,
        "content-type": "application/json",
    }
    
    # Add location filter if provided
    if location and location.strip():
        params["where"] = location.strip()
    
    logger.info(f"🔍 Searching Adzuna ({detected_country.upper()}): query='{query}', location='{location}'")
    
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except Exception as e:
        logger.error(f"Adzuna API error: {e}")
        return []
    
    results = data.get("results", [])
    logger.info(f"✅ Adzuna returned {len(results)} jobs")
    
    jobs = []
    for item in results:
        job_id = str(item.get("id", f"adzuna-{uuid4().hex[:8]}"))
        title = item.get("title", "Unknown Role")
        
        company_obj = item.get("company", {})
        company = company_obj.get("display_name", "Unknown") if isinstance(company_obj, dict) else "Unknown"
        
        location_obj = item.get("location", {})
        job_location = location_obj.get("display_name", "Remote") if isinstance(location_obj, dict) else "Remote"
        
        # Salary handling - ensure clean values
        salary_min = item.get("salary_min")
        salary_max = item.get("salary_max")
        
        # Convert to int and handle edge cases
        try:
            salary_min = int(salary_min) if salary_min else None
        except (ValueError, TypeError):
            salary_min = None
            
        try:
            salary_max = int(salary_max) if salary_max else None
        except (ValueError, TypeError):
            salary_max = None
        
        jobs.append({
            "id": f"adzuna-{job_id}",
            "title": title[:200],
            "company": company[:100],
            "location": job_location[:100],
            "url": item.get("redirect_url", ""),
            "description": item.get("description", "")[:2000],
            "salary_min": salary_min,
            "salary_max": salary_max,
            "is_remote": "remote" in job_location.lower() or "remote" in title.lower(),
            "source": "Adzuna",
        })
    
    # --- STRICT REGEX WORD-BOUNDARY FILTER ---
    import re
    
    # Banned words - must match as complete words (word boundaries)
    BANNED_WORDS = [
        # Healthcare
        'nurse', 'nursing', 'rn', 'lpn', 'cna', 'therapist', 'caregiver',
        'phlebotomist', 'pharmacy', 'pharmacist', 'medical',
        # Transportation  
        'driver', 'cdl', 'truck', 'trucker', 'delivery', 'courier',
        # Sales/Marketing
        'sales', 'representative', 'recruiter', 'marketing',
        # Technical trades
        'technician', 'mechanic', 'electrician', 'plumber', 'hvac',
        # Service/Retail
        'cashier', 'retail', 'warehouse', 'picker', 'packer', 'stocker',
        'housekeeper', 'janitor', 'custodian', 'aide',
        # Education
        'tutor', 'teacher', 'instructor',
        # Food service
        'cook', 'chef', 'server', 'waiter', 'waitress', 'bartender',
        # Security
        'security',
    ]
    
    # Build regex pattern with word boundaries
    BANNED_PATTERN = r'\b(' + '|'.join(BANNED_WORDS) + r')\b'
    
    query_lower = query.lower()
    query_words = [w.lower() for w in query.split() if len(w) >= 2]
    
    # Build query pattern to check if user searched for banned word
    QUERY_PATTERN = r'\b(' + '|'.join(query_words) + r')\b' if query_words else None
    
    def check_job_regex(job: Dict[str, Any]) -> tuple:
        """Check if job passes regex filter. Returns (keep, reason)."""
        title = job.get("title", "")
        title_lower = title.lower()
        
        # STEP 1: Check for banned words using REGEX word boundaries
        banned_match = re.search(BANNED_PATTERN, title_lower, re.IGNORECASE)
        
        if banned_match:
            matched_word = banned_match.group(1)
            # Only ban if user didn't search for this word
            if not re.search(r'\b' + re.escape(matched_word) + r'\b', query_lower, re.IGNORECASE):
                return (False, f"Banned: '{matched_word}'")
        
        # STEP 2: Check if at least one query word is in title
        if query_words:
            query_match = re.search(QUERY_PATTERN, title_lower, re.IGNORECASE) if QUERY_PATTERN else None
            if not query_match:
                return (False, "No query match")
        
        return (True, "Passed")
    
    # Apply filter using list comprehension (avoids iteration bugs)
    original_count = len(jobs)
    kept_jobs = []
    
    for job in jobs:
        title = job.get("title", "Unknown")
        keep, reason = check_job_regex(job)
        
        # Debug print for every job
        result = "KEEP" if keep else "DISCARD"
        print(f"[FILTER] Checking '{title}'... Result: {result} ({reason})")
        
        if keep:
            kept_jobs.append(job)
    
    print(f"[FILTER] ✅ Kept {len(kept_jobs)}/{original_count} jobs for query '{query}'")
    logger.info(f"[FILTER] ✅ Kept {len(kept_jobs)}/{original_count} jobs for query '{query}'")
    return kept_jobs


def run_scraper(query: str = "AI Engineer", country: str = "us", location: str = "") -> Dict[str, Any]:
    """
    Main scraper function. Fetches jobs from Adzuna and saves to database.
    
    Args:
        query: Search query for jobs
        country: Country code
        location: Location filter
    """
    logger.info(f"🔍 SCRAPER: Starting search for '{query}' in '{location or 'any location'}'...")
    
    jobs = search_adzuna_jobs(query, location=location, country=country, results_per_page=15)
    
    if not jobs:
        return {
            "status": "success",
            "added": 0,
            "skipped": 0,
            "total_processed": 0,
            "query": query,
            "location": location,
            "source": "Adzuna",
        }
    
    db = SessionLocal()
    added = 0
    skipped = 0
    
    try:
        for job_data in jobs:
            existing = db.query(JobPost).filter(
                (JobPost.id == job_data["id"]) | 
                (JobPost.url == job_data.get("url"))
            ).first()
            
            if existing:
                skipped += 1
                continue
            
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
            logger.info(f"✅ Added: {job_data['title']} at {job_data['company']}")
        
        db.commit()
        
        return {
            "status": "success",
            "added": added,
            "skipped": skipped,
            "total_processed": len(jobs),
            "query": query,
            "location": location,
            "source": "Adzuna",
            "jobs": jobs,  # Return filtered jobs directly
        }
        
    except Exception as e:
        logger.error(f"❌ SCRAPER ERROR: {e}")
        db.rollback()
        return {"status": "error", "error": str(e), "added": added, "query": query}
    finally:
        db.close()


def enrich_job_description(job_id: str) -> Dict[str, Any]:
    """
    Enrich a job's description by deep scraping its URL.
    """
    db = SessionLocal()
    
    try:
        job = db.query(JobPost).filter(JobPost.id == job_id).first()
        
        if not job:
            return {"status": "error", "error": "Job not found"}
        
        if not job.url:
            return {"status": "error", "error": "Job has no URL"}
        
        current_len = len(job.description or "")
        if current_len > 500:
            return {"status": "skipped", "reason": "Already has full description", "chars": current_len}
        
        full_description = scrape_job_details(job.url)
        
        if full_description and len(full_description) > current_len:
            job.description = full_description
            db.commit()
            return {"status": "success", "chars": len(full_description)}
        else:
            return {"status": "failed", "reason": "Could not extract more content"}
    
    except Exception as e:
        logger.error(f"Enrich error: {e}")
        db.rollback()
        return {"status": "error", "error": str(e)}
    finally:
        db.close()
