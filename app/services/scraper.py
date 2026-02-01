"""
Job Scraper Service
-------------------
Real job scraping using DuckDuckGo Search.
Decoupled from startup to ensure server stability.
"""
import re
import logging
from uuid import uuid4
from datetime import datetime
from typing import List, Dict, Any, Optional

from ddgs import DDGS

from app.db import SessionLocal
from app.models import JobPost

logger = logging.getLogger(__name__)


def extract_company_from_url(url: str) -> Optional[str]:
    """
    Extract company name from ATS URLs (Greenhouse, Lever, Ashby).
    
    Args:
        url: Job posting URL
    
    Returns:
        Company name or None if not found
    """
    pattern = r'(?:boards\.greenhouse\.io|jobs\.lever\.co|ashbyhq\.com)/([^/]+)'
    match = re.search(pattern, url)
    if match:
        return match.group(1).replace('-', ' ').replace('_', ' ').title()
    return None


def search_real_jobs(query: str, max_results: int = 15) -> List[Dict[str, Any]]:
    """
    Search for real job listings using DuckDuckGo.
    
    Args:
        query: Search query (e.g., "AI Engineer site:greenhouse.io")
        max_results: Maximum number of results to fetch
    
    Returns:
        List of job dictionaries ready for database insertion
    """
    logger.info(f"🔍 Searching DuckDuckGo for: {query}")
    
    try:
        results = DDGS().text(query, max_results=max_results)
    except Exception as e:
        logger.error(f"DuckDuckGo search failed: {e}")
        return []
    
    clean_results = []
    
    for item in results:
        link = item.get('href', '')
        
        # Filter: Only keep URLs that look like job postings
        job_indicators = ['/jobs/', '/o/', '/j/', '/apply/', '/posting/', '/careers/', '/position/']
        if not link or not any(x in link.lower() for x in job_indicators):
            logger.debug(f"Skipping non-job URL: {link}")
            continue
        
        # Extract title (often formatted as "Role - Company - Location")
        raw_title = item.get('title', 'Unknown Role')
        title = raw_title.split(' - ')[0].split(' | ')[0].strip()
        
        # Extract company from URL or title
        company = extract_company_from_url(link)
        if not company and ' - ' in raw_title:
            parts = raw_title.split(' - ')
            if len(parts) >= 2:
                company = parts[1].strip()
        if not company:
            company = "Unknown Company"
        
        # Extract location (often in title or default to Remote)
        location = "Remote"
        if ' - ' in raw_title:
            parts = raw_title.split(' - ')
            if len(parts) >= 3:
                location = parts[2].strip()
        
        clean_results.append({
            "id": f"ddg-{uuid4().hex[:8]}",
            "title": title[:200],  # Limit title length
            "company": company[:100],
            "url": link,
            "location": location[:100],
            "description": item.get('body', '')[:2000],
            "source": "DuckDuckGo",
            "is_remote": "remote" in location.lower() or "remote" in raw_title.lower(),
        })
    
    logger.info(f"✅ Found {len(clean_results)} valid job listings")
    return clean_results


def run_scraper(query: str = "AI Engineer") -> Dict[str, Any]:
    """
    Main scraper function. Searches for jobs and saves to database.
    
    Args:
        query: Search query for jobs (default: "AI Engineer")
    
    Returns:
        Summary of what was scraped
    """
    logger.info(f"🔍 SCRAPER: Starting job scrape for '{query}'...")
    
    # Build search query targeting job boards
    search_query = f"{query} (site:greenhouse.io OR site:lever.co OR site:ashbyhq.com OR site:jobs.workable.com)"
    
    # Fetch jobs from DuckDuckGo
    jobs = search_real_jobs(search_query, max_results=20)
    
    if not jobs:
        logger.warning("No jobs found from search")
        return {
            "status": "success",
            "added": 0,
            "skipped": 0,
            "total_processed": 0,
            "query": query,
        }
    
    # Save to database
    db = SessionLocal()
    added = 0
    skipped = 0
    
    try:
        for job_data in jobs:
            # Check if job already exists by URL
            existing = db.query(JobPost).filter(JobPost.url == job_data["url"]).first()
            
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
                is_remote=job_data.get("is_remote", False),
                source=job_data.get("source", "DuckDuckGo"),
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


def generate_mock_jobs() -> List[Dict[str, Any]]:
    """
    Generate mock jobs for testing (fallback if DuckDuckGo fails).
    """
    return [
        {
            "id": f"mock-{uuid4().hex[:8]}",
            "title": "Senior AI Engineer",
            "company": "OpenAI",
            "location": "San Francisco, CA (Remote)",
            "url": "https://openai.com/careers",
            "description": "Join our AI research team...",
            "is_remote": True,
            "source": "Mock",
        },
        {
            "id": f"mock-{uuid4().hex[:8]}",
            "title": "ML Research Scientist",
            "company": "Anthropic",
            "location": "San Francisco, CA",
            "url": "https://anthropic.com/careers",
            "description": "Work on Claude and AI safety...",
            "is_remote": False,
            "source": "Mock",
        },
    ]
