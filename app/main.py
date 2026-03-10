from fastapi import FastAPI

from app.database import engine, Base, SessionLocal
from app.routers import auth
from app.utils.create_admin import create_default_admin
from app.routers import auth
from app.routers import admin

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Career Companion API")

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