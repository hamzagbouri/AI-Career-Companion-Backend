import logging
import os

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, Base
from app.routers import auth, admin
from app.utils.create_admin import create_default_admin
from app.database import SessionLocal
from app.seed_data import seed_certificates
from app.routers import cv, exercises, certificates
from fastapi.staticfiles import StaticFiles


Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Career Companion API")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

logger = logging.getLogger(__name__)

# CORS configuration
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(cv.router)
app.include_router(exercises.router)
app.include_router(certificates.router)


@app.on_event("startup")
def startup():
    # Gemini healthcheck: fail fast at boot if Gemini is misconfigured (wrong model name / no key / blocked network).
    gemini_key = os.getenv("GEMINI_API_KEY")
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    if not gemini_key:
        print("Gemini healthcheck: disabled (GEMINI_API_KEY not set)")
    else:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={gemini_key}"
            with httpx.Client(timeout=httpx.Timeout(2.0, read=2.0)) as client:
                resp = client.get(url)
            if resp.status_code == 200:
                data = resp.json() or {}
                models = data.get("models") or []
                # Each entry typically contains "name": "models/<modelName>"
                model_names = [str(m.get("name", "")) for m in models if isinstance(m, dict)]
                if any(gemini_model in n for n in model_names):
                    print(f"Gemini healthcheck: OK model={gemini_model}")
                else:
                    print(f"Gemini healthcheck: API OK but model not listed model={gemini_model}")
            elif resp.status_code in (401, 403):
                print(f"Gemini healthcheck: auth failed status={resp.status_code}")
            else:
                print(f"Gemini healthcheck: API error status={resp.status_code}")
        except Exception as e:
            print(f"Gemini healthcheck: failed type={type(e).__name__}")

    db = SessionLocal()
    create_default_admin(db)
    seed_certificates(db)
    db.close()


@app.get("/")
def root():
    return {"message": "AI Career Companion API running"}