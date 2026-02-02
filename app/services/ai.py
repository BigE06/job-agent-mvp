"""
AI Service
----------
OpenAI client and helper functions for AI-powered features.
Extracted from main_backup.py for modular architecture.
"""
import os
import logging
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

# --- Configuration ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# --- OpenAI Client ---
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
