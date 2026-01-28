# FORCE UPDATE: v2 (Clean Startup)
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

# Import DB and Models
from app.db import engine, Base, SessionLocal
from app import models 
from app.models import JobPost

# Import Routers
from app.routers import jobs as jobs_router

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 1. TABLE CREATION LOGIC ---
def create_tables():
    logger.info("🚀 STARTUP: Checking/Creating database tables...")
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
        count = db.query(JobPost).count()
        logger.info(f"Database has {count} jobs.")
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

app.include_router(jobs_router.router)

@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request})

@app.get("/app", response_class=HTMLResponse)
async def app_home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health")
def health_check():
    return {"status": "ok"}