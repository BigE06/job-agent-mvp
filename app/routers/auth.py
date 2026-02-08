"""
Authentication Router
Handles user registration, login, and logout
"""
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import bcrypt
import logging

from app.db import SessionLocal
from app.models import User

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger(__name__)


# =============================================
# DATABASE DEPENDENCY
# =============================================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =============================================
# HELPER: Get current user from session cookie
# =============================================
def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Get user from session cookie. Returns None if not logged in."""
    user_id = request.cookies.get("user_id")
    if not user_id:
        return None
    try:
        user = db.query(User).filter(User.id == int(user_id)).first()
        return user
    except:
        return None


def require_auth(request: Request, db: Session = Depends(get_db)):
    """Dependency that requires authentication. Raises exception if not logged in."""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# =============================================
# REGISTRATION
# =============================================
@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Show registration form."""
    return templates.TemplateResponse("register.html", {"request": request})


@router.post("/register")
async def register_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Create new user account."""
    # Validation
    if password != confirm_password:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Passwords do not match"
        })
    
    if len(password) < 6:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Password must be at least 6 characters"
        })
    
    # Check if email already exists
    existing = db.query(User).filter(User.email == email.lower().strip()).first()
    if existing:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "Email already registered"
        })
    
    # Hash password and create user
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    new_user = User(
        email=email.lower().strip(),
        password_hash=password_hash
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    logger.info(f"[AUTH] New user registered: {email}")
    
    # Auto-login: Set session cookie and redirect to app
    response = RedirectResponse(url="/app", status_code=303)
    response.set_cookie(
        key="user_id",
        value=str(new_user.id),
        httponly=True,
        max_age=60 * 60 * 24 * 30  # 30 days
    )
    return response


# =============================================
# LOGIN
# =============================================
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Show login form."""
    # If already logged in, redirect to app
    user_id = request.cookies.get("user_id")
    if user_id:
        return RedirectResponse(url="/app", status_code=303)
    
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Validate credentials and set session cookie."""
    user = db.query(User).filter(User.email == email.lower().strip()).first()
    
    if not user:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid email or password"
        })
    
    # Verify password
    if not bcrypt.checkpw(password.encode('utf-8'), user.password_hash.encode('utf-8')):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid email or password"
        })
    
    logger.info(f"[AUTH] User logged in: {email}")
    
    # Set session cookie and redirect to app
    response = RedirectResponse(url="/app", status_code=303)
    response.set_cookie(
        key="user_id",
        value=str(user.id),
        httponly=True,
        max_age=60 * 60 * 24 * 30  # 30 days
    )
    return response


# =============================================
# LOGOUT
# =============================================
@router.get("/logout")
async def logout_user():
    """Clear session cookie and redirect to landing page."""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("user_id")
    return response
