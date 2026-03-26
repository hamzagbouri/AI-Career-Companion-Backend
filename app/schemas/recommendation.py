from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


RecommendationType = Literal["course", "video", "article", "exercise"]


class RecommendationItem(BaseModel):
    id: int
    type: RecommendationType
    title: str
    provider: str | None = None
    url: str | None = None
    duration: str | None = None
    rating: float | None = None
    tags: list[str] = Field(default_factory=list)
    reason: str | None = None
    source: str
    completed: bool
    created_at: datetime

    class Config:
        from_attributes = True


class RecommendationListResponse(BaseModel):
    items: list[RecommendationItem]
    total: int


class RecommendationRefreshResponse(BaseModel):
    created: int
    items: list[RecommendationItem]


class RecommendationUpdateRequest(BaseModel):
    completed: bool

