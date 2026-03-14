import os

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.cv import CV, CVAuditRecord
from app.schemas.cv import CVAuditRecordResponse
from app.services.cv_service import extract_text_from_pdf
from app.services.llm_service import audit_cv_with_llm, LLMUnavailableError
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
    search: str | None = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    q = db.query(CV).filter(CV.user_id == user.id)
    if search:
        q = q.filter(CV.filename.ilike(f"%{search.strip()}%"))
    cvs = q.order_by(CV.created_at.desc()).all()
    return cvs


@router.get("/")
def get_all_cvs(
    search: str | None = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    if user.role not in ["mentor", "admin"]:
        raise HTTPException(status_code=403, detail="Access denied")
    q = db.query(CV)
    if search:
        q = q.filter(CV.filename.ilike(f"%{search.strip()}%"))
    cvs = q.order_by(CV.created_at.desc()).all()
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


@router.post("/{cv_id}/audit")
async def audit_cv(
    cv_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    cv = db.query(CV).filter(CV.id == cv_id).first()

    if not cv:
        raise HTTPException(status_code=404, detail="CV not found")

    if user.role == "student" and cv.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        result = await audit_cv_with_llm(cv.extracted_text or "")
    except LLMUnavailableError as e:
        raise HTTPException(
            status_code=503,
            detail="LLM service temporarily unavailable. Ensure Ollama is running and the model is pulled (e.g. ollama pull llama3.1).",
        ) from e

    record = CVAuditRecord(
        cv_id=cv_id,
        summary=result["summary"],
        strengths=result["strengths"],
        weaknesses=result["weaknesses"],
        recommendations=result["recommendations"],
        score=result["score"],
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/{cv_id}/audits", response_model=list[CVAuditRecordResponse])
def get_cv_audits(
    cv_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    cv = db.query(CV).filter(CV.id == cv_id).first()
    if not cv:
        raise HTTPException(status_code=404, detail="CV not found")
    if user.role == "student" and cv.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    records = db.query(CVAuditRecord).filter(CVAuditRecord.cv_id == cv_id).order_by(CVAuditRecord.created_at.desc()).all()
    return records

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