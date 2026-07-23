from pydantic import BaseModel
from typing import List, Dict, Optional, Any
from datetime import datetime

# --- SCREEN 1 & 2: DASHBOARD & LIST ---
class QuizProgressStats(BaseModel):
    completed_count: int
    accuracy_percentage: int
    day_streak: int

class ContinueQuizSchema(BaseModel):
    attempt_id: int
    category: str
    quiz_title: str
    current_question: int
    total_questions: int
    progress_percentage: int

class QuizSetCardSchema(BaseModel):
    quiz_set_id: int
    title: str
    description: str
    level: str
    total_questions: int
    estimated_minutes: int
    xp_reward: int
    status: str # "not_started", "in_progress", "completed"
    score: Optional[int]
    last_attempt_id: Optional[int]

class QuizDashboardResponse(BaseModel):
    stats: QuizProgressStats
    continue_quiz: Optional[ContinueQuizSchema]
    categories: Dict[str, List[QuizSetCardSchema]] # Groups sets by Category (e.g. "Robotics")

# --- SCREEN 3: TAKE QUIZ ---
class QuizQuestionSchema(BaseModel):
    id: int
    question_text: str
    options: Dict[str, str]

class QuizStartResponse(BaseModel):
    attempt_id: int
    quiz_title: str
    total_questions: int
    questions: List[QuizQuestionSchema] # Frontend handles showing them 1 by 1

# --- SCREEN 4: SUBMIT & RESULT ---
class AnswerSubmission(BaseModel):
    question_id: int
    selected_option_key: str # "A", "B", "C", or "D"

class QuizSubmitRequest(BaseModel):
    answers: List[AnswerSubmission]
    duration_seconds: int
    focus_percentage: int

class ReviewItemSchema(BaseModel):
    question_text: str
    is_correct: bool
    user_answer: str
    correct_answer: str

class QuizResultResponse(BaseModel):
    score_percentage: int
    correct_count: int
    total_questions: int
    focus_percentage: int
    duration_formatted: str # e.g., "8:24"
    review: List[ReviewItemSchema]