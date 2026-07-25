from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, desc, text
from datetime import datetime, timedelta

from app.api.deps import get_db, get_current_admin
from app.db.models import User, ActivityLog, DailySession
from app.schemas.admin import AdminDashboardResponse, KpiCard, ChartDataPoint, ActivityLogItem

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
    active_val = active_users_res.scalar()

    # Suspended Users
    susp_users_res = await db.execute(select(func.count(User.id)).filter(User.is_suspended == True))
    susp_val = susp_users_res.scalar()

    # (In a real app, you would query the previous periods to calculate the trend percentages. 
    # For this snippet, we will return calculated mock trends matching your UI).

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
        total_users=KpiCard(value=total_val, trend_percentage=12, trend_type="up", trend_text="this week"),
        active_users=KpiCard(value=active_val, trend_percentage=5, trend_type="up", trend_text="vs last week"),
        new_users=KpiCard(value=new_val, trend_percentage=22, trend_type="up", trend_text="vs last month"),
        suspended_users=KpiCard(value=susp_val, trend_percentage=3, trend_type="down", trend_text="this week"),
        user_registrations_chart=reg_chart,
        daily_active_users_chart=dau_chart,
        recent_activity=formatted_logs
    )