from datetime import datetime

from sqlalchemy.orm import Session

from app.models.certificate import Certificate, CertificateQuestion
from app.models.user import User


def seed_certificates(db: Session) -> None:
    """Insert sample certificates and questions if none exist."""
    existing = db.query(Certificate).count()
    if existing > 0:
        return

    # Use the first user (default admin is created on startup) as creator
    owner = db.query(User).first()
    if not owner:
        # No users yet, skip seeding; it can run again on next startup
        return

    for i in range(1, 11):
        lang = "Python" if i <= 5 else "JavaScript"
        level = "Beginner" if i <= 3 else "Intermediate" if i <= 7 else "Advanced"
        cert = Certificate(
            title=f"{lang} fundamentals #{i}",
            language=lang,
            level=level,
            time_limit_minutes=30,
            created_by=owner.id,
            created_at=datetime.utcnow(),
        )
        db.add(cert)
        db.flush()

        q1 = CertificateQuestion(
            certificate_id=cert.id,
            question_text=f"In {lang}, what is the result of 2 + 3?",
            option_a="23",
            option_b="5",
            option_c="Error",
            option_d="None of the above",
            correct_answer="B",
            order_index=1,
        )
        q2 = CertificateQuestion(
            certificate_id=cert.id,
            question_text=f"In {lang}, which keyword defines a function?",
            option_a="func",
            option_b="def" if lang == "Python" else "function",
            option_c="fn",
            option_d="lambda",
            correct_answer="B",
            order_index=2,
        )
        db.add_all([q1, q2])

    db.commit()

