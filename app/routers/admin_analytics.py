from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import admin_required
from app.models.user import User
from app.models.certificate import Certificate, CertificateAttempt

router = APIRouter(prefix="/admin/analytics", tags=["Admin"])


@router.get("/mentors")
def list_mentors(
    search: str | None = Query(None),
    db: Session = Depends(get_db),
    _admin=Depends(admin_required),
):
    q = db.query(User).filter(User.role == "mentor")
    if search:
        like = f"%{search.strip()}%"
        q = q.filter((User.email.ilike(like)) | (User.full_name.ilike(like)))
    mentors = q.order_by(User.created_at.desc()).all()
    return [
        {
            "id": m.id,
            "full_name": m.full_name,
            "email": m.email,
            "status": m.status,
            "created_at": m.created_at,
        }
        for m in mentors
    ]


@router.get("/mentors/{mentor_id}")
def mentor_detail(
    mentor_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(admin_required),
):
    mentor = db.query(User).filter(User.id == mentor_id, User.role == "mentor").first()
    if not mentor:
        raise HTTPException(status_code=404, detail="Mentor not found")

    certs = (
        db.query(Certificate)
        .filter(Certificate.created_by == mentor_id)
        .order_by(Certificate.created_at.desc())
        .all()
    )

    cert_stats = []
    for c in certs:
        attempts_total = (
            db.query(func.count(CertificateAttempt.id))
            .filter(CertificateAttempt.certificate_id == c.id)
            .scalar()
            or 0
        )
        attempts_passed = (
            db.query(func.count(CertificateAttempt.id))
            .filter(CertificateAttempt.certificate_id == c.id, CertificateAttempt.score >= 70)
            .scalar()
            or 0
        )
        cert_stats.append(
            {
                "certificate_id": c.id,
                "title": c.title,
                "language": c.language,
                "level": c.level,
                "time_limit_minutes": c.time_limit_minutes,
                "created_at": c.created_at,
                "attempts_total": attempts_total,
                "attempts_passed": attempts_passed,
            }
        )

    return {
        "mentor": {
            "id": mentor.id,
            "full_name": mentor.full_name,
            "email": mentor.email,
            "status": mentor.status,
            "created_at": mentor.created_at,
        },
        "certificates": cert_stats,
    }

