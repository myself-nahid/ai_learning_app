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
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    
    primary_interest = Column(String, nullable=False) 
    ai_level = Column(String, nullable=False) # Beginner, Intermediate, Advanced
    primary_goal = Column(String, nullable=True) 

    user = relationship("User", back_populates="profile")

class UserProgress(Base):
    __tablename__ = "user_progress"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    
    # Matches Vision Doc (Section 12)
    current_xp = Column(Integer, default=0)
    current_streak = Column(Integer, default=0)
    longest_streak = Column(Integer, default=0)
    last_completion_date = Column(DateTime, nullable=True)
    
    user = relationship("User")

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

# 1. News Articles (Generated daily by your Celery Worker/AI)
class NewsArticle(Base):
    __tablename__ = "news_articles"

    id = Column(Integer, primary_key=True, index=True)
    headline = Column(String, nullable=False)
    summary = Column(String, nullable=False)
    
    # Store structured content here (e.g., Key Takeaways, paragraphs, quotes)
    content_blocks = Column(JSON, nullable=False) 
    
    image_url = Column(String, nullable=True)
    tag = Column(String, nullable=False) # e.g., "Generative AI", "AI Tools"
    category = Column(String, nullable=False) # e.g., "Trending", "Research"
    
    read_time_minutes = Column(Integer, default=3)
    published_at = Column(DateTime, default=datetime.datetime.utcnow)

# 2. Track User Interactions (Bookmarks and Read status)
class UserNewsInteraction(Base):
    __tablename__ = "user_news_interactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    news_id = Column(Integer, ForeignKey("news_articles.id"), nullable=False)
    
    is_bookmarked = Column(Boolean, default=False)
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime, nullable=True)

# 3. Update the Daily Feed Tracker (The "Daily Pulse")
class DailySession(Base):
    __tablename__ = "daily_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(DateTime, default=datetime.datetime.utcnow)
    assigned_news_ids = Column(JSON, nullable=False) # List of IDs
    lesson_data = Column(JSON, nullable=True)
    news_completed = Column(Integer, default=0)
    lesson_completed = Column(Boolean, default=False)
    quiz_completed = Column(Boolean, default=False)
    is_fully_completed = Column(Boolean, default=False)

    user = relationship("User")