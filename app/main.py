import sqlite3
import requests
import io
import os
import json
import time
import re
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Body, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from bs4 import BeautifulSoup
from pypdf import PdfReader
from openai import OpenAI
from ddgs import DDGS

# --- DATABASE IMPORTS ---
from app.db import engine, Base, init_db

# --- CONFIGURATION ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CX_ID = os.getenv("GOOGLE_CX_ID", "")

# Database URL for PostgreSQL support
DATABASE_URL = os.getenv("DATABASE_URL", "")
USE_POSTGRES = DATABASE_URL.startswith("postgres")
DB_PATH = "jobs.db"

def get_db_connection():
    """Get database connection. Supports both SQLite (local) and PostgreSQL (production)."""
    if USE_POSTGRES:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        db_url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
        return conn
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

# --- LIFESPAN (Startup/Shutdown) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. CREATE TABLES FIRST (Critical Step - must happen before any queries)
    print("🚀 STARTUP: Creating database tables...")
    try:
        from app import models  # Ensure models are registered
        Base.metadata.create_all(bind=engine)
        print("✅ Tables created successfully.")
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
    
    # 2. NOW it is safe to seed data or run queries
    # (Add your seeding logic here if needed)
    
    yield
    print("🛑 Shutting down...")

# --- FASTAPI APP ---
app = FastAPI(lifespan=lifespan)

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- LANDING PAGE ---
@app.get("/")
async def root():
    """Serve the stunning landing page at root URL."""
    landing_path = Path(__file__).resolve().parent.parent / "templates" / "landing.html"
    if landing_path.exists():
        return HTMLResponse(content=landing_path.read_text(encoding="utf-8"))
    return RedirectResponse(url="/app/")

# --- MIGRATIONS ---
def run_migrations():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS saved_jobs 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  title TEXT, company TEXT, location TEXT, 
                  url TEXT, is_direct BOOLEAN, 
                  notes TEXT, score INTEGER,
                  status TEXT DEFAULT 'Saved')''')
    c.execute('''CREATE TABLE IF NOT EXISTS profile 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, resume_text TEXT, skills TEXT)''')
    c.execute("PRAGMA table_info(saved_jobs)")
    columns = [info[1] for info in c.fetchall()]
    if 'status' not in columns:
        try: c.execute("ALTER TABLE saved_jobs ADD COLUMN status TEXT DEFAULT 'Saved'")
        except: pass
    if 'notes' not in columns:
        try: c.execute("ALTER TABLE saved_jobs ADD COLUMN notes TEXT")
        except: pass
    if 'due_date' not in columns:
        try: c.execute("ALTER TABLE saved_jobs ADD COLUMN due_date TEXT")
        except: pass
    conn.commit()
    conn.close()

run_migrations()

# --- AI HELPERS ---

def get_gpt_response(system_prompt, user_prompt, max_tokens=1000, json_mode=False):
    try:
        if "PLACE_YOUR" in OPENAI_API_KEY: return "Error: OpenAI Key missing."
        kwargs = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.7,
            "max_tokens": max_tokens
        }
        if json_mode: kwargs["response_format"] = {"type": "json_object"}
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"AI Error: {e}")
        return f"AI Error: {str(e)}"

# --- DUCKDUCKGO SEARCH ---

def extract_company_from_url(url):
    """Extract company name from ATS URLs like greenhouse.io/monzo/..."""
    if not url:
        return None
    # Match patterns: greenhouse.io/company, jobs.lever.co/company, ashbyhq.com/company
    pattern = r'(?:boards\.greenhouse\.io|jobs\.lever\.co|ashbyhq\.com)/([^/]+)'
    match = re.search(pattern, url)
    if match:
        company_slug = match.group(1)
        # Clean up and capitalize
        clean_name = company_slug.replace('-', ' ').replace('_', ' ').title()
        return clean_name
    return None

def search_google_api(query):
    """
    Uses DuckDuckGo to search for jobs. 
    Bypasses Google's API limits and permission errors.
    """
    print(f"\n[SEARCH] Searching DuckDuckGo for: {query}")
    results = []
    
    try:
        # DDGS() initializes the search engine
        ddg_results = DDGS().text(query, max_results=6)  # Get extra in case some are filtered
        
        if ddg_results:
            for item in ddg_results:
                link = item.get('href', '')
                
                # CRITICAL: Skip results with no link
                if not link:
                    print(f"[SEARCH] Skipping result with no link: {item.get('title', 'Unknown')}")
                    continue
                
                # Filter out generic career pages - only keep actual job links
                # Valid patterns: /jobs/, /o/, /j/, /apply/
                if not any(pattern in link for pattern in ['/jobs/', '/o/', '/j/', '/apply/', '/posting/']):
                    print(f"[SEARCH] Skipping non-job URL: {link[:60]}...")
                    continue
                
                raw_title = item.get('title', 'Unknown Role')
                
                # METHOD 1: Extract company from URL (most reliable for ATS)
                clean_company = extract_company_from_url(link)
                
                # METHOD 2: Fallback to title parsing
                if not clean_company:
                    if " at " in raw_title:
                        parts = raw_title.split(" at ", 1)
                        clean_company = parts[1].split(" - ")[0].strip()
                    elif " - " in raw_title:
                        parts = raw_title.split(" - ", 1)
                        clean_company = parts[1].strip()
                    else:
                        clean_company = "Unknown"
                
                # Clean up the title (remove "Job Application for" prefix)
                clean_title = raw_title
                if "Job Application for " in clean_title:
                    clean_title = clean_title.replace("Job Application for ", "")
                if " at " in clean_title:
                    clean_title = clean_title.split(" at ")[0].strip()
                if " - " in clean_title:
                    clean_title = clean_title.split(" - ")[0].strip()
                
                results.append({
                    'title': clean_title,
                    'company': clean_company,
                    'link': link,
                    'location': 'Remote',
                    'snippet': item.get('body', '')
                })
                
                # Stop after 4 valid results
                if len(results) >= 4:
                    break
        
        # DEBUG: Print exact data being sent
        print(f"[DEBUG] Sending {len(results)} jobs. First job sample: {results[0] if results else 'None'}")
        return results
            
    except Exception as e:
        print(f"[SEARCH] Error: {e}")
        return []
        
    return []

def get_demo_jobs(q, loc):
    """Fallback if Free Quota Exceeded"""
    print("   [WARN] Using Safety Net (Demo Jobs).")
    return [
        {
            "title": f"Senior {q.title()}",
            "company": "Monzo",
            "location": loc or "London",
            "absolute_url": "https://boards.greenhouse.io/monzo/jobs/demo1",
            "is_direct": True,
            "snippet": f"We are looking for a {q} to join our growing team..."
        },
        {
            "title": f"Lead {q.title()}",
            "company": "Revolut",
            "location": loc or "London",
            "absolute_url": "https://jobs.lever.co/revolut/demo2",
            "is_direct": True,
            "snippet": "Join our fast paced team..."
        }
    ]

@app.get("/api/search")
async def search_jobs(q: str, loc: str = ""):
    # Normalize location capitalization for consistent results
    loc = loc.strip().title() if loc else ""
    q = q.strip()
    print(f"--- Search Request: '{q}' in '{loc}' ---")
    results = []
    
    # We construct simplified queries to save quota
    # Instead of 3 separate calls, we can try to combine or just check 2 major boards
    queries = [
        f'site:boards.greenhouse.io {q} {loc}',
        f'site:jobs.lever.co {q} {loc}'
    ]
    
    for query in queries:
        raw_data = search_google_api(query)
        for res in raw_data:
            process_result(res, results, loc)

    # Safety Net
    if len(results) == 0:
        results = get_demo_jobs(q, loc)

    return {"jobs": results}

def process_result(res, results_list, default_loc):
    """Process a search result and add to results list."""
    # Use the pre-parsed data from search_google_api
    title = res.get('title', 'Unknown Role').strip()
    company = res.get('company', 'Unknown')
    link = res.get('link', '')  # Now correctly using 'link' key
    snippet = res.get('snippet', '')
    location = res.get('location', default_loc or 'Remote')
    
    # Skip invalid results
    if not link:
        return
    if any(x in link for x in ["login", "admin", "proxies"]): 
        return
    if any(r.get('absolute_url') == link or r.get('link') == link for r in results_list): 
        return
    
    # Clean up title
    clean_title = title.replace("Job Application for ", "").strip()
    if " - " in clean_title:
        clean_title = clean_title.split(" - ")[0].strip()
    if clean_title.lower() in ["jobs", "careers", "vacancies"]: 
        return

    results_list.append({
        "title": clean_title,
        "company": company,
        "location": location,
        "absolute_url": link,  # Keep for backward compatibility
        "link": link,          # Also include as 'link' for frontend
        "is_direct": True,
        "snippet": snippet
    })

# --- SMART ENDPOINTS (No Changes) ---
@app.post("/api/upload-resume")
async def upload_resume(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        pdf_file = io.BytesIO(contents)
        reader = PdfReader(pdf_file)
        text = ""
        for page in reader.pages: text += page.extract_text() + "\n"
        
        system_prompt = "You are a data extractor. Extract technical skills."
        user_prompt = f"RESUME: {text[:4000]}\n\nTask: Return comma-separated list of top 15 skills."
        extracted_skills = get_gpt_response(system_prompt, user_prompt, max_tokens=100)
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id FROM profile LIMIT 1")
        if c.fetchone(): c.execute("UPDATE profile SET resume_text = ?, skills = ?", (text, extracted_skills))
        else: c.execute("INSERT INTO profile (resume_text, skills) VALUES (?, ?)", (text, extracted_skills))
        conn.commit()
        conn.close()
        return {"message": "Parsed", "text": text, "skills": extracted_skills}
    except Exception as e: return {"error": str(e)}, 500

@app.post("/api/generate-pack")
async def generate_pack(data: dict = Body(...)):
    job_id = data.get('id')
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM saved_jobs WHERE id = ?", (job_id,))
    job_row = c.fetchone()
    c.execute("SELECT * FROM profile LIMIT 1")
    profile_row = c.fetchone()
    job = dict(job_row) if job_row else None
    profile = dict(profile_row) if profile_row else {}
    conn.close()
    if not job: return {"error": "Job not found"}, 404
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

@app.post("/api/analyze-text")
async def analyze_text(data: dict = Body(...)):
    job_text = data.get('job_description', '')
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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

@app.post("/api/gap-fill-interview")
async def gap_fill_interview(data: dict = Body(...)):
    """Curated CV: Identify missing skills to ask the user about."""
    job_id = data.get('job_id')
    if not job_id: return {"error": "job_id is required"}, 400
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Fetch job details
    c.execute("SELECT * FROM saved_jobs WHERE id = ?", (job_id,))
    job_row = c.fetchone()
    job = dict(job_row) if job_row else None
    
    # Fetch user profile
    c.execute("SELECT * FROM profile LIMIT 1")
    profile_row = c.fetchone()
    profile = dict(profile_row) if profile_row else {}
    conn.close()
    
    if not job: return {"error": "Job not found"}, 404
    
    job_context = f"Title: {job.get('title', 'Unknown')}\nCompany: {job.get('company', 'Unknown')}"
    resume_text = profile.get('resume_text', '')
    
    if not resume_text:
        return {"error": "No resume uploaded. Please upload your resume first."}, 400
    
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

@app.post("/api/generate-curated-cv")
async def generate_curated_cv(data: dict = Body(...)):
    """Curated CV: Generate a tailored CV with injected gap answers."""
    job_id = data.get('job_id')
    gap_answers = data.get('gap_answers', [])
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM saved_jobs WHERE id = ?", (job_id,))
    job_row = c.fetchone()
    job = dict(job_row) if job_row else None
    c.execute("SELECT * FROM profile LIMIT 1")
    profile_row = c.fetchone()
    profile = dict(profile_row) if profile_row else {}
    conn.close()
    
    if not job: return {"error": "Job not found"}, 404
    resume_text = profile.get('resume_text', '')
    if not resume_text: return {"error": "No resume uploaded."}, 400
    
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
- li { margin-bottom: 2px; font-size: 11pt; }
"""
    
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
    
    # --- CLEANING LOGIC (Strip markdown tags) ---
    clean_html = raw_html.replace("```html", "").replace("```", "").strip()
    
    return {"cv_html": clean_html}

# --- COLD EMAIL DRAFTER ---

@app.post("/api/generate-cold-email")
async def generate_cold_email(data: dict = Body(...)):
    """Generate a high-conversion cold email to a hiring manager."""
    job_id = data.get('job_id')
    if not job_id: return {"error": "job_id is required"}, 400
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM saved_jobs WHERE id = ?", (job_id,))
    job_row = c.fetchone()
    job = dict(job_row) if job_row else None
    c.execute("SELECT * FROM profile LIMIT 1")
    profile_row = c.fetchone()
    profile = dict(profile_row) if profile_row else {}
    conn.close()
    
    if not job: return {"error": "Job not found"}, 404
    
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

# --- VOICE INTERVIEW SIMULATOR ---
import uuid

@app.post("/api/interview/start")
async def interview_start(data: dict = Body(...)):
    """Start an interview session with an opening question."""
    job_id = data.get('job_id')
    if not job_id: return {"error": "job_id is required"}, 400
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM saved_jobs WHERE id = ?", (job_id,))
    job_row = c.fetchone()
    job = dict(job_row) if job_row else None
    conn.close()
    
    if not job: return {"error": "Job not found"}, 404
    
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

@app.post("/api/interview/chat")
async def interview_chat(data: dict = Body(...)):
    """Continue the interview conversation with follow-up questions."""
    job_id = data.get('job_id')
    history = data.get('history', [])
    
    if not job_id: return {"error": "job_id is required"}, 400
    
    # Check if interview is complete (5 turns = 10 messages: 5 AI + 5 User)
    if len(history) >= 10:
        return {"question": None, "message": "Interview Complete. Generating Report..."}
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM saved_jobs WHERE id = ?", (job_id,))
    job_row = c.fetchone()
    job = dict(job_row) if job_row else None
    conn.close()
    
    if not job: return {"error": "Job not found"}, 404
    
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

@app.post("/api/interview/report")
async def interview_report(data: dict = Body(...)):
    """Analyze the interview and generate a detailed report with scores."""
    job_id = data.get('job_id')
    history = data.get('history', [])
    
    if not job_id: return {"error": "job_id is required"}, 400
    if len(history) < 2: return {"error": "Not enough conversation to analyze"}, 400
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM saved_jobs WHERE id = ?", (job_id,))
    job_row = c.fetchone()
    job = dict(job_row) if job_row else None
    conn.close()
    
    if not job: return {"error": "Job not found"}, 404
    
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

# --- CRUD (No Changes) ---
@app.post("/api/save-job")
async def save_job(job: dict = Body(...)):
    try:
        # Support both 'link' (DuckDuckGo) and 'absolute_url' (legacy)
        job_url = job.get('link') or job.get('absolute_url') or job.get('url') or ''
        job_title = job.get('title', 'Unknown Role')
        job_company = job.get('company', 'Unknown')
        job_location = job.get('location', 'Remote')
        
        print(f"[SAVE] Saving job: {job_title} at {job_company} - URL: {job_url[:50]}...")
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id FROM saved_jobs WHERE url = ?", (job_url,))
        if c.fetchone(): 
            conn.close()
            return {"message": "Job already saved"}
        c.execute("INSERT INTO saved_jobs (title, company, location, url, is_direct, status) VALUES (?, ?, ?, ?, ?, 'Saved')",
                  (job_title, job_company, job_location, job_url, True))
        conn.commit()
        conn.close()
        return {"message": "Job Saved"}
    except Exception as e: 
        print(f"[SAVE] Error: {e}")
        return {"error": str(e)}, 500

@app.get("/api/saved-jobs")
async def get_saved_jobs():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM saved_jobs ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    # Add 'link' as alias for 'url' for frontend compatibility
    jobs = []
    for row in rows:
        job = dict(row)
        job['link'] = job.get('url', '')  # Alias for frontend
        jobs.append(job)
    return {"jobs": jobs}

@app.delete("/api/saved-jobs/{job_id}")
async def delete_job(job_id: int):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM saved_jobs WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()
        return {"message": "Job deleted"}
    except Exception as e: return {"error": str(e)}, 500

@app.post("/api/update-notes")
async def update_notes(data: dict = Body(...)):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE saved_jobs SET notes = ? WHERE id = ?", (data.get('notes'), data.get('id')))
        conn.commit()
        conn.close()
        return {"message": "Notes updated"}
    except Exception as e: return {"error": str(e)}, 500

@app.post("/api/update-status")
async def update_status(data: dict = Body(...)):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE saved_jobs SET status = ? WHERE id = ?", (data['status'], data['id']))
        conn.commit()
        conn.close()
        return {"message": "Status Updated", "status": data['status']}
    except Exception as e: return {"error": str(e)}, 500

@app.post("/api/update-deadline")
async def update_deadline(data: dict = Body(...)):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE saved_jobs SET due_date = ? WHERE id = ?", (data.get('due_date'), data.get('id')))
        conn.commit()
        conn.close()
        return {"message": "Deadline updated"}
    except Exception as e: return {"error": str(e)}, 500

@app.post("/api/save-profile")
async def save_profile(data: dict = Body(...)):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM profile")
        c.execute("INSERT INTO profile (resume_text, skills) VALUES (?, ?)", (data.get('resume_text'), data.get('skills')))
        conn.commit()
        conn.close()
        return {"message": "Profile Saved"}
    except Exception as e: return {"error": str(e)}, 500

@app.get("/api/get-profile")
async def get_profile():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM profile LIMIT 1")
    row = c.fetchone()
    conn.close()
    if row: return {"resume_text": row["resume_text"], "skills": row["skills"]}
    return {"resume_text": "", "skills": ""}

base_dir = Path(__file__).resolve().parent.parent
static_dir = base_dir / "jobs_site"
if static_dir.exists(): app.mount("/app", StaticFiles(directory=str(static_dir), html=True), name="jobs_site")