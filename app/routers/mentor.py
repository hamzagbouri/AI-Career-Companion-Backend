from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.cv import CV, CVAuditRecord
from app.models.exercise import Exercise, ExerciseSubmission, ExerciseSet
from app.models.certificate import CertificateAttempt, Certificate, CertificateRetakeRequest

router = APIRouter(prefix="/mentor", tags=["Mentor"])


def mentor_required(user: User = Depends(get_current_user)):
    if user.role not in ("mentor", "admin"):
        raise HTTPException(status_code=403, detail="Mentor access required")
    return user


@router.get("/students")
def list_students(
    search: str | None = Query(None),
    db: Session = Depends(get_db),
    _mentor=Depends(mentor_required),
):
    q = db.query(User).filter(User.role == "student")
    if search:
        like = f"%{search.strip()}%"
        q = q.filter((User.email.ilike(like)) | (User.full_name.ilike(like)))
    students = q.order_by(User.created_at.desc()).all()
    return [
        {
            "id": s.id,
            "full_name": s.full_name,
            "email": s.email,
            "status": s.status,
            "created_at": s.created_at,
        }
        for s in students
    ]


@router.get("/students/{student_id}")
def student_detail(
    student_id: int,
    db: Session = Depends(get_db),
    _mentor=Depends(mentor_required),
):
    student = db.query(User).filter(User.id == student_id, User.role == "student").first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    cv_count = db.query(func.count(CV.id)).filter(CV.user_id == student_id).scalar() or 0
    latest_cv = db.query(CV).filter(CV.user_id == student_id).order_by(CV.created_at.desc()).first()
    audit_count = 0
    if latest_cv:
        audit_count = db.query(func.count(CVAuditRecord.id)).filter(CVAuditRecord.cv_id == latest_cv.id).scalar() or 0

    sets_count = db.query(func.count(ExerciseSet.id)).filter(ExerciseSet.user_id == student_id).scalar() or 0
    exercises_total = db.query(func.count(Exercise.id)).filter(Exercise.user_id == student_id).scalar() or 0
    submissions_total = db.query(func.count(ExerciseSubmission.id)).filter(ExerciseSubmission.user_id == student_id).scalar() or 0
    submissions_passed = (
        db.query(func.count(ExerciseSubmission.id))
        .filter(ExerciseSubmission.user_id == student_id, ExerciseSubmission.passed.is_(True))
        .scalar()
        or 0
    )

    # Simple difficulty distribution from exercises
    diff_rows = (
        db.query(Exercise.difficulty, func.count(Exercise.id))
        .filter(Exercise.user_id == student_id)
        .group_by(Exercise.difficulty)
        .all()
    )
    exercises_by_difficulty = {str(d or "Unknown"): int(c) for d, c in diff_rows}

    # Certificates attempts
    attempts_total = db.query(func.count(CertificateAttempt.id)).filter(CertificateAttempt.user_id == student_id).scalar() or 0
    attempts_passed = (
        db.query(func.count(CertificateAttempt.id))
        .filter(CertificateAttempt.user_id == student_id, CertificateAttempt.score >= 70)
        .scalar()
        or 0
    )
    retake_pending = (
        db.query(func.count(CertificateRetakeRequest.id))
        .filter(CertificateRetakeRequest.user_id == student_id, CertificateRetakeRequest.status == "pending")
        .scalar()
        or 0
    )

    return {
        "student": {
            "id": student.id,
            "full_name": student.full_name,
            "email": student.email,
            "status": student.status,
            "created_at": student.created_at,
        },
        "stats": {
            "cvs": {"count": cv_count, "latest_cv_id": latest_cv.id if latest_cv else None, "audit_count_on_latest": audit_count},
            "exercises": {
                "sets": sets_count,
                "total": exercises_total,
                "submissions_total": submissions_total,
                "submissions_passed": submissions_passed,
                "by_difficulty": exercises_by_difficulty,
            },
            "certificates": {
                "attempts_total": attempts_total,
                "attempts_passed": attempts_passed,
                "retake_pending": retake_pending,
            },
        },
    }


@router.get("/students/{student_id}/cvs")
def student_cvs(
    student_id: int,
    db: Session = Depends(get_db),
    _mentor=Depends(mentor_required),
):
    cvs = db.query(CV).filter(CV.user_id == student_id).order_by(CV.created_at.desc()).all()
    return cvs


@router.get("/students/{student_id}/exercises/summary")
def student_exercises_summary(
    student_id: int,
    db: Session = Depends(get_db),
    _mentor=Depends(mentor_required),
):
    packs = db.query(func.count(ExerciseSet.id)).filter(ExerciseSet.user_id == student_id).scalar() or 0
    exercises_total = db.query(func.count(Exercise.id)).filter(Exercise.user_id == student_id).scalar() or 0
    submissions_total = db.query(func.count(ExerciseSubmission.id)).filter(ExerciseSubmission.user_id == student_id).scalar() or 0
    submissions_passed = (
        db.query(func.count(ExerciseSubmission.id))
        .filter(ExerciseSubmission.user_id == student_id, ExerciseSubmission.passed.is_(True))
        .scalar()
        or 0
    )
    return {
        "practice_packs": packs,
        "exercises_total": exercises_total,
        "submissions_total": submissions_total,
        "submissions_passed": submissions_passed,
    }


@router.get("/students/{student_id}/certificates/attempts")
def student_certificate_attempts(
    student_id: int,
    db: Session = Depends(get_db),
    _mentor=Depends(mentor_required),
):
    rows = (
        db.query(CertificateAttempt, Certificate.title)
        .join(Certificate, Certificate.id == CertificateAttempt.certificate_id)
        .filter(CertificateAttempt.user_id == student_id)
        .order_by(CertificateAttempt.started_at.desc())
        .all()
    )
    out = []
    for a, title in rows:
        out.append(
            {
                "id": a.id,
                "certificate_id": a.certificate_id,
                "certificate_title": title,
                "user_id": a.user_id,
                "started_at": a.started_at,
                "submitted_at": a.submitted_at,
                "time_limit_minutes": a.time_limit_minutes,
                "timed_out": a.timed_out,
                "score": a.score,
                "total_questions": a.total_questions,
                "answers": a.answers,
            }
        )
    return out

