from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from datetime import datetime

from app.api.deps import get_db, get_current_user
from app.db.models import User, Notification, NewsArticle
from app.schemas.notification import NotificationSchema
from app.core.config import settings

router = APIRouter(prefix="/notifications", tags=["Notifications"])

@router.get("", response_model=List[NotificationSchema])
async def get_notifications(
    is_read: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(Notification).filter(Notification.user_id == current_user.id)
    if is_read is not None:
        query = query.filter(Notification.is_read == is_read)
        
    query = query.order_by(Notification.created_at.desc())
    res = await db.execute(query)
    notifications = res.scalars().all()

    return notifications


@router.put("/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    res = await db.execute(
        select(Notification).filter(
            Notification.id == notification_id,
            Notification.user_id == current_user.id
        )
    )
    notif = res.scalars().first()
    if not notif:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
        
    notif.is_read = True
    await db.commit()
    return {"message": "Notification marked as read"}


@router.put("/read-all")
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    res = await db.execute(
        select(Notification).filter(
            Notification.user_id == current_user.id,
            Notification.is_read == False
        )
    )
    notifs = res.scalars().all()
    for n in notifs:
        n.is_read = True
    await db.commit()
    return {"message": "All notifications marked as read"}


@router.post("/send-test")
async def send_test_push_notification(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Sends a dynamic push notification with real database news data to the logged in user's device.
    Also creates an in-app Notification record.
    """
    if not current_user.fcm_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No push token registered for current user. Open the app to register your token."
        )

    from app.services.notification_service import send_push_notification

    # 1. Dynamically fetch top 3 news articles from database
    res_news = await db.execute(select(NewsArticle).order_by(NewsArticle.id.desc()).limit(3))
    articles = res_news.scalars().all()

    if articles:
        top_article = articles[0]
        article_ids_str = ",".join(str(a.id) for a in articles)
        total_mins = sum(a.read_time_minutes or 2 for a in articles)
        title = "Your daily AI briefing is ready."
        body = f"{len(articles)} stories. {total_mins} minutes."
        image_url = top_article.image_url or f"{settings.BASE_URL.rstrip('/')}/static/logo.png"
        first_id = str(top_article.id)
    else:
        article_ids_str = "3,4,6"
        title = "Your daily AI briefing is ready."
        body = "3 stories. 5 minutes."
        image_url = f"{settings.BASE_URL.rstrip('/')}/static/logo.png"
        first_id = "3"

    payload = {
        "briefing": "true",
        "briefingIds": article_ids_str,
        "url": f"/(protected)/news/{first_id}"
    }

    # 2. Save in-app notification DB record
    new_notif = Notification(
        user_id=current_user.id,
        title=title,
        message=body,
        is_read=False,
    )
    db.add(new_notif)
    await db.commit()

    # 3. Dispatch remote push notification
    res = await send_push_notification(
        token=current_user.fcm_token,
        title=title,
        body=body,
        data_payload=payload,
        image_url=image_url
    )

    return {
        "message": "Dynamic push notification dispatched successfully!",
        "target_token": current_user.fcm_token,
        "notification_data": {
            "title": title,
            "body": body,
            "briefing_ids": article_ids_str,
            "image_url": image_url
        },
        "response": res
    }
