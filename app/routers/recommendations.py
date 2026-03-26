from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.recommendation import Recommendation
from app.schemas.recommendation import (
    RecommendationListResponse,
    RecommendationRefreshResponse,
    RecommendationUpdateRequest,
)
from app.services.recommendation_engine import generate_recommendations

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


@router.get("/my", response_model=RecommendationListResponse)
def my_recommendations(
    q: str | None = Query(None, description="Search title/provider/tags"),
    type: str | None = Query(None, description="course|video|article|exercise"),
    completed: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    query = db.query(Recommendation).filter(Recommendation.user_id == user.id)
    if type:
        query = query.filter(Recommendation.type == type)
    if completed is not None:
        query = query.filter(Recommendation.completed.is_(completed))
    if q:
        s = f"%{q.strip()}%"
        query = query.filter(or_(Recommendation.title.ilike(s), Recommendation.provider.ilike(s)))

    total = query.count()
    items = query.order_by(Recommendation.created_at.desc()).offset(offset).limit(limit).all()
    return RecommendationListResponse(items=items, total=total)


@router.post("/refresh", response_model=RecommendationRefreshResponse)
def refresh_recommendations(
    limit: int = Query(10, ge=1, le=30),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    created = generate_recommendations(db, user.id, limit=limit)
    # Return the newest items after refresh (including existing)
    items = (
        db.query(Recommendation)
        .filter(Recommendation.user_id == user.id)
        .order_by(Recommendation.created_at.desc())
        .limit(50)
        .all()
    )
    return RecommendationRefreshResponse(created=len(created), items=items)


@router.patch("/{rec_id}", response_model=dict)
def update_recommendation(
    rec_id: int,
    body: RecommendationUpdateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    rec = db.query(Recommendation).filter(Recommendation.id == rec_id, Recommendation.user_id == user.id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    rec.completed = bool(body.completed)
    db.commit()
    return {"ok": True}

