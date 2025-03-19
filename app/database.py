# database.py
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"  # SQLite를 사용하려면 이와 같이 설정

# 데이터베이스 연결 엔진 생성
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})

# 세션을 관리하는 객체
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 모든 모델의 기본 클래스
Base = declarative_base()

# 데이터베이스 연결
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()