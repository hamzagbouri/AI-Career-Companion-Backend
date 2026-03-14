from datetime import datetime
from pydantic import BaseModel


class CVResponse(BaseModel):
    id: int
    filename: str
    extracted_text: str

    class Config:
        from_attributes = True


class CVAuditRecordResponse(BaseModel):
    id: int
    cv_id: int
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    recommendations: list[str]
    score: int
    created_at: datetime

    class Config:
        from_attributes = True