from sqlalchemy import Column, Integer, String, Boolean, DateTime, CheckConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import synonym
from ..core.database import Base

class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("extra_spaces_allowance >= 0", name="user_extra_spaces_nonnegative"),
        CheckConstraint("preferred_language IN ('es', 'en')", name="user_preferred_language_valid"),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    password_hash = synonym("hashed_password")
    full_name = Column(String(255), nullable=False, default="", server_default="")
    preferred_language = Column(String(5), nullable=False, default="es", server_default="es")
    extra_spaces_allowance = Column(Integer, nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)
