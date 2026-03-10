from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, Base
from app.routers import auth, admin
from app.utils.create_admin import create_default_admin
from app.database import SessionLocal

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Career Companion API")

# CORS configuration
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin.router)


@app.on_event("startup")
def startup():
    db = SessionLocal()
    create_default_admin(db)
    db.close()


@app.get("/")
def root():
    return {"message": "AI Career Companion API running"}