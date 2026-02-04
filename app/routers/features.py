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


@router.post("/interview/chat")
async def interview_chat(data: dict = Body(...)):
    """Continue the interview conversation with follow-up questions."""
    import re
    from app.services.ai import client, OPENAI_API_KEY
    
    job_id = data.get('job_id')
    history = data.get('history', [])
    answer = data.get('answer', '')  # Latest user answer
    
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    
    if len(history) >= 10:
        return {"question": None, "message": "Interview Complete. Generating Report..."}
    
    job = get_job_by_id(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job_context = f"{job.get('title', 'Role')} at {job.get('company', 'Company')}"
    
    # --- BUILD OPENAI MESSAGES ARRAY WITH HISTORY INJECTION ---
    messages = [
        {
            "role": "system",
            "content": f"""You are a professional job interviewer for the role: {job_context}.

RULES:
1. Be professional but critical - this is practice, so push the candidate.
2. Ask follow-up questions based on their last answer.
3. If they gave a vague answer, probe for specifics (metrics, technologies, outcomes).
4. Mix behavioral (STAR) and technical questions relevant to the role.
5. Keep questions concise (1-2 sentences max).

OUTPUT FORMAT:
- Return ONLY the next interview question.
- Do NOT say "Thank you", "Good answer", "Great", or any filler.
- Do NOT acknowledge their answer. Just ask the next question immediately.
- Start directly with the question. No preamble."""
        }
    ]
    
    # Add conversation history as alternating user/assistant messages
    for msg in history:
        role = msg.get('role', '')
        content = msg.get('message', msg.get('content', ''))
        
        if role in ['user', 'candidate']:
            messages.append({"role": "user", "content": content})
        elif role in ['interviewer', 'ai', 'assistant']:
            messages.append({"role": "assistant", "content": content})
    
    # Add latest answer if provided
    if answer:
        messages.append({"role": "user", "content": answer})
    
    # CRITICAL: Inject instruction at the END of messages
    messages.append({
        "role": "system",
        "content": "CRITICAL: IGNORE pleasantries. DO NOT say 'Thank you' or 'Great answer' or 'Good point'. IMMEDIATELY ask the next interview question. Start with the question directly."
    })
    
    # --- CALL OPENAI DIRECTLY WITH MESSAGES ARRAY ---
    try:
        if not client:
            return {"question": "What specific technical challenges have you faced in your previous role?"}
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7,
            max_tokens=150
        )
        next_question = response.choices[0].message.content.strip()
        
    except Exception as e:
        logger.error(f"Interview AI Error: {e}")
        return {"question": "Can you describe a time when you had to solve a complex problem under pressure?"}
    
    # --- BACKUP SANITIZER: Strip any remaining filler text ---
    response_text = next_question
    
    FILLER_PHRASES = [
        "Thank you for your answer.",
        "Thank you for sharing that.",
        "Thank you for that response.",
        "That's a great answer.",
        "That's a good answer.",
        "That's interesting.",
        "Let me ask another question.",
        "Let me ask you about",
        "I appreciate your response.",
        "Thanks for sharing.",
    ]
    
    for filler in FILLER_PHRASES:
        response_text = response_text.replace(filler, "")
    
    # Strip leading "Great", "Good", "Nice", "Excellent" followed by punctuation
    response_text = re.sub(r'^(Great|Good|Nice|Excellent|Wonderful|Perfect)[.,!]?\s*', '', response_text, flags=re.IGNORECASE)
    
    # Strip leading "Now," or "So," or "Alright,"
    response_text = re.sub(r'^(Now|So|Alright|Okay|OK)[.,]?\s*', '', response_text, flags=re.IGNORECASE)
    
    response_text = response_text.strip()
    
    # If response is now empty or too short, return a default question
    if len(response_text) < 10:
        response_text = "Can you walk me through your approach to handling conflicting priorities?"
    
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
