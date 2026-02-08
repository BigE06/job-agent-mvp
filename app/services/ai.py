"""
AI Service
----------
OpenAI client and helper functions for AI-powered features.
Extracted from main_backup.py for modular architecture.
"""
import os
import logging
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

# Load .env in case this module is imported before main.py
load_dotenv()

logger = logging.getLogger(__name__)

# --- Configuration ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Debug: Log API key status at startup
if OPENAI_API_KEY and "PLACE_YOUR" not in OPENAI_API_KEY:
    logger.info("✅ OpenAI API key loaded successfully.")
else:
    logger.warning("⚠️ OpenAI API key NOT found. AI features will not work. Check your .env file.")

# --- OpenAI Client ---
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY and "PLACE_YOUR" not in OPENAI_API_KEY else None


def get_gpt_response(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 1000,
    json_mode: bool = False,
    model: str = "gpt-4o"
) -> str:
    """
    Get a response from GPT-4.
    Exact implementation from main_backup.py.
    
    Args:
        system_prompt: System instructions for the AI
        user_prompt: User's message/query
        max_tokens: Maximum tokens in response
        json_mode: If True, request JSON output format
        model: OpenAI model to use
    
    Returns:
        AI response text, or error message if failed
    """
    try:
        if not OPENAI_API_KEY or "PLACE_YOUR" in OPENAI_API_KEY:
            return "Error: OpenAI Key missing."
        
        if not client:
            return "Error: OpenAI client not initialized."
        
        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.7,
            "max_tokens": max_tokens
        }
        
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        logger.error(f"AI Error: {e}")
        return f"AI Error: {str(e)}"


# =============================================
# SMART FIX LOOP: Keyword Extraction Functions
# =============================================

def extract_jd_keywords(job_description: str, max_keywords: int = 15) -> list:
    """
    Extract the most important hard skills/keywords from a Job Description using LLM.
    This is the first step of the Smart Fix Loop.
    
    Args:
        job_description: The full job description text
        max_keywords: Maximum number of keywords to extract
    
    Returns:
        List of extracted keywords (hard skills, technologies, qualifications)
    """
    if not job_description or len(job_description) < 50:
        return []
    
    system_prompt = """You are an ATS keyword extractor. Extract the most important hard skills and qualifications.

RULES:
1. Focus on HARD SKILLS: technologies, tools, frameworks, certifications, methodologies
2. Include REQUIRED qualifications: degrees, years of experience, certifications
3. Do NOT include soft skills like "communication" or "teamwork"
4. Do NOT include generic terms like "experience" or "ability"
5. Be specific: "Python" instead of "programming", "AWS" instead of "cloud"
6. Return as comma-separated list, NO numbering, NO explanations
7. Maximum 15 keywords, prioritize by importance"""

    user_prompt = f"""Extract the top {max_keywords} most important ATS keywords from this Job Description:

{job_description[:3000]}

Return ONLY a comma-separated list of keywords. Example format:
Python, AWS, Docker, React, Machine Learning, SQL, CI/CD, Kubernetes, TypeScript, REST APIs"""

    result = get_gpt_response(system_prompt, user_prompt, max_tokens=150)
    
    # Parse the comma-separated result
    if "Error:" in result:
        logger.warning(f"Keyword extraction failed: {result}")
        return []
    
    keywords = [kw.strip() for kw in result.split(",") if kw.strip()]
    logger.info(f"📌 Extracted {len(keywords)} keywords from JD: {keywords[:5]}...")
    return keywords


def find_missing_keywords(jd_keywords: list, resume_text: str) -> tuple:
    """
    Compare JD keywords against resume to find missing AND existing keywords.
    This is the second step of the Smart Fix Loop.
    
    Args:
        jd_keywords: List of keywords extracted from job description
        resume_text: The user's resume text
    
    Returns:
        Tuple of (existing_keywords, missing_keywords)
    """
    if not jd_keywords or not resume_text:
        return [], []
    
    resume_lower = resume_text.lower()
    missing = []
    existing = []
    
    for keyword in jd_keywords:
        # Check if keyword (or close variations) appear in resume
        kw_lower = keyword.lower().strip()
        
        # Skip very short keywords that might cause false matches
        if len(kw_lower) < 3:
            continue
        
        # Check for exact match or common variations
        found = False
        if kw_lower in resume_lower:
            found = True
        else:
            # Also check without common suffixes
            base_kw = kw_lower.rstrip('s')  # e.g., "APIs" -> "API"
            if base_kw in resume_lower:
                found = True
        
        if found:
            existing.append(keyword)
        else:
            missing.append(keyword)
    
    logger.info(f"✅ Found {len(existing)} existing keywords: {existing}")
    logger.info(f"⚠️ Found {len(missing)} missing keywords: {missing}")
    return existing, missing


def build_keyword_injection_prompt(existing_keywords: list, missing_keywords: list) -> str:
    """
    Build the SURGICAL INJECTION prompt for keyword optimization.
    This strategy preserves 90% of original content and only adds keywords surgically.
    
    Args:
        existing_keywords: List of keywords ALREADY in resume (must preserve)
        missing_keywords: List of keywords missing from resume (must add)
    
    Returns:
        Prompt section to inject into CV generation prompt
    """
    if not missing_keywords and not existing_keywords:
        return ""
    
    existing_str = ", ".join(existing_keywords) if existing_keywords else "None identified"
    missing_str = ", ".join(missing_keywords) if missing_keywords else "None"
    
    return f"""
### ⚠️ SURGICAL INJECTION PROTOCOL - READ BEFORE GENERATING ⚠️

YOU ARE IN "SURGICAL MODE" - NOT "REWRITE MODE"

**PROTECTED CONTENT (DO NOT MODIFY):**
The following sections MUST BE COPIED VERBATIM from the original resume:
- Work Experience: Copy ALL bullet points EXACTLY as written
- Projects: Copy ALL project descriptions EXACTLY as written  
- Education: Copy EXACTLY as written
- Certifications: Copy EXACTLY as written

**EXISTING KEYWORDS TO PRESERVE:** {existing_str}
These keywords are ALREADY in the resume and giving the user ATS points. 
DELETING ANY OF THESE = LOWER SCORE = TASK FAILURE

**SURGICAL INJECTION TARGETS (ONLY modify these areas):**
Missing keywords to inject: {missing_str}

1. **PROFESSIONAL SUMMARY (Top):** Write a 2-3 sentence summary that naturally includes 2-3 of the missing keywords
2. **ADD NEW SECTION "Key Technical Skills":** Place immediately after summary. List missing keywords here:
   - Format: "Key Technical Skills: {missing_str}"
3. **SKILLS SECTION:** Add missing keywords to the FRONT of the existing skills list

**ABSOLUTE PROHIBITIONS:**
❌ DO NOT summarize or shorten any work experience bullets
❌ DO NOT remove any content from the original resume
❌ DO NOT paraphrase the user's accomplishments
❌ DO NOT change job titles, dates, or company names
❌ DO NOT delete any existing skills

**SUCCESS = Original content preserved + Missing keywords surgically added**

"""

