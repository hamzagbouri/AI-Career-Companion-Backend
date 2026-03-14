from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Boolean, JSON
from sqlalchemy.sql import func
from app.database import Base


class Certificate(Base):
    """Certification created by mentor: language, level, time limit."""

    __tablename__ = "certificates"

    id = Column(Integer, primary_key=True)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    language = Column(String(32), nullable=False)
    level = Column(String(32), nullable=False)  # Beginner, Intermediate, Advanced
    title = Column(String(256), nullable=False)
    time_limit_minutes = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CertificateQuestion(Base):
    """Multiple-choice question for a certificate (mentor creates)."""

    __tablename__ = "certificate_questions"

    id = Column(Integer, primary_key=True)
    certificate_id = Column(Integer, ForeignKey("certificates.id", ondelete="CASCADE"), nullable=False)
    question_text = Column(Text, nullable=False)
    option_a = Column(Text, nullable=False)
    option_b = Column(Text, nullable=False)
    option_c = Column(Text, nullable=False)
    option_d = Column(Text, nullable=False)
    correct_answer = Column(String(1), nullable=False)  # A, B, C, or D
    order_index = Column(Integer, nullable=False, default=0)


class CertificateAttempt(Base):
    """Student's attempt at a certificate: answers, score, timed_out."""

    __tablename__ = "certificate_attempts"

    id = Column(Integer, primary_key=True)
    certificate_id = Column(Integer, ForeignKey("certificates.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    time_limit_minutes = Column(Integer, nullable=False)
    timed_out = Column(Boolean, nullable=False, default=False)
    score = Column(Integer, nullable=False)  # number of correct answers
    total_questions = Column(Integer, nullable=False)
    answers = Column(JSON, nullable=False)  # {"question_id": "A", ...} selected answers


class CertificateRetakeRequest(Base):
    """Student request to retake a certificate; mentor approves or rejects."""

    __tablename__ = "certificate_retake_requests"

    id = Column(Integer, primary_key=True)
    certificate_id = Column(Integer, ForeignKey("certificates.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), nullable=False, default="pending")  # pending, approved, rejected
    requested_at = Column(DateTime(timezone=True), server_default=func.now())
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True)  # when student used this approval to take the exam
