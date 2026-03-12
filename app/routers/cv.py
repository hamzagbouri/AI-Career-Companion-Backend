import os

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.cv import CV
from app.services.cv_service import extract_text_from_pdf
import uuid

router = APIRouter(prefix="/cv", tags=["CV"])

UPLOAD_DIR = "uploads"

os.makedirs(UPLOAD_DIR, exist_ok=True)



@router.post("/upload")
async def upload_cv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):

    unique_name = f"{uuid.uuid4()}_{file.filename}"

    file_path = f"uploads/{unique_name}"

    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    extracted_text = extract_text_from_pdf(file_path)

    cv = CV(
        user_id=user.id,
        filename=file.filename,
        file_path=file_path,
        extracted_text=extracted_text
    )

    db.add(cv)
    db.commit()
    db.refresh(cv)

    return cv

@router.get("/my")
def get_my_cvs(
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):

    cvs = db.query(CV).filter(CV.user_id == user.id).all()

    return cvs

@router.get("/")
def get_all_cvs(
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):

    if user.role not in ["mentor", "admin"]:
        raise HTTPException(status_code=403, detail="Access denied")

    cvs = db.query(CV).all()

    return cvs  

@router.get("/{cv_id}")
def get_cv(
    cv_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):

    cv = db.query(CV).filter(CV.id == cv_id).first()

    if not cv:
        raise HTTPException(status_code=404, detail="CV not found")

    if user.role == "student" and cv.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    return cv

@router.put("/{cv_id}")
def update_cv(
    cv_id: int,
    filename: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):

    cv = db.query(CV).filter(CV.id == cv_id).first()

    if not cv:
        raise HTTPException(status_code=404, detail="CV not found")

    if user.role == "student" and cv.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not allowed")

    if user.role not in ["student", "admin"]:
        raise HTTPException(status_code=403, detail="Not allowed")

    cv.filename = filename

    db.commit()

    return {"message": "CV updated"}

@router.delete("/{cv_id}")
def delete_cv(
    cv_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):

    cv = db.query(CV).filter(CV.id == cv_id).first()

    if not cv:
        raise HTTPException(status_code=404, detail="CV not found")

    if user.role == "student" and cv.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not allowed")

    if user.role not in ["student", "admin"]:
        raise HTTPException(status_code=403, detail="Not allowed")

    db.delete(cv)

    db.commit()

    return {"message": "CV deleted"}