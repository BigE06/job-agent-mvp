"""
Job Scraper Service
-------------------
On-demand job scraping that saves to the database.
Decoupled from startup to ensure server stability.
"""
import logging
from uuid import uuid4
from datetime import datetime
from typing import List, Dict, Any

from app.db import SessionLocal
from app.models import JobPost

logger = logging.getLogger(__name__)


def generate_mock_jobs() -> List[Dict[str, Any]]:
    """
    Generate realistic mock AI job listings for testing.
    Replace with real scraper logic when ready.
    """
    return [
        {
            "id": f"scrape-{uuid4().hex[:8]}",
            "title": "Senior AI Engineer",
            "company": "OpenAI",
            "location": "San Francisco, CA (Remote)",
            "url": "https://openai.com/careers",
            "description": """We're looking for a Senior AI Engineer to join our research team.

Responsibilities:
- Design and implement large-scale ML systems
- Contribute to cutting-edge AI research
- Collaborate with world-class researchers

Requirements:
- 5+ years of experience in ML/AI
- Strong Python and PyTorch skills
- Experience with distributed training
- PhD preferred but not required""",
            "is_remote": True,
            "salary_min": 200000,
            "salary_max": 350000,
            "source": "Scraper-v1",
        },
        {
            "id": f"scrape-{uuid4().hex[:8]}",
            "title": "LLM Research Scientist",
            "company": "Anthropic",
            "location": "San Francisco, CA",
            "url": "https://anthropic.com/careers",
            "description": """Join Anthropic to work on Claude and next-generation AI safety.

What you'll do:
- Conduct research on large language models
- Develop novel alignment techniques
- Publish papers and advance AI safety

What we're looking for:
- PhD in ML, NLP, or related field
- Published research in top venues
- Experience with transformer architectures
- Passion for AI safety""",
            "is_remote": False,
            "salary_min": 250000,
            "salary_max": 400000,
            "source": "Scraper-v1",
        },
        {
            "id": f"scrape-{uuid4().hex[:8]}",
            "title": "Machine Learning Engineer",
            "company": "Google DeepMind",
            "location": "London, UK (Hybrid)",
            "url": "https://deepmind.google/careers",
            "description": """DeepMind is seeking an ML Engineer to build production systems.

Role:
- Build and deploy ML models at scale
- Optimize inference pipelines
- Work with research scientists to productionize breakthroughs

Requirements:
- 3+ years of ML engineering experience
- Proficiency in Python, TensorFlow/JAX
- Experience with cloud infrastructure (GCP preferred)
- Strong software engineering fundamentals""",
            "is_remote": False,
            "salary_min": 120000,
            "salary_max": 180000,
            "source": "Scraper-v1",
        },
    ]


def run_scraper() -> Dict[str, Any]:
    """
    Main scraper function. Fetches jobs and saves to database.
    Returns a summary of what was scraped.
    """
    logger.info("🔍 SCRAPER: Starting job scrape...")
    
    db = SessionLocal()
    added = 0
    skipped = 0
    
    try:
        # Get mock jobs (replace with real scraper later)
        jobs = generate_mock_jobs()
        
        for job_data in jobs:
            # Check if job already exists by URL or ID
            existing = db.query(JobPost).filter(
                (JobPost.id == job_data["id"]) | 
                (JobPost.url == job_data.get("url"))
            ).first()
            
            if existing:
                logger.info(f"⏭️ Skipping existing job: {job_data['title']} at {job_data['company']}")
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
                requirements=job_data.get("requirements"),
                is_remote=job_data.get("is_remote", False),
                visa_sponsorship=job_data.get("visa_sponsorship", False),
                salary_min=job_data.get("salary_min"),
                salary_max=job_data.get("salary_max"),
                source=job_data.get("source", "Scraper-v1"),
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
        }
        
    except Exception as e:
        logger.error(f"❌ SCRAPER ERROR: {e}")
        db.rollback()
        return {
            "status": "error",
            "error": str(e),
            "added": added,
        }
    finally:
        db.close()
