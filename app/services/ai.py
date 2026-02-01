"""
AI Service
----------
OpenAI client and helper functions for AI-powered features.
"""
import os
import logging
from typing import Optional, Dict, Any

from openai import OpenAI

logger = logging.getLogger(__name__)

# --- OpenAI Client ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


def get_gpt_response(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 1000,
    json_mode: bool = False,
    model: str = "gpt-4o"
) -> str:
    """
    Get a response from GPT-4.
    
    Args:
        system_prompt: System instructions for the AI
        user_prompt: User's message/query
        max_tokens: Maximum tokens in response
        json_mode: If True, request JSON output format
        model: OpenAI model to use
    
    Returns:
        AI response text, or error message if failed
    """
    if not client:
        logger.error("OpenAI client not initialized. Check OPENAI_API_KEY.")
        return "Error: OpenAI API key not configured."
    
    try:
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }
        
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""
        
    except Exception as e:
        logger.error(f"GPT API error: {e}")
        return f"Error: {str(e)}"


def analyze_job_text(job_description: str) -> Dict[str, Any]:
    """
    Analyze a job description using AI to extract key information.
    
    Args:
        job_description: Raw job posting text
    
    Returns:
        Dictionary with extracted fields (skills, experience, summary)
    """
    if not job_description or len(job_description) < 50:
        return {"error": "Job description too short to analyze"}
    
    system_prompt = """You are a job analysis expert. Analyze the job description and extract:
1. Required skills (list of strings)
2. Years of experience required (number or range)
3. Key responsibilities (list of strings)
4. Company culture indicators
5. Remote/hybrid/onsite status

Return as JSON with keys: skills, experience_years, responsibilities, culture, work_mode"""

    user_prompt = f"Analyze this job posting:\n\n{job_description[:3000]}"
    
    response = get_gpt_response(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=800,
        json_mode=True
    )
    
    try:
        import json
        return json.loads(response)
    except:
        return {"raw_analysis": response}


def generate_cover_letter(
    job_title: str,
    company: str,
    job_description: str,
    resume_text: str
) -> str:
    """
    Generate a tailored cover letter for a job application.
    
    Args:
        job_title: Position title
        company: Company name
        job_description: Job posting text
        resume_text: Candidate's resume/CV text
    
    Returns:
        Generated cover letter text
    """
    system_prompt = """You are an expert career coach who writes compelling cover letters.
Write a professional, personalized cover letter that:
- Opens with a strong hook
- Highlights relevant experience from the resume
- Addresses key requirements from the job description
- Shows enthusiasm for the company
- Ends with a confident call to action

Keep it concise (about 300 words) and professional."""

    user_prompt = f"""Write a cover letter for:

Position: {job_title}
Company: {company}

Job Description:
{job_description[:2000]}

My Resume:
{resume_text[:2000]}"""

    return get_gpt_response(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=600
    )


def generate_cold_email(
    job_title: str,
    company: str,
    resume_text: str
) -> Dict[str, str]:
    """
    Generate a cold outreach email for a job opportunity.
    
    Args:
        job_title: Target position
        company: Target company
        resume_text: Candidate's background
    
    Returns:
        Dictionary with 'subject' and 'body' keys
    """
    system_prompt = """You are an expert at cold outreach for job opportunities.
Write a brief, compelling cold email that:
- Has an attention-grabbing subject line
- Opens with a personalized hook (not generic)
- Briefly states value proposition
- Includes a clear, low-friction call to action
- Is under 150 words

Return JSON with keys: subject, body"""

    user_prompt = f"""Write a cold email for:

Target Role: {job_title}
Target Company: {company}

My Background:
{resume_text[:1500]}"""

    response = get_gpt_response(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=400,
        json_mode=True
    )
    
    try:
        import json
        return json.loads(response)
    except:
        return {"subject": "Opportunity Inquiry", "body": response}
