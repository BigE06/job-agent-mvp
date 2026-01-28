from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    openai_api_key: str | None = None
    model_name: str = "gpt-4o-mini"
    database_url: str = "sqlite:///./data/app.db"

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings() -> Settings:
    return Settings()
