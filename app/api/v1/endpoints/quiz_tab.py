# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException
# pyrefly: ignore [missing-import]
from sqlalchemy.ext.asyncio import AsyncSession
# pyrefly: ignore [missing-import]
from sqlalchemy import select
# pyrefly: ignore [missing-import]
from sqlalchemy import distinct
# pyrefly: ignore [missing-import]
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



import random


def _shorten_quiz_str(s: str, max_len: int = 80) -> str:
    s = (s or "").strip()
    return s[:max_len] + ("..." if len(s) > max_len else "")


def _clean_quiz_category(article) -> str:
    raw = f"{article.category or ''} {article.tag or ''} {article.headline or ''}".lower()

    if any(k in raw for k in ["worm", "hack", "cyber", "security", "malicious", "vulnerability", "breach", "exploit", "copilot worm"]):
        return "Cybersecurity"
    if any(k in raw for k in ["robot", "autonomous", "drone", "humanoid", "boston dynamics"]):
        return "Robotics"
    if any(k in raw for k in ["llm", "gpt", "generative", "diffusion", "ai model", "openai", "claude", "gemini"]):
        return "Generative AI"
    if any(k in raw for k in ["tool", "app", "software", "productivity", "hardware", "platform", "device"]):
        return "Tools"
    if any(k in raw for k in ["research", "science", "paper", "study", "health", "bio", "medical", "clinical"]):
        return "Research"
    if any(k in raw for k in ["invest", "finance", "market", "stock", "fund", "equity", "rare earth", "pentagon", "capital"]):
        return "Finance"
    if any(k in raw for k in ["ceo", "cmo", "cfo", "appoint", "leadership", "executive", "hire", "leader"]):
        return "Leadership"
    if any(k in raw for k in ["strategy", "consulting", "deal", "acquisition", "merge", "corporate"]):
        return "Strategy"
    if any(k in raw for k in ["business", "revenue", "enterprise", "industry"]):
        return "Business"
    if "sport" in raw:
        return "Sports"
    if any(k in raw for k in ["politic", "government", "policy", "law"]):
        return "Politics"

    cat = (article.category or article.tag or "Generative AI").strip()
    if ":" in cat:
        cat = cat.split(":")[0].strip()
    return cat if cat else "Generative AI"


def _determine_quiz_difficulty(article) -> str:
    full_text = f"{article.headline or ''} {article.summary or ''}".lower()
    blocks = article.content_blocks or []
    for b in blocks:
        if isinstance(b, dict):
            b_text = str(b.get("content") or b.get("text") or "")
            full_text += " " + b_text.lower()

    word_count = len(full_text.split())
    tech_terms = [
        "worm", "vulnerability", "malicious", "exploit", "quantum",
        "infrastructure", "rare earth", "pentagon", "algorithm",
        "architecture", "hyperscale", "deployment"
    ]
    tech_count = sum(1 for term in tech_terms if term in full_text)

    if word_count > 320 or tech_count >= 3:
        return "Advanced"
    elif word_count > 160 or tech_count >= 1:
        return "Intermediate"
    else:
        return "Beginner"


def _build_dynamic_questions_for_article(article) -> list:
    """
    Generates 3 to 6 unique, article-specific questions with shuffled choices (A, B, C, D).
    """
    headline = (article.headline or "").strip() or "this news story"
    clean_cat = _clean_quiz_category(article)
    publisher = (article.publisher or "Industry Analysts").strip()
    summary = (article.summary or "").strip()
    art_id = getattr(article, "id", 1) or 1

    content_blocks = article.content_blocks or []
    paragraphs: list = []
    takeaways: list = []
    quotes: list = []

    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "")
        bcontent = block.get("content") or block.get("text") or ""
        if btype == "paragraph" and bcontent:
            paragraphs.append(str(bcontent).strip())
        elif btype in ["takeaways", "bullets"] and isinstance(bcontent, list):
            takeaways.extend([str(i).strip() for i in bcontent if i])
        elif btype == "quote" and bcontent:
            quotes.append(str(bcontent).strip())

    questions_raw = []

    # ── Question 1: Headline & Core Summary ──────────────────────────────────
    q1_text = f"According to {publisher}, what is the main takeaway of '{_shorten_quiz_str(headline, 50)}'?"
    correct_1 = _shorten_quiz_str(summary if summary else f"{headline} presents key developments in {clean_cat}.", 85)
    distractors_1 = [
        f"All operations across {clean_cat} have been permanently shut down",
        f"A complete repeal of all technology standards in {clean_cat} was enacted",
        f"The development was proved to have zero impact on industry practices"
    ]
    questions_raw.append((q1_text, correct_1, distractors_1))

    # ── Question 2: Key Impact / Practical Relevance ──────────────────────────
    q2_text = f"What core impact or insight does this development hold for {clean_cat}?"
    if takeaways:
        correct_2 = _shorten_quiz_str(takeaways[0], 85)
    elif len(paragraphs) > 1:
        correct_2 = _shorten_quiz_str(paragraphs[1], 85)
    else:
        correct_2 = _shorten_quiz_str(f"It introduces structural improvements and strategic value for {clean_cat}.", 85)

    distractors_2 = [
        f"It mandates a complete return to legacy paper-based workflows",
        f"It halts further investment in {clean_cat} indefinitely",
        f"It only affects isolated research laboratories with no commercial use"
    ]
    questions_raw.append((q2_text, correct_2, distractors_2))

    # ── Question 3: Primary Detail / Takeaway 1 ──────────────────────────────
    if takeaways or paragraphs:
        detail1 = takeaways[0] if takeaways else paragraphs[0]
        q3_text = f"Which detail is specifically highlighted regarding {clean_cat}?"
        correct_3 = _shorten_quiz_str(detail1, 85)
        distractors_3 = [
            f"No verified empirical data could be gathered during reporting",
            f"The initiative failed to meet any established performance metrics",
            f"Industry leaders unanimously agreed to pause activities for 5 years"
        ]
        questions_raw.append((q3_text, correct_3, distractors_3))

    # ── Question 4: Secondary Detail / Takeaway 2 ──────────────────────────────
    if len(takeaways) > 1 or len(paragraphs) > 1:
        detail2 = takeaways[1] if len(takeaways) > 1 else paragraphs[1]
        q4_text = f"What secondary key finding is described in the article?"
        correct_4 = _shorten_quiz_str(detail2, 85)
        distractors_4 = [
            f"Stakeholders confirmed zero progress was made",
            f"The deployment resulted in immediate catastrophic failure",
            f"All participants opted to revert to previous generation tools"
        ]
        questions_raw.append((q4_text, correct_4, distractors_4))

    # ── Question 5: Quote / Expert Perspective ────────────────────────────────
    if quotes or len(paragraphs) > 2:
        q5_text = f"What perspective or quote is emphasized regarding {clean_cat}?"
        q5_source = quotes[0] if quotes else paragraphs[-1]
        correct_5 = _shorten_quiz_str(q5_source, 85)
        distractors_5 = [
            "All experts recommend discontinuing adoption immediately",
            "The final consensus was that traditional methods remain vastly superior",
            "The project was abandoned due to unexpected cost overruns"
        ]
        questions_raw.append((q5_text, correct_5, distractors_5))

    labels = ["A", "B", "C", "D"]
    final_questions = []

    for item in questions_raw:
        q_text, corr_ans, dists = item[0], item[1], item[2]
        opts = [corr_ans] + dists[:3]
        random.shuffle(opts)

        options_dict = {}
        correct_key = "A"
        for i, opt_text in enumerate(opts):
            lbl = labels[i]
            options_dict[lbl] = opt_text
            if opt_text == corr_ans:
                correct_key = lbl

        final_questions.append({
            "question_text": q_text,
            "options": options_dict,
            "correct_option_key": correct_key,
        })

    return final_questions


async def _ensure_news_quiz_set(db: AsyncSession, article) -> Optional[dict]:
    """
    Find or create a real QuizSet + QuizQuestions from a NewsArticle.
    Builds dynamic, article-specific questions with dynamic difficulty, estimated minutes, and XP rewards.
    """
    from app.db.models import QuizSet as QS, QuizQuestion as QQ

    headline = (article.headline or "").strip() or "this news story"
    clean_cat = _clean_quiz_category(article)
    difficulty_level = _determine_quiz_difficulty(article)
    quiz_title = f"Quick Quiz: {headline[:55]}{'...' if len(headline) > 55 else ''}"
    description = f"Test your understanding of {headline} and why it matters."

    questions_data = _build_dynamic_questions_for_article(article)
    total_q = len(questions_data)
    estimated_minutes = max(3, int(total_q * 1.5))

    if difficulty_level == "Advanced":
        xp_reward = 20 + (total_q * 5)
    elif difficulty_level == "Intermediate":
        xp_reward = 15 + (total_q * 3)
    else:
        xp_reward = 10 + (total_q * 2)

    # ── Look up existing quiz set with this title ───────────────────────────
    existing_res = await db.execute(select(QS).filter(QS.title == quiz_title))
    existing_qs = existing_res.scalars().first()

    if existing_qs:
        # Upgrade existing QuizSet attributes to match dynamic level, category, minutes, and XP
        existing_qs.category = clean_cat
        existing_qs.level = difficulty_level
        existing_qs.estimated_minutes = estimated_minutes
        existing_qs.xp_reward = xp_reward

        q_res = await db.execute(select(QQ).filter(QQ.quiz_set_id == existing_qs.id))
        existing_questions = q_res.scalars().all()

        # Upgrade static legacy questions if questions were fewer or static
        if len(existing_questions) != total_q or all(q.correct_option_key == "A" for q in existing_questions):
            for old_q in existing_questions:
                await db.delete(old_q)
            await db.flush()

            for qd in questions_data:
                q = QQ(
                    quiz_set_id=existing_qs.id,
                    question_text=qd["question_text"],
                    options=qd["options"],
                    correct_option_key=qd["correct_option_key"],
                )
                db.add(q)
            existing_qs.total_questions = total_q

        await db.commit()

        return {
            "quiz_set_id": existing_qs.id,
            "title": existing_qs.title,
            "description": existing_qs.description or description,
            "category": clean_cat,
            "level": difficulty_level,
            "total_questions": total_q,
            "estimated_minutes": estimated_minutes,
            "xp_reward": xp_reward,
        }

    # ── Create new QuizSet with dynamic parameters ───────────────────────────
    new_qs = QS(
        category=clean_cat,
        title=quiz_title,
        description=description,
        level=difficulty_level,
        total_questions=total_q,
        estimated_minutes=estimated_minutes,
        xp_reward=xp_reward,
    )
    db.add(new_qs)
    await db.flush()
    saved_qs_id = new_qs.id

    for qd in questions_data:
        q = QQ(
            quiz_set_id=saved_qs_id,
            question_text=qd["question_text"],
            options=qd["options"],
            correct_option_key=qd["correct_option_key"],
        )
        db.add(q)

    await db.commit()

    return {
        "quiz_set_id": saved_qs_id,
        "title": quiz_title,
        "description": description,
        "category": clean_cat,
        "level": difficulty_level,
        "total_questions": total_q,
        "estimated_minutes": estimated_minutes,
        "xp_reward": xp_reward,
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
    total_correct = sum(a.score or 0 for a in completed_attempts)
    total_answered = sum(len(a.user_answers or {}) for a in completed_attempts)
    
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

    news_res = await db.execute(select(NewsArticle).order_by(NewsArticle.published_at.desc()).limit(15))
    latest_news = news_res.scalars().all()

    # ── Ensure every news article has a real QuizSet + Questions ────────────
    news_quiz_contexts = []
    seen_set_ids = set()
    for article in latest_news:
        ctx = await _ensure_news_quiz_set(db, article)
        if ctx and ctx["quiz_set_id"] not in seen_set_ids:
            seen_set_ids.add(ctx["quiz_set_id"])
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
                category=ctx["category"],
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
        latest_att = sorted(attempts_for_set, key=lambda x: x.started_at or datetime.min, reverse=True)[0] if attempts_for_set else None

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
            category=q_set.category,
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
            QuizAttempt.id != attempt.id,
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