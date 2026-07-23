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

    # OpenAI API Key
    OPENAI_API_KEY: str 

    # Base URL for the application
    BASE_URL: str = "http://localhost:8000"

    @property
    def ASYNC_DATABASE_URI(self) -> str:
        # Connection string for asyncpg
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    class Config:
        env_file = ".env"
        from_attributes = True

settings = Settings()