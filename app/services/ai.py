import os
from openai import OpenAI

from dotenv import load_dotenv
load_dotenv()  # <--- This forces Python to read your .env file

# Initialize client - expects OPENAI_API_KEY in environment variables
# or you can hardcode it here for local testing: api_key="sk-..."
# api_key = "sk-YOUR-ACTUAL-KEY"  <-- DELETE THIS
api_key = os.getenv("OPENAI_API_KEY") # <-- USE THIS
client = OpenAI(api_key=api_key) if api_key else None

def generate_pack(job):
    """
    Generates an HTML Application Pack using OpenAI.
    """
    if not client:
        return """
        <div style="padding:20px; color:#721c24; background-color:#f8d7da; border:1px solid #f5c6cb;">
            <h3>⚠️ AI Not Configured</h3>
            <p>OpenAI API Key is missing. Please set <code>OPENAI_API_KEY</code> environment variable or add it to <code>app/services/ai.py</code>.</p>
        </div>
        """

    system_prompt = "You are an expert career coach. You generate high-quality, ATS-friendly application materials. Output ONLY raw HTML (no markdown blocks)."
    
    user_prompt = f"""
    Create a 'OneTap Application Pack' for this job:
    Title: {job['title']}
    Company: {job['company']}
    Description: {job['description']}

    Generate a structured HTML report with these 3 sections:
    1. <h2>Strategy & Fit</h2>: A 3-bullet summary of why this role fits a developer profile and key keywords to emphasize.
    2. <h2>Cover Letter Draft</h2>: A professional, concise cover letter (max 200 words).
    3. <h2>Screening Question Prep</h2>: 3 likely screening questions for this role and suggested 1-sentence answers.

    Use proper HTML tags (<p>, <ul>, <li>, <strong>). Do not include <html> or <body> tags.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini", # Or gpt-3.5-turbo if 4o-mini is unavailable
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"<p>Error generating pack: {str(e)}</p>"

def generate_application_pack(title, company, description, user_profile):
    """
    Generates an HTML Application Pack using OpenAI, customized with user profile.
    """
    if not client:
        return "<p>Error: OpenAI API Key missing.</p>"

    profile_text = f"Candidate: {user_profile.get('name', 'Candidate')}\nSkills: {user_profile.get('skills', 'Standard Developer Skills')}" if user_profile else "Candidate: Junior Developer"

    system_prompt = "You are an expert career coach. You generate high-quality, ATS-friendly application materials. Output ONLY raw HTML (no markdown blocks)."
    
    user_prompt = f"""
    Create a 'OneTap Application Pack' for this job:
    Title: {title}
    Company: {company}
    Description: {description}

    My Profile:
    {profile_text}

    Generate a structured HTML report with these 3 sections:
    1. <h2>Strategy & Fit</h2>: A 3-bullet summary of why this role fits my profile and key keywords to emphasize.
    2. <h2>Cover Letter Draft</h2>: A professional, concise cover letter (max 200 words) using my details.
    3. <h2>Screening Question Prep</h2>: 3 likely screening questions for this role and suggested 1-sentence answers based on my profile.

    Use proper HTML tags (<p>, <ul>, <li>, <strong>). Do not include <html> or <body> tags.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"<p>Error generating pack: {str(e)}</p>"

import json

def analyze_job_match(job_description: str, user_profile: dict = None):
    """
    Analyzes job description against the provided user profile.
    Returns JSON with match_score, key_skills, missing_skills, and questions.
    """
    if not client:
        return {
            "match_score": 0,
            "key_skills": [],
            "missing_skills": ["OpenAI Key Missing"],
            "questions": []
        }

    profile_desc = "Junior Developer, Python/JS skills, 1-2 years exp."
    if user_profile and user_profile.get('skills'):
        profile_desc = f"Name: {user_profile.get('name')}. Skills: {user_profile.get('skills')}. Experience: {user_profile.get('experience_summary', '')}"

    system_prompt = "You are an expert career coach. Analyze the job description for the candidate. Output valid JSON."
    
    user_prompt = f"""
    Analyze this job description:
    {job_description[:4000]} 

    Candidate Profile: 
    {profile_desc}

    Return a JSON object with:
    - match_score (integer 0-100)
    - key_skills (list of strings found in job that match candidate)
    - missing_skills (list of strings found in job but missing in candidate)
    - questions (list of strings, max 3 yes/no screening questions to clarify fit)
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"Error analyzing job: {e}")
        return {
            "match_score": 0,
            "key_skills": [],
            "missing_skills": ["Error analyzing job"],
            "questions": []
        }

def generate_cover_letter(job_description: str, user_skills: str):
    """
    Generates a personalized cover letter based on job description and user skills.
    """
    if not client:
        return "Error: OpenAI API Key missing."

    system_prompt = "You are an expert copywriter. Write a concise, professional cover letter."
    
    user_prompt = f"""
    Write a cover letter for this job:
    {job_description[:3000]}

    My Skills/Qualifications:
    {user_skills}

    Address the job requirements using my skills. 
    Keep it under 300 words. 
    Do NOT use placeholders like '[Insert Name]' or '[Company Name]'. 
    Use 'Candidate' if name is unknown, and infer company name from text if possible, or use 'Hiring Manager'.
    Do not invent facts not present in my skills.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error generating letter: {str(e)}"

def generate_tailored_resume(profile_json: dict, job_description: str):
    """
    Rewrites the user's resume content to target keywords in the Job Description.
    Returns JSON structure: {summary, experience: [{role, company, dates, bullets}], skills}.
    """
    if not client:
        return {"error": "OpenAI Key Missing"}

    system_prompt = "You are an expert ATS optimizer. Rewrite the user's 'Key Achievements' to specifically target keywords in this Job Description. Do not lie, but rephrase for relevance. Return JSON structure: {summary, experience: [{role, company, dates, bullets}], skills}."

    user_prompt = f"""
    Job Description:
    {job_description[:4000]}

    User Profile:
    {json.dumps(profile_json)}

    Rewrite the Summary and Bullet points to better match the Job Description.
    Keep the same number of experience entries, just optimize the content.
    Return valid JSON only.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"Error tailoring resume: {e}")
        return {"error": str(e)}
