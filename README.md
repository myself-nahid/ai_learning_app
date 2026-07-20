# AI Learning Platform

AI Learning Platform is a FastAPI-based backend for an AI-driven microlearning application. It provides user authentication with email OTP verification, personalized onboarding, daily AI-generated learning feeds, interactive quizzes, and scheduled background generation with Celery.

## Key Features

- FastAPI REST API with versioned endpoints.
- JWT-based authentication with access and refresh tokens.
- Email OTP verification for signup, resend OTP, and password reset flows.
- User onboarding with profile settings, interests, and difficulty level.
- Daily AI-generated learning feed: news summary, lesson, and quiz.
- Interactive quiz submission and scoring.
- Async PostgreSQL database access using SQLAlchemy and asyncpg.
- OpenAI integration for generating structured learning content.
- Celery worker and beat scheduler for background daily feed generation.
- Docker and Docker Compose support for local deployment.

## Project Structure

- `app/main.py` - FastAPI application and startup lifecycle.
- `app/api/v1/endpoints/auth.py` - Authentication flows: signup, OTP verification, login, refresh token, forgot password, reset password.
- `app/api/v1/endpoints/users.py` - User onboarding and profile retrieval.
- `app/api/v1/endpoints/content.py` - Daily AI content generation and retrieval.
- `app/api/v1/endpoints/quizzes.py` - Quiz submission and grading.
- `app/core/config.py` - Environment configuration and settings.
- `app/core/security.py` - Password hashing and JWT token creation.
- `app/db/models.py` - SQLAlchemy ORM models.
- `app/db/session.py` - Async database session factory.
- `app/services/ai_service.py` - OpenAI content generation service.
- `app/services/email_service.py` - OTP generation and email sending mock.
- `app/worker/celery_app.py` - Celery setup and scheduling.
- `app/worker/tasks.py` - Celery task for generating feeds for all users.

## Requirements

- Python 3.11+
- PostgreSQL
- Redis
- Docker / Docker Compose (optional but recommended)

## Install Dependencies

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Environment Variables

Create a `.env` file in the project root with these values:

```env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=aishowcase
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
SECRET_KEY=your_super_secret_jwt_key_here_12345
ALGORITHM=HS256
OPENAI_API_KEY=your_openai_api_key
REDIS_URL=redis://localhost:6379/0
```

> Note: The Docker Compose service already provides example environment variables for development.

## Running Locally

1. Start PostgreSQL and Redis (locally or with Docker).
2. Set environment variables from `.env`.
3. Run the app with Uvicorn:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

4. Visit API docs at `http://localhost:8000/docs`.

## Docker Compose

Start the full stack with:

```bash
docker-compose up --build
```

This will launch:

- `db` - PostgreSQL database on port `5434`
- `redis` - Redis on port `6379`
- `web` - FastAPI app on port `8000`
- `worker` - Celery worker
- `beat` - Celery beat scheduler

## API Endpoints

### Authentication

- `POST /api/v1/auth/signup`
  - Create a new user and send signup OTP.
- `POST /api/v1/auth/verify-otp`
  - Verify user email with OTP.
- `POST /api/v1/auth/resend-otp`
  - Resend signup OTP email.
- `POST /api/v1/auth/login`
  - Login and receive access/refresh tokens.
- `POST /api/v1/auth/refresh`
  - Refresh access token using refresh token.
- `POST /api/v1/auth/forgot-password`
  - Send password reset OTP.
- `POST /api/v1/auth/reset-password`
  - Reset password using OTP.

### Users & Profile

- `POST /api/v1/users/onboarding`
  - Complete onboarding with full name, difficulty level, and interests.
- `GET /api/v1/users/me`
  - Get current user profile details.

### Daily Content

- `GET /api/v1/content/daily-feed`
  - Retrieve or generate today's AI-driven daily learning feed.

### Quizzes

- `POST /api/v1/quizzes/{feed_id}/submit`
  - Submit quiz answers and receive score and feedback.

## Database Models

- `User` - Authenticated app user.
- `OTP` - One-time password records for email verification and password reset.
- `UserProfile` - Onboarding profile with interests and difficulty.
- `DailyFeed` - Saved daily AI-generated content and quiz data.
- `QuizAttempt` - Stored quiz attempts, score, and user answers.

## Notes

- OTP email sending is currently mocked in `app/services/email_service.py`.
- The app currently auto-creates database tables on startup for dev/testing convenience.
- OpenAI generation uses `gpt-4o-mini` via the async `openai` client.
- Celery beat is configured to run a daily task and generate feeds for verified users.
