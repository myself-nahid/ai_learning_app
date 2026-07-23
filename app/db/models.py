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

# class QuizAttempt(Base):
#     __tablename__ = "quiz_attempts"

#     id = Column(Integer, primary_key=True, index=True)
#     user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
#     daily_feed_id = Column(Integer, ForeignKey("daily_feeds.id"), nullable=False)
    
#     score = Column(Integer, nullable=False) # e.g., 2 (meaning 2 out of 3 correct)
#     total_questions = Column(Integer, nullable=False)
    
#     # Store what the user actually submitted to show them later if needed
#     user_answers = Column(JSON, nullable=False) 
    
#     attempted_at = Column(DateTime, default=datetime.datetime.utcnow)

#     # Relationships
#     user = relationship("User")
#     daily_feed = relationship("DailyFeed")

# 1. News Articles (Generated daily by your Celery Worker/AI)
class NewsArticle(Base):
    __tablename__ = "news_articles"

    id = Column(Integer, primary_key=True, index=True)
    headline = Column(String, nullable=False)
    summary = Column(String, nullable=False)
    
    # Store structured blocks: [{"type": "paragraph", "text": "..."}, {"type": "takeaway", "items": [...]}]
    content_blocks = Column(JSON, nullable=False) 
    
    image_url = Column(String, nullable=True)
    tag = Column(String, nullable=False) # e.g., "Generative AI"
    category = Column(String, nullable=False) # e.g., "Tools", "Research", "Trending"
    
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

# --- COURSE CONTENT MODELS ---

class LearningPath(Base):
    __tablename__ = "learning_paths"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False) # e.g., "Generative AI Fundamentals"
    description = Column(String)
    level = Column(String) # Beginner, Intermediate
    total_lessons = Column(Integer, default=0)
    total_minutes = Column(Integer, default=0)
    image_url = Column(String)
    
    lessons = relationship("Lesson", back_populates="path", order_by="Lesson.sequence_order")

class Lesson(Base):
    __tablename__ = "lessons"
    id = Column(Integer, primary_key=True, index=True)
    path_id = Column(Integer, ForeignKey("learning_paths.id"))
    sequence_order = Column(Integer, nullable=False) # 1, 2, 3 (Used for locking/unlocking)
    
    title = Column(String, nullable=False) # e.g., "How AI Models Learn"
    description = Column(String)
    estimated_minutes = Column(Integer, default=5)
    
    # JSON array containing all cards (Text, Example, Comparison, List, Quiz)
    cards_data = Column(JSON, nullable=False) 
    
    path = relationship("LearningPath", back_populates="lessons")

# --- USER PROGRESS MODELS ---

class UserLessonProgress(Base):
    __tablename__ = "user_lesson_progress"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    lesson_id = Column(Integer, ForeignKey("lessons.id"), nullable=False)
    path_id = Column(Integer, ForeignKey("learning_paths.id"), nullable=False)
    
    cards_completed = Column(Integer, default=0)
    status = Column(String, default="locked") # 'locked', 'in_progress', 'completed'
    last_accessed = Column(DateTime, default=datetime.datetime.utcnow)

class WeeklyActivity(Base):
    """Tracks the M, T, W, T, F, S, S circles on the Learn Dashboard"""
    __tablename__ = "weekly_activities"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    week_start_date = Column(DateTime, nullable=False) # The Monday of this week
    
    # JSON object storing boolean or lesson counts per day: {"mon": true, "tue": true, ...}
    days_active = Column(JSON, default={"mon": False, "tue": False, "wed": False, "thu": False, "fri": False, "sat": False, "sun": False})
    total_lessons_this_week = Column(Integer, default=0)
    total_minutes_this_week = Column(Integer, default=0)

# --- QUIZ CONTENT MODELS ---

class QuizSet(Base):
    __tablename__ = "quiz_sets"
    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, nullable=False) # e.g., "Robotics", "Generative AI"
    title = Column(String, nullable=False) # e.g., "Sensors and Perception"
    description = Column(String)
    level = Column(String) # e.g., "Beginner"
    
    total_questions = Column(Integer, default=10)
    estimated_minutes = Column(Integer, default=5)
    xp_reward = Column(Integer, default=10)
    
    questions = relationship("QuizQuestion", back_populates="quiz_set")

class QuizQuestion(Base):
    __tablename__ = "quiz_questions"
    id = Column(Integer, primary_key=True, index=True)
    quiz_set_id = Column(Integer, ForeignKey("quiz_sets.id"))
    
    question_text = Column(String, nullable=False)
    # JSON containing {"A": "Anna", "B": "Marek", "C": "Zofia", "D": "None of them"}
    options = Column(JSON, nullable=False) 
    correct_option_key = Column(String, nullable=False) # e.g., "A"
    
    quiz_set = relationship("QuizSet", back_populates="questions")

# --- USER PROGRESS MODELS ---

class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    quiz_set_id = Column(Integer, ForeignKey("quiz_sets.id"), nullable=False)
    
    status = Column(String, default="in_progress") # "in_progress", "completed"
    current_question_index = Column(Integer, default=0) # For "Question 4 of 10"
    
    # JSON storing user's answers: {"question_id_1": "A", "question_id_2": "C"}
    user_answers = Column(JSON, default={}) 
    
    score = Column(Integer, default=0)
    focus_percentage = Column(Integer, default=100) # Provided by frontend
    duration_seconds = Column(Integer, default=0)
    
    started_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    quiz_set = relationship("QuizSet")