from sqlalchemy import Column, Date, Integer, String, Boolean, DateTime, ForeignKey, JSON, Time, func
from sqlalchemy.orm import declarative_base, relationship
import datetime 

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False) 
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    profile_image = Column(String, nullable=True) # URL or File Path
    push_notifications = Column(Boolean, default=True)
    daily_reminder_time = Column(Time, default=datetime.time(9, 0)) 
    member_since = Column(DateTime, default=datetime.datetime.utcnow)

    profile = relationship("UserProfile", back_populates="user", uselist=False)

class OTP(Base):
    __tablename__ = "otps"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True, nullable=False)
    otp_code = Column(String, nullable=False)
    purpose = Column(String)
    expires_at = Column(DateTime, nullable=False)

class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    full_name = Column(String, nullable=True)
    difficulty_level = Column(String, default="beginner") # beginner, intermediate, advanced
    interests = Column(JSON, default=list) # Stores a list of strings e.g. ["Python", "AI", "Business"]
    
    user = relationship("User", back_populates="profile")

class DailyFeed(Base):
    __tablename__ = "daily_feeds"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, default=func.current_date(), nullable=False)
    
    news_summary = Column(String, nullable=False)
    lesson = Column(String, nullable=False)
    quiz_data = Column(JSON, nullable=False) # Stores the structured quiz array
    
    user = relationship("User")

class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    daily_feed_id = Column(Integer, ForeignKey("daily_feeds.id"), nullable=False)
    
    score = Column(Integer, nullable=False) # e.g., 2 (meaning 2 out of 3 correct)
    total_questions = Column(Integer, nullable=False)
    
    # Store what the user actually submitted to show them later if needed
    user_answers = Column(JSON, nullable=False) 
    
    attempted_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    user = relationship("User")
    daily_feed = relationship("DailyFeed")