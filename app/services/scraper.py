"""
Job Scraper Service
-------------------
Real job scraping using Adzuna API + Deep Scraping for full descriptions.
"""
import os
import re
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
    
    Args:
        url: The job posting URL to scrape
    
    Returns:
        Full job description text, or None if scraping fails
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
    except httpx.HTTPStatusError as e:
        logger.warning(f"Deep scrape HTTP error: {e.response.status_code} for {url}")
        return None
    except httpx.RequestError as e:
        logger.warning(f"Deep scrape request failed: {e}")
        return None
    except Exception as e:
        logger.warning(f"Deep scrape unexpected error: {e}")
        return None
    
    # Parse HTML
    soup = BeautifulSoup(html, "html.parser")
    
    # Remove script and style elements
    for element in soup(["script", "style", "nav", "header", "footer", "aside"]):
        element.decompose()
    
    # Try to find job description in common containers
    description_text = ""
    
    # Strategy 1: Look for common job description selectors
    selectors = [
        # Greenhouse
        '[data-qa="job-description"]',
        '.job-description',
        '#job-description',
        '.content__content',
        # Lever
        '.posting-page',
        '.section-wrapper',
        '[data-qa="job-detail"]',
        # Workable
        '.job-description-wrapper',
        # Generic
        'article',
        '.job-details',
        '.job-content',
        'main',
    ]
    
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            text = element.get_text(separator='\n', strip=True)
            if len(text) > 200:  # Must have substantial content
                description_text = text
                break
    
    # Strategy 2: Fallback to body text if no specific container found
    if not description_text or len(description_text) < 200:
        body = soup.find('body')
        if body:
            description_text = body.get_text(separator='\n', strip=True)
    
    # Clean up the text
    if description_text:
        # Remove excessive whitespace
        lines = [line.strip() for line in description_text.split('\n') if line.strip()]
        description_text = '\n'.join(lines)
        
        # Truncate if too long (keep first 8000 chars for AI context)
        if len(description_text) > 8000:
            description_text = description_text[:8000] + "..."
        
        logger.info(f"✅ Deep scrape success: {len(description_text)} chars extracted")
        return description_text
    
    logger.warning(f"⚠️ Deep scrape: No content found for {url}")
    return None


def search_adzuna_jobs(query: str, country: str = "us", results_per_page: int = 10) -> List[Dict[str, Any]]:
    """
    Search for jobs using the Adzuna API.
    """
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        logger.warning("⚠️ Adzuna API credentials not configured.")
        return []
    
    url = f"{ADZUNA_BASE_URL}/{country}/search/1"
    
    params = {
        "app_id": ADZUNA_APP_ID,
        "app_key": ADZUNA_APP_KEY,
        "what": query,
        "results_per_page": results_per_page,
        "content-type": "application/json",
    }
    
    logger.info(f"🔍 Searching Adzuna for: {query}")
    
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
        location = location_obj.get("display_name", "Remote") if isinstance(location_obj, dict) else "Remote"
        
        jobs.append({
            "id": f"adzuna-{job_id}",
            "title": title[:200],
            "company": company[:100],
            "location": location[:100],
            "url": item.get("redirect_url", ""),
            "description": item.get("description", "")[:2000],
            "salary_min": item.get("salary_min"),
            "salary_max": item.get("salary_max"),
            "is_remote": "remote" in location.lower() or "remote" in title.lower(),
            "source": "Adzuna",
        })
    
    return jobs


def run_scraper(query: str = "AI Engineer", country: str = "us") -> Dict[str, Any]:
    """
    Main scraper function. Fetches jobs from Adzuna and saves to database.
    """
    logger.info(f"🔍 SCRAPER: Starting job scrape for '{query}'...")
    
    jobs = search_adzuna_jobs(query, country=country, results_per_page=15)
    
    if not jobs:
        return {
            "status": "success",
            "added": 0,
            "skipped": 0,
            "total_processed": 0,
            "query": query,
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
            "source": "Adzuna",
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
    Updates the database with the full description.
    
    Args:
        job_id: The job ID to enrich
    
    Returns:
        Result with status and updated description length
    """
    db = SessionLocal()
    
    try:
        job = db.query(JobPost).filter(JobPost.id == job_id).first()
        
        if not job:
            return {"status": "error", "error": "Job not found"}
        
        if not job.url:
            return {"status": "error", "error": "Job has no URL"}
        
        # Check if already has full description
        current_len = len(job.description or "")
        if current_len > 500:
            return {"status": "skipped", "reason": "Already has full description", "chars": current_len}
        
        # Deep scrape
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
