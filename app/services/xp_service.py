import logging
from typing import Dict, Any
# pyrefly: ignore [missing-import]
from sqlalchemy.ext.asyncio import AsyncSession
# pyrefly: ignore [missing-import]
from sqlalchemy import select

from app.db.models import UserProgress

logger = logging.getLogger(__name__)

# Multi-tier Badge Configuration
BADGES_TIERS = [
    {
        "name": "AI Novice",
        "level": "Tier 1",
        "min_xp": 0,
        "icon": "✨",
        "color": "#06B6D4",  # Cyan
        "next_xp": 500,
    },
    {
        "name": "AI Explorer",
        "level": "Tier 2",
        "min_xp": 500,
        "icon": "⚡",
        "color": "#3B82F6",  # Blue
        "next_xp": 1000,
    },
    {
        "name": "AI Practitioner",
        "level": "Tier 3",
        "min_xp": 1000,
        "icon": "🥇",
        "color": "#8B5CF6",  # Purple
        "next_xp": 2000,
    },
    {
        "name": "AI Scholar",
        "level": "Tier 4",
        "min_xp": 2000,
        "icon": "🎓",
        "color": "#EC4899",  # Pink
        "next_xp": 5000,
    },
    {
        "name": "AI Innovator",
        "level": "Tier 5",
        "min_xp": 5000,
        "icon": "👑",
        "color": "#F59E0B",  # Gold
        "next_xp": 10000,
    },
    {
        "name": "AI Mastermind",
        "level": "Tier 6",
        "min_xp": 10000,
        "icon": "💎",
        "color": "#10B981",  # Emerald
        "next_xp": 50000,
    },
]


def calculate_badge(current_xp: int) -> Dict[str, Any]:
    """
    Computes tier level, badge title, icon, color, and progress to next badge.
    """
    xp = max(0, current_xp or 0)
    current_badge = BADGES_TIERS[0]
    
    for b in BADGES_TIERS:
        if xp >= b["min_xp"]:
            current_badge = b
        else:
            break

    min_xp = current_badge["min_xp"]
    next_xp = current_badge["next_xp"]
    
    if next_xp > min_xp:
        progress_pct = int(min(100, max(0, ((xp - min_xp) / (next_xp - min_xp)) * 100)))
    else:
        progress_pct = 100

    return {
        "current_xp": xp,
        "badge_name": current_badge["name"],
        "badge_level": current_badge["level"],
        "badge_icon": current_badge["icon"],
        "badge_color": current_badge["color"],
        "next_badge_xp": next_xp,
        "progress_percentage": progress_pct,
    }


async def add_user_xp(db: AsyncSession, user_id: int, xp_amount: int) -> Dict[str, Any]:
    """
    Increments a user's current_xp in UserProgress table and returns updated badge info.
    """
    if xp_amount <= 0:
        return await get_user_xp_info(db, user_id)

    res = await db.execute(select(UserProgress).filter(UserProgress.user_id == user_id))
    prog = res.scalars().first()
    
    if not prog:
        prog = UserProgress(user_id=user_id, current_xp=0, current_streak=0, longest_streak=0)
        db.add(prog)
        await db.flush()

    prog.current_xp = (prog.current_xp or 0) + xp_amount
    await db.commit()
    await db.refresh(prog)

    logger.info("[XP Service] User %s earned +%s XP (Total: %s XP)", user_id, xp_amount, prog.current_xp)
    return calculate_badge(prog.current_xp)


async def get_user_xp_info(db: AsyncSession, user_id: int) -> Dict[str, Any]:
    """
    Retrieves user's total earned XP and tier badge details.
    """
    res = await db.execute(select(UserProgress).filter(UserProgress.user_id == user_id))
    prog = res.scalars().first()
    xp_val = prog.current_xp if prog else 0
    return calculate_badge(xp_val)
