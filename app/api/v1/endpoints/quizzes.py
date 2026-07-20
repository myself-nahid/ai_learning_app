from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.deps import get_db, get_current_user
from app.db.models import User, DailyFeed, QuizAttempt
from app.schemas.quiz import QuizSubmitRequest, QuizResultResponse

router = APIRouter(prefix="/quizzes", tags=["Interactive Quizzes"])

@router.post("/{feed_id}/submit", response_model=QuizResultResponse)
async def submit_quiz(
    feed_id: int,
    submission: QuizSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # 1. Fetch the Daily Feed to get the correct answers
    feed_result = await db.execute(
        select(DailyFeed).filter(DailyFeed.id == feed_id)
    )
    feed = feed_result.scalars().first()

    if not feed:
        raise HTTPException(status_code=404, detail="Daily feed not found.")

    # 2. Check if the user already took this quiz
    attempt_result = await db.execute(
        select(QuizAttempt).filter(
            QuizAttempt.user_id == current_user.id, 
            QuizAttempt.daily_feed_id == feed_id
        )
    )
    if attempt_result.scalars().first():
        raise HTTPException(status_code=400, detail="You have already completed this quiz!")

    # 3. Grade the quiz
    score = 0
    total_questions = len(feed.quiz_data)
    user_answers_dict = {ans.question_index: ans.selected_option for ans in submission.answers}

    for index, question_data in enumerate(feed.quiz_data):
        correct_answer = question_data.get("correct_answer")
        user_choice = user_answers_dict.get(index)

        if user_choice == correct_answer:
            score += 1

    # 4. Save the attempt to the database
    new_attempt = QuizAttempt(
        user_id=current_user.id,
        daily_feed_id=feed.id,
        score=score,
        total_questions=total_questions,
        user_answers=[ans.model_dump() for ans in submission.answers]
    )
    
    db.add(new_attempt)
    await db.commit()

    # 5. Return a nice message based on score
    if score == total_questions:
        msg = "Perfect score! Outstanding job!"
    elif score > 0:
        msg = "Good effort! Keep learning."
    else:
        msg = "Better luck next time. Review the lesson and try again tomorrow!"

    return QuizResultResponse(
        score=score,
        total_questions=total_questions,
        message=msg
    )