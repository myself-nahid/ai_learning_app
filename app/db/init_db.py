import logging
# pyrefly: ignore [missing-import]
from sqlalchemy import text
# pyrefly: ignore [missing-import]
from sqlalchemy import select
from app.db.session import SessionLocal, engine
from app.db.models import LearningPath, Lesson, QuizSet, QuizQuestion, NewsArticle


logger = logging.getLogger(__name__)


async def ensure_db_columns():
    """Ensure database tables have expected columns."""
    logger.info("Ensuring schema columns exist.")
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS publisher VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS original_url VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR DEFAULT 'user'"
        ))
    logger.info("Schema columns check complete.")


async def seed_admin_user():
    """Create default admin user from env if it doesn't already exist or update credentials."""
    from app.core.config import settings
    from app.core.security import get_password_hash, verify_password
    from app.db.models import User, UserProfile

    logger.info(f"Checking for default admin user: {settings.FIRST_SUPERUSER_EMAIL}")
    async with SessionLocal() as db:
        result = await db.execute(select(User).filter(User.email == settings.FIRST_SUPERUSER_EMAIL))
        admin_user = result.scalars().first()

        if not admin_user:
            admin_user = User(
                full_name=settings.FIRST_SUPERUSER_FULL_NAME,
                email=settings.FIRST_SUPERUSER_EMAIL,
                hashed_password=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
                is_active=True,
                is_verified=True,
                is_superuser=True,
                is_suspended=False,
                role="admin",
            )
            db.add(admin_user)
            await db.flush()  # to populate admin_user.id

            admin_profile = UserProfile(
                user_id=admin_user.id,
                interests=["General AI", "Technology"],
                ai_level="Advanced",
                primary_goal="System Administration",
            )
            db.add(admin_profile)
            await db.commit()
            logger.info(f"Default admin user created successfully: {settings.FIRST_SUPERUSER_EMAIL}")
        else:
            # Ensure full admin privileges & sync password if updated
            updated = False
            if not verify_password(settings.FIRST_SUPERUSER_PASSWORD, admin_user.hashed_password):
                admin_user.hashed_password = get_password_hash(settings.FIRST_SUPERUSER_PASSWORD)
                updated = True
            if not admin_user.is_superuser:
                admin_user.is_superuser = True
                updated = True
            if admin_user.role != "admin":
                admin_user.role = "admin"
                updated = True
            if not admin_user.is_verified:
                admin_user.is_verified = True
                updated = True
            if not admin_user.is_active:
                admin_user.is_active = True
                updated = True
            if admin_user.is_suspended:
                admin_user.is_suspended = False
                updated = True

            if updated:
                await db.commit()
                logger.info(f"Default admin user credentials/privileges updated: {settings.FIRST_SUPERUSER_EMAIL}")
            else:
                logger.info(f"Default admin user already exists with full admin access: {settings.FIRST_SUPERUSER_EMAIL}")



async def init_db():
    """
    Run schema column checks and seed initial admin data.
    """
    await ensure_db_columns()
    await seed_admin_user()
    logger.info("Database initialization check complete.")

