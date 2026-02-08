from sqlalchemy import Column, Integer, String, Boolean, Text, Float, TIMESTAMP, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db import Base


# =============================================
# USER MODEL (Authentication)
# =============================================
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=func.now())
    
    # Relationship to jobs
    jobs = relationship("JobPost", back_populates="owner")


# =============================================
# JOB POST MODEL
# =============================================
class JobPost(Base):
    __tablename__ = "job_posts"

    # We use String for ID to handle both "1" and "job-001"
    id = Column(String, primary_key=True, index=True)
    
    # Owner (optional - for user-scoped data)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    owner = relationship("User", back_populates="jobs")
    
    title = Column(String)
    company = Column(String)
    location = Column(String)
    url = Column(String)
    description = Column(Text)
    requirements = Column(Text, nullable=True)
    
    source = Column(String, default="Manual")
    is_remote = Column(Boolean, default=False)
    visa_sponsorship = Column(Boolean, default=False)
    
    salary_min = Column(Float, nullable=True)
    salary_max = Column(Float, nullable=True)
    
    # CRITICAL FIX: Use TIMESTAMP explicitly. 
    # This stops SQLAlchemy from trying to "parse" the date as a string.
    fetched_at = Column(TIMESTAMP(timezone=True), default=func.now())
    source_ts = Column(TIMESTAMP(timezone=True), default=func.now())
    
    # Optional metadata field
    metadata_json = Column(Text, nullable=True)