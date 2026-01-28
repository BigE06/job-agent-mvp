from sqlalchemy import Column, Integer, String, Boolean, Text, Float, TIMESTAMP
from sqlalchemy.sql import func
from app.db import Base

class JobPost(Base):
    __tablename__ = "job_posts"

    # We use String for ID to handle both "1" and "job-001"
    id = Column(String, primary_key=True, index=True)
    
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