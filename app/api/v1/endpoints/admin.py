# pyrefly: ignore [missing-import]
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
# pyrefly: ignore [missing-import]
from sqlalchemy.ext.asyncio import AsyncSession
# pyrefly: ignore [missing-import]
from sqlalchemy import select
# pyrefly: ignore [missing-import]
from sqlalchemy import func, desc, or_, text
from datetime import datetime, timedelta

# pyrefly: ignore [missing-import]
from sqlalchemy.orm import selectinload

from app.api.deps import get_db, get_current_admin
from app.db.models import OTP, AppSettings, QuizAttempt, User, ActivityLog, DailySession, UserLessonProgress, UserProfile, UserProgress, Lesson, QuizSet, DailyFeed, UserNewsInteraction, WeeklyActivity, Notification


from app.schemas.admin import AdminDashboardResponse, AdminProfileResponse, AdminProfileUpdate, AdminUserDetailResponse, AdminUserDetailStats, AdminUserListItem, AdminUserListResponse, AppSettingsSchema, AppSettingsUpdate, KpiCard, ChartDataPoint, ActivityLogItem, SuspendUserRequest
from app.schemas.response import ImageUploadResponse, MessageResponse, SuspendActionResponse
from app.services.email_service import generate_and_save_otp, send_otp_email
import os
import shutil
# pyrefly: ignore [missing-import]
from fastapi import UploadFile, File
from app.core.security import get_password_hash, verify_password

from app.core.config import settings

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

    # Fetch Progress Stats
    prog_res = await db.execute(select(UserProgress).filter(UserProgress.user_id == user_id))
    progress = prog_res.scalars().first()
    c_streak = progress.current_streak if progress else 0
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
    UPLOAD_DIR = "uploads/profiles"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    file_extension = file.filename.split(".")[-1]
    file_name = f"admin_{admin.id}.{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, file_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    relative_path = f"/static/profiles/{file_name}"
    admin.profile_image = relative_path
    
    await db.commit()
    return {"image_url": f"{settings.BASE_URL.rstrip('/')}{relative_path}"}

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