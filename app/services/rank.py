from sqlalchemy.orm import Session
from app.models import JobPost
from typing import Iterable
import math

def keyword_score(text: str, keywords: Iterable[str]) -> float:
    if not text:
        return 0.0
    text_lower = text.lower()
    hits = sum(1 for k in keywords if k.lower() in text_lower)
    return hits / max(1, len(list(keywords)))

def rank_job(job: JobPost, profile_keywords: list[str]) -> float:
    desc = (job.title or "") + " " + (job.description or "") + " " + (job.requirements or "")
    base = keyword_score(desc, profile_keywords)
    # Simple boosts
    boost = 0.0
    if job.visa_sponsorship:
        boost += 0.1
    if job.is_remote:
        boost += 0.05
    return min(1.0, base + boost)
