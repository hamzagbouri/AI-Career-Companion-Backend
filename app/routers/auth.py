from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.user import StudentRegister, MentorRegister, LoginSchema
from app.utils.security import hash_password, verify_password, create_access_token

router = APIRouter(
    prefix="/auth",
    tags=["Auth"]
)


@router.post("/register/student")
def register_student(user: StudentRegister, db: Session = Depends(get_db)):

    existing_user = db.query(User).filter(User.email == user.email).first()

    if existing_user:
        raise HTTPException(status_code=400, detail="Email already exists")

    new_user = User(
        full_name=user.full_name,
        email=user.email,
        password_hash=hash_password(user.password),
        role="student",
        status="active"
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {"message": "Student registered successfully"}


@router.post("/register/mentor")
def register_mentor(user: MentorRegister, db: Session = Depends(get_db)):

    existing_user = db.query(User).filter(User.email == user.email).first()

    if existing_user:
        raise HTTPException(status_code=400, detail="Email already exists")

    new_user = User(
        full_name=user.full_name,
        email=user.email,
        password_hash=hash_password(user.password),
        role="mentor",
        status="pending"
    )

    db.add(new_user)
    db.commit()

    return {"message": "Mentor registration submitted. Awaiting admin approval."}


@router.post("/login")
def login(data: LoginSchema, db: Session = Depends(get_db)):

    user = db.query(User).filter(User.email == data.email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if user.status == "pending":
        raise HTTPException(status_code=403, detail="Mentor awaiting approval")

    if user.status == "banned":
        raise HTTPException(status_code=403, detail="Account banned")

    token = create_access_token({"user_id": user.id, "role": user.role})

    return {"access_token": token, "token_type": "bearer"}