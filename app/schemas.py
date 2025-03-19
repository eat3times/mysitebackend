from pydantic import BaseModel

# 회원가입에 필요한 데이터 모델
class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    telegram_token: str
    telegram_bot_id: str 
    binance_key: str
    binance_secret: str

# 로그인에 필요한 데이터 모델
class UserLogin(BaseModel):
    username: str
    password: str

# 응답 데이터 모델
class User(BaseModel):
    username: str
    email: str

    class Config:
        from_attributes = True
