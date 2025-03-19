import os

# 기본 설정들
class Settings:
    API_KEY: str = os.getenv("API_KEY", "your_default_api_key_here")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your_secret_key_here")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/dbname")

# 환경변수 읽기
settings = Settings()
