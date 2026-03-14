from datetime import datetime
from pydantic import BaseModel


class ExerciseResponse(BaseModel):
    id: int
    user_id: int
    language: str
    topic: str | None = None
    title: str
    difficulty: str
    description: str
    skeleton_code: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class GenerateExerciseRequest(BaseModel):
    language: str = "python"
    difficulty: str = "Beginner"
    topic: str = "basics"  # e.g. OOP, dictionaries, tuples, lists, functions, loops


class SubmitExerciseRequest(BaseModel):
    code: str


class SubmitExerciseResponse(BaseModel):
    passed: bool
    feedback: str
    correct_answer: str | None  # when passed=False


class ExerciseSubmissionResponse(BaseModel):
    id: int
    exercise_id: int
    submitted_code: str
    passed: bool
    feedback: str | None
    correct_answer: str | None
    created_at: datetime

    class Config:
        from_attributes = True
