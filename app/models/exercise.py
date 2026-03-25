from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.sql import func
from app.database import Base


class ExerciseSet(Base):
    """A named practice pack (several exercises) generated together for a student."""

    __tablename__ = "exercise_sets"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(256), nullable=False)
    language = Column(String(32), nullable=False)
    topic = Column(String(128), nullable=True)
    difficulty = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Exercise(Base):
    """LLM-generated coding exercise, tied to a user, language, and topic."""

    __tablename__ = "exercises"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    set_id = Column(Integer, ForeignKey("exercise_sets.id", ondelete="CASCADE"), nullable=True)
    order_in_set = Column(Integer, nullable=True)
    language = Column(String(32), nullable=False)
    topic = Column(String(128), nullable=True)  # e.g. OOP, dictionaries, tuples
    title = Column(String(256), nullable=False)
    difficulty = Column(String(32), nullable=False)  # Beginner, Intermediate, Advanced
    description = Column(Text, nullable=False)
    skeleton_code = Column(Text, nullable=True)
    expected_solution = Column(Text, nullable=True)  # used for evaluation, not sent to client until after submit
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ExerciseSubmission(Base):
    """One attempt at an exercise: submitted code and AI evaluation result."""

    __tablename__ = "exercise_submissions"

    id = Column(Integer, primary_key=True)
    exercise_id = Column(Integer, ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    submitted_code = Column(Text, nullable=False)
    passed = Column(Boolean, nullable=False)
    feedback = Column(Text, nullable=True)
    correct_answer = Column(Text, nullable=True)  # shown when failed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
