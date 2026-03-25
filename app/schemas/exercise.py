from datetime import datetime
from pydantic import BaseModel


class ExerciseResponse(BaseModel):
    id: int
    user_id: int
    set_id: int | None = None
    order_in_set: int | None = None
    language: str
    topic: str | None = None
    title: str
    difficulty: str
    description: str
    skeleton_code: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class ExerciseSetSummary(BaseModel):
    id: int
    title: str
    language: str
    topic: str | None
    difficulty: str
    exercise_count: int
    solved_count: int
    created_at: datetime


class ExerciseSetDetail(BaseModel):
    id: int
    title: str
    language: str
    topic: str | None
    difficulty: str
    created_at: datetime
    exercises: list[ExerciseResponse]


class ExercisesSummaryResponse(BaseModel):
    practice_packs: int
    exercises_total: int
    submissions_total: int
    submissions_passed: int


class RecentSubmissionItem(BaseModel):
    id: int
    exercise_id: int
    exercise_title: str
    passed: bool
    created_at: datetime


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


class PreviewExerciseDraft(BaseModel):
    """Draft exercise shown to the student. Does NOT include expected_solution."""
    language: str
    topic: str | None = None
    title: str
    difficulty: str
    description: str
    skeleton_code: str | None


class PreviewGenerateRequest(BaseModel):
    language: str = "python"
    difficulty: str = "Beginner"
    topic: str = "basics"
    count: int = 1


class PreviewGenerateResponse(BaseModel):
    batch_id: str
    exercises: list[PreviewExerciseDraft]


class PreviewAcceptRequest(BaseModel):
    batch_id: str
    title: str | None = None


class PreviewDiscardRequest(BaseModel):
    batch_id: str
