from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.dependencies import admin_required

router = APIRouter(
    prefix="/admin",
    tags=["Admin"]
)

@router.get("/users")
def get_users(
    db: Session = Depends(get_db),
    admin=Depends(admin_required)
):

    users = db.query(User).all()

    return users

@router.get("/mentors/pending")
def pending_mentors(
    db: Session = Depends(get_db),
    admin=Depends(admin_required)
):

    mentors = db.query(User).filter(
        User.role == "mentor",
        User.status == "pending"
    ).all()

    return mentors

@router.patch("/mentors/{mentor_id}/approve")
def approve_mentor(
    mentor_id: int,
    db: Session = Depends(get_db),
    admin=Depends(admin_required)
):

    mentor = db.query(User).filter(User.id == mentor_id).first()

    if not mentor:
        return {"error": "Mentor not found"}

    mentor.status = "active"

    db.commit()

    return {"message": "Mentor approved"}


@router.patch("/mentors/{mentor_id}/approve")
def approve_mentor(
    mentor_id: int,
    db: Session = Depends(get_db),
    admin=Depends(admin_required)
):

    mentor = db.query(User).filter(User.id == mentor_id).first()

    if not mentor:
        return {"error": "Mentor not found"}

    mentor.status = "active"

    db.commit()

    return {"message": "Mentor approved"}

@router.patch("/mentors/{mentor_id}/reject")
def reject_mentor(
    mentor_id: int,
    db: Session = Depends(get_db),
    admin=Depends(admin_required)
):

    mentor = db.query(User).filter(User.id == mentor_id).first()

    if not mentor:
        return {"error": "Mentor not found"}

    mentor.status = "rejected"

    db.commit()

    return {"message": "Mentor rejected"}

@router.patch("/users/{user_id}/ban")
def ban_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin=Depends(admin_required)
):

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        return {"error": "User not found"}

    user.status = "banned"

    db.commit()

    return {"message": "User banned"}


@router.patch("/users/{user_id}/unban")
def unban_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin=Depends(admin_required)
):

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        return {"error": "User not found"}

    user.status = "active"

    db.commit()

    return {"message": "User unbanned"}