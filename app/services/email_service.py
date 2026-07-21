from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from app.core.config import settings
from app.db.models import OTP
from datetime import datetime, timedelta
import random
from sqlalchemy.ext.asyncio import AsyncSession

# 1. Configuration for FastAPI-Mail
conf = ConnectionConfig(
    MAIL_USERNAME=settings.MAIL_USERNAME,
    MAIL_PASSWORD=settings.MAIL_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_PORT=settings.MAIL_PORT,
    MAIL_SERVER=settings.MAIL_SERVER,
    MAIL_FROM_NAME=settings.MAIL_FROM_NAME,
    MAIL_STARTTLS=True,
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True
)

async def generate_and_save_otp(db: AsyncSession, email: str, purpose: str) -> str:
    otp_code = str(random.randint(100000, 999999))
    expires_at = datetime.utcnow() + timedelta(minutes=10)

    new_otp = OTP(email=email, otp_code=otp_code, purpose=purpose, expires_at=expires_at)
    db.add(new_otp)
    await db.commit()
    return otp_code

async def send_otp_email(email: str, otp_code: str, purpose: str):
    """Sends a real HTML email to the user."""
    
    html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px;">
                <h2 style="color: #4CAF50;">AI Learning Platform</h2>
                <p>Hello,</p>
                <p>You requested a code for <strong>{purpose}</strong>.</p>
                <div style="background: #f4f4f4; padding: 10px; text-align: center; font-size: 24px; font-weight: bold; letter-spacing: 5px;">
                    {otp_code}
                </div>
                <p>This code is valid for 10 minutes. If you did not request this, please ignore this email.</p>
                <hr>
                <p style="font-size: 12px; color: #777;">Sent via AI Learning Platform Backend</p>
            </div>
        </body>
    </html>
    """

    message = MessageSchema(
        subject=f"Your OTP for {purpose}",
        recipients=[email],
        body=html,
        subtype=MessageType.html
    )

    fm = FastMail(conf)
    try:
        await fm.send_message(message)
    except Exception as e:
        # In production, log this error to Sentry or a log file
        print(f"FAILED TO SEND EMAIL: {e}")