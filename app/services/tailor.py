from app.config import get_settings

def draft_cover_letter(company: str, title: str, requirements: str, highlights: list[str]) -> str:
    settings = get_settings()
    # Placeholder deterministic draft to avoid API calls when key is absent
    highlights_fmt = "; ".join(highlights[:3]) if highlights else "impactful analytics projects"
    draft = (
        f"Dear Hiring Team,\n\n"
        f"I’m excited to apply for the {title} role at {company}. "
        f"I bring hands-on experience in {highlights_fmt}. "
        f"I’ve reviewed the requirements (e.g., {requirements.split(',')[0] if requirements else 'the core stack'}) and can contribute from day one.\n\n"
        f"I value clear communication, rapid iteration, and measurable outcomes. "
        f"I’d welcome the chance to discuss how I can help {company} achieve its goals.\n\n"
        f"Kind regards,\nYour Name"
    )
    # TODO: If settings.openai_api_key, call provider to refine this draft.
    return draft
