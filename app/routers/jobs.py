from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any, Dict, List
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, or_

from app.db import SessionLocal
from app.models import JobPost
from app.services.scraper import run_scraper

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _utc_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def _job_to_dict(job: JobPost) -> Dict[str, Any]:
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": job.url,
        "description": job.description,
        "requirements": job.requirements,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "is_remote": job.is_remote,
        "visa_sponsorship": job.visa_sponsorship,
        "source": job.source,
        "source_ts": job.source_ts.isoformat() if job.source_ts else None,
        "fetched_at": job.fetched_at.isoformat() if job.fetched_at else None,
        "created_at": job.fetched_at.isoformat() if job.fetched_at else None, # Backwards compat
    }

@router.get("/jobs")
def list_jobs(limit: int = 200, db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """
    DB-backed job list.
    """
    stmt = select(JobPost).order_by(JobPost.fetched_at.desc()).limit(max(1, limit))
    jobs = db.scalars(stmt).all()
    return [_job_to_dict(j) for j in jobs]

@router.post("/jobs/import")
def import_jobs(payload: Any = Body(...), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Manual import endpoint to DB.
    """
    incoming: List[Dict[str, Any]] = []

    if isinstance(payload, dict) and isinstance(payload.get("jobs"), list):
        incoming = [j for j in payload["jobs"] if isinstance(j, dict)]
    elif isinstance(payload, list):
        incoming = [j for j in payload if isinstance(j, dict)]
    elif isinstance(payload, dict):
        incoming = [payload]
    else:
        return {"ok": False, "error": "Payload must be an object, array, or {jobs:[...]}"}

    added = 0
    updated = 0
    
    for j in incoming:
        data = dict(j)
        
        # Keys for finding duplicates
        url = str(data.get("url", "")).strip()
        title = str(data.get("title", "")).strip()
        company = str(data.get("company", "")).strip()
        location = str(data.get("location", "")).strip()
        
        # Try to find existing
        existing_job = None
        if url:
             existing_job = db.scalar(select(JobPost).where(JobPost.url == url))
        
        if not existing_job and title and company:
            # Fallback composite check
            # We use ILIKE logic manually or strict match. 
            # For simplicity, let's use exact match or basic normalization if needed.
            # Using specific filters for MVP.
            stmt = select(JobPost).where(
                JobPost.title == title,
                JobPost.company == company,
                JobPost.location == location
            )
            existing_job = db.scalar(stmt)

        if existing_job:
            # For manual imports, we might want to update fields? 
            # Let's assume re-importing updates the description/metadata.
            # But we won't overwrite ID.
            updated += 1
            # Update fields if provided
            if data.get("description"): existing_job.description = data.get("description")
            if data.get("requirements"): existing_job.requirements = data.get("requirements")
            if data.get("salary_min"): existing_job.salary_min = data.get("salary_min")
            if data.get("salary_max"): existing_job.salary_max = data.get("salary_max")
            # existing_job.fetched_at = datetime.utcnow() # Maybe update definition of 'freshness'?
        else:
            # Create new
            new_id = data.get("id") or ("job-" + uuid4().hex[:10])
            new_job = JobPost(
                id=new_id,
                source=data.get("source", "manual"),
                url=url if url else None,
                title=title,
                company=company,
                location=location,
                description=data.get("description"),
                requirements=data.get("requirements"),
                salary_min=data.get("salary_min"),
                salary_max=data.get("salary_max"),
                is_remote=data.get("is_remote", False),
                visa_sponsorship=data.get("visa_sponsorship", False),
                fetched_at=datetime.utcnow()
            )
            db.add(new_job)
            added += 1

    db.commit()

    return {"ok": True, "added": added, "updated": updated, "backend": "sqlite"}

@router.post("/jobs/{job_id}/tailor", response_class=HTMLResponse)
def tailor(job_id: str, db: Session = Depends(get_db)) -> HTMLResponse:
    """
    Returns HTML so the viewer can POST into an iframe.
    """
    job = db.scalar(select(JobPost).where(JobPost.id == job_id))
    
    if not job:
         return HTMLResponse(
            f"""<!doctype html><html><body style="font-family:Segoe UI,Arial;padding:16px">
            <h3>Job not found.</h3>
            <p>job_id: <code>{html.escape(job_id)}</code></p>
            <p>Tip: refresh the jobs list and try again.</p>
            </body></html>""",
            status_code=404,
        )

    title = html.escape(job.title or "")
    company = html.escape(job.company or "")
    location = html.escape(job.location or "")
    url = html.escape(job.url or "")
    desc = html.escape(job.description or "")

    body = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Application Pack</title>
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; padding: 16px; line-height: 1.45; }}
    .h {{ font-size: 18px; font-weight: 700; margin: 0 0 8px; }}
    .sub {{ color: #555; margin: 0 0 16px; }}
    .box {{ border: 1px solid #eee; border-radius: 12px; padding: 12px; margin: 12px 0; }}
    .k {{ font-weight: 700; margin-bottom: 6px; }}
    pre {{ white-space: pre-wrap; font-family: inherit; }}
    a {{ color: #0a66c2; }}
  </style>
</head>
<body>
  <div class="h">Application Pack (Draft)</div>
  <div class="sub">{company} • {location} • <a href="{url}" target="_blank" rel="noopener">Open posting</a></div>

  <div class="box">
    <div class="k">1) Fit Summary (placeholder)</div>
    <pre>- Strengths: (TODO)
- Gaps: (TODO)
- Quick recommendation: (TODO)</pre>
  </div>

  <div class="box">
    <div class="k">2) Cover Letter (placeholder)</div>
    <pre>Dear Hiring Manager,
...
(We will generate this from JD + profile later.)</pre>
  </div>

  <div class="box">
    <div class="k">3) Screening Questions (placeholder)</div>
    <pre>- Are you eligible to work in the UK? (TODO)
- Years of experience? (TODO)
- Key tools? (TODO)</pre>
  </div>

  <div class="box">
    <div class="k">4) Job Description (stored)</div>
    <pre>{desc}</pre>
  </div>
</body>
</html>"""

    return HTMLResponse(body, status_code=200)


# --- ON-DEMAND SCRAPER ---
@router.post("/jobs/scrape")
def trigger_scrape(
    background_tasks: BackgroundTasks,
    query: str = "AI Engineer"
) -> Dict[str, Any]:
    """
    Trigger job scraping in the background.
    Returns immediately while scraper runs asynchronously.
    
    Args:
        query: Search query (default: "AI Engineer")
    """
    background_tasks.add_task(run_scraper, query)
    return {
        "message": "Scraping started",
        "status": "background_task_queued",
        "query": query,
        "note": "Check /jobs endpoint in a few seconds for new listings"
    }


@router.post("/jobs/scrape-sync")
def trigger_scrape_sync(query: str = "AI Engineer") -> Dict[str, Any]:
    """
    Trigger job scraping synchronously (for testing).
    Waits for scraper to complete before returning.
    
    Args:
        query: Search query (default: "AI Engineer")
    """
    result = run_scraper(query)
    return {
        "message": "Scraping complete",
        **result
    }
