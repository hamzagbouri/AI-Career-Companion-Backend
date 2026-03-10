from pydantic import BaseModel, EmailStr


class StudentRegister(BaseModel):
    full_name: str
    email: EmailStr
    password: str


class MentorRegister(BaseModel):
    full_name: str
    email: EmailStr
    password: str


class LoginSchema(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    full_name: str
    email: EmailStr
    role: str
    status: str

    class Config:
        from_attributes = True