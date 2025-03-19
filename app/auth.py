from datetime import datetime, timedelta
from jose import JWTError, jwt
from typing import Union
from passlib.context import CryptContext
from fastapi import HTTPException, status
from app import models, schemas, crud
from sqlalchemy.orm import Session
from app import auth as auth_utils
from datetime import timedelta

# 비밀 키와 알고리즘 설정
SECRET_KEY = "d5bfc82432fa226ed0e17883f25d6d4c5a8fdad9b5d15eb07938ef16b1a3b167"  # 실제 서비스에서는 더 안전한 키로 설정하세요!
ALGORITHM = "HS256"

# Pydantic의 데이터 모델을 사용할 때 사용되는 암호화 설정
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# 로그인 처리
def login_user(user: schemas.UserLogin, db: Session):
    db_user = db.query(models.User).filter(models.User.username == user.username).first()
    if not db_user or not auth_utils.verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    
    # JWT 토큰 생성
    access_token = auth_utils.create_access_token(data={"sub": db_user.username}, expires_delta=timedelta(minutes=60))
    return {"access_token": access_token, "token_type": "bearer"}

# 회원가입 처리
def register_user(user: schemas.UserCreate, db: Session):
    if db.query(models.User).filter(models.User.username == user.username).first():
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_pw = auth_utils.hash_password(user.password)
    new_user = models.User(
        username=user.username,
        email=user.email,
        hashed_password=hashed_pw,
        telegram_token=user.telegram_token,
        telegram_bot_id=user.telegram_bot_id,
        binance_key=user.binance_key,
        binance_secret=user.binance_secret
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

# JWT 토큰 생성 함수
def create_access_token(data: dict, expires_delta: timedelta = timedelta(minutes=15)):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# JWT 토큰 검증 함수
def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload if payload["exp"] >= datetime.utcnow() else None
    except JWTError:
        return None

# 비밀번호 해싱 함수
def hash_password(password: str):
    return pwd_context.hash(password)

# 비밀번호 검증 함수
def verify_password(plain_password: str, hashed_password: str):
    return pwd_context.verify(plain_password, hashed_password)
