from datetime import datetime
from pydantic import BaseModel


class CertificateResponse(BaseModel):
    id: int
    created_by: int
    language: str
    level: str
    title: str
    time_limit_minutes: int
    created_at: datetime

    class Config:
        from_attributes = True


class CertificateCreate(BaseModel):
    language: str
    level: str
    title: str
    time_limit_minutes: int


class CertificateUpdate(BaseModel):
    title: str | None = None
    language: str | None = None
    level: str | None = None
    time_limit_minutes: int | None = None


class CertificateQuestionResponse(BaseModel):
    id: int
    certificate_id: int
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str
    order_index: int

    class Config:
        from_attributes = True


class CertificateQuestionCreate(BaseModel):
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str  # A, B, C, or D


class CertificateQuestionUpdate(BaseModel):
    question_text: str | None = None
    option_a: str | None = None
    option_b: str | None = None
    option_c: str | None = None
    option_d: str | None = None
    correct_answer: str | None = None  # A, B, C, or D


class CertificateAttemptResponse(BaseModel):
    id: int
    certificate_id: int
    user_id: int
    started_at: datetime
    submitted_at: datetime | None
    time_limit_minutes: int
    timed_out: bool
    score: int
    total_questions: int
    answers: dict

    class Config:
        from_attributes = True


class CertificateAttemptWithUserResponse(CertificateAttemptResponse):
    """For mentor: attempt with student email and name."""
    user_email: str = ""
    user_name: str = ""


class CertificateAttemptSubmit(BaseModel):
    answers: dict  # {"question_id": "A", ...}
    started_at: str | None = None  # ISO datetime when student started (for timeout check)


class CertificateForStudent(BaseModel):
    """Certificate with questions (for taking exam); no correct_answer exposed."""
    id: int
    language: str
    level: str
    title: str
    time_limit_minutes: int
    questions: list[dict]  # id, question_text, option_a, option_b, option_c, option_d (no correct_answer)

    class Config:
        from_attributes = True


class AttemptResult(BaseModel):
    score: int
    total_questions: int
    timed_out: bool
    passed: bool  # e.g. score >= 70% of total


class AttemptWithCertTitle(CertificateAttemptResponse):
    """Attempt with certificate title for listing."""
    certificate_title: str = ""


class AttemptDetailQuestion(BaseModel):
    """One question in attempt detail: text, options, correct answer, user's choice."""
    id: int
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str  # A, B, C, or D
    user_answer: str | None = None  # what the student chose


class AttemptDetailResponse(BaseModel):
    """Full attempt detail for student to review: cert title, attempt, and each question with correct + user answer."""
    certificate_title: str
    certificate_id: int
    attempt: CertificateAttemptResponse
    questions: list[AttemptDetailQuestion]


class RetakeRequestResponse(BaseModel):
    id: int
    certificate_id: int
    user_id: int
    status: str  # pending, approved, rejected
    requested_at: datetime
    reviewed_at: datetime | None
    used_at: datetime | None
    certificate_title: str = ""
    user_email: str = ""
    user_name: str = ""

    class Config:
        from_attributes = True


class RetakeRequestStudentResponse(BaseModel):
    """For student: my retake requests."""
    id: int
    certificate_id: int
    certificate_title: str = ""
    status: str
    requested_at: datetime
    reviewed_at: datetime | None
    used_at: datetime | None

    class Config:
        from_attributes = True
