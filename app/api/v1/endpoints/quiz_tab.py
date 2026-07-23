from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from datetime import datetime

from app.api.deps import get_db, get_current_user
from app.db.models import User, QuizSet, QuizQuestion, QuizAttempt
from app.schemas.quiz_tab import (
    QuizDashboardResponse, QuizStartResponse, QuizSubmitRequest, QuizResultResponse,
    QuizSetCardSchema, ContinueQuizSchema, QuizProgressStats, ReviewItemSchema
)

router = APIRouter(prefix="/quiz-tab", tags=["Dedicated Quiz Section"])

# 1. GET QUIZ DASHBOARD (Screens 1 & 2)
@router.get("/dashboard", response_model=QuizDashboardResponse)
async def get_quiz_dashboard(
    category_tab: str = "For You",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1. Fetch User Stats (Accuracy, Completed Count)
    attempts_res = await db.execute(select(QuizAttempt).filter(QuizAttempt.user_id == current_user.id))
    all_attempts = attempts_res.scalars().all()
    
    completed_attempts = [a for a in all_attempts if a.status == "completed"]
    total_correct = sum(a.score for a in completed_attempts)
    total_answered = sum(len(a.user_answers) for a in completed_attempts)
    
    accuracy = int((total_correct / total_answered) * 100) if total_answered > 0 else 0
    
    stats = QuizProgressStats(
        completed_count=len(completed_attempts),
        accuracy_percentage=accuracy,
        day_streak=5 # Mocked, reuse logic from earlier
    )

    # 2. Fetch "Continue Quiz" (Latest in_progress attempt)
    in_progress = [a for a in all_attempts if a.status == "in_progress"]
    continue_quiz = None
    if in_progress:
        latest = sorted(in_progress, key=lambda x: x.started_at, reverse=True)[0]
        # Fetch related set to get titles
        set_res = await db.execute(select(QuizSet).filter(QuizSet.id == latest.quiz_set_id))
        q_set = set_res.scalars().first()
        
        continue_quiz = ContinueQuizSchema(
            attempt_id=latest.id,
            category=q_set.category,
            quiz_title=q_set.title,
            current_question=len(latest.user_answers) + 1,
            total_questions=q_set.total_questions,
            progress_percentage=int((len(latest.user_answers) / q_set.total_questions) * 100)
        )

    # 3. Fetch Quiz Sets and group by Category
    query = select(QuizSet)
    if category_tab != "For You" and category_tab != "Trending":
        query = query.filter(QuizSet.category == category_tab)
        
    sets_res = await db.execute(query)
    quiz_sets = sets_res.scalars().all()

    categories_dict = {}
    for q_set in quiz_sets:
        # Find if user has an attempt for this set
        user_attempt = next((a for a in all_attempts if a.quiz_set_id == q_set.id), None)
        status = user_attempt.status if user_attempt else "not_started"
        score = user_attempt.score if user_attempt and status == "completed" else None
        
        card = QuizSetCardSchema(
            quiz_set_id=q_set.id, title=q_set.title, description=q_set.description,
            level=q_set.level, total_questions=q_set.total_questions,
            estimated_minutes=q_set.estimated_minutes, xp_reward=q_set.xp_reward,
            status=status, score=score, last_attempt_id=user_attempt.id if user_attempt else None
        )
        
        if q_set.category not in categories_dict:
            categories_dict[q_set.category] = []
        categories_dict[q_set.category].append(card)

    return QuizDashboardResponse(stats=stats, continue_quiz=continue_quiz, categories=categories_dict)

# 2. START OR RETAKE A QUIZ (Screen 3)
@router.post("/start/{quiz_set_id}", response_model=QuizStartResponse)
async def start_quiz(
    quiz_set_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1. Fetch Quiz Set with questions
    qset_res = await db.execute(
        select(QuizSet)
        .options(selectinload(QuizSet.questions))
        .filter(QuizSet.id == quiz_set_id)
    )
    q_set = qset_res.scalars().first()
    
    if not q_set: 
        raise HTTPException(status_code=404, detail="Quiz Set not found")

    # --- FIX START: EXTRACT DATA BEFORE COMMIT ---
    # We pull the title and format the questions now, while q_set is still "fresh"
    quiz_title = q_set.title
    formatted_questions = [
        {"id": q.id, "question_text": q.question_text, "options": q.options} 
        for q in q_set.questions
    ]
    # --- FIX END ---

    # 2. Create a NEW attempt (Allows Retaking)
    attempt = QuizAttempt(user_id=current_user.id, quiz_set_id=quiz_set_id)
    db.add(attempt)
    
    # 3. Commit to database
    await db.commit()
    await db.refresh(attempt)

    # 4. Return the safely extracted data
    return QuizStartResponse(
        attempt_id=attempt.id,
        quiz_title=quiz_title,
        total_questions=len(formatted_questions),
        questions=formatted_questions
    )

# 3. SUBMIT QUIZ & GET RESULTS (Screen 4)
@router.post("/attempts/{attempt_id}/submit", response_model=QuizResultResponse)
async def submit_quiz(
    attempt_id: int,
    data: QuizSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1. Fetch Attempt and related Questions
    att_res = await db.execute(select(QuizAttempt).options(selectinload(QuizAttempt.quiz_set).selectinload(QuizSet.questions)).filter(QuizAttempt.id == attempt_id))
    attempt = att_res.scalars().first()
    
    if not attempt or attempt.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Attempt not found")
    if attempt.status == "completed":
        raise HTTPException(status_code=400, detail="Quiz already submitted")

    questions_map = {q.id: q for q in attempt.quiz_set.questions}
    
    score = 0
    review_items = []
    saved_answers = {}

    # 2. Grade the answers
    for answer in data.answers:
        q = questions_map.get(answer.question_id)
        if not q: continue
        
        is_correct = (answer.selected_option_key == q.correct_option_key)
        if is_correct: score += 1
        
        saved_answers[str(q.id)] = answer.selected_option_key
        
        review_items.append(ReviewItemSchema(
            question_text=q.question_text,
            is_correct=is_correct,
            user_answer=q.options.get(answer.selected_option_key, ""),
            correct_answer=q.options.get(q.correct_option_key, "")
        ))

    # 3. Update Attempt Record
    attempt.status = "completed"
    attempt.completed_at = datetime.utcnow()
    attempt.score = score
    attempt.user_answers = saved_answers
    attempt.focus_percentage = data.focus_percentage
    attempt.duration_seconds = data.duration_seconds
    
    await db.commit()

    # 4. Format Duration (e.g., 504 seconds -> "8:24")
    mins, secs = divmod(data.duration_seconds, 60)
    duration_str = f"{mins}:{secs:02d}"

    return QuizResultResponse(
        score_percentage=int((score / len(questions_map)) * 100),
        correct_count=score,
        total_questions=len(questions_map),
        focus_percentage=data.focus_percentage,
        duration_formatted=duration_str,
        review=review_items
    )

@router.post("/test/seed-quiz-data")
async def seed_quiz_data(db: AsyncSession = Depends(get_db)):
    # 1. Create the Quiz Set (Matches UI Screen 2)
    q_set = QuizSet(
        category="Robotics",
        title="Robotics Fundamentals",
        description="Test your understanding of robots, automation, and intelligent machines.",
        level="Beginner",
        total_questions=2, # Using 2 questions for quick testing
        estimated_minutes=2,
        xp_reward=10
    )
    db.add(q_set)
    await db.flush()

    # 2. Create Questions (Matches UI Screen 3)
    q1 = QuizQuestion(
        quiz_set_id=q_set.id,
        question_text="Who mentioned that the meeting was postponed to Friday?",
        options={"A": "Anna", "B": "Marek", "C": "Zofia", "D": "None of them"},
        correct_option_key="C" # Zofia
    )
    q2 = QuizQuestion(
        quiz_set_id=q_set.id,
        question_text="What is the primary function of an LLM?",
        options={"A": "Storing images", "B": "Predicting text patterns", "C": "Driving cars", "D": "None of the above"},
        correct_option_key="B" # Predicting text
    )
    
    db.add_all([q1, q2])
    await db.commit()
    return {"message": "Quiz Data Seeded Successfully!"}