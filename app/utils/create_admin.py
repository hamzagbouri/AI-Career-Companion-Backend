from sqlalchemy.orm import Session
from app.models.user import User
from app.utils.security import hash_password


def create_default_admin(db: Session):

    admin_email = "admin@iacareer.com"

    existing_admin = db.query(User).filter(User.email == admin_email).first()

    if existing_admin:
        return

    admin = User(
        full_name="System Admin",
        email=admin_email,
        password_hash=hash_password("admin"),
        role="admin",
        status="active"
    )

    db.add(admin)
    db.commit()

    print("Default admin created: admin@iacareer.com / admin")