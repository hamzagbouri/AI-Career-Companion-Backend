from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
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