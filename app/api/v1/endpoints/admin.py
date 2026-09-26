# pyrefly: ignore [missing-import]
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
# pyrefly: ignore [missing-import]
from sqlalchemy.ext.asyncio import AsyncSession
# pyrefly: ignore [missing-import]
from sqlalchemy import select
# pyrefly: ignore [missing-import]
from sqlalchemy import func, desc, or_, text
from datetime import datetime, timedelta
from typing import Optional, List

# pyrefly: ignore [missing-import]
from sqlalchemy.orm import selectinload

from app.api.deps import get_db, get_current_admin
from app.db.models import OTP, AppSettings, QuizAttempt, User, ActivityLog, DailySession, UserLessonProgress, UserProfile, UserProgress, Lesson, LearningPath, QuizSet, DailyFeed, UserNewsInteraction, WeeklyActivity, Notification


from app.schemas.admin import (
    AdminDashboardResponse, AdminProfileResponse, AdminProfileUpdate,
    AdminUserDetailResponse, AdminUserDetailStats, AdminUserListItem,
    AdminUserListResponse, AppSettingsSchema, AppSettingsUpdate,
    KpiCard, ChartDataPoint, ActivityLogItem, SuspendUserRequest,
    CurriculumListResponse, CurriculumPathItem, CurriculumLessonItem,
    LessonCreateRequest, LessonUpdateRequest,
    LessonBulkDeleteRequest, LessonBulkDeleteResponse,
    LessonReorderRequest,
    PathBulkDeleteRequest, PathBulkDeleteResponse,
    PathCreateRequest, PathUpdateRequest, CurriculumImportResponse,
)
from app.schemas.response import ImageUploadResponse, MessageResponse, SuspendActionResponse
from app.services.email_service import generate_and_save_otp, send_otp_email
import os
import shutil
# pyrefly: ignore [missing-import]
from fastapi import UploadFile, File
from app.core.security import get_password_hash, verify_password
from app.services.user_service import validate_image_file

from app.core.config import settings
import re
import uuid

router = APIRouter(prefix="/admin", tags=["Admin Panel"])

# Helper function for Time Ago
def get_time_ago(log_time: datetime) -> str:
    diff = datetime.utcnow() - log_time
    minutes = diff.total_seconds() // 60
    if minutes < 60:
        return f"{int(minutes)}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{int(hours)}h ago"
    return f"{int(hours // 24)}d ago"

@router.get("/dashboard/overview", response_model=AdminDashboardResponse)
async def get_dashboard_overview(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin) # <--- Secured by Admin Dep
):
    now = datetime.utcnow()
    one_week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0)

    # --- 1. CALCULATE KPIs ---
    
    # Total Users
    total_users = await db.execute(select(func.count(User.id)))
    total_val = total_users.scalar()
    
    # New Users (This month)
    new_users_res = await db.execute(select(func.count(User.id)).filter(User.created_at >= start_of_month))
    new_val = new_users_res.scalar()

    # Active Users (Last 7 days)
    active_users_res = await db.execute(select(func.count(User.id)).filter(User.last_active_at >= one_week_ago))
    active_val = active_users_res.scalar() or 0

    # Active Users Previous Week (Between 14 days ago and 7 days ago) using two_weeks_ago
    prev_active_res = await db.execute(
        select(func.count(User.id)).filter(
            User.last_active_at >= two_weeks_ago,
            User.last_active_at < one_week_ago
        )
    )
    prev_active_val = prev_active_res.scalar() or 0

    # Calculate active users week-over-week trend percentage & type
    if prev_active_val > 0:
        active_trend_pct = int(abs(active_val - prev_active_val) / prev_active_val * 100)
        active_trend_type = "up" if active_val >= prev_active_val else "down"
    else:
        active_trend_pct = 100 if active_val > 0 else 0
        active_trend_type = "up"

    # Suspended Users
    susp_users_res = await db.execute(select(func.count(User.id)).filter(User.is_suspended == True))
    susp_val = susp_users_res.scalar() or 0

    # --- 2. CALCULATE CHART DATA (Last 7 Days) ---
    
    # This generates a list of the last 7 days: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    # And queries the DB for counts on those specific dates.
    reg_chart = []
    dau_chart = []
    
    for i in range(6, -1, -1):
        target_date = now - timedelta(days=i)
        day_name = target_date.strftime("%a") # "Mon", "Tue"
        
        # Count Registrations for this specific day
        reg_count = await db.execute(
            select(func.count(User.id)).filter(func.date(User.created_at) == target_date.date())
        )
        reg_chart.append(ChartDataPoint(day=day_name, count=reg_count.scalar() or 0))
        
        # Count Active Users for this specific day (Using DailySession as a proxy for activity)
        dau_count = await db.execute(
            select(func.count(func.distinct(DailySession.user_id))).filter(func.date(DailySession.date) == target_date.date())
        )
        dau_chart.append(ChartDataPoint(day=day_name, count=dau_count.scalar() or 0))

    # --- 3. FETCH RECENT ACTIVITY LOGS ---
    logs_res = await db.execute(select(ActivityLog).order_by(desc(ActivityLog.created_at)).limit(5))
    recent_logs = logs_res.scalars().all()
    
    formatted_logs = [
        ActivityLogItem(
            id=log.id,
            action_type=log.action_type,
            description=log.description,
            time_ago=get_time_ago(log.created_at)
        ) for log in recent_logs
    ]

    # --- 4. RETURN FULL RESPONSE ---
    return AdminDashboardResponse(
        total_users=KpiCard(value=total_val or 0, trend_percentage=12, trend_type="up", trend_text="this week"),
        active_users=KpiCard(value=active_val, trend_percentage=active_trend_pct, trend_type=active_trend_type, trend_text="vs last week"),
        new_users=KpiCard(value=new_val or 0, trend_percentage=22, trend_type="up", trend_text="vs last month"),
        suspended_users=KpiCard(value=susp_val, trend_percentage=0, trend_type="down", trend_text="this week"),
        user_registrations_chart=reg_chart,
        daily_active_users_chart=dau_chart,
        recent_activity=formatted_logs
    )





def format_interests(profile: UserProfile | None) -> str:
    if not profile or not profile.interests:
        return "N/A"
    if isinstance(profile.interests, list):
        return ", ".join([str(i) for i in profile.interests]) if len(profile.interests) > 0 else "N/A"
    return str(profile.interests)


# 1. GET ALL USERS (List View - Non-Admin Accounts)
@router.get("/users", response_model=AdminUserListResponse)
async def get_all_users(
    search: str = "",
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin)
):
    # Exclude admins/superusers from normal user list
    query = select(User).options(selectinload(User.profile)).filter(
        User.is_superuser == False,
        or_(User.role == None, User.role != "admin")
    ).order_by(User.created_at.desc())
    
    count_query = select(func.count(User.id)).filter(
        User.is_superuser == False,
        or_(User.role == None, User.role != "admin")
    )

    # Apply Search Filter
    if search:
        search_filter = or_(User.full_name.ilike(f"%{search}%"), User.email.ilike(f"%{search}%"))
        query = query.filter(search_filter)
        count_query = count_query.filter(search_filter)

    result = await db.execute(query.offset(skip).limit(limit))
    users = result.scalars().all()

    # Total count for pagination
    total_res = await db.execute(count_query)
    total_accounts = total_res.scalar() or 0

    formatted_users = []
    for u in users:
        # Default fallbacks if profile missing
        level = u.profile.ai_level if u.profile else "N/A"
        interest = format_interests(u.profile)
        status = "Suspended" if u.is_suspended else "Active"

        formatted_users.append(AdminUserListItem(
            id=u.id,
            full_name=u.full_name,
            email=u.email,
            ai_level=level,
            interest=interest,
            joined_date=u.created_at.strftime("%d %b %Y"),
            status=status
        ))

    return AdminUserListResponse(total_accounts=total_accounts, users=formatted_users)



# 2. GET USER DETAILS & STATS
@router.get("/users/{user_id}", response_model=AdminUserDetailResponse)
async def get_user_details(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin)
):
    # Fetch User
    res = await db.execute(select(User).options(selectinload(User.profile)).filter(User.id == user_id))
    user = res.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Fetch User Progress for actual Streak
    prog_res = await db.execute(select(UserProgress).filter(UserProgress.user_id == user_id))
    user_prog = prog_res.scalars().first()

    today = datetime.utcnow().date()
    c_streak = 0

    if user_prog and user_prog.current_streak and user_prog.current_streak > 0:
        # Check if the streak is still active (completed today or yesterday)
        if user_prog.last_completion_date:
            last_date = user_prog.last_completion_date.date()
            if last_date >= today - timedelta(days=1):
                c_streak = user_prog.current_streak
            else:
                # If last completion was more than 1 day ago, streak is broken
                c_streak = 0
        else:
            c_streak = user_prog.current_streak

    # Fallback to WeeklyActivity if UserProgress is 0 or missing
    if c_streak == 0:
        week_start = today - timedelta(days=today.weekday())
        weekly_res = await db.execute(
            select(WeeklyActivity)
            .filter(
                WeeklyActivity.user_id == user_id,
                WeeklyActivity.week_start_date >= datetime(
                    week_start.year, week_start.month, week_start.day
                )
            )
            .order_by(WeeklyActivity.week_start_date.desc())
        )
        weekly_activity = weekly_res.scalars().first()
        days_active = weekly_activity.days_active if weekly_activity else {}
        day_order = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        
        # Check starting from today or yesterday (if today not completed yet)
        streak_start = today.weekday()
        if not days_active.get(day_order[streak_start], False):
            streak_start = streak_start - 1
            
        while streak_start >= 0 and days_active.get(day_order[streak_start], False):
            c_streak += 1
            streak_start -= 1

    streak_str = f"{c_streak} day" if c_streak == 1 else f"{c_streak} days"

    # Fetch Lessons Completed
    les_res = await db.execute(
        select(func.count(UserLessonProgress.id))
        .filter(UserLessonProgress.user_id == user_id, UserLessonProgress.status == "completed")
    )
    lessons_completed = les_res.scalar() or 0

    # Fetch Lesson estimated minutes for completed lessons
    les_time_res = await db.execute(
        select(func.coalesce(func.sum(Lesson.estimated_minutes), 0))
        .join(UserLessonProgress, UserLessonProgress.lesson_id == Lesson.id)
        .filter(UserLessonProgress.user_id == user_id, UserLessonProgress.status == "completed")
    )
    lesson_time_minutes = les_time_res.scalar() or 0

    # Fetch Quiz Stats
    quiz_res = await db.execute(
        select(QuizAttempt)
        .options(selectinload(QuizAttempt.quiz_set).selectinload(QuizSet.questions))
        .filter(QuizAttempt.user_id == user_id, QuizAttempt.status == "completed")
    )
    quizzes = quiz_res.scalars().all()
    quizzes_completed = len(quizzes)
    
    total_percentage_sum = 0
    total_quiz_seconds = 0
    for q in quizzes:
        total_qs = len(q.quiz_set.questions) if (q.quiz_set and q.quiz_set.questions) else len(q.user_answers or {})
        if total_qs > 0:
            total_percentage_sum += int(((q.score or 0) / total_qs) * 100)
        total_quiz_seconds += (q.duration_seconds or 0)

    avg_score = int(total_percentage_sum / quizzes_completed) if quizzes_completed > 0 else 0

    # Format Total Time (Lessons + Quizzes)
    total_time_seconds = (lesson_time_minutes * 60) + total_quiz_seconds
    hours, remainder = divmod(total_time_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    time_str = f"{int(hours)}h {int(minutes)}m"

    # Determine "Last Active" display
    last_active_str = "Today"
    if user.last_active_at:
        diff_days = (datetime.utcnow().date() - user.last_active_at.date()).days
        if diff_days <= 0:
            last_active_str = "Today"
        elif diff_days == 1:
            last_active_str = "1 day ago"
        else:
            last_active_str = f"{diff_days} days ago"

    return AdminUserDetailResponse(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        ai_level=user.profile.ai_level if user.profile else "N/A",
        interest=format_interests(user.profile),
        joined_date=user.created_at.strftime("%d %b %Y"),
        last_active=last_active_str,
        status="Suspended" if user.is_suspended else "Active",
        stats=AdminUserDetailStats(
            learning_streak=streak_str,
            lessons_completed=lessons_completed,
            quizzes_completed=quizzes_completed,
            avg_quiz_score=f"{avg_score}%",
            total_learning_time=time_str
        )
    )


# 3. ACTION: SUSPEND / UNSUSPEND USER
@router.patch("/users/{user_id}/suspend", response_model=SuspendActionResponse)
async def toggle_suspend_user(
    user_id: int, 
    data: SuspendUserRequest, 
    db: AsyncSession = Depends(get_db), 
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(User).filter(User.id == user_id))
    user = res.scalars().first()
    if not user: raise HTTPException(status_code=404, detail="User not found")
    if user.is_superuser: raise HTTPException(status_code=403, detail="Cannot suspend an admin")

    user.is_suspended = data.suspend
    
    # Audit Log
    action = "SUSPENDED" if data.suspend else "UNSUSPENDED"
    db.add(ActivityLog(action_type=action, description=f"{admin.full_name} {action.lower()} account for {user.full_name}"))
    
    await db.commit()
    return {"message": f"User successfully {action.lower()}."}

# 4. ACTION: SEND RESET PASSWORD EMAIL
@router.post("/users/{user_id}/reset-password", response_model=MessageResponse)
async def admin_reset_user_password(
    user_id: int, 
    background_tasks: BackgroundTasks, 
    db: AsyncSession = Depends(get_db), 
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(User).filter(User.id == user_id))
    user = res.scalars().first()
    if not user: 
        raise HTTPException(status_code=404, detail="User not found")

    target_email = user.email
    target_name = user.full_name
    admin_name = admin.full_name

    # Generate OTP (This function calls db.commit() inside, which expires 'user' and 'admin')
    otp_code = await generate_and_save_otp(db, target_email, purpose="reset_password")
    
    # Use the extracted variables safely
    background_tasks.add_task(send_otp_email, email=target_email, otp_code=otp_code, purpose="Password Reset")

    # Write to activity log safely
    db.add(ActivityLog(
        action_type="PWD_RESET_SENT", 
        description=f"{admin_name} triggered a password reset for {target_name}"
    ))
    
    await db.commit()
    return {"message": "Password reset email sent to user."}

# 5. ACTION: RESET PROGRESS
@router.post("/users/{user_id}/reset-progress", response_model=MessageResponse)
async def reset_user_progress(
    user_id: int, 
    db: AsyncSession = Depends(get_db), 
    admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(User).filter(User.id == user_id))
    user = res.scalars().first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Erase all learning history!
    await db.execute(UserLessonProgress.__table__.delete().where(UserLessonProgress.user_id == user_id))
    await db.execute(QuizAttempt.__table__.delete().where(QuizAttempt.user_id == user_id))
    
    # Reset streak and XP to 0
    prog_res = await db.execute(select(UserProgress).filter(UserProgress.user_id == user_id))
    progress = prog_res.scalars().first()
    if progress:
        progress.current_streak = 0
        progress.longest_streak = 0
        progress.current_xp = 0

    # Now 'user.full_name' works perfectly for the log
    db.add(ActivityLog(
        action_type="PROGRESS_RESET", 
        description=f"{admin.full_name} erased learning progress for {user.full_name}"
    ))
    
    await db.commit()
    return {"message": "User's progress has been permanently reset."}

# 6. ACTION: DELETE USER
@router.delete("/users/{user_id}", response_model=MessageResponse)
async def delete_user(
    user_id: int, 
    db: AsyncSession = Depends(get_db), 
    _admin: User = Depends(get_current_admin)
):
    res = await db.execute(select(User).filter(User.id == user_id))
    user = res.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_superuser:
        raise HTTPException(status_code=403, detail="Cannot delete an admin account")

    name = user.full_name
    email = user.email

    # Delete all associated user records cleanly
    await db.execute(UserProfile.__table__.delete().where(UserProfile.user_id == user_id))
    await db.execute(UserProgress.__table__.delete().where(UserProgress.user_id == user_id))
    await db.execute(UserLessonProgress.__table__.delete().where(UserLessonProgress.user_id == user_id))
    await db.execute(QuizAttempt.__table__.delete().where(QuizAttempt.user_id == user_id))
    await db.execute(DailyFeed.__table__.delete().where(DailyFeed.user_id == user_id))
    await db.execute(DailySession.__table__.delete().where(DailySession.user_id == user_id))
    await db.execute(UserNewsInteraction.__table__.delete().where(UserNewsInteraction.user_id == user_id))
    await db.execute(WeeklyActivity.__table__.delete().where(WeeklyActivity.user_id == user_id))
    await db.execute(Notification.__table__.delete().where(Notification.user_id == user_id))
    await db.execute(OTP.__table__.delete().where(OTP.email == email))

    # Finally, delete user account
    await db.delete(user)

    db.add(ActivityLog(action_type="USER_DELETED", description=f"Permanently deleted user account for {name} ({email})"))
    await db.commit()

    return {"message": "User account permanently deleted."}


#  ADMIN PROFILE
@router.get("/profile", response_model=AdminProfileResponse)
async def get_admin_profile(admin: User = Depends(get_current_admin)):
    """Fetch current admin details for the settings page."""
    image_url = admin.profile_image
    if image_url and not image_url.startswith("http"):
        image_url = f"{settings.BASE_URL.rstrip('/')}{image_url}"
        
    return {
        "full_name": admin.full_name,
        "email": admin.email,
        "profile_image": image_url
    }

@router.patch("/profile", response_model=AdminProfileResponse)
async def update_admin_profile(
    data: AdminProfileUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Update Admin Name, Email, or Password."""
    
    # Check if they are trying to change to an email that already exists
    if data.email and data.email != admin.email:
        email_check = await db.execute(select(User).filter(User.email == data.email))
        if email_check.scalars().first():
            raise HTTPException(status_code=400, detail="Email is already in use.")
        admin.email = data.email

    if data.full_name:
        admin.full_name = data.full_name
        
    if data.new_password:
        if not data.current_password:
            raise HTTPException(status_code=400, detail="Current password is required to change your password.")
        if not verify_password(data.current_password, admin.hashed_password):
            raise HTTPException(status_code=400, detail="Incorrect current password.")
        if len(data.new_password) < 6:
            raise HTTPException(status_code=400, detail="New password must be at least 6 characters long.")
        admin.hashed_password = get_password_hash(data.new_password)
        
    await db.commit()
    await db.refresh(admin)
    
    image_url = admin.profile_image
    if image_url and not image_url.startswith("http"):
        image_url = f"{settings.BASE_URL.rstrip('/')}{image_url}"
        
    return {
        "full_name": admin.full_name,
        "email": admin.email,
        "profile_image": image_url
    }

@router.post("/profile/upload-image", response_model=ImageUploadResponse)
async def upload_admin_image(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Upload a new profile picture for the Admin."""
    validate_image_file(file)

    UPLOAD_DIR = "uploads/profiles"
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # Remove old admin profile files so the browser does not keep showing a cached image.
    for existing in os.listdir(UPLOAD_DIR):
        if existing.startswith(f"admin_{admin.id}.") or existing.startswith(f"admin_{admin.id}_"):
            try:
                os.remove(os.path.join(UPLOAD_DIR, existing))
            except OSError:
                pass

    file_extension = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "jpg"
    import time
    timestamp = int(time.time())
    unique_name = f"admin_{admin.id}_{timestamp}.{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    file.file.seek(0)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    relative_path = f"/static/profiles/{unique_name}"
    admin.profile_image = relative_path

    await db.commit()
    await db.refresh(admin)

    full_url = f"{settings.BASE_URL.rstrip('/')}{relative_path}"
    return {"image_url": full_url}

# APP SETTINGS
@router.get("/app-settings", response_model=AppSettingsSchema)
async def get_app_settings(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin)
):
    """Fetch global app configurations."""
    res = await db.execute(select(AppSettings).filter(AppSettings.id == 1))
    app_config = res.scalars().first()
    
    if not app_config:
        # Create default settings if it doesn't exist yet
        app_config = AppSettings(id=1)
        db.add(app_config)
        await db.commit()
        await db.refresh(app_config)
        
    return app_config

@router.patch("/app-settings", response_model=AppSettingsSchema)
async def update_app_settings(
    data: AppSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Update global App Configurations."""
    res = await db.execute(select(AppSettings).filter(AppSettings.id == 1))
    app_config = res.scalars().first()
    
    if not app_config:
        app_config = AppSettings(id=1)
        db.add(app_config)

    # Update only provided fields
    if data.support_email is not None:
        app_config.support_email = data.support_email
    if data.privacy_policy is not None:
        app_config.privacy_policy = data.privacy_policy
    if data.terms_conditions is not None:
        app_config.terms_conditions = data.terms_conditions
    if data.account_deletion_policy is not None:
        app_config.account_deletion_policy = data.account_deletion_policy

    # Log action to ActivityLog
    db.add(ActivityLog(
        action_type="SETTINGS_UPDATED", 
        description=f"{admin.full_name} updated the global App Settings."
    ))

    await db.commit()
    await db.refresh(app_config)
    
    return app_config


# ── CURRICULUM MANAGEMENT ──────────────────────────────────────────────────

# Excel blocks are the authoritative curriculum; keep them FIRST regardless of
# id ordering so admin-created blocks appear after the predefined content.
_EXCEL_SLUG_PREFIX = "excel-block-"


def _serialize_lesson(
    l: Lesson,
    *,
    include_cards: bool,
) -> CurriculumLessonItem:
    cards = l.cards_data if isinstance(l.cards_data, list) else []
    return CurriculumLessonItem(
        lesson_id=l.id,
        path_id=l.path_id,
        sequence_order=l.sequence_order,
        title=l.title,
        description=l.description,
        learning_goal=l.learning_goal,
        estimated_minutes=l.estimated_minutes or 5,
        cards_data=cards if include_cards else [],
        card_count=len(cards),
    )


def _serialize_path(
    p: LearningPath,
    *,
    include_cards: bool,
) -> CurriculumPathItem:
    sorted_lessons = sorted(p.lessons or [], key=lambda l: l.sequence_order)
    lesson_items = [
        _serialize_lesson(l, include_cards=include_cards) for l in sorted_lessons
    ]
    return CurriculumPathItem(
        path_id=p.id,
        title=p.title,
        description=p.description,
        level=p.level or "Beginner",
        total_lessons=len(lesson_items),
        total_minutes=sum(l.estimated_minutes or 5 for l in sorted_lessons),
        curriculum_slug=p.curriculum_slug,
        lessons=lesson_items,
    )


def _path_sort_key(p: LearningPath):
    """Excel blocks first (block-number order), then admin-created blocks."""
    slug = p.curriculum_slug or ""
    if slug.startswith(_EXCEL_SLUG_PREFIX):
        try:
            return (0, int(slug[len(_EXCEL_SLUG_PREFIX):]), p.id)
        except ValueError:
            return (0, 9999, p.id)
    return (1, 0, p.id)


@router.get("/curriculum", response_model=CurriculumListResponse)
async def get_curriculum(
    db: AsyncSession = Depends(get_db),
    level: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    include_cards: bool = Query(False, description="Include full card bodies (heavy)"),
    page: int = Query(1, ge=1, description="1-based page number"),
    page_size: int = Query(0, ge=0, description="Blocks per page; 0 = all"),
    _admin: User = Depends(get_current_admin),
):
    """
    List curriculum LearningPaths with their Lessons.

    By default the response is LIGHT: cards_data is empty and only card_count
    is returned (the full 98-lesson payload with card text is ~1MB). Pass
    include_cards=true only when card bodies are actually needed.

    Filters: level (Beginner/Intermediate/Advanced), search (lesson title /
    sequence number). Excel blocks are always listed first.
    """
    paths_res = await db.execute(
        select(LearningPath)
        .options(selectinload(LearningPath.lessons))
        .filter(LearningPath.source_type == "curriculum")
    )
    paths = list(paths_res.scalars().all())
    paths.sort(key=_path_sort_key)

    if level and level != "All":
        paths = [p for p in paths if (p.level or "Beginner") == level]

    search_q = (search or "").strip().lower()

    # Apply the search filter first so totals reflect EVERYTHING that matches.
    filtered = []
    for p in paths:
        sorted_lessons = sorted(p.lessons or [], key=lambda l: l.sequence_order)
        if search_q:
            sorted_lessons = [
                l for l in sorted_lessons
                if search_q in (l.title or "").lower()
                or search_q == str(l.sequence_order)
                or search_q in (l.learning_goal or "").lower()
            ]
            if not sorted_lessons and search_q not in (p.title or "").lower():
                continue
        filtered.append((p, sorted_lessons))

    total_paths = len(filtered)
    total_lessons = sum(len(ls) for _, ls in filtered)

    # Dynamic server-side pagination over the BLOCKS (page_size 0 = all).
    if page_size and page_size > 0:
        total_pages = (total_paths + page_size - 1) // page_size
        page = min(page, max(1, total_pages))
        offset = (page - 1) * page_size
        page_slice = filtered[offset: offset + page_size]
    else:
        total_pages = 1
        page = 1
        page_slice = filtered

    path_items = []
    for p, sorted_lessons in page_slice:
        lesson_items = [
            _serialize_lesson(l, include_cards=include_cards) for l in sorted_lessons
        ]
        path_items.append(
            CurriculumPathItem(
                path_id=p.id,
                title=p.title,
                description=p.description,
                level=p.level or "Beginner",
                total_lessons=len(lesson_items),
                total_minutes=sum(l.estimated_minutes or 5 for l in sorted_lessons),
                curriculum_slug=p.curriculum_slug,
                lessons=lesson_items,
            )
        )

    return CurriculumListResponse(
        total_paths=total_paths,
        total_lessons=total_lessons,
        paths=path_items,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/curriculum/lessons/{lesson_id}", response_model=CurriculumLessonItem)
async def get_curriculum_lesson_detail(
    lesson_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """Full single lesson (with card bodies) for the admin card editor."""
    res = await db.execute(select(Lesson).filter(Lesson.id == lesson_id))
    lesson = res.scalars().first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return _serialize_lesson(lesson, include_cards=True)


@router.post("/curriculum/lessons/delete-bulk", response_model=LessonBulkDeleteResponse)
async def bulk_delete_curriculum_lessons(
    data: LessonBulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """
    Delete many lessons at once. Progress rows are removed and each affected
    path's remaining lessons are re-sequenced 1..N (no gaps for the app's
    unlock logic). Path totals are recomputed.
    """
    if not data.lesson_ids:
        raise HTTPException(status_code=400, detail="lesson_ids must not be empty")

    res = await db.execute(select(Lesson).filter(Lesson.id.in_(data.lesson_ids)))
    lessons = res.scalars().all()
    if not lessons:
        raise HTTPException(status_code=404, detail="No matching lessons found")

    affected_path_ids = {l.path_id for l in lessons if l.path_id}

    await db.execute(
        UserLessonProgress.__table__.delete().where(
            UserLessonProgress.lesson_id.in_(data.lesson_ids)
        )
    )
    for l in lessons:
        await db.delete(l)

    # Re-sequence remaining lessons per affected path + recompute totals.
    for path_id in affected_path_ids:
        rem_res = await db.execute(
            select(Lesson)
            .filter(Lesson.path_id == path_id)
            .order_by(Lesson.sequence_order)
        )
        remaining = list(rem_res.scalars().all())
        for idx, les in enumerate(remaining, start=1):
            les.sequence_order = idx
        path_res = await db.execute(
            select(LearningPath).filter(LearningPath.id == path_id)
        )
        path = path_res.scalars().first()
        if path:
            path.total_lessons = len(remaining)
            path.total_minutes = sum(l.estimated_minutes or 5 for l in remaining)

    db.add(ActivityLog(
        action_type="CURRICULUM_LESSON_BULK_DELETED",
        description=(
            f"{admin.full_name} deleted {len(lessons)} lessons "
            f"(ids: {data.lesson_ids[:20]})"
        )
    ))
    await db.commit()

    return LessonBulkDeleteResponse(
        message=f"Deleted {len(lessons)} lesson(s).",
        deleted_count=len(lessons),
    )


@router.post("/curriculum/upload-excel", response_model=CurriculumImportResponse)
async def upload_excel_curriculum(
    files: List[UploadFile] = File(..., description="One or more .xlsx curriculum files"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """
    Upload one or more Excel curriculum files (same 11-column layout as the
    original TodAI_Lessons_1-98 Optimized.xlsx) and upsert their blocks and
    lessons. Blocks are matched by block number (slug excel-block-{n}) and
    lessons by lesson number, so re-uploading an updated file refreshes the
    existing content instead of duplicating it.
    """
    from app.services.excel_import_service import (
        parse_uploaded_workbook,
        upsert_lessons,
    )
    from app.db.session import SessionLocal

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    all_lessons = []
    file_summaries = []
    for f in files:
        content = await f.read()
        if not content:
            raise HTTPException(status_code=400, detail=f"File '{f.filename}' is empty.")
        if f.filename and not f.filename.lower().endswith((".xlsx", ".xlsm")):
            raise HTTPException(
                status_code=400,
                detail=f"File '{f.filename}' is not an .xlsx workbook.",
            )
        try:
            parsed = parse_uploaded_workbook(content)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        all_lessons.extend(parsed)
        file_summaries.append(f"{f.filename}: {len(parsed)} lessons")

    if not all_lessons:
        raise HTTPException(status_code=422, detail="No lesson rows found in the uploaded files.")

    # Upsert in its own session (mirrors import-excel behavior).
    async with SessionLocal() as import_db:
        summary = await upsert_lessons(import_db, all_lessons)
        await import_db.commit()

    db.add(ActivityLog(
        action_type="CURRICULUM_EXCEL_UPLOADED",
        description=(
            f"{admin.full_name} uploaded {len(files)} Excel file(s) — "
            f"{'; '.join(file_summaries)} — "
            f"blocks: {summary['blocks']}, lessons upserted: {summary['lessons_upserted']}"
        )
    ))
    await db.commit()

    return CurriculumImportResponse(
        message=(
            f"Imported {len(files)} file(s): {summary['blocks']} block(s), "
            f"{summary['lessons_upserted']} lesson(s) upserted."
        ),
        paths_upserted=summary["paths_upserted"] or summary["blocks"],
        lessons_upserted=summary["lessons_upserted"],
    )


@router.post("/curriculum/import-excel", response_model=CurriculumImportResponse)
async def import_excel_curriculum(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """
    Re-import / refresh the curriculum from the Excel file.
    This is idempotent — existing paths/lessons are updated, not duplicated.
    """
    from app.db.seed_excel_curriculum import seed_excel_learning_paths, parse_excel_curriculum
    from app.db.session import SessionLocal

    # Count before
    before_paths_res = await db.execute(
        select(func.count(LearningPath.id)).filter(LearningPath.source_type == "curriculum")
    )
    before_lessons_res = await db.execute(
        select(func.count(Lesson.id))
        .join(LearningPath, Lesson.path_id == LearningPath.id)
        .filter(LearningPath.source_type == "curriculum")
    )
    before_paths = before_paths_res.scalar() or 0
    before_lessons = before_lessons_res.scalar() or 0

    await seed_excel_learning_paths(SessionLocal)

    # Count after (re-query in same session after commit)
    after_paths_res = await db.execute(
        select(func.count(LearningPath.id)).filter(LearningPath.source_type == "curriculum")
    )
    after_lessons_res = await db.execute(
        select(func.count(Lesson.id))
        .join(LearningPath, Lesson.path_id == LearningPath.id)
        .filter(LearningPath.source_type == "curriculum")
    )
    after_paths = after_paths_res.scalar() or 0
    after_lessons = after_lessons_res.scalar() or 0

    db.add(ActivityLog(
        action_type="CURRICULUM_IMPORT",
        description=f"{admin.full_name} re-imported curriculum from Excel. "
                    f"Paths: {before_paths}→{after_paths}, Lessons: {before_lessons}→{after_lessons}"
    ))
    await db.commit()

    return CurriculumImportResponse(
        message="Curriculum successfully imported from Excel.",
        paths_upserted=after_paths,
        lessons_upserted=after_lessons,
    )


@router.post("/curriculum/paths", response_model=CurriculumPathItem)
async def create_curriculum_path(
    data: PathCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Create a new curriculum learning path (block)."""
    # Give the new block a unique slug so the user app's Learning Feed picks
    # it up: /learn/dashboard only lists paths with curriculum_slug set.
    base_slug = re.sub(r"[^a-z0-9]+", "-", (data.title or "block").lower()).strip("-") or "block"
    slug = base_slug
    suffix = 1
    while True:
        dup_res = await db.execute(
            select(LearningPath).filter(LearningPath.curriculum_slug == slug)
        )
        if not dup_res.scalars().first():
            break
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    path = LearningPath(
        title=data.title,
        description=data.description or "",
        level=data.level,
        total_lessons=0,
        total_minutes=0,
        source_type="curriculum",
        curriculum_slug=slug,
    )
    db.add(path)
    await db.commit()
    await db.refresh(path)

    db.add(ActivityLog(
        action_type="CURRICULUM_PATH_CREATED",
        description=f"{admin.full_name} created curriculum path: {data.title}"
    ))
    await db.commit()

    return CurriculumPathItem(
        path_id=path.id, title=path.title, description=path.description,
        level=path.level, total_lessons=0, total_minutes=0,
        curriculum_slug=path.curriculum_slug, lessons=[],
    )


@router.patch("/curriculum/paths/{path_id}", response_model=CurriculumPathItem)
async def update_curriculum_path(
    path_id: int,
    data: PathUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Update a curriculum path's title, description, or level."""
    res = await db.execute(
        select(LearningPath).options(selectinload(LearningPath.lessons)).filter(LearningPath.id == path_id)
    )
    path = res.scalars().first()
    if not path:
        raise HTTPException(status_code=404, detail="Path not found")

    if data.title is not None:
        path.title = data.title
    if data.description is not None:
        path.description = data.description
    if data.level is not None:
        path.level = data.level

    db.add(ActivityLog(
        action_type="CURRICULUM_PATH_UPDATED",
        description=f"{admin.full_name} updated curriculum path #{path_id}: {path.title}"
    ))
    await db.commit()
    await db.refresh(path)

    sorted_lessons = sorted(path.lessons or [], key=lambda l: l.sequence_order)
    return CurriculumPathItem(
        path_id=path.id, title=path.title, description=path.description,
        level=path.level or "Beginner",
        total_lessons=len(sorted_lessons),
        total_minutes=sum(l.estimated_minutes or 5 for l in sorted_lessons),
        curriculum_slug=path.curriculum_slug,
        lessons=[
            CurriculumLessonItem(
                lesson_id=l.id, path_id=path.id,
                sequence_order=l.sequence_order, title=l.title,
                description=l.description, learning_goal=l.learning_goal,
                estimated_minutes=l.estimated_minutes or 5,
                cards_data=l.cards_data if isinstance(l.cards_data, list) else [],
            ) for l in sorted_lessons
        ],
    )


@router.delete("/curriculum/paths/{path_id}", response_model=MessageResponse)
async def delete_curriculum_path(
    path_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Delete a curriculum path and all its lessons."""
    res = await db.execute(select(LearningPath).filter(LearningPath.id == path_id))
    path = res.scalars().first()
    if not path:
        raise HTTPException(status_code=404, detail="Path not found")

    path_title = path.title
    # Delete child lessons first
    await db.execute(Lesson.__table__.delete().where(Lesson.path_id == path_id))
    await db.execute(UserLessonProgress.__table__.delete().where(UserLessonProgress.path_id == path_id))
    await db.delete(path)

    db.add(ActivityLog(
        action_type="CURRICULUM_PATH_DELETED",
        description=f"{admin.full_name} deleted curriculum path: {path_title}"
    ))
    await db.commit()
    return {"message": f"Path '{path_title}' and all its lessons have been deleted."}


@router.post("/curriculum/paths/delete-bulk", response_model=PathBulkDeleteResponse)
async def bulk_delete_curriculum_paths(
    data: PathBulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """
    Delete many curriculum blocks at once. Every block's lessons and all
    related user lesson progress rows are removed as well.
    """
    if not data.path_ids:
        raise HTTPException(status_code=400, detail="path_ids must not be empty")

    res = await db.execute(
        select(LearningPath).filter(LearningPath.id.in_(data.path_ids))
    )
    targets = res.scalars().all()
    if not targets:
        raise HTTPException(status_code=404, detail="No matching paths found")

    deleted_lessons = 0
    titles = []
    for path in targets:
        lessons_res = await db.execute(select(Lesson).filter(Lesson.path_id == path.id))
        path_lessons = lessons_res.scalars().all()
        deleted_lessons += len(path_lessons)
        titles.append(path.title)

        await db.execute(
            UserLessonProgress.__table__.delete().where(
                UserLessonProgress.path_id == path.id
            )
        )
        await db.execute(Lesson.__table__.delete().where(Lesson.path_id == path.id))
        await db.delete(path)

    db.add(ActivityLog(
        action_type="CURRICULUM_PATH_BULK_DELETED",
        description=(
            f"{admin.full_name} deleted {len(targets)} block(s) "
            f"({deleted_lessons} lessons): {', '.join(titles[:5])}"
        )
    ))
    await db.commit()

    return PathBulkDeleteResponse(
        message=f"Deleted {len(targets)} block(s) and {deleted_lessons} lesson(s).",
        deleted_count=len(targets),
        deleted_lessons=deleted_lessons,
    )


@router.post("/curriculum/lessons", response_model=CurriculumLessonItem)
async def create_curriculum_lesson(
    data: LessonCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Add a new lesson to an existing curriculum path."""
    path_res = await db.execute(select(LearningPath).filter(LearningPath.id == data.path_id))
    path = path_res.scalars().first()
    if not path:
        raise HTTPException(status_code=404, detail="Learning path not found")

    # Shift existing lessons to make room for the new one (sequence 1..N, no gaps,
    # no duplicates — the mobile app unlocks lessons by sequence_order).
    lessons_res = await db.execute(
        select(Lesson)
        .filter(Lesson.path_id == data.path_id)
        .order_by(Lesson.sequence_order)
    )
    siblings = list(lessons_res.scalars().all())
    target_seq = max(1, data.sequence_order)
    for l in siblings:
        if l.sequence_order >= target_seq:
            l.sequence_order += 1
    if target_seq > len(siblings) + 1:
        target_seq = len(siblings) + 1  # append at the end if out of range

    lesson = Lesson(
        path_id=data.path_id,
        sequence_order=target_seq,
        title=data.title,
        description=data.description,
        learning_goal=data.learning_goal,
        estimated_minutes=data.estimated_minutes,
        cards_data=data.cards_data,
    )
    db.add(lesson)

    # Update path totals (count + real per-lesson minutes)
    path.total_lessons = len(siblings) + 1
    path.total_minutes = sum(l.estimated_minutes or 5 for l in siblings) + data.estimated_minutes

    db.add(ActivityLog(
        action_type="CURRICULUM_LESSON_CREATED",
        description=f"{admin.full_name} added lesson '{data.title}' to path #{data.path_id}"
    ))
    await db.commit()
    await db.refresh(lesson)

    return CurriculumLessonItem(
        lesson_id=lesson.id, path_id=lesson.path_id,
        sequence_order=lesson.sequence_order, title=lesson.title,
        description=lesson.description, learning_goal=lesson.learning_goal,
        estimated_minutes=lesson.estimated_minutes or 5,
        cards_data=lesson.cards_data if isinstance(lesson.cards_data, list) else [],
    )


@router.patch("/curriculum/lessons/{lesson_id}", response_model=CurriculumLessonItem)
async def update_curriculum_lesson(
    lesson_id: int,
    data: LessonUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Update a lesson's title, content cards, or sequence order."""
    res = await db.execute(select(Lesson).filter(Lesson.id == lesson_id))
    lesson = res.scalars().first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")

    if data.sequence_order is not None:
        lesson.sequence_order = data.sequence_order
    if data.title is not None:
        lesson.title = data.title
    if data.description is not None:
        lesson.description = data.description
    if data.learning_goal is not None:
        lesson.learning_goal = data.learning_goal
    if data.estimated_minutes is not None:
        lesson.estimated_minutes = data.estimated_minutes
    if data.cards_data is not None:
        lesson.cards_data = data.cards_data

    db.add(ActivityLog(
        action_type="CURRICULUM_LESSON_UPDATED",
        description=f"{admin.full_name} updated lesson #{lesson_id}: {lesson.title}"
    ))
    await db.commit()
    await db.refresh(lesson)

    return CurriculumLessonItem(
        lesson_id=lesson.id, path_id=lesson.path_id,
        sequence_order=lesson.sequence_order, title=lesson.title,
        description=lesson.description, learning_goal=lesson.learning_goal,
        estimated_minutes=lesson.estimated_minutes or 5,
        cards_data=lesson.cards_data if isinstance(lesson.cards_data, list) else [],
    )


@router.delete("/curriculum/lessons/{lesson_id}", response_model=MessageResponse)
async def delete_curriculum_lesson(
    lesson_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Delete a specific lesson. Progress records for this lesson are also removed."""
    res = await db.execute(select(Lesson).filter(Lesson.id == lesson_id))
    lesson = res.scalars().first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")

    lesson_title = lesson.title
    path_id = lesson.path_id

    # Clean up progress
    await db.execute(
        UserLessonProgress.__table__.delete().where(UserLessonProgress.lesson_id == lesson_id)
    )
    await db.delete(lesson)

    # Update path totals and re-sequence remaining lessons 1..N in their
    # current relative order (no gaps — the app unlocks by sequence_order).
    if path_id:
        remaining_res = await db.execute(
            select(Lesson)
            .filter(Lesson.path_id == path_id)
            .order_by(Lesson.sequence_order)
        )
        remaining = list(remaining_res.scalars().all())
        for idx, l in enumerate(remaining, start=1):
            l.sequence_order = idx
        path_res = await db.execute(select(LearningPath).filter(LearningPath.id == path_id))
        path = path_res.scalars().first()
        if path:
            path.total_lessons = len(remaining)
            path.total_minutes = sum(l.estimated_minutes or 5 for l in remaining)

    db.add(ActivityLog(
        action_type="CURRICULUM_LESSON_DELETED",
        description=f"{admin.full_name} deleted lesson '{lesson_title}'"
    ))
    await db.commit()
    return {"message": f"Lesson '{lesson_title}' has been deleted."}


@router.patch("/curriculum/lessons-reorder", response_model=CurriculumListResponse)
async def reorder_curriculum_lessons(
    data: LessonReorderRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """
    Atomically reorder the lessons of one path (single transaction).

    Body: { "path_id": 3, "orders": [{"lesson_id": 41, "sequence_order": 1}, ...] }
    Every lesson of the path must be included exactly once; sequence_order
    must be a permutation of 1..N. Applied in two phases so the unique-ish
    (path_id, sequence_order) pairs never collide mid-update.
    """
    path_res = await db.execute(select(LearningPath).filter(LearningPath.id == data.path_id))
    path = path_res.scalars().first()
    if not path:
        raise HTTPException(status_code=404, detail="Learning path not found")

    lessons_res = await db.execute(select(Lesson).filter(Lesson.path_id == data.path_id))
    lessons = {l.id: l for l in lessons_res.scalars().all()}

    if sorted(item.lesson_id for item in data.orders) != sorted(lessons.keys()):
        raise HTTPException(
            status_code=400,
            detail="orders must contain every lesson of the path exactly once",
        )

    requested = sorted(item.sequence_order for item in data.orders)
    if requested != list(range(1, len(data.orders) + 1)):
        raise HTTPException(
            status_code=400,
            detail="sequence_order values must be a permutation of 1..N with no gaps",
        )

    # Phase 1: move everything to negative temporary positions (no collisions).
    for item in data.orders:
        lessons[item.lesson_id].sequence_order = -item.sequence_order
    await db.flush()

    # Phase 2: set the final positive positions.
    id_to_order = {item.lesson_id: item.sequence_order for item in data.orders}
    for lesson_id, order in id_to_order.items():
        lessons[lesson_id].sequence_order = order

    db.add(ActivityLog(
        action_type="CURRICULUM_LESSONS_REORDERED",
        description=f"{admin.full_name} reordered {len(data.orders)} lessons in path #{data.path_id}: {path.title}"
    ))
    await db.commit()

    # Return the refreshed LIGHT curriculum (no card bodies) so the UI list
    # stays cheap; the editor refetches card bodies per lesson on demand.
    paths_res = await db.execute(
        select(LearningPath)
        .options(selectinload(LearningPath.lessons))
        .filter(LearningPath.source_type == "curriculum")
    )
    paths = list(paths_res.scalars().all())
    paths.sort(key=_path_sort_key)

    path_items = [_serialize_path(p, include_cards=False) for p in paths]
    total_lessons = sum(p.total_lessons for p in path_items)

    return CurriculumListResponse(
        total_paths=len(path_items),
        total_lessons=total_lessons,
        paths=path_items,
    )
