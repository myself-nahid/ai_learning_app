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
docker compose up --build
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

## Developer Docker Compose Commands (recommended)

Use these commands when developing locally with Docker Compose (the project uses `docker compose`):

- Start the full stack (build images if needed):

```powershell
docker compose up -d --build
```

- Start only Redis + Postgres (fast start when you only need DB services):

```powershell
docker compose up -d db redis
```

- Recreate worker and beat after config changes (ensures env updates like `POSTGRES_PORT` are applied):

```powershell
docker compose up -d --force-recreate --no-deps worker beat
```

- Check worker environment inside the container (verify `REDIS_URL`, `POSTGRES_PORT`):

```powershell
docker compose exec worker env | findstr REDIS_URL
docker compose exec worker env | findstr POSTGRES_PORT
```

- Trigger the daily generation manually (requires authenticated API call). If you can't authenticate, run the task inside the worker container for testing:

```powershell
# (preferred) authenticated request from your frontend or curl
curl -X POST http://localhost:8000/api/v1/home/trigger-daily-pulse \
  -H "Authorization: Bearer <ACCESS_TOKEN>"

# (testing) invoke task synchronously inside the worker container
docker compose exec worker python -c "from app.worker.tasks import generate_real_daily_content; generate_real_daily_content()"
```

- Follow logs to watch task processing:

```powershell
docker compose logs -f worker
docker compose logs -f beat
```

- Connect to Postgres on the host (the Compose file maps container port 5432 to host 5434):

```powershell
# psql example (Windows with psql in PATH)
psql -h localhost -p 5434 -U postgres -d aishowcase
```

Notes:

- When running services in Docker, use the container hostnames defined in Compose (e.g., `db`, `redis`). Do not rely on `localhost` inside containers.
- If you change `docker-compose.yml`, recreate the affected containers so they pick up new environment variables.
- The `version` key in `docker-compose.yml` is obsolete for newer Docker Compose versions; you can safely remove it to avoid warnings.

