from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, JSON
from sqlalchemy.sql import func
from app.database import Base


class CV(Base):

    __tablename__ = "cvs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))

    filename = Column(String)
    file_path = Column(String)

    extracted_text = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CVAuditRecord(Base):
    """Stored result of an AI audit for a CV (history)."""

    __tablename__ = "cv_audit_records"

    id = Column(Integer, primary_key=True)
    cv_id = Column(Integer, ForeignKey("cvs.id", ondelete="CASCADE"), nullable=False)
    summary = Column(Text, nullable=False)
    strengths = Column(JSON, nullable=False)  # list of strings
    weaknesses = Column(JSON, nullable=False)
    recommendations = Column(JSON, nullable=False)
    score = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())