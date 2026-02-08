"""
Database Reset Script
Force deletes and recreates BOTH databases with fresh schema.
Run: python reset_db.py

CRITICAL: This resets all user data. Only use in development.
NOTE: For production, switch DATABASE_URL to PostgreSQL.
"""
import os
import sys
import time

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# SQLAlchemy database paths
DB_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db")
SQLALCHEMY_DB_PATH = os.path.join(DB_FOLDER, "jobs.db")

# Legacy SQLite database (for saved_jobs and profile)
LEGACY_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs.db")


def reset_sqlalchemy_db():
    """Reset the SQLAlchemy database (db/jobs.db)."""
    print("\n🔷 STEP 1: Resetting SQLAlchemy Database...")
    
    if os.path.exists(SQLALCHEMY_DB_PATH):
        print(f"   📁 Found: {SQLALCHEMY_DB_PATH}")
        try:
            os.remove(SQLALCHEMY_DB_PATH)
            print("   🗑️  Deleted old file.")
        except PermissionError:
            print("\n   ⚠️  File locked. Please stop the server (Ctrl+C) and try again.")
            return False
    else:
        print(f"   📁 No existing database at: {SQLALCHEMY_DB_PATH}")
    
    # Ensure db folder exists
    os.makedirs(DB_FOLDER, exist_ok=True)
    
    try:
        from app.db import Base, engine
        from app.models import User, JobPost
        
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        
        print("   ✅ SQLAlchemy tables created:")
        for table in Base.metadata.tables.keys():
            print(f"      • {table}")
        return True
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def reset_legacy_db():
    """Reset the legacy SQLite database (jobs.db) with owner_id columns for multi-user support."""
    print("\n🔷 STEP 2: Resetting Legacy SQLite Database...")
    
    if os.path.exists(LEGACY_DB_PATH):
        print(f"   📁 Found: {LEGACY_DB_PATH}")
        try:
            os.remove(LEGACY_DB_PATH)
            print("   🗑️  Deleted old file.")
        except PermissionError:
            print("\n   ⚠️  File locked. Please stop the server (Ctrl+C) and try again.")
            return False
    else:
        print(f"   📁 No existing database at: {LEGACY_DB_PATH}")
    
    try:
        import sqlite3
        conn = sqlite3.connect(LEGACY_DB_PATH)
        c = conn.cursor()
        
        # Create saved_jobs table with owner_id for multi-user isolation
        c.execute('''CREATE TABLE IF NOT EXISTS saved_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            title TEXT,
            company TEXT,
            location TEXT,
            url TEXT,
            is_direct BOOLEAN,
            notes TEXT,
            score INTEGER,
            status TEXT DEFAULT 'Saved',
            due_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Create profile table with owner_id for multi-user isolation
        c.execute('''CREATE TABLE IF NOT EXISTS profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL UNIQUE,
            resume_text TEXT,
            skills TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Create indexes for faster owner_id lookups
        c.execute('CREATE INDEX IF NOT EXISTS idx_saved_jobs_owner ON saved_jobs(owner_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_profile_owner ON profile(owner_id)')
        
        conn.commit()
        conn.close()
        
        print("   ✅ Legacy tables created with owner_id (multi-user ready):")
        print("      • saved_jobs (owner_id, title, company, ...)")
        print("      • profile (owner_id, resume_text, skills)")
        return True
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def main():
    print("=" * 60)
    print("🔄 DATABASE RESET PROTOCOL (Multi-User SaaS)")
    print("=" * 60)
    print("\n⚠️  WARNING: This will DELETE all existing data!")
    print("   For production, use PostgreSQL instead of SQLite.\n")
    
    # Reset both databases
    success1 = reset_sqlalchemy_db()
    success2 = reset_legacy_db()
    
    print("\n" + "=" * 60)
    
    if success1 and success2:
        print("✅ DATABASE RESET COMPLETE!")
        print("\n🚀 Ready! Start server with:")
        print("   uvicorn app.main:app --reload")
        print("\n📋 Tables with owner_id isolation:")
        print("   • users (SQLAlchemy)")
        print("   • job_posts (SQLAlchemy)")
        print("   • saved_jobs (Legacy SQLite)")
        print("   • profile (Legacy SQLite)")
    else:
        print("⚠️  Reset incomplete. Check errors above.")
    
    print("=" * 60)


if __name__ == "__main__":
    main()
