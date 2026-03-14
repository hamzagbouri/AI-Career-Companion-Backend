from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.exercise import Exercise, ExerciseSubmission
from app.schemas.exercise import (
    ExerciseResponse,
    ExerciseSubmissionResponse,
    GenerateExerciseRequest,
    SubmitExerciseRequest,
    SubmitExerciseResponse,
)
from app.services.llm_service import (
    evaluate_submission_with_llm,
    generate_exercise_with_llm,
    LLMUnavailableError,
)

router = APIRouter(prefix="/exercises", tags=["Exercises"])


@router.get("", response_model=list[ExerciseResponse])
def list_exercises(
    search: str | None = Query(None, description="Search in title and topic"),
    language: str | None = Query(None, description="Filter by language"),
    difficulty: str | None = Query(None, description="Filter by difficulty"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """List exercises for the current user. Optional search and filters."""
    q = db.query(Exercise).filter(Exercise.user_id == user.id)
    if search:
        s = f"%{search.strip()}%"
        q = q.filter(or_(Exercise.title.ilike(s), Exercise.topic.ilike(s)))
    if language:
        q = q.filter(Exercise.language == language)
    if difficulty:
        q = q.filter(Exercise.difficulty == difficulty)
    exercises = q.order_by(Exercise.created_at.desc()).all()
    return exercises


@router.post("/generate", response_model=ExerciseResponse)
async def generate_exercise(
    body: GenerateExerciseRequest | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Generate a new exercise via LLM (language, level, topic) and save for the current user."""
    body = body or GenerateExerciseRequest()
    try:
        result = await generate_exercise_with_llm(
            language=body.language,
            difficulty=body.difficulty,
            topic=body.topic,
        )
    except LLMUnavailableError as e:
        raise HTTPException(
            status_code=503,
            detail="LLM unavailable. Ensure Ollama is running and the model is pulled.",
        ) from e
    exercise = Exercise(
        user_id=user.id,
        language=body.language,
        topic=body.topic or "basics",
        title=result["title"],
        difficulty=result["difficulty"],
        description=result["description"],
        skeleton_code=result["skeleton_code"],
        expected_solution=result.get("expected_solution") or "",
    )
    db.add(exercise)
    db.commit()
    db.refresh(exercise)
    return exercise


@router.get("/{exercise_id}", response_model=ExerciseResponse)
def get_exercise(
    exercise_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get one exercise (own only)."""
    ex = db.query(Exercise).filter(Exercise.id == exercise_id, Exercise.user_id == user.id).first()
    if not ex:
        raise HTTPException(status_code=404, detail="Exercise not found")
    return ex


@router.post("/{exercise_id}/submit", response_model=SubmitExerciseResponse)
async def submit_exercise(
    exercise_id: int,
    body: SubmitExerciseRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Submit code for an exercise. AI evaluates and returns result; if wrong, returns correct answer. Saves to history."""
    ex = db.query(Exercise).filter(Exercise.id == exercise_id, Exercise.user_id == user.id).first()
    if not ex:
        raise HTTPException(status_code=404, detail="Exercise not found")
    try:
        result = await evaluate_submission_with_llm(
            language=ex.language,
            description=ex.description,
            expected_solution=ex.expected_solution or "",
            submitted_code=body.code.strip(),
        )
    except LLMUnavailableError as e:
        raise HTTPException(status_code=503, detail="LLM unavailable for evaluation.") from e
    submission = ExerciseSubmission(
        exercise_id=exercise_id,
        user_id=user.id,
        submitted_code=body.code.strip(),
        passed=result["correct"],
        feedback=result["feedback"],
        correct_answer=result["correct_answer"] if not result["correct"] else None,
    )
    db.add(submission)
    db.commit()
    return SubmitExerciseResponse(
        passed=result["correct"],
        feedback=result["feedback"],
        correct_answer=result["correct_answer"] if not result["correct"] else None,
    )


@router.get("/{exercise_id}/submissions", response_model=list[ExerciseSubmissionResponse])
def list_submissions(
    exercise_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """List submission history for an exercise (own only)."""
    ex = db.query(Exercise).filter(Exercise.id == exercise_id, Exercise.user_id == user.id).first()
    if not ex:
        raise HTTPException(status_code=404, detail="Exercise not found")
    subs = (
        db.query(ExerciseSubmission)
        .filter(ExerciseSubmission.exercise_id == exercise_id, ExerciseSubmission.user_id == user.id)
        .order_by(ExerciseSubmission.created_at.desc())
        .all()
    )
    return subs
