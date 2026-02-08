from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    openai_api_key: str | None = None
    model_name: str = "gpt-4o-mini"
    database_url: str = "sqlite:///./data/app.db"
    
    # Adzuna API credentials (optional)
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None

    class Config:
        env_file = ".env"
        extra = "ignore"  # Allow unknown env vars without crashing

@lru_cache()
def get_settings() -> Settings:
    return Settings()

