"""
Features Router
---------------
AI-powered endpoints for job application assistance.
Migrated from main_backup.py with SQLAlchemy models.
"""
from __future__ import annotations

import io
import json
import uuid
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Body, HTTPException, UploadFile, File
from pypdf import PdfReader

from app.services.ai import get_gpt_response
from app.db import SessionLocal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["AI Features"])


# --- Helper: Get Legacy DB Connection (for SQLite tables) ---
def get_legacy_db():
    """Get SQLite connection for legacy saved_jobs and profile tables."""
    import sqlite3
    DB_PATH = "jobs.db"
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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
        
        # Save to profile table
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
# GAP FILL INTERVIEW (Identify Missing Skills)
# =============================================
@router.post("/gap-fill-interview")
async def gap_fill_interview(data: dict = Body(...)):
    """Identify missing skills between resume and job description."""
    job_id = data.get('job_id')
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    
    conn = get_legacy_db()
    c = conn.cursor()
    c.execute("SELECT * FROM saved_jobs WHERE id = ?", (job_id,))
    job_row = c.fetchone()
    job = dict(job_row) if job_row else None
    c.execute("SELECT * FROM profile LIMIT 1")
    profile_row = c.fetchone()
    profile = dict(profile_row) if profile_row else {}
    conn.close()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job_context = f"Title: {job.get('title', 'Unknown')}\nCompany: {job.get('company', 'Unknown')}"
    resume_text = profile.get('resume_text', '')
    
    if not resume_text:
        raise HTTPException(status_code=400, detail="No resume uploaded. Please upload your resume first.")
    
    system_prompt = """You are a strict Skills Gap Analyzer. Your job is to identify ONLY genuine missing skills.

RULES:
1. EXPLICIT GAPS: Skills explicitly stated in the job that are completely absent from the resume.
2. IMPLICIT GAPS: Skills strongly implied by the job (e.g., "Cloud architecture") where the resume has NO related experience.
3. DO NOT hallucinate. If unsure, do not include the skill.
4. Ignore soft skills like "communication" or "teamwork" unless they are a core job requirement.
5. Return 3-7 skills maximum. Quality over quantity.
6. Return ONLY valid JSON. No explanations."""

    user_prompt = f"""JOB DESCRIPTION:
{job_context}

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
# GENERATE CURATED CV (Harvard Style HTML)
# =============================================
@router.post("/generate-curated-cv")
async def generate_curated_cv(data: dict = Body(...)):
    """Generate a tailored CV with injected gap answers. Uses Harvard Style CSS."""
    job_id = data.get('job_id')
    gap_answers = data.get('gap_answers', [])
    
    conn = get_legacy_db()
    c = conn.cursor()
    c.execute("SELECT * FROM saved_jobs WHERE id = ?", (job_id,))
    job_row = c.fetchone()
    job = dict(job_row) if job_row else None
    c.execute("SELECT * FROM profile LIMIT 1")
    profile_row = c.fetchone()
    profile = dict(profile_row) if profile_row else {}
    conn.close()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    resume_text = profile.get('resume_text', '')
    if not resume_text:
        raise HTTPException(status_code=400, detail="No resume uploaded.")
    
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
   - Then list the previous job, and so on (e.g., "2019-2022" comes after "2022-2024").
   - Do NOT list them in the order they appear in the source text if it is incorrect.
   - Check the dates carefully to determine the correct order.
4. COPY the 'Education' section EXACTLY as it appears (also in reverse chronological order if multiple entries).
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
JOB DESCRIPTION: {job.get('snippet', '')}

=== SOURCE RESUME (COPY EXPERIENCE & EDUCATION VERBATIM) ===
{resume_text[:6000]}

=== GAP SKILLS TO INTEGRATE INTO PROFILE SUMMARY ===
{json.dumps(gap_answers)}

REMINDER: The Experience and Education sections must be copied WORD-FOR-WORD from the source resume above. Only the Professional Profile summary should be written by you.
"""
    
    # Get AI Response (4000 tokens for complete CV generation)
    raw_html = get_gpt_response(system_prompt, user_prompt, max_tokens=4000)
    
    # Clean markdown tags
    clean_html = raw_html.replace("```html", "").replace("```", "").strip()
    
    return {"cv_html": clean_html}


# =============================================
# GENERATE COLD EMAIL (Standalone)
# =============================================
@router.post("/generate-cold-email")
async def generate_cold_email(data: dict = Body(...)):
    """Generate a high-conversion cold email to a hiring manager."""
    job_id = data.get('job_id')
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    
    conn = get_legacy_db()
    c = conn.cursor()
    c.execute("SELECT * FROM saved_jobs WHERE id = ?", (job_id,))
    job_row = c.fetchone()
    job = dict(job_row) if job_row else None
    c.execute("SELECT * FROM profile LIMIT 1")
    profile_row = c.fetchone()
    profile = dict(profile_row) if profile_row else {}
    conn.close()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job_context = f"Title: {job.get('title', 'Unknown')}\nCompany: {job.get('company', 'Unknown')}"
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
# VOICE INTERVIEW SIMULATOR
# =============================================
@router.post("/interview/start")
async def interview_start(data: dict = Body(...)):
    """Start an interview session with an opening question."""
    job_id = data.get('job_id')
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    
    conn = get_legacy_db()
    c = conn.cursor()
    c.execute("SELECT * FROM saved_jobs WHERE id = ?", (job_id,))
    job_row = c.fetchone()
    job = dict(job_row) if job_row else None
    conn.close()
    
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
    job_id = data.get('job_id')
    history = data.get('history', [])
    
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    
    # Check if interview is complete (5 turns = 10 messages)
    if len(history) >= 10:
        return {"question": None, "message": "Interview Complete. Generating Report..."}
    
    conn = get_legacy_db()
    c = conn.cursor()
    c.execute("SELECT * FROM saved_jobs WHERE id = ?", (job_id,))
    job_row = c.fetchone()
    job = dict(job_row) if job_row else None
    conn.close()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job_context = f"{job.get('title', 'Role')} at {job.get('company', 'Company')}"
    
    # Build conversation for OpenAI
    formatted_history = ""
    for msg in history:
        role = "Interviewer" if msg.get('role') == 'ai' else "Candidate"
        formatted_history += f"{role}: {msg.get('content', '')}\n"
    
    system_prompt = """You are a professional job interviewer conducting a behavioral/technical interview.

RULES:
1. Be professional but critical - this is practice, so push the candidate.
2. Ask follow-up questions based on their last answer.
3. If they gave a vague answer, probe for specifics (metrics, technologies, outcomes).
4. Mix behavioral (STAR) and technical questions relevant to the role.
5. Keep questions concise (1-2 sentences max).
6. Return ONLY the next question, nothing else."""

    user_prompt = f"""JOB: {job_context}

CONVERSATION SO FAR:
{formatted_history}

Generate the next interview question based on the candidate's last response."""

    next_question = get_gpt_response(system_prompt, user_prompt, max_tokens=150)
    
    return {"question": next_question.strip()}


@router.post("/interview/report")
async def interview_report(data: dict = Body(...)):
    """Analyze the interview and generate a detailed report with scores."""
    job_id = data.get('job_id')
    history = data.get('history', [])
    
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    if len(history) < 2:
        raise HTTPException(status_code=400, detail="Not enough conversation to analyze")
    
    conn = get_legacy_db()
    c = conn.cursor()
    c.execute("SELECT * FROM saved_jobs WHERE id = ?", (job_id,))
    job_row = c.fetchone()
    job = dict(job_row) if job_row else None
    conn.close()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job_context = f"{job.get('title', 'Role')} at {job.get('company', 'Company')}"
    
    # Build conversation transcript
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
# CRUD OPERATIONS (Save/Get/Delete Jobs)
# =============================================
@router.post("/save-job")
async def save_job(job: dict = Body(...)):
    """Save a job to the Kanban board."""
    try:
        job_url = job.get('link') or job.get('absolute_url') or job.get('url') or ''
        job_title = job.get('title', 'Unknown Role')
        job_company = job.get('company', 'Unknown')
        job_location = job.get('location', 'Remote')
        
        logger.info(f"[SAVE] Saving job: {job_title} at {job_company}")
        
        conn = get_legacy_db()
        c = conn.cursor()
        c.execute("SELECT id FROM saved_jobs WHERE url = ?", (job_url,))
        if c.fetchone():
            conn.close()
            return {"message": "Job already saved"}
        
        c.execute(
            "INSERT INTO saved_jobs (title, company, location, url, is_direct, status) VALUES (?, ?, ?, ?, ?, 'Saved')",
            (job_title, job_company, job_location, job_url, True)
        )
        conn.commit()
        conn.close()
        return {"message": "Job Saved"}
    except Exception as e:
        logger.error(f"[SAVE] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/saved-jobs")
async def get_saved_jobs():
    """Get all saved jobs for the Kanban board."""
    conn = get_legacy_db()
    c = conn.cursor()
    c.execute("SELECT * FROM saved_jobs ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    
    jobs = []
    for row in rows:
        job = dict(row)
        job['link'] = job.get('url', '')  # Alias for frontend
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
