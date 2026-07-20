import random
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import OTP

async def generate_and_save_otp(db: AsyncSession, email: str, purpose: str) -> str:
    otp_code = str(random.randint(100000, 999999))
    expires_at = datetime.utcnow() + timedelta(minutes=10) # OTP valid for 10 mins

    new_otp = OTP(email=email, otp_code=otp_code, purpose=purpose, expires_at=expires_at)
    db.add(new_otp)
    await db.commit()
    
    return otp_code

async def send_otp_email(email: str, otp_code: str, purpose: str):
    # In production, use fastapi-mail or aiosmtplib to integrate SendGrid/AWS SES here
    print(f"--- MOCK EMAIL ---")
    print(f"To: {email}")
    print(f"Subject: Your {purpose} OTP Code")
    print(f"Code: {otp_code}")
    print(f"------------------")