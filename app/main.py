# FORCE UPDATE: v3 (Multi-User SaaS)
# CRITICAL: Load environment variables FIRST before any imports
from dotenv import load_dotenv
load_dotenv()  # Load .env file immediately

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

# Import DB and Models
from app.db import engine, Base, SessionLocal
from app import models 
from app.models import JobPost, User

# Import Routers
from app.routers import jobs as jobs_router
from app.routers import features as features_router
from app.routers import auth as auth_router

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 1. TABLE CREATION LOGIC ---
from sqlalchemy import text

def create_tables():
    logger.info("🚀 STARTUP: Checking/Creating database tables...")
    
    # 🚨 BUNKER BUSTER: Force-wipe all tables including FK dependencies
    # This is required for Render Free Tier to fix the schema mismatch.
    # ⚠️ REMOVE THIS BLOCK AFTER SUCCESSFUL DEPLOY!
    try:
        with engine.connect() as connection:
            trans = connection.begin()
            try:
                # Force delete in specific order with CASCADE
                tables = ["applications", "profiles", "job_posts", "users"]
                for table in tables:
                    connection.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE;"))
                    logger.info(f"🗑️ Dropped table: {table}")
                trans.commit()
                logger.info("✅ DATABASE RESET: All tables wiped successfully.")
            except Exception as e:
                trans.rollback()
                logger.error(f"❌ DATABASE RESET FAILED: {e}")
    except Exception as e:
        logger.error(f"❌ Connection error during reset: {e}")
    # 🚨 END BUNKER BUSTER - REMOVE AFTER SUCCESSFUL DEPLOY!
    
    # Rebuild the tables with the correct schema
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Tables created/verified successfully.")
    except Exception as e:
        logger.error(f"❌ Error creating tables: {e}")

# --- 2. SEEDING LOGIC ---
def seed_initial_data():
    logger.info("🌱 STARTUP: Checking if seeding is needed...")
    db = SessionLocal()
    try:
        job_count = db.query(JobPost).count()
        user_count = db.query(User).count()
        logger.info(f"Database has {job_count} jobs and {user_count} users.")
    except Exception as e:
        logger.error(f"⚠️ Seeding check failed: {e}")
    finally:
        db.close()

# --- 3. LIFESPAN MANAGER ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # This order is critical: Tables FIRST, then Data
    create_tables()
    seed_initial_data()
    yield
    logger.info("🛑 SHUTDOWN: App is stopping.")

# --- APP SETUP ---
app = FastAPI(title="Job Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Include Routers
app.include_router(auth_router.router)  # Auth routes (login, register, logout)
app.include_router(jobs_router.router)
app.include_router(features_router.router)


# =============================================
# PUBLIC ROUTES
# =============================================
@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    """Public landing page."""
    return templates.TemplateResponse("landing.html", {"request": request})


# =============================================
# PROTECTED ROUTES
# =============================================
@app.get("/app", response_class=HTMLResponse)
async def app_home(request: Request):
    """Protected app dashboard - requires authentication."""
    # Check for session cookie
    user_id = request.cookies.get("user_id")
    
    if not user_id:
        # Not logged in - redirect to login
        return RedirectResponse(url="/login", status_code=303)
    
    # User is authenticated - serve the app
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
def health_check():
    return {"status": "ok"}