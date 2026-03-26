import re
from collections import Counter

from sqlalchemy.orm import Session

from app.models.cv import CV, CVAuditRecord
from app.models.exercise import Exercise, ExerciseSubmission
from app.models.recommendation import Recommendation


_RESOURCE_CATALOG: list[dict] = [
    # Python
    {
        "type": "course",
        "title": "Python for Everybody",
        "provider": "Coursera",
        "duration": "4-6 weeks",
        "rating": 4.8,
        "url": "https://www.coursera.org/specializations/python",
        "tags": ["python", "basics"],
    },
    {
        "type": "video",
        "title": "Python Full Course for Beginners",
        "provider": "freeCodeCamp",
        "duration": "4h",
        "rating": 4.9,
        "url": "https://www.youtube.com/watch?v=rfscVS0vtbw",
        "tags": ["python", "basics"],
    },
    {
        "type": "article",
        "title": "Python Lists and Dictionaries (Guide)",
        "provider": "Real Python",
        "duration": "15 min read",
        "rating": 4.8,
        "url": "https://realpython.com/python-lists-tuples/",
        "tags": ["python", "lists", "dicts"],
    },
    # JavaScript
    {
        "type": "course",
        "title": "JavaScript Algorithms and Data Structures",
        "provider": "freeCodeCamp",
        "duration": "self-paced",
        "rating": 4.8,
        "url": "https://www.freecodecamp.org/learn/javascript-algorithms-and-data-structures-v8/",
        "tags": ["javascript", "basics"],
    },
    {
        "type": "video",
        "title": "JavaScript Tutorial for Beginners",
        "provider": "Programming with Mosh",
        "duration": "1h",
        "rating": 4.7,
        "url": "https://www.youtube.com/watch?v=W6NZfCO5SIk",
        "tags": ["javascript", "basics"],
    },
    # General
    {
        "type": "article",
        "title": "Clean Code: A Handbook of Agile Software Craftsmanship (Key ideas)",
        "provider": "Summary",
        "duration": "10 min read",
        "rating": 4.7,
        "url": "https://gist.github.com/wojteklu/73c6914cc446146b8b533c0988cf8d29",
        "tags": ["clean-code", "best-practices"],
    },
]


def _tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9+# ]+", " ", text)
    parts = [p.strip() for p in text.split() if p.strip()]
    stop = {"and", "or", "the", "a", "to", "of", "in", "for", "with", "on", "your", "you", "is", "are"}
    return [p for p in parts if p not in stop and len(p) > 2]


def _top_tags_from_cv(db: Session, user_id: int) -> list[str]:
    cv = db.query(CV).filter(CV.user_id == user_id).order_by(CV.created_at.desc()).first()
    if not cv:
        return []
    audit = db.query(CVAuditRecord).filter(CVAuditRecord.cv_id == cv.id).order_by(CVAuditRecord.created_at.desc()).first()
    if not audit:
        return []
    blob = " ".join([audit.summary or "", " ".join(audit.weaknesses or []), " ".join(audit.recommendations or [])])
    tokens = _tokenize(blob)
    c = Counter(tokens)
    # Map a few common keywords to normalized tags
    mapped: list[str] = []
    for tok, _cnt in c.most_common(12):
        if tok in {"python", "django", "fastapi"}:
            mapped.append("python")
        elif tok in {"javascript", "react", "node"}:
            mapped.append("javascript")
        elif tok in {"oop", "classes", "class"}:
            mapped.append("oop")
        elif tok in {"api", "rest"}:
            mapped.append("api")
        elif tok in {"tests", "testing", "pytest", "unit"}:
            mapped.append("testing")
        elif tok in {"clean", "refactor", "readable"}:
            mapped.append("clean-code")
        else:
            mapped.append(tok)
    # unique preserve order
    seen = set()
    out = []
    for t in mapped:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:8]


def _top_tags_from_exercises(db: Session, user_id: int) -> list[str]:
    # Focus on what the student fails.
    rows = (
        db.query(Exercise.topic, Exercise.language)
        .join(ExerciseSubmission, ExerciseSubmission.exercise_id == Exercise.id)
        .filter(ExerciseSubmission.user_id == user_id, ExerciseSubmission.passed.is_(False))
        .all()
    )
    tokens: list[str] = []
    for topic, language in rows:
        tokens.extend(_tokenize(topic or ""))
        tokens.extend(_tokenize(language or ""))
    c = Counter(tokens)
    out = []
    for tok, _cnt in c.most_common(10):
        out.append(tok)
    return out[:6]


def _pick_resources(tags: list[str], limit: int = 8) -> list[dict]:
    wanted = set(tags)
    scored: list[tuple[int, dict]] = []
    for item in _RESOURCE_CATALOG:
        item_tags = set(item.get("tags") or [])
        score = len(wanted.intersection(item_tags))
        scored.append((score, item))
    scored.sort(key=lambda x: (x[0], x[1].get("rating") or 0.0), reverse=True)
    picked = []
    seen = set()
    for score, item in scored:
        if score <= 0:
            continue
        key = (item["type"], item["title"])
        if key in seen:
            continue
        seen.add(key)
        picked.append(item)
        if len(picked) >= limit:
            break
    return picked


def generate_recommendations(db: Session, user_id: int, limit: int = 10) -> list[Recommendation]:
    """
    Minimal NLP engine:
    - extracts keyword tags from latest CV audit + failed exercise topics
    - matches against a curated catalog
    - stores recommendations (dedup by title+type per user)
    """
    tags = []
    tags.extend(_top_tags_from_cv(db, user_id))
    tags.extend(_top_tags_from_exercises(db, user_id))
    # make sure we always have something
    if not tags:
        tags = ["clean-code", "best-practices"]
    # uniq preserve order
    seen = set()
    uniq = []
    for t in tags:
        if t in seen:
            continue
        seen.add(t)
        uniq.append(t)
    tags = uniq

    resources = _pick_resources(tags, limit=limit)
    created: list[Recommendation] = []
    for r in resources:
        exists = (
            db.query(Recommendation)
            .filter(
                Recommendation.user_id == user_id,
                Recommendation.type == r["type"],
                Recommendation.title == r["title"],
            )
            .first()
        )
        if exists:
            continue
        rec = Recommendation(
            user_id=user_id,
            type=r["type"],
            title=r["title"],
            provider=r.get("provider"),
            url=r.get("url"),
            duration=r.get("duration"),
            rating=r.get("rating"),
            tags=r.get("tags") or [],
            reason="Suggested based on your CV audit and exercise performance.",
            source="nlp",
            completed=False,
        )
        db.add(rec)
        created.append(rec)
    db.commit()
    for rec in created:
        db.refresh(rec)
    return created

