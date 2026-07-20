from pydantic import BaseModel
from typing import List

class AnswerSubmit(BaseModel):
    question_index: int  # 0, 1, or 2 (for the 3 questions)
    selected_option: str # The exact string the user clicked

class QuizSubmitRequest(BaseModel):
    answers: List[AnswerSubmit]

class QuizResultResponse(BaseModel):
    score: int
    total_questions: int
    message: str