from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, Float, Integer
from sqlalchemy.dialects.sqlite import DATETIME as SQLITE_DATETIME
from sqlalchemy.orm import relationship, Mapped, mapped_column
from datetime import datetime
from app.db import Base

def now() -> datetime:
    return datetime.utcnow()

class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String, default="owner")
    created_at: Mapped[datetime] = mapped_column(SQLITE_DATETIME, default=now)

class Resume(Base):
    __tablename__ = "resumes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String, nullable=False)
    file_url: Mapped[str | None] = mapped_column(String)
    parsed_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(SQLITE_DATETIME, default=now)

class JobPost(Base):
    __tablename__ = "job_posts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String)
    company: Mapped[str | None] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String)
    location: Mapped[str | None] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    requirements: Mapped[str | None] = mapped_column(Text)
    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False)
    visa_sponsorship: Mapped[bool] = mapped_column(Boolean, default=False)
    source_ts: Mapped[datetime | None] = mapped_column(SQLITE_DATETIME)
    fetched_at: Mapped[datetime] = mapped_column(SQLITE_DATETIME, default=now)
    metadata_json: Mapped[str | None] = mapped_column(Text)

class Application(Base):
    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"))
    job_post_id: Mapped[str] = mapped_column(String, ForeignKey("job_posts.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String, default="saved")  # saved|prepared|submitted|interview|rejected|on_hold
    score: Mapped[float | None] = mapped_column(Float)
    resume_id: Mapped[str | None] = mapped_column(String, ForeignKey("resumes.id"))
    cover_letter_md: Mapped[str | None] = mapped_column(Text)
    qa_json: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(SQLITE_DATETIME, default=now)
    submitted_at: Mapped[datetime | None] = mapped_column(SQLITE_DATETIME)

class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    application_id: Mapped[str] = mapped_column(String, ForeignKey("applications.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String)  # ingested|ranked|tailored|opened|submitted|note
    payload: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(SQLITE_DATETIME, default=now)

class Prompt(Base):
    __tablename__ = "prompts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    template: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(SQLITE_DATETIME, default=now)
