from fastapi import APIRouter, Depends, HTTPException, Query
from uuid import uuid4
from datetime import datetime, timezone
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.exercise import Exercise, ExerciseSet, ExerciseSubmission
from app.schemas.exercise import (
    ExerciseResponse,
    ExerciseSubmissionResponse,
    ExerciseSetDetail,
    ExerciseSetSummary,
    ExercisesSummaryResponse,
    GenerateExerciseRequest,
    PreviewAcceptRequest,
    PreviewDiscardRequest,
    PreviewExerciseDraft,
    PreviewGenerateRequest,
    PreviewGenerateResponse,
    RecentSubmissionItem,
    SubmitExerciseRequest,
    SubmitExerciseResponse,
)
from app.services.llm_service import (
    evaluate_submission_with_llm,
    generate_exercise_with_llm,
    LLMUnavailableError,
)
from app.utils.code_compare import codes_equivalent

router = APIRouter(prefix="/exercises", tags=["Exercises"])

# In-memory preview store:
# batch_id -> { user_id, created_at, exercises: [... draft payload with expected_solution] }
EXERCISE_DRAFT_BATCHES: dict[str, dict] = {}


def _solved_exercise_ids(db: Session, user_id: int, exercise_ids: list[int]) -> set[int]:
    if not exercise_ids:
        return set()
    rows = (
        db.query(ExerciseSubmission.exercise_id)
        .filter(
            ExerciseSubmission.user_id == user_id,
            ExerciseSubmission.exercise_id.in_(exercise_ids),
            ExerciseSubmission.passed.is_(True),
        )
        .distinct()
        .all()
    )
    return {r[0] for r in rows}


@router.get("/summary", response_model=ExercisesSummaryResponse)
def exercises_summary(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Counts for the student dashboard strip."""
    packs = db.query(ExerciseSet).filter(ExerciseSet.user_id == user.id).count()
    exercises_total = db.query(Exercise).filter(Exercise.user_id == user.id).count()
    submissions_total = db.query(ExerciseSubmission).filter(ExerciseSubmission.user_id == user.id).count()
    submissions_passed = (
        db.query(ExerciseSubmission)
        .filter(ExerciseSubmission.user_id == user.id, ExerciseSubmission.passed.is_(True))
        .count()
    )
    return ExercisesSummaryResponse(
        practice_packs=packs,
        exercises_total=exercises_total,
        submissions_total=submissions_total,
        submissions_passed=submissions_passed,
    )


@router.get("/sets", response_model=list[ExerciseSetSummary])
def list_exercise_sets(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """All practice packs for the current user."""
    sets = (
        db.query(ExerciseSet)
        .filter(ExerciseSet.user_id == user.id)
        .order_by(ExerciseSet.created_at.desc())
        .all()
    )
    out: list[ExerciseSetSummary] = []
    for s in sets:
        ex_ids = [row[0] for row in db.query(Exercise.id).filter(Exercise.set_id == s.id).all()]
        solved = len(_solved_exercise_ids(db, user.id, ex_ids))
        out.append(
            ExerciseSetSummary(
                id=s.id,
                title=s.title,
                language=s.language,
                topic=s.topic,
                difficulty=s.difficulty,
                exercise_count=len(ex_ids),
                solved_count=solved,
                created_at=s.created_at,
            )
        )
    return out


@router.get("/sets/{set_id}", response_model=ExerciseSetDetail)
def get_exercise_set(
    set_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    s = db.query(ExerciseSet).filter(ExerciseSet.id == set_id, ExerciseSet.user_id == user.id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Practice pack not found")
    exercises = (
        db.query(Exercise)
        .filter(Exercise.set_id == s.id, Exercise.user_id == user.id)
        .order_by(Exercise.order_in_set.asc(), Exercise.id.asc())
        .all()
    )
    return ExerciseSetDetail(
        id=s.id,
        title=s.title,
        language=s.language,
        topic=s.topic,
        difficulty=s.difficulty,
        created_at=s.created_at,
        exercises=exercises,
    )


@router.delete("/sets/{set_id}")
def delete_exercise_set(
    set_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    s = db.query(ExerciseSet).filter(ExerciseSet.id == set_id, ExerciseSet.user_id == user.id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Practice pack not found")
    db.delete(s)
    db.commit()
    return {"message": "Practice pack deleted"}


@router.get("/submissions/recent", response_model=list[RecentSubmissionItem])
def recent_submissions(
    limit: int = Query(15, ge=1, le=50),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    rows = (
        db.query(ExerciseSubmission, Exercise.title)
        .join(Exercise, Exercise.id == ExerciseSubmission.exercise_id)
        .filter(ExerciseSubmission.user_id == user.id)
        .order_by(ExerciseSubmission.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        RecentSubmissionItem(
            id=sub.id,
            exercise_id=sub.exercise_id,
            exercise_title=title,
            passed=sub.passed,
            created_at=sub.created_at,
        )
        for sub, title in rows
    ]


@router.get("", response_model=list[ExerciseResponse])
def list_exercises(
    search: str | None = Query(None, description="Search in title and topic"),
    language: str | None = Query(None, description="Filter by language"),
    difficulty: str | None = Query(None, description="Filter by difficulty"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
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


@router.post("/preview-generate", response_model=PreviewGenerateResponse)
async def preview_generate_exercises(
    body: PreviewGenerateRequest,
    user=Depends(get_current_user),
):
    """Generate drafts in one batch (not saved). Student reviews then accepts."""
    desired = max(1, min(body.count or 1, 10))
    batch_id = str(uuid4())
    draft_exercises: list[PreviewExerciseDraft] = []
    stored: list[dict] = []
    existing_titles: set[str] = set()

    for _i in range(desired):
        try:
            result = None
            # Retry a couple times inside the same batch to reduce duplicates.
            for _retry in range(3):
                variant_nonce = str(uuid4())
                candidate = await generate_exercise_with_llm(
                    language=body.language,
                    difficulty=body.difficulty,
                    topic=body.topic,
                    variant_nonce=variant_nonce,
                    avoid_titles=list(existing_titles),
                )
                if candidate and candidate.get("title") not in existing_titles:
                    result = candidate
                    break
            if result is None:
                # Last fallback: accept whatever we got.
                result = candidate
        except LLMUnavailableError as e:
            raise HTTPException(
                status_code=503,
                detail="LLM unavailable. Ensure Ollama is running and the model is pulled.",
            ) from e

        draft_exercises.append(
            PreviewExerciseDraft(
                language=body.language,
                topic=body.topic,
                title=result["title"],
                difficulty=result["difficulty"],
                description=result["description"],
                skeleton_code=result["skeleton_code"],
            )
        )
        existing_titles.add(result["title"])
        stored.append(
            {
                "language": body.language,
                "topic": body.topic,
                "title": result["title"],
                "difficulty": result["difficulty"],
                "description": result["description"],
                "skeleton_code": result["skeleton_code"],
                "expected_solution": result.get("expected_solution") or "",
            }
        )

    EXERCISE_DRAFT_BATCHES[batch_id] = {
        "user_id": user.id,
        "created_at": datetime.now(timezone.utc),
        "exercises": stored,
    }
    return PreviewGenerateResponse(batch_id=batch_id, exercises=draft_exercises)


@router.post("/preview-accept", response_model=list[ExerciseResponse])
async def preview_accept_exercises(
    body: PreviewAcceptRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    batch = EXERCISE_DRAFT_BATCHES.get(body.batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Preview batch not found")
    if batch["user_id"] != user.id:
        raise HTTPException(status_code=403, detail="Not allowed")

    items = batch["exercises"]
    if not items:
        raise HTTPException(status_code=400, detail="Empty batch")

    first = items[0]
    default_title = f"{first['language']} · {first.get('topic') or 'practice'} ({len(items)} exercises)"
    title = (body.title or default_title).strip()[:256]

    ex_set = ExerciseSet(
        user_id=user.id,
        title=title,
        language=str(first["language"]),
        topic=first.get("topic"),
        difficulty=str(first["difficulty"]),
    )
    db.add(ex_set)
    db.flush()

    created: list[Exercise] = []
    for idx, ex in enumerate(items):
        exercise = Exercise(
            user_id=user.id,
            set_id=ex_set.id,
            order_in_set=idx + 1,
            language=ex["language"],
            topic=ex["topic"],
            title=ex["title"],
            difficulty=ex["difficulty"],
            description=ex["description"],
            skeleton_code=ex["skeleton_code"],
            expected_solution=ex["expected_solution"],
        )
        db.add(exercise)
        created.append(exercise)

    db.commit()
    for exercise in created:
        db.refresh(exercise)

    EXERCISE_DRAFT_BATCHES.pop(body.batch_id, None)
    return created


@router.post("/preview-discard")
async def preview_discard_exercises(
    body: PreviewDiscardRequest,
    user=Depends(get_current_user),
):
    batch = EXERCISE_DRAFT_BATCHES.get(body.batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Preview batch not found")
    if batch["user_id"] != user.id:
        raise HTTPException(status_code=403, detail="Not allowed")
    EXERCISE_DRAFT_BATCHES.pop(body.batch_id, None)
    return {"message": "Preview discarded"}


@router.post("/generate", response_model=ExerciseResponse)
async def generate_exercise(
    body: GenerateExerciseRequest | None = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Generate and immediately save one exercise (no preview)."""
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
    ex = db.query(Exercise).filter(Exercise.id == exercise_id, Exercise.user_id == user.id).first()
    if not ex:
        raise HTTPException(status_code=404, detail="Exercise not found")

    code = body.code.strip()
    expected = (ex.expected_solution or "").strip()

    try:
        result = await evaluate_submission_with_llm(
            language=ex.language,
            description=ex.description,
            expected_solution=expected,
            submitted_code=code,
        )
    except LLMUnavailableError:
        if expected and codes_equivalent(code, expected):
            result = {
                "correct": True,
                "feedback": "AI checker is offline. Your answer matches the reference solution.",
                "correct_answer": "",
            }
        else:
            result = {
                "correct": False,
                "feedback": (
                    "AI checker is offline. A simple comparison did not match the reference; "
                    "when online, resubmit for detailed feedback."
                ),
                "correct_answer": expected or "Reference not available.",
            }

    submission = ExerciseSubmission(
        exercise_id=exercise_id,
        user_id=user.id,
        submitted_code=code,
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
