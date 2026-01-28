from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.models import JobPost
from app.utils import uid

SAMPLE_JOBS = [
    {
        "company": "Acme Analytics",
        "title": "Digital Transformation Analyst",
        "location": "London, UK",
        "url": "https://careers.example.com/roles/123",
        "description": "Drive analytics initiatives and support transformation programmes.",
        "requirements": "SQL, Python, stakeholder management, process mapping",
        "is_remote": True,
        "visa_sponsorship": True,
        "salary_min": 40000.0,
        "salary_max": 60000.0,
    },
    {
        "company": "Bytebank",
        "title": "Product Analyst",
        "location": "London, UK",
        "url": "https://jobs.example.com/roles/456",
        "description": "Partner with PMs to optimise funnel and monetisation.",
        "requirements": "Experimentation, BI tools, SQL",
        "is_remote": False,
        "visa_sponsorship": False,
        "salary_min": 45000.0,
        "salary_max": 65000.0,
    },
]

def seed_sample_jobs(db: Session) -> int:
    """Seed a few sample job posts if table is empty."""
    count = db.query(JobPost).count()
    if count > 0:
        return 0
    for j in SAMPLE_JOBS:
        job = JobPost(
            id=uid(),
            source="seed",
            external_id=None,
            company=j["company"],
            title=j["title"],
            location=j["location"],
            url=j["url"],
            description=j["description"],
            requirements=j["requirements"],
            salary_min=j["salary_min"],
            salary_max=j["salary_max"],
            is_remote=j["is_remote"],
            visa_sponsorship=j["visa_sponsorship"],
            source_ts=datetime.utcnow() - timedelta(days=1),
        )
        db.add(job)
    db.commit()
    return len(SAMPLE_JOBS)
