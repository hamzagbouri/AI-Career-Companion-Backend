from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.certificate import Certificate, CertificateQuestion, CertificateAttempt, CertificateRetakeRequest
from app.schemas.certificate import (
    CertificateResponse,
    CertificateCreate,
    CertificateUpdate,
    CertificateQuestionResponse,
    CertificateQuestionCreate,
    CertificateQuestionUpdate,
    CertificateAttemptResponse,
    CertificateAttemptWithUserResponse,
    CertificateAttemptSubmit,
    AttemptResult,
    AttemptWithCertTitle,
    AttemptDetailResponse,
    AttemptDetailQuestion,
    RetakeRequestResponse,
    RetakeRequestStudentResponse,
)

router = APIRouter(prefix="/certificates", tags=["Certificates"])


def mentor_or_admin(user: User = Depends(get_current_user)):
    if user.role not in ("mentor", "admin"):
        raise HTTPException(status_code=403, detail="Mentor or admin required")
    return user


# ---- Mentor: create / manage certificates and questions ----

@router.get("/mentor", response_model=list[CertificateResponse])
def mentor_list_certificates(
    search: str | None = Query(None),
    language: str | None = Query(None),
    level: str | None = Query(None),
    db: Session = Depends(get_db),
    user=Depends(mentor_or_admin),
):
    """List all certificates (created by any mentor/admin). Optional search and filters."""
    if user.role == "admin":
        q = db.query(Certificate)
    else:
        q = db.query(Certificate).filter(Certificate.created_by == user.id)
    if search:
        q = q.filter(Certificate.title.ilike(f"%{search.strip()}%"))
    if language:
        q = q.filter(Certificate.language == language)
    if level:
        q = q.filter(Certificate.level == level)
    certs = q.order_by(Certificate.created_at.desc()).all()
    return certs


@router.post("", response_model=CertificateResponse)
def create_certificate(
    body: CertificateCreate,
    db: Session = Depends(get_db),
    user=Depends(mentor_or_admin),
):
    """Create a new certificate (language, level, time limit)."""
    cert = Certificate(
        created_by=user.id,
        language=body.language,
        level=body.level,
        title=body.title,
        time_limit_minutes=body.time_limit_minutes,
    )
    db.add(cert)
    db.commit()
    db.refresh(cert)
    return cert


@router.get("/mentor/retake-requests", response_model=list[RetakeRequestResponse])
def mentor_list_retake_requests(
    status: str | None = Query(None),
    search: str | None = Query(None),
    db: Session = Depends(get_db),
    user=Depends(mentor_or_admin),
):
    """List retake requests (all for admin, or for certs created by mentor)."""
    q = db.query(CertificateRetakeRequest).join(Certificate, CertificateRetakeRequest.certificate_id == Certificate.id)
    if user.role != "admin":
        q = q.filter(Certificate.created_by == user.id)
    if status:
        q = q.filter(CertificateRetakeRequest.status == status)
    if search:
        search_like = f"%{search.strip()}%"
        q = q.join(User, User.id == CertificateRetakeRequest.user_id).filter(
            (Certificate.title.ilike(search_like)) | (User.email.ilike(search_like)) | (User.full_name.ilike(search_like))
        )
    requests = q.order_by(CertificateRetakeRequest.requested_at.desc()).all()
    result = []
    for r in requests:
        cert = db.query(Certificate).filter(Certificate.id == r.certificate_id).first()
        student = db.query(User).filter(User.id == r.user_id).first()
        result.append(RetakeRequestResponse(
            id=r.id,
            certificate_id=r.certificate_id,
            user_id=r.user_id,
            status=r.status,
            requested_at=r.requested_at,
            reviewed_at=r.reviewed_at,
            used_at=r.used_at,
            certificate_title=cert.title if cert else "",
            user_email=student.email if student else "",
            user_name=student.full_name if student else "",
        ))
    return result


@router.post("/mentor/retake-requests/{request_id}/approve")
def mentor_approve_retake(
    request_id: int,
    db: Session = Depends(get_db),
    user=Depends(mentor_or_admin),
):
    """Approve a retake request; student can then take the exam again."""
    req = db.query(CertificateRetakeRequest).filter(CertificateRetakeRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Retake request not found")
    cert = db.query(Certificate).filter(Certificate.id == req.certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if user.role != "admin" and cert.created_by != user.id:
        raise HTTPException(status_code=403, detail="Not your certificate")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail="Request already reviewed")
    req.status = "approved"
    req.reviewed_at = datetime.now(timezone.utc)
    req.reviewed_by_id = user.id
    db.commit()
    return {"message": "Approved", "id": req.id}


@router.post("/mentor/retake-requests/{request_id}/reject")
def mentor_reject_retake(
    request_id: int,
    db: Session = Depends(get_db),
    user=Depends(mentor_or_admin),
):
    """Reject a retake request."""
    req = db.query(CertificateRetakeRequest).filter(CertificateRetakeRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Retake request not found")
    cert = db.query(Certificate).filter(Certificate.id == req.certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if user.role != "admin" and cert.created_by != user.id:
        raise HTTPException(status_code=403, detail="Not your certificate")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail="Request already reviewed")
    req.status = "rejected"
    req.reviewed_at = datetime.now(timezone.utc)
    req.reviewed_by_id = user.id
    db.commit()
    return {"message": "Rejected", "id": req.id}


@router.get("/mentor/{certificate_id}", response_model=CertificateResponse)
def mentor_get_certificate(
    certificate_id: int,
    db: Session = Depends(get_db),
    user=Depends(mentor_or_admin),
):
    """Get one certificate (with questions for mentor)."""
    cert = db.query(Certificate).filter(Certificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if user.role != "admin" and cert.created_by != user.id:
        raise HTTPException(status_code=403, detail="Not your certificate")
    return cert


@router.put("/mentor/{certificate_id}", response_model=CertificateResponse)
def mentor_update_certificate(
    certificate_id: int,
    body: CertificateUpdate,
    db: Session = Depends(get_db),
    user=Depends(mentor_or_admin),
):
    """Update a certificate (title, language, level, time limit)."""
    cert = db.query(Certificate).filter(Certificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if user.role != "admin" and cert.created_by != user.id:
        raise HTTPException(status_code=403, detail="Not your certificate")
    if body.title is not None:
        cert.title = body.title
    if body.language is not None:
        cert.language = body.language
    if body.level is not None:
        cert.level = body.level
    if body.time_limit_minutes is not None:
        cert.time_limit_minutes = body.time_limit_minutes
    db.commit()
    db.refresh(cert)
    return cert


@router.delete("/mentor/{certificate_id}")
def mentor_delete_certificate(
    certificate_id: int,
    db: Session = Depends(get_db),
    user=Depends(mentor_or_admin),
):
    """Delete a certificate (and its questions/attempts)."""
    cert = db.query(Certificate).filter(Certificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if user.role != "admin" and cert.created_by != user.id:
        raise HTTPException(status_code=403, detail="Not your certificate")
    db.delete(cert)
    db.commit()
    return {"message": "Deleted"}


@router.get("/mentor/{certificate_id}/questions", response_model=list[CertificateQuestionResponse])
def mentor_list_questions(
    certificate_id: int,
    db: Session = Depends(get_db),
    user=Depends(mentor_or_admin),
):
    """List questions for a certificate (mentor only; includes correct_answer)."""
    cert = db.query(Certificate).filter(Certificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if user.role != "admin" and cert.created_by != user.id:
        raise HTTPException(status_code=403, detail="Not your certificate")
    questions = db.query(CertificateQuestion).filter(CertificateQuestion.certificate_id == certificate_id).order_by(CertificateQuestion.order_index).all()
    return questions


@router.post("/mentor/{certificate_id}/questions", response_model=CertificateQuestionResponse)
def add_question(
    certificate_id: int,
    body: CertificateQuestionCreate,
    db: Session = Depends(get_db),
    user=Depends(mentor_or_admin),
):
    """Add a multiple-choice question to a certificate."""
    cert = db.query(Certificate).filter(Certificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if user.role != "admin" and cert.created_by != user.id:
        raise HTTPException(status_code=403, detail="Not your certificate")
    if body.correct_answer not in ("A", "B", "C", "D"):
        raise HTTPException(status_code=400, detail="correct_answer must be A, B, C, or D")
    count = db.query(CertificateQuestion).filter(CertificateQuestion.certificate_id == certificate_id).count()
    q = CertificateQuestion(
        certificate_id=certificate_id,
        question_text=body.question_text,
        option_a=body.option_a,
        option_b=body.option_b,
        option_c=body.option_c,
        option_d=body.option_d,
        correct_answer=body.correct_answer.upper(),
        order_index=count,
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


@router.put("/mentor/{certificate_id}/questions/{question_id}", response_model=CertificateQuestionResponse)
def update_question(
    certificate_id: int,
    question_id: int,
    body: CertificateQuestionUpdate,
    db: Session = Depends(get_db),
    user=Depends(mentor_or_admin),
):
    """Update a question."""
    cert = db.query(Certificate).filter(Certificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if user.role != "admin" and cert.created_by != user.id:
        raise HTTPException(status_code=403, detail="Not your certificate")
    q = db.query(CertificateQuestion).filter(CertificateQuestion.id == question_id, CertificateQuestion.certificate_id == certificate_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    if body.question_text is not None:
        q.question_text = body.question_text
    if body.option_a is not None:
        q.option_a = body.option_a
    if body.option_b is not None:
        q.option_b = body.option_b
    if body.option_c is not None:
        q.option_c = body.option_c
    if body.option_d is not None:
        q.option_d = body.option_d
    if body.correct_answer is not None:
        if body.correct_answer.upper() not in ("A", "B", "C", "D"):
            raise HTTPException(status_code=400, detail="correct_answer must be A, B, C, or D")
        q.correct_answer = body.correct_answer.upper()
    db.commit()
    db.refresh(q)
    return q


@router.delete("/mentor/{certificate_id}/questions/{question_id}")
def delete_question(
    certificate_id: int,
    question_id: int,
    db: Session = Depends(get_db),
    user=Depends(mentor_or_admin),
):
    """Delete a question from a certificate."""
    cert = db.query(Certificate).filter(Certificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if user.role != "admin" and cert.created_by != user.id:
        raise HTTPException(status_code=403, detail="Not your certificate")
    q = db.query(CertificateQuestion).filter(CertificateQuestion.id == question_id, CertificateQuestion.certificate_id == certificate_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    db.delete(q)
    db.commit()
    return {"message": "Deleted"}


@router.get("/mentor/{certificate_id}/attempts", response_model=list[CertificateAttemptWithUserResponse])
def mentor_list_attempts(
    certificate_id: int,
    search: str | None = Query(None),
    db: Session = Depends(get_db),
    user=Depends(mentor_or_admin),
):
    """List all attempts for a certificate (scores, answers, timed_out, student name/email). Optional search by student."""
    cert = db.query(Certificate).filter(Certificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if user.role != "admin" and cert.created_by != user.id:
        raise HTTPException(status_code=403, detail="Not your certificate")
    q = db.query(CertificateAttempt).filter(CertificateAttempt.certificate_id == certificate_id)
    if search:
        search_like = f"%{search.strip()}%"
        q = q.join(User, User.id == CertificateAttempt.user_id).filter(
            (User.email.ilike(search_like)) | (User.full_name.ilike(search_like))
        )
    attempts = q.order_by(CertificateAttempt.submitted_at.desc()).all()
    result = []
    for a in attempts:
        student = db.query(User).filter(User.id == a.user_id).first()
        result.append(CertificateAttemptWithUserResponse(
            id=a.id,
            certificate_id=a.certificate_id,
            user_id=a.user_id,
            started_at=a.started_at,
            submitted_at=a.submitted_at,
            time_limit_minutes=a.time_limit_minutes,
            timed_out=a.timed_out,
            score=a.score,
            total_questions=a.total_questions,
            answers=a.answers or {},
            user_email=student.email if student else "",
            user_name=student.full_name if student else "",
        ))
    return result


# ---- Student: list certs, take exam, submit ----

@router.get("/available", response_model=list[CertificateResponse])
def student_list_certificates(
    search: str | None = Query(None),
    language: str | None = Query(None),
    level: str | None = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """List certificates available to take (no questions exposed). Optional search and filters."""
    q = db.query(Certificate).filter(Certificate.id.in_(
        db.query(CertificateQuestion.certificate_id).distinct()
    ))
    if search:
        q = q.filter(Certificate.title.ilike(f"%{search.strip()}%"))
    if language:
        q = q.filter(Certificate.language == language)
    if level:
        q = q.filter(Certificate.level == level)
    certs = q.order_by(Certificate.created_at.desc()).all()
    return certs


def _student_can_take_exam(db: Session, certificate_id: int, user_id: int) -> tuple[bool, str]:
    """Returns (can_take, message). Student can take if no attempt yet or has an approved retake with used_at is None."""
    attempt_count = db.query(CertificateAttempt).filter(
        CertificateAttempt.certificate_id == certificate_id,
        CertificateAttempt.user_id == user_id,
    ).count()
    if attempt_count == 0:
        return True, ""
    approved = db.query(CertificateRetakeRequest).filter(
        CertificateRetakeRequest.certificate_id == certificate_id,
        CertificateRetakeRequest.user_id == user_id,
        CertificateRetakeRequest.status == "approved",
        CertificateRetakeRequest.used_at.is_(None),
    ).first()
    if approved:
        return True, ""
    return False, "You have already attempted this certificate. Request a retake from your mentor to try again."


@router.post("/{certificate_id}/request-retake", response_model=RetakeRequestStudentResponse)
def student_request_retake(
    certificate_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Request permission to retake a certificate exam (after first attempt)."""
    cert = db.query(Certificate).filter(Certificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    existing = db.query(CertificateAttempt).filter(
        CertificateAttempt.certificate_id == certificate_id,
        CertificateAttempt.user_id == user.id,
    ).first()
    if not existing:
        raise HTTPException(status_code=400, detail="You have not attempted this certificate yet. You can start the exam directly.")
    pending = db.query(CertificateRetakeRequest).filter(
        CertificateRetakeRequest.certificate_id == certificate_id,
        CertificateRetakeRequest.user_id == user.id,
        CertificateRetakeRequest.status == "pending",
    ).first()
    if pending:
        raise HTTPException(status_code=400, detail="You already have a pending retake request for this certificate.")
    req = CertificateRetakeRequest(certificate_id=certificate_id, user_id=user.id, status="pending")
    db.add(req)
    db.commit()
    db.refresh(req)
    return RetakeRequestStudentResponse(
        id=req.id,
        certificate_id=req.certificate_id,
        certificate_title=cert.title,
        status=req.status,
        requested_at=req.requested_at,
        reviewed_at=req.reviewed_at,
        used_at=req.used_at,
    )


@router.get("/my-retake-requests", response_model=list[RetakeRequestStudentResponse])
def student_my_retake_requests(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """List current user's retake requests."""
    requests = db.query(CertificateRetakeRequest).filter(
        CertificateRetakeRequest.user_id == user.id,
    ).order_by(CertificateRetakeRequest.requested_at.desc()).all()
    result = []
    for r in requests:
        cert = db.query(Certificate).filter(Certificate.id == r.certificate_id).first()
        result.append(RetakeRequestStudentResponse(
            id=r.id,
            certificate_id=r.certificate_id,
            certificate_title=cert.title if cert else "",
            status=r.status,
            requested_at=r.requested_at,
            reviewed_at=r.reviewed_at,
            used_at=r.used_at,
        ))
    return result


@router.get("/{certificate_id}/exam")
def student_get_exam(
    certificate_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get certificate with questions for taking the exam (no correct_answer). One attempt per cert unless mentor approved retake."""
    cert = db.query(Certificate).filter(Certificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    can_take, msg = _student_can_take_exam(db, certificate_id, user.id)
    if not can_take:
        raise HTTPException(status_code=403, detail=msg)
    questions = db.query(CertificateQuestion).filter(CertificateQuestion.certificate_id == certificate_id).order_by(CertificateQuestion.order_index).all()
    if not questions:
        raise HTTPException(status_code=404, detail="Certificate has no questions yet")
    return {
        "id": cert.id,
        "language": cert.language,
        "level": cert.level,
        "title": cert.title,
        "time_limit_minutes": cert.time_limit_minutes,
        "questions": [
            {
                "id": q.id,
                "question_text": q.question_text,
                "option_a": q.option_a,
                "option_b": q.option_b,
                "option_c": q.option_c,
                "option_d": q.option_d,
            }
            for q in questions
        ],
    }


@router.post("/{certificate_id}/attempt", response_model=AttemptResult)
def student_submit_attempt(
    certificate_id: int,
    body: CertificateAttemptSubmit,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Submit attempt. If timeout, unanswered questions count as wrong. Returns score and passed."""
    cert = db.query(Certificate).filter(Certificate.id == certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    questions = db.query(CertificateQuestion).filter(CertificateQuestion.certificate_id == certificate_id).order_by(CertificateQuestion.order_index).all()
    if not questions:
        raise HTTPException(status_code=404, detail="Certificate has no questions")

    started_at = body.started_at
    if started_at:
        try:
            started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
        except Exception:
            started = datetime.now(timezone.utc)
    else:
        started = datetime.now(timezone.utc)

    answers = body.answers
    now = datetime.now(timezone.utc)
    limit_seconds = cert.time_limit_minutes * 60
    elapsed = (now - started).total_seconds()
    timed_out = elapsed > limit_seconds

    correct = 0
    for q in questions:
        chosen = answers.get(str(q.id))
        if chosen and str(chosen).upper() in ("A", "B", "C", "D") and str(chosen).upper() == q.correct_answer:
            correct += 1
        # if timed out or not answered, count as wrong (no need to add)

    attempt = CertificateAttempt(
        certificate_id=certificate_id,
        user_id=user.id,
        started_at=started,
        submitted_at=now,
        time_limit_minutes=cert.time_limit_minutes,
        timed_out=timed_out,
        score=correct,
        total_questions=len(questions),
        answers=answers,
    )
    db.add(attempt)
    db.commit()

    # Mark one approved retake as used (so they need a new request for another retake)
    retake = db.query(CertificateRetakeRequest).filter(
        CertificateRetakeRequest.certificate_id == certificate_id,
        CertificateRetakeRequest.user_id == user.id,
        CertificateRetakeRequest.status == "approved",
        CertificateRetakeRequest.used_at.is_(None),
    ).order_by(CertificateRetakeRequest.reviewed_at.asc()).first()
    if retake:
        retake.used_at = now
        db.commit()

    passed = correct >= (len(questions) * 70 // 100) if len(questions) else False
    return AttemptResult(
        score=correct,
        total_questions=len(questions),
        timed_out=timed_out,
        passed=passed,
    )


@router.get("/my-attempts", response_model=list[AttemptWithCertTitle])
def student_my_attempts(
    search: str | None = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """List current user's attempts with certificate title. Optional search by cert title."""
    attempts = db.query(CertificateAttempt).filter(CertificateAttempt.user_id == user.id).order_by(CertificateAttempt.submitted_at.desc()).all()
    result = []
    for a in attempts:
        cert = db.query(Certificate).filter(Certificate.id == a.certificate_id).first()
        title = cert.title if cert else ""
        if search and search.strip().lower() not in title.lower():
            continue
        result.append(AttemptWithCertTitle(
            id=a.id,
            certificate_id=a.certificate_id,
            user_id=a.user_id,
            started_at=a.started_at,
            submitted_at=a.submitted_at,
            time_limit_minutes=a.time_limit_minutes,
            timed_out=a.timed_out,
            score=a.score,
            total_questions=a.total_questions,
            answers=a.answers or {},
            certificate_title=title,
        ))
    return result


@router.get("/my-attempts/{attempt_id}/detail", response_model=AttemptDetailResponse)
def student_attempt_detail(
    attempt_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get one attempt detail for current user: cert title, attempt, and each question with correct + user answer."""
    attempt = db.query(CertificateAttempt).filter(CertificateAttempt.id == attempt_id, CertificateAttempt.user_id == user.id).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    cert = db.query(Certificate).filter(Certificate.id == attempt.certificate_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    questions = db.query(CertificateQuestion).filter(CertificateQuestion.certificate_id == attempt.certificate_id).order_by(CertificateQuestion.order_index).all()
    answers = attempt.answers or {}
    detail_questions = [
        AttemptDetailQuestion(
            id=q.id,
            question_text=q.question_text,
            option_a=q.option_a,
            option_b=q.option_b,
            option_c=q.option_c,
            option_d=q.option_d,
            correct_answer=q.correct_answer,
            user_answer=answers.get(str(q.id)),
        )
        for q in questions
    ]
    return AttemptDetailResponse(
        certificate_title=cert.title,
        certificate_id=cert.id,
        attempt=CertificateAttemptResponse(
            id=attempt.id,
            certificate_id=attempt.certificate_id,
            user_id=attempt.user_id,
            started_at=attempt.started_at,
            submitted_at=attempt.submitted_at,
            time_limit_minutes=attempt.time_limit_minutes,
            timed_out=attempt.timed_out,
            score=attempt.score,
            total_questions=attempt.total_questions,
            answers=attempt.answers or {},
        ),
        questions=detail_questions,
    )
