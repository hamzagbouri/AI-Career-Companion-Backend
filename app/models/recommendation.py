from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from app.database import Base


class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # course | video | article | exercise
    type = Column(String(32), nullable=False, index=True)

    title = Column(String(256), nullable=False)
    provider = Column(String(128), nullable=True)
    url = Column(String(1024), nullable=True)
    duration = Column(String(64), nullable=True)
    rating = Column(Float, nullable=True)

    tags = Column(JSON, nullable=False, default=list)  # list[str]
    reason = Column(Text, nullable=True)
    source = Column(String(32), nullable=False, default="nlp")  # cv | exercises | nlp

    completed = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

