"""
Features Router
---------------
AI-powered endpoints for job application assistance.
Supports both SQLAlchemy JobPost model and legacy SQLite saved_jobs.
Includes auto-enrichment for short descriptions.
"""
from __future__ import annotations

import io
import json
import uuid
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, UploadFile, File
from pypdf import PdfReader

from app.services.ai import get_gpt_response
from app.services.scraper import scrape_job_details
from app.db import SessionLocal
from app.models import JobPost

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["AI Features"])

# Minimum description length for AI features to work well
MIN_DESCRIPTION_LENGTH = 500


# --- Helper: Get Legacy DB Connection (for SQLite tables) ---
def get_legacy_db():
    """Get SQLite connection for legacy saved_jobs and profile tables."""
    import sqlite3
    DB_PATH = "jobs.db"
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a job by ID from either PostgreSQL (job_posts) or SQLite (saved_jobs).
    Returns a unified job dict or None.
    """
    # Try PostgreSQL first (job_posts table)
    db = SessionLocal()
    try:
        job = db.query(JobPost).filter(JobPost.id == job_id).first()
        if job:
            return {
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "url": job.url,
                "description": job.description,
                "source": "job_posts",
            }
    finally:
        db.close()
    
    # Fallback to SQLite saved_jobs
    try:
        conn = get_legacy_db()
        c = conn.cursor()
        c.execute("SELECT * FROM saved_jobs WHERE id = ?", (job_id,))
        row = c.fetchone()
        conn.close()
        if row:
            job = dict(row)
            job["source"] = "saved_jobs"
            job["description"] = job.get("notes", "")  # saved_jobs uses notes
            return job
    except Exception as e:
        logger.warning(f"SQLite lookup failed: {e}")
    
    return None


def enrich_if_needed(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check if job description is too short and enrich it via deep scraping.
    Updates the database with the full description if successful.
    """
    description = job.get("description") or ""
    url = job.get("url", "")
    
    if len(description) >= MIN_DESCRIPTION_LENGTH:
        logger.info(f"Description already sufficient ({len(description)} chars)")
        return job
    
    if not url:
        logger.warning("Cannot enrich: job has no URL")
        return job
    
    logger.info(f"📡 Description too short ({len(description)} chars), deep scraping...")
    
    full_description = scrape_job_details(url)
    
    if full_description and len(full_description) > len(description):
        job["description"] = full_description
        
        # Update database
        if job.get("source") == "job_posts":
            db = SessionLocal()
            try:
                db_job = db.query(JobPost).filter(JobPost.id == job["id"]).first()
                if db_job:
                    db_job.description = full_description
                    db.commit()
                    logger.info(f"✅ Updated job_posts with {len(full_description)} chars")
            finally:
                db.close()
    else:
        logger.warning("Deep scrape did not return more content")
    
    return job


# =============================================
# RESUME UPLOAD
# =============================================
@router.post("/upload-resume")
async def upload_resume(file: UploadFile = File(...)):
    """Parse a PDF resume and extract skills."""
    try:
        contents = await file.read()
        pdf_file = io.BytesIO(contents)
        reader = PdfReader(pdf_file)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        
        system_prompt = "You are a data extractor. Extract technical skills."
        user_prompt = f"RESUME: {text[:4000]}\n\nTask: Return comma-separated list of top 15 skills."
        extracted_skills = get_gpt_response(system_prompt, user_prompt, max_tokens=100)
        
        conn = get_legacy_db()
        c = conn.cursor()
        c.execute("SELECT id FROM profile LIMIT 1")
        if c.fetchone():
            c.execute("UPDATE profile SET resume_text = ?, skills = ?", (text, extracted_skills))
        else:
            c.execute("INSERT INTO profile (resume_text, skills) VALUES (?, ?)", (text, extracted_skills))
        conn.commit()
        conn.close()
        
        return {"message": "Parsed", "text": text, "skills": extracted_skills}
    except Exception as e:
        logger.error(f"Resume upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================
# ANALYZE TEXT (Job Description Analysis)
# =============================================
@router.post("/analyze-text")
async def analyze_text(data: dict = Body(...)):
    """Analyze a job description against user's profile."""
    job_text = data.get('job_description', '')
    
    conn = get_legacy_db()
    c = conn.cursor()
    c.execute("SELECT * FROM profile LIMIT 1")
    profile_row = c.fetchone()
    profile = dict(profile_row) if profile_row else {}
    conn.close()
    
    resume_context = profile.get('resume_text', '')
    
    system_prompt = "You are a recruiter API. Return JSON."
    user_prompt = f"JOB: {job_text[:3000]}\nCANDIDATE: {resume_context[:3000]}\nTask: Return JSON with keys: match_score(int), verdict(str), strengths(list), gaps(list), summary(str)."
    
    analysis = get_gpt_response(system_prompt, user_prompt, json_mode=True)
    return {"analysis": analysis}


# =============================================
# GENERATE COVER LETTER (NEW)
# =============================================
@router.post("/generate-cover-letter")
async def generate_cover_letter(data: dict = Body(...)):
    """Generate a professional cover letter for a job."""
    job_id = data.get('job_id')
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    
    job = get_job_by_id(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Enrich description if needed
    job = enrich_if_needed(job)
    
    conn = get_legacy_db()
    c = conn.cursor()
    c.execute("SELECT * FROM profile LIMIT 1")
    profile_row = c.fetchone()
    profile = dict(profile_row) if profile_row else {}
    conn.close()
    
    resume_text = profile.get('resume_text', '')
    if not resume_text:
        raise HTTPException(status_code=400, detail="No resume uploaded. Please upload your resume first.")
    
    job_description = job.get('description', '') or f"Role: {job.get('title')} at {job.get('company')}"
    
    system_prompt = """You are an expert career coach writing professional cover letters.

RULES:
1. Format as a proper cover letter with greeting, 3-4 body paragraphs, and closing.
2. Opening paragraph: Express enthusiasm for the specific role and company.
3. Body paragraphs: Connect the candidate's SPECIFIC experiences to job requirements.
4. Include 1-2 quantifiable achievements from their background.
5. Closing: Strong call-to-action expressing desire for an interview.
6. Tone: Professional, confident, and genuine.
7. Length: 300-400 words.
8. Do NOT use generic filler. Every sentence should add value.

Return JSON: {"greeting": "...", "body": "...", "closing": "...", "full_letter": "..."}"""

    user_prompt = f"""JOB DETAILS:
Title: {job.get('title', 'Role')}
Company: {job.get('company', 'Company')}
Description: {job_description[:3000]}

CANDIDATE RESUME:
{resume_text[:4000]}

Generate a tailored cover letter as JSON."""

    result = get_gpt_response(system_prompt, user_prompt, json_mode=True, max_tokens=1200)
    
    try:
        parsed = json.loads(result)
        return parsed
    except json.JSONDecodeError:
        return {"full_letter": result, "error": "Parsing failed"}


# =============================================
# GENERATE COLD EMAIL (with auto-enrichment)
# =============================================
@router.post("/generate-cold-email")
async def generate_cold_email(data: dict = Body(...)):
    """Generate a high-conversion cold email to a hiring manager."""
    job_id = data.get('job_id')
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    
    job = get_job_by_id(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Enrich if needed
    job = enrich_if_needed(job)
    
    conn = get_legacy_db()
    c = conn.cursor()
    c.execute("SELECT * FROM profile LIMIT 1")
    profile_row = c.fetchone()
    profile = dict(profile_row) if profile_row else {}
    conn.close()
    
    job_context = f"Title: {job.get('title', 'Unknown')}\nCompany: {job.get('company', 'Unknown')}\nDescription: {(job.get('description') or '')[:1500]}"
    resume_text = profile.get('resume_text', '')
    skills = profile.get('skills', '')
    
    system_prompt = """You are a career strategist. Write a concise cold email (max 150 words) to a Hiring Manager.

RULES:
1. Subject line must be catchy and specific to the role.
2. Opening line must hook - no generic "I hope this email finds you well".
3. Body must connect the candidate's specific skills to the company's needs.
4. Include ONE impressive metric or achievement from their background.
5. End with a clear, low-pressure call to action.
6. Tone: Professional but confident.
7. Do NOT use placeholders like '[Your Name]' - use 'Candidate' or leave a generic signature.

Return JSON: {"subject": "...", "body": "..."}"""

    user_prompt = f"""JOB TARGET:
{job_context}

CANDIDATE PROFILE:
{resume_text[:3000]}

KEY SKILLS: {skills}

Generate the cold email as JSON."""

    result = get_gpt_response(system_prompt, user_prompt, json_mode=True, max_tokens=400)
    
    try:
        parsed = json.loads(result)
        return parsed
    except json.JSONDecodeError:
        return {"subject": "Regarding the Open Position", "body": result, "error": "Parsing failed"}


# =============================================
# GENERATE CURATED CV (with auto-enrichment)
# =============================================
@router.post("/generate-curated-cv")
async def generate_curated_cv(data: dict = Body(...)):
    """Generate a tailored CV with Harvard Style CSS. Auto-enriches job description if needed."""
    job_id = data.get('job_id')
    gap_answers = data.get('gap_answers', [])
    
    job = get_job_by_id(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Enrich if needed for better AI context
    job = enrich_if_needed(job)
    
    conn = get_legacy_db()
    c = conn.cursor()
    c.execute("SELECT * FROM profile LIMIT 1")
    profile_row = c.fetchone()
    profile = dict(profile_row) if profile_row else {}
    conn.close()
    
    resume_text = profile.get('resume_text', '')
    if not resume_text:
        raise HTTPException(status_code=400, detail="No resume uploaded.")
    
    job_description = job.get('description', '') or f"{job.get('title', '')} at {job.get('company', '')}"
    
    system_prompt = """You are a Resume Formatting Engine. Output ONLY raw HTML code.
DO NOT use markdown code blocks (no ```html).

YOUR ONLY GOAL is to take the user's raw resume text and format it into a clean, professional HTML structure.

CRITICAL RULES - READ CAREFULLY:
1. DO NOT SUMMARIZE. DO NOT PARAPHRASE. DO NOT SHORTEN.
2. COPY the 'Experience' section EXACTLY as it appears in the source text.
   - If the user lists 5 roles, you MUST output all 5 roles.
   - If a role has 10 bullet points, you MUST output all 10 bullet points.
   - Copy the exact wording. Do not "improve" or "tailor" the bullets.
3. CRITICAL SORTING RULE: You MUST re-order the 'Experience' section in REVERSE CHRONOLOGICAL ORDER.
   - Start with the CURRENT or MOST RECENT job first (e.g., "2024-Present").
   - Then list the previous job, and so on.
4. COPY the 'Education' section EXACTLY as it appears (reverse chronological order).
5. COPY the 'Skills' section EXACTLY as it appears, but you may reorder to prioritize job-relevant skills.
6. The ONLY section you are allowed to WRITE YOURSELF is the 'Professional Profile' summary at the top, which should be 2-3 sentences tailored to the Job Description.

OUTPUT STRUCTURE:
1. Header (Name, Contact Info from source)
2. Professional Profile (YOU WRITE THIS - tailored to the job)
3. Skills (From source, reordered for relevance)
4. Experience (VERBATIM COPY from source - ALL roles, ALL bullets - REVERSE CHRONOLOGICAL ORDER)
5. Education (VERBATIM COPY from source - REVERSE CHRONOLOGICAL ORDER)

CSS Rules (Harvard Style):
- @page { margin: 0; }
- body { font-family: 'Times New Roman', serif; margin: 1in; color: #000; line-height: 1.4; }
- h1 { text-align: center; text-transform: uppercase; font-size: 20pt; margin-bottom: 5px; }
- .contact-info { text-align: center; font-size: 10pt; margin-bottom: 20px; }
- h2 { text-transform: uppercase; font-size: 11pt; border-bottom: 1px solid #000; margin-top: 15px; margin-bottom: 8px; }
- .job-header { display: flex; justify-content: space-between; font-weight: bold; font-size: 11pt; margin-top: 12px; }
- .job-sub { display: flex; justify-content: space-between; font-style: italic; font-size: 11pt; margin-bottom: 2px; }
- ul { margin: 0; padding-left: 18px; }
- li { margin-bottom: 2px; font-size: 11pt; }"""

    user_prompt = f"""
TARGET JOB: {job.get('title', 'Role')} at {job.get('company', 'Company')}
JOB DESCRIPTION: {job_description[:3000]}

=== SOURCE RESUME (COPY EXPERIENCE & EDUCATION VERBATIM) ===
{resume_text[:6000]}

=== GAP SKILLS TO INTEGRATE INTO PROFILE SUMMARY ===
{json.dumps(gap_answers)}

REMINDER: The Experience and Education sections must be copied WORD-FOR-WORD from the source resume above. Only the Professional Profile summary should be written by you.
"""
    
    raw_html = get_gpt_response(system_prompt, user_prompt, max_tokens=4000)
    clean_html = raw_html.replace("```html", "").replace("```", "").strip()
    
    return {"cv_html": clean_html}


# =============================================
# GAP FILL INTERVIEW (with auto-enrichment)
# =============================================
@router.post("/gap-fill-interview")
async def gap_fill_interview(data: dict = Body(...)):
    """Identify missing skills between resume and job description."""
    job_id = data.get('job_id')
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    
    job = get_job_by_id(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Enrich if needed
    job = enrich_if_needed(job)
    
    conn = get_legacy_db()
    c = conn.cursor()
    c.execute("SELECT * FROM profile LIMIT 1")
    profile_row = c.fetchone()
    profile = dict(profile_row) if profile_row else {}
    conn.close()
    
    resume_text = profile.get('resume_text', '')
    if not resume_text:
        raise HTTPException(status_code=400, detail="No resume uploaded. Please upload your resume first.")
    
    job_description = job.get('description', '') or f"{job.get('title', '')} at {job.get('company', '')}"
    
    system_prompt = """You are a strict Skills Gap Analyzer. Your job is to identify ONLY genuine missing skills.

RULES:
1. EXPLICIT GAPS: Skills explicitly stated in the job that are completely absent from the resume.
2. IMPLICIT GAPS: Skills strongly implied by the job (e.g., "Cloud architecture") where the resume has NO related experience.
3. DO NOT hallucinate. If unsure, do not include the skill.
4. Ignore soft skills like "communication" or "teamwork" unless they are a core job requirement.
5. Return 3-7 skills maximum. Quality over quantity.
6. Return ONLY valid JSON. No explanations."""

    user_prompt = f"""JOB DESCRIPTION:
Title: {job.get('title', 'Unknown')}
Company: {job.get('company', 'Unknown')}
Full Description: {job_description[:3000]}

CANDIDATE RESUME:
{resume_text[:4000]}

Task: Identify skills the candidate is MISSING for this role.
Return JSON: {{"missing_skills": ["Skill1", "Skill2"], "job_title": "Title from JD"}}"""

    result = get_gpt_response(system_prompt, user_prompt, json_mode=True, max_tokens=300)
    
    try:
        parsed = json.loads(result)
        return parsed
    except json.JSONDecodeError:
        return {"missing_skills": [], "job_title": job.get('title', 'Unknown'), "error": "AI parsing failed"}


# =============================================
# GENERATE PACK (Cold Email + Strategy)
# =============================================
@router.post("/generate-pack")
async def generate_pack(data: dict = Body(...)):
    """Generate a cold outreach email for a saved job."""
    job_id = data.get('id')
    
    conn = get_legacy_db()
    c = conn.cursor()
    c.execute("SELECT * FROM saved_jobs WHERE id = ?", (job_id,))
    job_row = c.fetchone()
    c.execute("SELECT * FROM profile LIMIT 1")
    profile_row = c.fetchone()
    job = dict(job_row) if job_row else None
    profile = dict(profile_row) if profile_row else {}
    conn.close()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    resume_context = profile.get('resume_text', '') or f"Skills: {profile.get('skills', 'General')}"
    
    system_prompt = """You are a career coach writing professional cold outreach emails.
Output strictly in Email Format:
- Line 1: 'Subject: [Compelling Subject Line]'
- Line 2: [Blank line]
- Line 3: 'Hi [Hiring Team/Name],'
- Body: Concise, 3-4 paragraphs max
- Sign off: 'Best regards, [Candidate Name]'
Do NOT include physical addresses, dates, formal headers, or 'Dear Sir/Madam'."""

    user_prompt = f"JOB: {job['title']} at {job['company']}\nPROFILE: {resume_context[:4000]}\nTask: Write a compelling cold email to apply for this role (150-200 words max)."
    
    content = get_gpt_response(system_prompt, user_prompt)
    return {"message": "Pack Generated", "pack_content": content}


# =============================================
# VOICE INTERVIEW SIMULATOR
# =============================================
@router.post("/interview/start")
async def interview_start(data: dict = Body(...)):
    """Start an interview session with an opening question."""
    job_id = data.get('job_id')
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    
    job = get_job_by_id(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    company = job.get('company', 'the company')
    title = job.get('title', 'this role')
    context_id = str(uuid.uuid4())[:8]
    
    opening_question = f"Tell me about yourself and why you want this {title} role at {company}?"
    
    return {
        "question": opening_question,
        "context_id": context_id,
        "job_title": title,
        "company": company
    }


# =============================================
# DETERMINISTIC INTERVIEW (5 Questions Upfront)
# =============================================
@router.post("/interview/generate-questions")
async def interview_generate_questions(data: dict = Body(...)):
    """
    Generate exactly 5 interview questions upfront.
    Frontend iterates through them without waiting for AI between turns.
    """
    import re
    import json
    from app.services.ai import client, OPENAI_API_KEY
    
    job_id = data.get('job_id')
    resume_text = data.get('resume_text', '')
    
    # Fallback data from request (in case job not in DB yet - race condition)
    fallback_title = data.get('job_title', 'the role')
    fallback_company = data.get('company', 'the company')
    
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    
    # --- CRASH-PROOF: Handle race condition gracefully ---
    job = None
    try:
        job = get_job_by_id(str(job_id))
    except Exception as e:
        logger.warning(f"[INTERVIEW] Error fetching job {job_id}: {e}")
    
    # Use job data if found, otherwise use fallback from request
    if job and isinstance(job, dict):
        raw_title = job.get('title') or fallback_title
        company = job.get('company') or fallback_company
        description = job.get('description', '')[:2000] if job.get('description') else ''
    else:
        logger.warning(f"[INTERVIEW] Job {job_id} not found in DB, using fallback data")
        raw_title = fallback_title
        company = fallback_company
        description = ''
    
    # Clean job title for prompt
    clean_title = re.sub(r'\$[\d,]+.*', '', raw_title)
    clean_title = re.sub(r'\s*[-–—]\s*(?:Remote|Hybrid|Full-?time).*', '', clean_title, flags=re.IGNORECASE)
    clean_title = clean_title.strip()[:50] or 'the role'
    
    # Build prompt
    system_prompt = """You are a strict interview question generator.
Generate exactly 5 professional interview questions for a job candidate.
Return ONLY a raw JSON array of strings with no additional text.

Example output format:
["Question 1?", "Question 2?", "Question 3?", "Question 4?", "Question 5?"]

Rules:
- Questions must be relevant to the job and resume
- Mix behavioral, technical, and situational questions
- Keep each question to 1-2 sentences
- NO pleasantries or filler text
- Output ONLY the JSON array, nothing else"""

    user_prompt = f"""JOB: {clean_title} at {company}

JOB DESCRIPTION:
{description[:1500] if description else 'Not provided'}

CANDIDATE RESUME:
{resume_text[:1500] if resume_text else 'Not provided'}

Generate 5 interview questions:"""

    # Default fallback questions
    FALLBACK_QUESTIONS = [
        f"Tell me about yourself and why you're interested in the {clean_title} role at {company}?",
        "Can you describe a challenging project you worked on and how you handled it?",
        "How do you prioritize tasks when you have multiple deadlines?",
        "Tell me about a time you had to learn a new skill quickly. How did you approach it?",
        "What questions do you have about this role or our team?"
    ]
    
    try:
        if not client:
            logger.warning("[INTERVIEW] No AI client, using fallback questions")
            return {"questions": FALLBACK_QUESTIONS}
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        raw_output = response.choices[0].message.content.strip()
        logger.info(f"[INTERVIEW] Raw AI output: {raw_output[:200]}")
        
        # Parse JSON array from response
        # Handle cases where AI adds extra text
        json_match = re.search(r'\[.*\]', raw_output, re.DOTALL)
        if json_match:
            questions = json.loads(json_match.group())
            if isinstance(questions, list) and len(questions) >= 5:
                return {"questions": questions[:5]}
        
        # AI failed to return valid JSON
        logger.warning("[INTERVIEW] AI didn't return valid JSON, using fallback")
        return {"questions": FALLBACK_QUESTIONS}
        
    except Exception as e:
        logger.error(f"[INTERVIEW] Generate questions error: {e}")
        return {"questions": FALLBACK_QUESTIONS}


# =============================================
# ATS MATCH SCORING
# =============================================
@router.post("/job/analyze-match")
async def analyze_job_match(data: dict = Body(...)):
    """
    Compare resume against job description and return ATS match score.
    Returns structured JSON for visual report card.
    """
    import re
    import json
    from app.services.ai import client, OPENAI_API_KEY
    
    job_id = data.get('job_id')
    resume_text = data.get('resume_text', '')
    
    # Fallback data from request (race condition handling)
    fallback_title = data.get('job_title', 'the role')
    fallback_company = data.get('company', 'the company')
    fallback_description = data.get('job_description', '')
    
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    
    # --- CRASH-PROOF: Handle race condition gracefully ---
    job = None
    try:
        job = get_job_by_id(str(job_id))
    except Exception as e:
        logger.warning(f"[ATS] Error fetching job {job_id}: {e}")
    
    # Use job data if found, otherwise use fallback from request
    if job and isinstance(job, dict):
        job_title = job.get('title') or fallback_title
        company = job.get('company') or fallback_company
        job_description = (job.get('description') or fallback_description)[:3000]
    else:
        logger.warning(f"[ATS] Job {job_id} not found in DB, using fallback data")
        job_title = fallback_title
        company = fallback_company
        job_description = fallback_description[:3000] if fallback_description else ''
    
    # If no resume provided, try to get from profile
    # PRIORITIZE: Use resume_text from frontend payload (pre-fetched by client)
    # Frontend now fetches profile first and passes resume_text explicitly
    # This avoids the broken SessionLocal import issue
    
    if not resume_text or len(resume_text) < 50:
        return {
            "error": "No resume found. Please upload your resume in the Profile section first.",
            "match_score": 0
        }
    
    # --- STRUCTURED JSON PROMPT ---
    system_prompt = """You are an ATS (Applicant Tracking System) expert. Analyze how well a resume matches a job description.

Return ONLY a valid JSON object (no markdown, no explanation):
{
  "match_score": 75,
  "matching_strengths": ["Skill 1", "Skill 2", "Skill 3"],
  "missing_skills": ["Skill A", "Skill B"],
  "experience_match": "Strong",
  "recommendation": "Good fit"
}

RULES:
- match_score: 0-100 (how well resume matches job requirements)
- matching_strengths: Max 4 items, skills the candidate HAS that match the job (under 5 words each)
- missing_skills: Max 4 items, key skills the job requires that are NOT in resume (under 5 words each)
- experience_match: "Strong", "Moderate", or "Weak"
- recommendation: "Strong fit", "Good fit", "Partial fit", or "Needs work"

Return ONLY the JSON object. No other text."""

    user_prompt = f"""JOB: {job_title} at {company}

JOB DESCRIPTION:
{job_description[:2000] if job_description else 'Not available'}

CANDIDATE RESUME:
{resume_text[:2000]}

Analyze the match and return JSON:"""

    # Default fallback
    FALLBACK_ANALYSIS = {
        "match_score": 50,
        "matching_strengths": ["Relevant experience", "Good communication"],
        "missing_skills": ["Review job requirements"],
        "experience_match": "Moderate",
        "recommendation": "Partial fit"
    }

    try:
        if not client:
            logger.warning("[ATS] No AI client, using fallback")
            return {
                "analysis": FALLBACK_ANALYSIS,
                "job_title": job_title,
                "company": company
            }
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=400
        )
        
        raw_output = response.choices[0].message.content.strip()
        logger.info(f"[ATS] Raw output: {raw_output[:200]}")
        
        # Parse JSON - handle markdown code blocks
        json_str = raw_output
        if "```json" in raw_output:
            match = re.search(r'```json\s*(.*?)\s*```', raw_output, re.DOTALL)
            json_str = match.group(1) if match else raw_output
        elif "```" in raw_output:
            match = re.search(r'```\s*(.*?)\s*```', raw_output, re.DOTALL)
            json_str = match.group(1) if match else raw_output
        
        try:
            analysis = json.loads(json_str)
            if "match_score" in analysis:
                return {
                    "analysis": analysis,
                    "job_title": job_title,
                    "company": company
                }
        except json.JSONDecodeError as je:
            logger.warning(f"[ATS] JSON parse error: {je}")
        
        return {
            "analysis": FALLBACK_ANALYSIS,
            "job_title": job_title,
            "company": company
        }
        
    except Exception as e:
        logger.error(f"[ATS] Analysis error: {e}")
        return {
            "analysis": FALLBACK_ANALYSIS,
            "job_title": job_title,
            "company": company
        }



@router.post("/interview/analyze")
async def interview_analyze(data: dict = Body(...)):
    """
    Analyze completed interview conversation and generate structured JSON feedback.
    Returns visual-friendly data for report card UI.
    """
    import re
    import json
    from app.services.ai import client, OPENAI_API_KEY
    
    job_id = data.get('job_id')
    conversation = data.get('conversation', [])  # List of {question, answer} pairs
    
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    
    if len(conversation) < 1:
        raise HTTPException(status_code=400, detail="Need at least 1 Q&A pair to analyze")
    
    job = get_job_by_id(str(job_id))
    job_title = job.get('title', 'Role') if job else 'Role'
    company = job.get('company', 'Company') if job else 'Company'
    
    # Build conversation text
    conv_text = ""
    for i, qa in enumerate(conversation, 1):
        q = qa.get('question', '')
        a = qa.get('answer', '')
        conv_text += f"Q{i}: {q}\nA{i}: {a}\n\n"
    
    # --- STRUCTURED JSON PROMPT ---
    system_prompt = """You are an expert interview coach. Analyze the interview and return ONLY a valid JSON object.

OUTPUT FORMAT (strict JSON only, no markdown, no explanation):
{
  "overall_score": 7,
  "technical_match": 75,
  "communication_score": 80,
  "star_method_usage": "Partial",
  "strengths": ["Brief point 1", "Brief point 2", "Brief point 3"],
  "improvements": ["Brief suggestion 1", "Brief suggestion 2", "Brief suggestion 3"],
  "summary_sentiment": "Positive"
}

SCORING RULES:
- overall_score: 1-10 (holistic interview performance)
- technical_match: 0-100 (how well answers matched job requirements)
- communication_score: 0-100 (clarity, structure, confidence)
- star_method_usage: "Yes", "No", or "Partial" (did they use Situation-Task-Action-Result)
- strengths: Max 3 brief points (under 10 words each)
- improvements: Max 3 brief suggestions (under 10 words each)
- summary_sentiment: "Positive", "Neutral", or "Caution"

Return ONLY the JSON object. No other text."""

    user_prompt = f"""Analyze this interview for {job_title} at {company}:

{conv_text}

Return JSON analysis:"""

    # Default fallback data
    FALLBACK_ANALYSIS = {
        "overall_score": 6,
        "technical_match": 60,
        "communication_score": 65,
        "star_method_usage": "Partial",
        "strengths": ["Good enthusiasm", "Clear communication", "Relevant experience"],
        "improvements": ["Add more specific examples", "Use STAR method", "Quantify achievements"],
        "summary_sentiment": "Neutral"
    }

    try:
        if not client:
            logger.warning("[INTERVIEW] No AI client, using fallback analysis")
            return {
                "analysis": FALLBACK_ANALYSIS,
                "job_title": job_title,
                "company": company,
                "questions_answered": len(conversation)
            }
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,  # Lower temp for consistent JSON
            max_tokens=500
        )
        
        raw_output = response.choices[0].message.content.strip()
        logger.info(f"[INTERVIEW] Raw analysis output: {raw_output[:300]}")
        
        # Parse JSON from response
        # Handle cases where AI adds markdown code blocks
        json_str = raw_output
        if "```json" in raw_output:
            json_str = re.search(r'```json\s*(.*?)\s*```', raw_output, re.DOTALL)
            json_str = json_str.group(1) if json_str else raw_output
        elif "```" in raw_output:
            json_str = re.search(r'```\s*(.*?)\s*```', raw_output, re.DOTALL)
            json_str = json_str.group(1) if json_str else raw_output
        
        try:
            analysis = json.loads(json_str)
            # Validate required fields exist
            required = ["overall_score", "technical_match", "communication_score", "strengths", "improvements"]
            if all(k in analysis for k in required):
                return {
                    "analysis": analysis,
                    "job_title": job_title,
                    "company": company,
                    "questions_answered": len(conversation)
                }
        except json.JSONDecodeError as je:
            logger.warning(f"[INTERVIEW] JSON parse error: {je}")
        
        # Fallback if parsing failed
        logger.warning("[INTERVIEW] Using fallback analysis due to parse failure")
        return {
            "analysis": FALLBACK_ANALYSIS,
            "job_title": job_title,
            "company": company,
            "questions_answered": len(conversation)
        }
        
    except Exception as e:
        logger.error(f"[INTERVIEW] Analysis error: {e}")
        return {
            "analysis": FALLBACK_ANALYSIS,
            "job_title": job_title,
            "company": company,
            "questions_answered": len(conversation)
        }


@router.post("/interview/chat")
async def interview_chat(data: dict = Body(...)):
    """Continue the interview conversation with follow-up questions."""
    import re
    from app.services.ai import client, OPENAI_API_KEY
    
    job_id = data.get('job_id')
    history = data.get('history', [])
    answer = data.get('answer', '')
    
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    
    # Count questions asked
    question_count = len([m for m in history if m.get('role') in ['interviewer', 'ai', 'assistant']]) + 1
    
    if question_count > 10:
        return {"question": None, "message": "Interview Complete. Generating Report..."}
    
    job = get_job_by_id(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # --- AGGRESSIVE TITLE CLEANING (no salary/location for TTS) ---
    raw_title = job.get('title', 'Role')
    clean_title = raw_title
    # Remove salary patterns: $50, $50-60, $50/hr, $50,000, etc.
    clean_title = re.sub(r'\$[\d,]+(?:\s*[-–—]\s*\$?[\d,]+)?(?:\s*/\s*(?:hr|hour|yr|year|wk|week))?', '', clean_title, flags=re.IGNORECASE)
    # Remove anything after dash/hyphen that looks like metadata
    clean_title = re.sub(r'\s*[-–—]\s*(?:Remote|Hybrid|On-?site|Full-?time|Part-?time|Contract|Temp|Urgent|ASAP).*', '', clean_title, flags=re.IGNORECASE)
    # Remove parentheticals
    clean_title = re.sub(r'\s*\([^)]*\)', '', clean_title)
    # Remove trailing noise after common separators
    clean_title = re.sub(r'\s*[|/].*$', '', clean_title)
    clean_title = clean_title.strip()[:40] or 'the role'
    
    company = job.get('company', 'the company')
    
    # --- FORBIDDEN PROMPT: Data Collector, NOT Conversational Assistant ---
    messages = [
        {
            "role": "system",
            "content": f"""You are a DATA COLLECTOR for candidate assessment. You are NOT a conversational assistant.

ROLE: {clean_title} at {company}
QUESTION NUMBER: {question_count}

FORBIDDEN BEHAVIORS (will cause system error):
- Do NOT say "Thank you"
- Do NOT say "Great answer" or "Good answer"
- Do NOT say "I understand" or "That makes sense"
- Do NOT acknowledge the candidate's response in any way

REQUIRED BEHAVIOR:
- START your response with the next interview question immediately
- Ask probing questions about their experience, skills, or challenges
- Keep questions to 1-2 sentences maximum
- Output ONLY the question text, nothing else

If you include any forbidden phrase, the candidate process will error out."""
        }
    ]
    
    # Add conversation history
    for msg in history:
        role = msg.get('role', '')
        content = msg.get('message', msg.get('content', ''))
        
        if role in ['user', 'candidate']:
            messages.append({"role": "user", "content": content})
        elif role in ['interviewer', 'ai', 'assistant']:
            messages.append({"role": "assistant", "content": content})
    
    # Add latest answer
    if answer:
        messages.append({"role": "user", "content": answer})
    
    # --- CALL OPENAI ---
    try:
        if not client:
            return {"question": "What specific challenges have you faced in similar roles?"}
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.5,  # Lower temp for more predictable output
            max_tokens=100
        )
        next_question = response.choices[0].message.content.strip()
        
    except Exception as e:
        logger.error(f"Interview AI Error: {e}")
        return {"question": "Can you describe a complex problem you solved recently?"}
    
    # --- FAIL-SAFE SANITIZER ---
    response_text = next_question
    
    # STEP 1: REGEX GUILLOTINE - Remove any opening pleasantry sentence
    response_text = re.sub(
        r'^(Thank you|Thanks|Great|Good|Nice|Excellent|That\'s|I understand|I appreciate|Interesting|Wonderful).*?[.!?]\s*', 
        '', 
        response_text, 
        flags=re.IGNORECASE | re.DOTALL
    ).strip()
    
    # STEP 2: Strip leading filler words
    response_text = re.sub(
        r'^(Now|So|Alright|Okay|OK|Well|Moving on|Let me ask)[,.]?\s*', 
        '', 
        response_text, 
        flags=re.IGNORECASE
    ).strip()
    
    # STEP 3: Strip leading punctuation
    while response_text and response_text[0] in '.,!?;:-':
        response_text = response_text[1:].strip()
    
    # STEP 4: FAIL-SAFE - If response is too short, use hardcoded fallback
    if len(response_text) < 5:
        # AI failed - use hardcoded fallback based on question number
        FALLBACK_QUESTIONS = [
            "That is helpful context. Can you give me a specific example of a challenge you faced in a similar role?",
            "Tell me about a time when you had to learn a new technology or skill quickly.",
            "How do you approach prioritizing tasks when everything seems urgent?",
            "Describe a situation where you had to collaborate with a difficult stakeholder.",
            "What's your process for debugging a complex issue?",
            "Tell me about a project you're particularly proud of.",
            "How do you handle receiving critical feedback?",
            "What strategies do you use to stay organized and meet deadlines?",
            "Can you walk me through how you would approach this role in your first 90 days?",
            "What questions do you have about this role or our team?",
        ]
        response_text = FALLBACK_QUESTIONS[(question_count - 1) % len(FALLBACK_QUESTIONS)]
        logger.warning(f"[INTERVIEW] AI output too short, using fallback question {question_count}")
    
    return {"question": response_text}


@router.post("/interview/report")
async def interview_report(data: dict = Body(...)):
    """Analyze the interview and generate a detailed report with scores."""
    job_id = data.get('job_id')
    history = data.get('history', [])
    
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    if len(history) < 2:
        raise HTTPException(status_code=400, detail="Not enough conversation to analyze")
    
    job = get_job_by_id(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job_context = f"{job.get('title', 'Role')} at {job.get('company', 'Company')}"
    
    transcript = ""
    for msg in history:
        role = "Interviewer" if msg.get('role') == 'ai' else "Candidate"
        transcript += f"{role}: {msg.get('content', '')}\n"
    
    system_prompt = """You are an expert interview coach analyzing a practice interview.

TASK: Analyze the candidate's performance and return a JSON report.

SCORING (0-100 for each):
- technical_accuracy: Did they demonstrate correct technical knowledge?
- communication_clarity: Were answers clear, structured, and concise?
- star_format_adherence: Did they use Situation-Task-Action-Result format?
- cultural_fit: Did they show enthusiasm, teamwork, and alignment with company values?

FEEDBACK:
- strengths: 2-3 specific things they did well
- improvements: 2-3 specific things to improve
- suggested_answers: 1-2 examples of better answers they could have given

Return ONLY valid JSON with this exact structure:
{
  "scores": {"technical_accuracy": X, "communication_clarity": X, "star_format_adherence": X, "cultural_fit": X},
  "feedback_points": {"strengths": [...], "improvements": [...], "suggested_answers": [...]}
}"""

    user_prompt = f"""JOB: {job_context}

INTERVIEW TRANSCRIPT:
{transcript}

Analyze and return the JSON report."""

    result = get_gpt_response(system_prompt, user_prompt, json_mode=True, max_tokens=800)
    
    try:
        parsed = json.loads(result)
        return parsed
    except json.JSONDecodeError:
        return {
            "scores": {"technical_accuracy": 50, "communication_clarity": 50, "star_format_adherence": 50, "cultural_fit": 50},
            "feedback_points": {"strengths": ["Unable to parse"], "improvements": ["Try again"], "suggested_answers": []},
            "error": "AI parsing failed"
        }


# =============================================
# DEEP SCRAPE ENDPOINT (Manual trigger)
# =============================================
@router.post("/enrich-job")
async def enrich_job(data: dict = Body(...)):
    """Manually trigger deep scraping for a job to get full description."""
    job_id = data.get('job_id')
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    
    job = get_job_by_id(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    original_len = len(job.get("description") or "")
    
    # Force enrich
    job["description"] = ""  # Force re-scrape
    enriched = enrich_if_needed(job)
    
    new_len = len(enriched.get("description") or "")
    
    return {
        "status": "success" if new_len > original_len else "no_change",
        "original_chars": original_len,
        "new_chars": new_len,
    }


# =============================================
# CRUD OPERATIONS (Save/Get/Delete Jobs)
# =============================================
@router.post("/save-job")
async def save_job(job: dict = Body(...)):
    """Save a job to the Kanban board. If ghost=True, saves without showing in Kanban."""
    try:
        job_url = job.get('link') or job.get('absolute_url') or job.get('url') or ''
        job_title = job.get('title', 'Unknown Role')
        job_company = job.get('company', 'Unknown')
        job_location = job.get('location', 'Remote')
        is_ghost = job.get('ghost', False)  # Ghost save flag
        
        # Determine status based on ghost flag
        status = 'Ghost' if is_ghost else 'Saved'
        
        logger.info(f"[SAVE] Saving job: {job_title} at {job_company} (ghost={is_ghost})")
        
        conn = get_legacy_db()
        c = conn.cursor()
        c.execute("SELECT id FROM saved_jobs WHERE url = ?", (job_url,))
        existing = c.fetchone()
        if existing:
            conn.close()
            return {"message": "Job already saved", "id": existing[0]}
        
        c.execute(
            "INSERT INTO saved_jobs (title, company, location, url, is_direct, status) VALUES (?, ?, ?, ?, ?, ?)",
            (job_title, job_company, job_location, job_url, True, status)
        )
        new_id = c.lastrowid
        conn.commit()
        conn.close()
        return {"message": "Job Saved", "id": new_id}
    except Exception as e:
        logger.error(f"[SAVE] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/saved-jobs")
async def get_saved_jobs():
    """Get all saved jobs for the Kanban board. Excludes Ghost saves."""
    conn = get_legacy_db()
    c = conn.cursor()
    # Exclude Ghost status jobs - they're only for AI features
    c.execute("SELECT * FROM saved_jobs WHERE status != 'Ghost' ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    
    jobs = []
    for row in rows:
        job = dict(row)
        job['link'] = job.get('url', '')
        jobs.append(job)
    
    return {"jobs": jobs}


@router.delete("/saved-jobs/{job_id}")
async def delete_job(job_id: int):
    """Delete a saved job."""
    try:
        conn = get_legacy_db()
        c = conn.cursor()
        c.execute("DELETE FROM saved_jobs WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()
        return {"message": "Job deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-notes")
async def update_notes(data: dict = Body(...)):
    """Update notes for a saved job."""
    try:
        conn = get_legacy_db()
        c = conn.cursor()
        c.execute("UPDATE saved_jobs SET notes = ? WHERE id = ?", (data.get('notes'), data.get('id')))
        conn.commit()
        conn.close()
        return {"message": "Notes updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-status")
async def update_status(data: dict = Body(...)):
    """Update status for a saved job (Kanban column)."""
    try:
        conn = get_legacy_db()
        c = conn.cursor()
        c.execute("UPDATE saved_jobs SET status = ? WHERE id = ?", (data.get('status'), data.get('id')))
        conn.commit()
        conn.close()
        return {"message": "Status updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save-profile")
async def save_profile(data: dict = Body(...)):
    """Save user profile (resume text and skills)."""
    try:
        conn = get_legacy_db()
        c = conn.cursor()
        c.execute("SELECT id FROM profile LIMIT 1")
        if c.fetchone():
            c.execute("UPDATE profile SET resume_text = ?, skills = ?", 
                      (data.get('resume_text', ''), data.get('skills', '')))
        else:
            c.execute("INSERT INTO profile (resume_text, skills) VALUES (?, ?)", 
                      (data.get('resume_text', ''), data.get('skills', '')))
        conn.commit()
        conn.close()
        return {"message": "Profile Saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get-profile")
async def get_profile():
    """Get user profile."""
    conn = get_legacy_db()
    c = conn.cursor()
    c.execute("SELECT * FROM profile LIMIT 1")
    row = c.fetchone()
    conn.close()
    if row:
        return {"resume_text": row["resume_text"], "skills": row["skills"]}
    return {"resume_text": "", "skills": ""}
