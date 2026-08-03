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



DEFAULT_PRIVACY_POLICY = """# Privacy Policy
*Last Updated: July 2026*

## 1. Information We Collect

### 1.1 Account Information
When you create an account, we may collect:
- Your name or username
- Email address
- Login credentials

This information is used to create and manage your account securely.

### 1.2 Listening and Learning Data
While using the app, we may collect information related to your learning progress, including:
- Completed listening sessions
- Quiz results and scores
- Focus and concentration metrics
- Listening time and activity history
- Achievement badges and progress statistics

This information is used to personalize your experience and track your improvement over time.

### 1.3 Usage Information
We may collect limited information about how you use the app, such as:
- Features and lessons accessed
- Session activity and completion status
- Device type and operating system
- App performance and crash reports

This information helps us improve the app's functionality, performance, and user experience."""

DEFAULT_TERMS_CONDITIONS = """# Terms and Conditions
*Last Updated: July 2026*

## 1. Acceptance of Terms
By creating an account and using the application, you agree to comply with these Terms and Conditions. If you do not agree with any part of these terms, please do not use the app.

## 2. User Accounts
To access certain features of the app, you may be required to create an account. You are responsible for:
- Providing accurate and up-to-date information.
- Maintaining the confidentiality of your login credentials.
- All activities that occur under your account.

You are responsible for keeping your account information secure and notifying us immediately of any unauthorized use.

## 3. Use of the Application
The app is designed to help users improve their focus, concentration, active listening, and memory skills through interactive listening exercises and quizzes.

By using the app, you agree to:
- Use the application only for lawful purposes.
- Not misuse or attempt to interfere with the app's functionality.
- Not copy, distribute, or modify any content without permission.
- Respect the intellectual property rights associated with the application."""

DEFAULT_ACCOUNT_DELETION_POLICY = """# Account Deletion Policy
*Last Updated: July 2026*

## 1. Right to Delete Your Account
You have the right to permanently delete your account and associated personal data at any time through the app settings or by contacting support.

## 2. Data Eradication
Upon processing an account deletion request:
- Your profile credentials and personal identifiers will be permanently removed.
- Your progress records, quiz attempt history, and streak statistics will be erased from active databases.
- Associated temporary security tokens and session records will be invalidated immediately.

## 3. Irreversibility
Once account deletion is confirmed, this action cannot be undone. If you wish to use the service again in the future, a new account must be created."""


async def seed_app_settings():
    """Ensure AppSettings has proper default Markdown text matching mobile app."""
    from app.db.models import AppSettings

    async with SessionLocal() as db:
        res = await db.execute(select(AppSettings).filter(AppSettings.id == 1))
        config = res.scalars().first()

        if not config:
            config = AppSettings(
                id=1,
                support_email="support@todai.app",
                privacy_policy=DEFAULT_PRIVACY_POLICY,
                terms_conditions=DEFAULT_TERMS_CONDITIONS,
                account_deletion_policy=DEFAULT_ACCOUNT_DELETION_POLICY,
            )
            db.add(config)
            await db.commit()
            logger.info("Seeded initial AppSettings with mobile app default policies.")
        else:
            # If current values are generic placeholders, update to official app markdown content
            updated = False
            if not config.privacy_policy or "here" in config.privacy_policy or len(config.privacy_policy) < 50:
                config.privacy_policy = DEFAULT_PRIVACY_POLICY
                updated = True
            if not config.terms_conditions or "here" in config.terms_conditions or len(config.terms_conditions) < 50:
                config.terms_conditions = DEFAULT_TERMS_CONDITIONS
                updated = True
            if not config.account_deletion_policy or "instructions" in config.account_deletion_policy or len(config.account_deletion_policy) < 50:
                config.account_deletion_policy = DEFAULT_ACCOUNT_DELETION_POLICY
                updated = True


            if updated:
                await db.commit()
                logger.info("Updated AppSettings generic placeholders to official mobile app policies.")


async def init_db():
    """
    Run schema column checks and seed initial admin & app settings data.
    """
    await ensure_db_columns()
    await seed_admin_user()
    await seed_app_settings()
    logger.info("Database initialization check complete.")


