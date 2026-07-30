from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import distinct
from sqlalchemy.orm import selectinload
from datetime import datetime
from typing import Optional

from app.api.deps import get_db, get_current_user
from app.db.models import User, QuizSet, QuizQuestion, QuizAttempt, NewsArticle
from app.schemas.quiz_tab import (
    QuizDashboardResponse, QuizStartResponse, QuizSubmitRequest, QuizResultResponse,
    QuizSetCardSchema, ContinueQuizSchema, QuizProgressStats, ReviewItemSchema
)
from app.schemas.response import MessageResponse

router = APIRouter(prefix="/quiz-tab", tags=["Dedicated Quiz Section"])



async def _ensure_news_quiz_set(db: AsyncSession, article) -> Optional[dict]:
    """
    Find or create a real QuizSet + QuizQuestions from a NewsArticle.
    Always returns a real quiz_set_id > 0.
    """
    from app.db.models import QuizSet as QS, QuizQuestion as QQ

    headline = (article.headline or "").strip() or "this news story"
    topic = (article.tag or article.category or headline or "").strip()
    quiz_title = f"Quick Quiz: {headline[:55]}{'...' if len(headline) > 55 else ''}"
    description = f"Test your understanding of {headline} and why it matters."

    # ── Look up existing quiz set with this title ───────────────────────────
    existing_res = await db.execute(select(QS).filter(QS.title == quiz_title))
    existing_qs = existing_res.scalars().first()
    if existing_qs:
        q_count_res = await db.execute(select(QQ).filter(QQ.quiz_set_id == existing_qs.id))
        actual_q_count = len(q_count_res.scalars().all())
        return {
            "quiz_set_id": existing_qs.id,
            "title": existing_qs.title,
            "description": existing_qs.description or description,
            "category": existing_qs.category or topic,
            "level": existing_qs.level or "Beginner",
            "total_questions": actual_q_count,
            "estimated_minutes": existing_qs.estimated_minutes or 3,
            "xp_reward": existing_qs.xp_reward or 10,
        }

    # ── Build dynamic questions from article content ────────────────────────
    content_blocks = article.content_blocks or []
    takeaways: list = []
    paragraph_text: str = ""
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "")
        bcontent = block.get("content") or block.get("text") or ""
        if btype == "paragraph" and bcontent and not paragraph_text:
            paragraph_text = str(bcontent).strip()
        elif btype == "takeaways" and isinstance(bcontent, list):
            takeaways.extend([str(i).strip() for i in bcontent if i])

    questions_data = [
        {
            "question_text": f"What is the main idea behind: {headline[:60]}?",
            "options": {
                "A": f"{topic} introduces a new development or tool",
                "B": "It has no practical impact on everyday work",
                "C": "It only affects a very small niche group",
                "D": "It is purely for entertainment purposes",
            },
            "correct_option_key": "A",
        },
        {
            "question_text": f"Why should professionals pay attention to {topic}?",
            "options": {
                "A": "It may improve efficiency or understanding",
                "B": "It creates no value for most people",
                "C": "It is only relevant to scientists",
                "D": "It is too complex to be useful",
            },
            "correct_option_key": "A",
        },
    ]

    # Add a takeaway-based question if we have data
    if takeaways:
        first_takeaway = takeaways[0][:80]
        questions_data.append({
            "question_text": f"Which of the following is a key takeaway from this topic?",
            "options": {
                "A": first_takeaway,
                "B": "This topic has no real-world applications",
                "C": "Only large corporations benefit from this",
                "D": "This replaces all human judgment entirely",
            },
            "correct_option_key": "A",
        })

    # Add a paragraph-comprehension question if we have a paragraph
    if paragraph_text:
        questions_data.append({
            "question_text": f"According to the article, what best describes the situation around {topic}?",
            "options": {
                "A": paragraph_text[:80] + ("..." if len(paragraph_text) > 80 else ""),
                "B": f"{topic} is being completely abandoned",
                "C": "No significant changes are happening",
                "D": "Only negative effects are being reported",
            },
            "correct_option_key": "A",
        })

    estimated_minutes = max(2, len(questions_data))

    # ── Create QuizSet ──────────────────────────────────────────────────────
    new_qs = QS(
        category=topic,
        title=quiz_title,
        description=description,
        level="Beginner",
        total_questions=len(questions_data),
        estimated_minutes=estimated_minutes,
        xp_reward=10,
    )
    db.add(new_qs)
    await db.flush()

    for qd in questions_data:
        q = QQ(
            quiz_set_id=new_qs.id,
            question_text=qd["question_text"],
            options=qd["options"],
            correct_option_key=qd["correct_option_key"],
        )
        db.add(q)

    await db.commit()

    return {
        "quiz_set_id": new_qs.id,
        "title": quiz_title,
        "description": description,
        "category": topic,
        "level": "Beginner",
        "total_questions": len(questions_data),
        "estimated_minutes": estimated_minutes,
        "xp_reward": 10,
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

    # ── Ensure every news article has a real QuizSet + Questions ────────────
    news_quiz_contexts = []
    for article in latest_news:
        ctx = await _ensure_news_quiz_set(db, article)
        if ctx:
            news_quiz_contexts.append(ctx)

    # Fetch Quiz Sets and group by Category (now includes auto-created sets)
    query = select(QuizSet)
    if category_tab != "For You" and category_tab != "Trending":
        query = query.filter(QuizSet.category == category_tab)

    sets_res = await db.execute(query)
    quiz_sets = sets_res.scalars().all()

    # ── Continue Quiz: 3-tier priority ───────────────────────────────────────
    completed_set_ids = {a.quiz_set_id for a in all_attempts if a.status == "completed"}
    in_progress = [a for a in all_attempts if a.status == "in_progress" and a.quiz_set_id not in completed_set_ids]

    continue_quiz = None
    # Priority 1: Resume an in_progress attempt
    if in_progress:
        latest = sorted(in_progress, key=lambda x: x.started_at or datetime.min, reverse=True)[0]
        set_res = await db.execute(select(QuizSet).filter(QuizSet.id == latest.quiz_set_id))
        q_set = set_res.scalars().first()

        if q_set:
            # Get actual question count from DB
            q_count_res = await db.execute(select(QuizQuestion).filter(QuizQuestion.quiz_set_id == q_set.id))
            actual_total = len(q_count_res.scalars().all()) or q_set.total_questions
            answered_count = len(latest.user_answers or {})
            continue_quiz = ContinueQuizSchema(
                card_type="continue",
                attempt_id=latest.id,
                quiz_set_id=q_set.id,
                category=q_set.category,
                quiz_title=q_set.title,
                current_question=min(answered_count + 1, actual_total),
                total_questions=actual_total,
                progress_percentage=int((answered_count / max(1, actual_total)) * 100),
                estimated_minutes=q_set.estimated_minutes,
            )

    # Priority 2: Use first news-derived quiz set (real ID from DB)
    if not continue_quiz and news_quiz_contexts:
        ctx = news_quiz_contexts[0]
        continue_quiz = ContinueQuizSchema(
            card_type="recommended",
            quiz_set_id=ctx["quiz_set_id"],
            category=ctx["category"],
            quiz_title=ctx["title"],
            total_questions=ctx["total_questions"],
            progress_percentage=0,
            estimated_minutes=ctx["estimated_minutes"],
        )

    # Priority 3: First uncompleted set from DB
    if not continue_quiz and quiz_sets:
        uncompleted_sets = [qs for qs in quiz_sets if qs.id not in completed_set_ids]
        if uncompleted_sets:
            rec_set = uncompleted_sets[0]
            q_count_res = await db.execute(select(QuizQuestion).filter(QuizQuestion.quiz_set_id == rec_set.id))
            actual_total = len(q_count_res.scalars().all()) or rec_set.total_questions
            continue_quiz = ContinueQuizSchema(
                card_type="recommended",
                quiz_set_id=rec_set.id,
                category=rec_set.category,
                quiz_title=rec_set.title,
                total_questions=actual_total,
                progress_percentage=0,
                estimated_minutes=rec_set.estimated_minutes,
            )
        else:
            feat_set = quiz_sets[0]
            continue_quiz = ContinueQuizSchema(
                card_type="all_completed",
                quiz_set_id=feat_set.id,
                category=feat_set.category,
                quiz_title=feat_set.title,
                total_completed_sets=len(completed_set_ids),
                progress_percentage=100,
            )

    # ── Build categories dict ─────────────────────────────────────────────────
    categories_dict: dict = {}

    # "For You" tab: show all news-derived quiz sets with real IDs
    if news_quiz_contexts:
        for_you_cards = []
        for ctx in news_quiz_contexts:
            attempt_for_ctx = next(
                (a for a in all_attempts if a.quiz_set_id == ctx["quiz_set_id"]), None
            )
            if attempt_for_ctx and attempt_for_ctx.status == "completed":
                status = "completed"
                score = attempt_for_ctx.score
                last_attempt_id = attempt_for_ctx.id
            elif attempt_for_ctx:
                status = attempt_for_ctx.status
                score = attempt_for_ctx.score
                last_attempt_id = attempt_for_ctx.id
            else:
                status = "not_started"
                score = None
                last_attempt_id = None

            for_you_cards.append(QuizSetCardSchema(
                quiz_set_id=ctx["quiz_set_id"],
                title=ctx["title"],
                description=ctx["description"],
                level=ctx["level"],
                total_questions=ctx["total_questions"],
                estimated_minutes=ctx["estimated_minutes"],
                xp_reward=ctx["xp_reward"],
                status=status,
                score=score,
                last_attempt_id=last_attempt_id,
            ))
        categories_dict["For You"] = for_you_cards

    # All other sets grouped by their category
    for q_set in quiz_sets:
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

        # Get actual question count
        q_count_res = await db.execute(select(QuizQuestion).filter(QuizQuestion.quiz_set_id == q_set.id))
        actual_total = len(q_count_res.scalars().all()) or q_set.total_questions

        card = QuizSetCardSchema(
            quiz_set_id=q_set.id,
            title=q_set.title,
            description=q_set.description,
            level=q_set.level,
            total_questions=actual_total,
            estimated_minutes=q_set.estimated_minutes,
            xp_reward=q_set.xp_reward,
            status=status,
            score=score,
            last_attempt_id=last_attempt_id,
        )

        if q_set.category not in categories_dict:
            categories_dict[q_set.category] = []
        categories_dict[q_set.category].append(card)

    # Build full category list for tab bar
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
        all_categories=all_categories_list,
    )

# 2. START OR RETAKE A QUIZ (Screen 3)
@router.post("/start/{quiz_set_id}", response_model=QuizStartResponse)
async def start_quiz(
    quiz_set_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # All quiz_set_ids are now real DB IDs — no need for the quiz_set_id=0 special case

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