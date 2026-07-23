from pydantic import BaseModel
from typing import List, Dict, Any, Optional

# --- GET SEQUENCE SCHEMAS ---
class SequenceItem(BaseModel):
    type: str # "news" or "quiz"
    data: Any # The actual news article or quiz questions

class DailyBriefingSequenceResponse(BaseModel):
    session_id: int
    items: List[SequenceItem]

# --- POST COMPLETION SCHEMAS ---
class QuizAnswerInput(BaseModel):
    question_index: int
    selected_option_key: str

class DailyBriefingCompleteRequest(BaseModel):
    duration_seconds: int
    focus_percentage: int
    quiz_answers: List[QuizAnswerInput]

class DailyBriefingResultResponse(BaseModel):
    focus_percentage: int
    duration_formatted: str
    quiz_score: int
    quiz_total: int
    current_streak: int
    weekly_tracker: Dict[str, bool] # For the M,T,W,T,F,S,S UI