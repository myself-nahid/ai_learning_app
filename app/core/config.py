# pyrefly: ignore [missing-import]
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "AI Learning Platform"
    
    # DB
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str
    POSTGRES_PORT: str = "5432"

    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"

    # Email Settings
    MAIL_USERNAME: str
    MAIL_PASSWORD: str
    MAIL_FROM: str
    MAIL_PORT: int
    MAIL_SERVER: str
    MAIL_FROM_NAME: str
    MAIL_USE_TLS: bool = True
    MAIL_USE_SSL: bool = False
    EMAIL_BACKEND: str = "smtp"

    # OpenAI API Key
    OPENAI_API_KEY: str 

    # Base URL for the application
    BASE_URL: str = "http://localhost:8000"

    # News API Key
    NEWS_API_KEY: str

    # Admin User Settings
    FIRST_SUPERUSER_EMAIL: str = "admin@todai.app"
    FIRST_SUPERUSER_PASSWORD: str = "admin123"
    FIRST_SUPERUSER_FULL_NAME: str = "System Admin"

    DATABASE_URL: str | None = None

    @property
    def ASYNC_DATABASE_URI(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        # Connection string for asyncpg
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    REDIS_URL: str = "redis://localhost:6379/0"

    class Config:
        env_file = ".env"
        from_attributes = True
        extra = "ignore"

settings = Settings()