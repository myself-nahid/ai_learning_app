from pydantic import BaseModel, Field
from typing import List

# 1. The Structure we enforce on OpenAI
class QuizQuestion(BaseModel):
    question: str = Field(description="The quiz question text")
    options: List[str] = Field(description="Exactly 4 multiple choice options")
    correct_answer: str = Field(description="The exact string of the correct option")
    explanation: str = Field(description="Short explanation of why this is correct")

class DailyContent(BaseModel):
    news_summary: str = Field(description="A 3-paragraph curated summary of recent news based on user interests.")
    lesson: str = Field(description="A short microlearning lesson related to the news.")
    quiz: List[QuizQuestion] = Field(description="3 interactive quiz questions testing the lesson.")

# 2. Response Schema for the API
class DailyFeedResponse(BaseModel):
    id: int
    date: str
    news_summary: str
    lesson: str
    quiz_data: List[QuizQuestion]

    class Config:
        from_attributes = True