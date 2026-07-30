from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import distinct
from sqlalchemy.orm import selectinload
from datetime import datetime

from app.api.deps import get_db, get_current_user
from app.db.models import User, QuizSet, QuizQuestion, QuizAttempt, NewsArticle
from app.schemas.quiz_tab import (
    QuizDashboardResponse, QuizStartResponse, QuizSubmitRequest, QuizResultResponse,
    QuizSetCardSchema, ContinueQuizSchema, QuizProgressStats, ReviewItemSchema
)
from app.schemas.response import MessageResponse

router = APIRouter(prefix="/quiz-tab", tags=["Dedicated Quiz Section"])


def _build_news_quiz_context(news_articles):
    if not news_articles:
        return None

    article = news_articles[0]
    headline = (article.headline or "").strip() or "this news story"
    topic = (article.tag or article.category or headline or "").strip()
    return {
        "title": f"Quick Quiz: {headline}",
        "description": f"Test your understanding of {headline} and why it matters.",
        "category": topic or "News",
        "level": "Beginner",
        "estimated_minutes": 3,
        "xp_reward": 10,
        "questions": [
            {
                "question_text": f"What is the main idea behind {headline}?",
                "options": {
                    "A": "It introduces a new tool or idea",
                    "B": "It has no practical impact",
                    "C": "It only affects a very small group",
                    "D": "It is unrelated to everyday work"
                },
                "correct_option_key": "A"
            },
            {
                "question_text": f"Why should someone care about {headline}?",
                "options": {
                    "A": "It may improve efficiency or understanding",
                    "B": "It likely creates no value",
                    "C": "It only matters for specialists",
                    "D": "It is only for entertainment"
                },
                "correct_option_key": "A"
            }
        ]
    }

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
    
    # Fetch day streak dynamically from WeeklyActivity
    from app.db.models import WeeklyActivity
    from datetime import timedelta
    today = datetime.utcnow().date()
    week_start = today - timedelta(days=today.weekday())
    wa_res = await db.execute(
        select(WeeklyActivity).filter(
            WeeklyActivity.user_id == current_user.id,
            WeeklyActivity.week_start_date >= datetime(week_start.year, week_start.month, week_start.day)
        )
    )
    wa = wa_res.scalars().first()
    day_order = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    streak_days = 0
    if wa and wa.days_active:
        today_idx = today.weekday()
        for i in range(today_idx, -1, -1):
            if wa.days_active.get(day_order[i], False):
                streak_days += 1
            else:
                break

    stats = QuizProgressStats(
        completed_count=len(completed_attempts),
        accuracy_percentage=accuracy,
        day_streak=streak_days
    )

    news_res = await db.execute(select(NewsArticle).order_by(NewsArticle.published_at.desc()).limit(3))
    latest_news = news_res.scalars().all()
    news_quiz_context = _build_news_quiz_context(latest_news)

    # Fetch Quiz Sets and group by Category
    query = select(QuizSet)
    if category_tab != "For You" and category_tab != "Trending":
        query = query.filter(QuizSet.category == category_tab)
        
    sets_res = await db.execute(query)
    quiz_sets = sets_res.scalars().all()

    # 2. Fetch "Continue Quiz" (3-tier state logic matching mockData & UI design)
    completed_set_ids = {a.quiz_set_id for a in all_attempts if a.status == "completed"}
    in_progress = [a for a in all_attempts if a.status == "in_progress" and a.quiz_set_id not in completed_set_ids]
    
    continue_quiz = None
    if in_progress:
        latest = sorted(in_progress, key=lambda x: x.started_at, reverse=True)[0]
        set_res = await db.execute(select(QuizSet).filter(QuizSet.id == latest.quiz_set_id))
        q_set = set_res.scalars().first()
        
        if q_set:
            answered_count = len(latest.user_answers or {})
            continue_quiz = ContinueQuizSchema(
                card_type="continue",
                attempt_id=latest.id,
                quiz_set_id=q_set.id,
                category=q_set.category,
                quiz_title=q_set.title,
                current_question=min(answered_count + 1, q_set.total_questions),
                total_questions=q_set.total_questions,
                progress_percentage=int((answered_count / q_set.total_questions) * 100),
                estimated_minutes=q_set.estimated_minutes
            )

    if not continue_quiz and news_quiz_context:
        continue_quiz = ContinueQuizSchema(
            card_type="recommended",
            quiz_set_id=0,
            category=news_quiz_context["category"],
            quiz_title=news_quiz_context["title"],
            total_questions=len(news_quiz_context["questions"]),
            progress_percentage=0,
            estimated_minutes=news_quiz_context["estimated_minutes"]
        )

    if not continue_quiz and len(quiz_sets) > 0:
        uncompleted_sets = [qs for qs in quiz_sets if qs.id not in completed_set_ids]
        if uncompleted_sets:
            rec_set = uncompleted_sets[0]
            continue_quiz = ContinueQuizSchema(
                card_type="recommended",
                quiz_set_id=rec_set.id,
                category=rec_set.category,
                quiz_title=rec_set.title,
                total_questions=rec_set.total_questions,
                progress_percentage=0,
                estimated_minutes=rec_set.estimated_minutes
            )
        else:
            feat_set = quiz_sets[0]
            continue_quiz = ContinueQuizSchema(
                card_type="all_completed",
                quiz_set_id=feat_set.id,
                category=feat_set.category,
                quiz_title=feat_set.title,
                total_completed_sets=len(completed_set_ids),
                progress_percentage=100
            )

    categories_dict = {}
    if news_quiz_context:
        categories_dict["For You"] = [
            QuizSetCardSchema(
                quiz_set_id=0,
                title=news_quiz_context["title"],
                description=news_quiz_context["description"],
                level=news_quiz_context["level"],
                total_questions=len(news_quiz_context["questions"]),
                estimated_minutes=news_quiz_context["estimated_minutes"],
                xp_reward=news_quiz_context["xp_reward"],
                status="not_started",
                score=None,
                last_attempt_id=None
            )
        ]

    for q_set in quiz_sets:
        # Find all attempts for this set
        attempts_for_set = [a for a in all_attempts if a.quiz_set_id == q_set.id]
        completed_att = next((a for a in attempts_for_set if a.status == "completed"), None)
        latest_att = sorted(attempts_for_set, key=lambda x: x.started_at, reverse=True)[0] if attempts_for_set else None

        if completed_att:
            status = "completed"
            score = completed_att.score
            last_attempt_id = completed_att.id
        elif latest_att:
            status = latest_att.status
            score = latest_att.score
            last_attempt_id = latest_att.id
        else:
            status = "not_started"
            score = None
            last_attempt_id = None

        card = QuizSetCardSchema(
            quiz_set_id=q_set.id, title=q_set.title, description=q_set.description,
            level=q_set.level, total_questions=q_set.total_questions,
            estimated_minutes=q_set.estimated_minutes, xp_reward=q_set.xp_reward,
            status=status, score=score, last_attempt_id=last_attempt_id
        )
        
        if q_set.category not in categories_dict:
            categories_dict[q_set.category] = []
        categories_dict[q_set.category].append(card)

    # Fetch distinct categories across the database to maintain full tab bar options
    distinct_cat_res = await db.execute(select(distinct(QuizSet.category)))
    db_categories = [c for c in distinct_cat_res.scalars().all() if c]
    
    default_tabs = ["For You", "Trending", "Robotics", "Generative AI", "Tools", "Research", "Sports", "Politics"]
    all_categories_list = ["For You"]
    for category in default_tabs:
        if category not in all_categories_list:
            all_categories_list.append(category)
    for category in db_categories:
        if category not in all_categories_list:
            all_categories_list.append(category)

    return QuizDashboardResponse(
        stats=stats,
        continue_quiz=continue_quiz,
        categories=categories_dict,
        all_categories=all_categories_list
    )

# 2. START OR RETAKE A QUIZ (Screen 3)
@router.post("/start/{quiz_set_id}", response_model=QuizStartResponse)
async def start_quiz(
    quiz_set_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if quiz_set_id == 0:
        news_res = await db.execute(select(NewsArticle).order_by(NewsArticle.published_at.desc()).limit(1))
        latest_news = news_res.scalars().first()
        news_quiz_context = _build_news_quiz_context([latest_news] if latest_news else [])
        if not news_quiz_context:
            raise HTTPException(status_code=404, detail="Quiz Set not found")

        formatted_questions = [
            {"id": idx + 1, "question_text": q["question_text"], "options": q["options"]}
            for idx, q in enumerate(news_quiz_context["questions"])
        ]
        return QuizStartResponse(
            attempt_id=0,
            quiz_title=news_quiz_context["title"],
            total_questions=len(formatted_questions),
            questions=formatted_questions
        )

    # 1. Fetch Quiz Set with questions
    qset_res = await db.execute(
        select(QuizSet)
        .options(selectinload(QuizSet.questions))
        .filter(QuizSet.id == quiz_set_id)
    )
    q_set = qset_res.scalars().first()
    
    if not q_set: 
        raise HTTPException(status_code=404, detail="Quiz Set not found")

    quiz_title = q_set.title
    formatted_questions = [
        {"id": q.id, "question_text": q.question_text, "options": q.options} 
        for q in q_set.questions
    ]

    # Abandon any previous in_progress attempts for this quiz set
    old_attempts_res = await db.execute(
        select(QuizAttempt).filter(
            QuizAttempt.user_id == current_user.id,
            QuizAttempt.quiz_set_id == quiz_set_id,
            QuizAttempt.status == "in_progress"
        )
    )
    for old_att in old_attempts_res.scalars().all():
        old_att.status = "abandoned"

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

    questions_map = {q.id: q for q in attempt.quiz_set.questions}
    
    if attempt.status == "completed":
        # Handle already completed attempt gracefully without throwing 400
        saved = attempt.user_answers or {}
        review_items = []
        for qid, q in questions_map.items():
            u_ans = saved.get(str(qid), "")
            is_cor = (u_ans == q.correct_option_key)
            review_items.append(ReviewItemSchema(
                question_text=q.question_text,
                is_correct=is_cor,
                user_answer=q.options.get(u_ans, ""),
                correct_answer=q.options.get(q.correct_option_key, "")
            ))
        mins, secs = divmod(attempt.duration_seconds or 0, 60)
        return QuizResultResponse(
            score_percentage=int(((attempt.score or 0) / (len(questions_map) or 1)) * 100),
            correct_count=attempt.score or 0,
            total_questions=len(questions_map),
            focus_percentage=attempt.focus_percentage or 100,
            duration_formatted=f"{mins}:{secs:02d}",
            review=review_items
        )

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

    # Abandon any other in_progress attempts for this quiz set
    other_in_prog = await db.execute(
        select(QuizAttempt).filter(
            QuizAttempt.user_id == current_user.id,
            QuizAttempt.quiz_set_id == attempt.quiz_set_id,
            QuizAttempt.status == "in_progress"
        )
    )
    for old_a in other_in_prog.scalars().all():
        old_a.status = "abandoned"

    # Update DailySession for /home/dashboard check_quiz
    from app.services.session_service import get_or_create_daily_session
    daily_session = await get_or_create_daily_session(db, current_user.id)
    daily_session.quiz_completed = True
    
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

@router.post("/test/seed-quiz-data", response_model=MessageResponse)
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