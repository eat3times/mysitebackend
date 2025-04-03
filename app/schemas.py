from pydantic import BaseModel
from typing import Optional
from datetime import datetime

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

# API 요청용 스키마
class APIKeyUpdate(BaseModel):
    access_key: str
    secret_key: str

class UserInfo(BaseModel):
    email: Optional[str]
    telegram_token: Optional[str]
    telegram_bot_id: Optional[str]

class TradeRecordCreate(BaseModel):
    user_id: int
    symbol: str
    side: str
    entry_price: float
    quantity: float
    leverage: int
    order_id: Optional[str] = None

class TradeRecordOut(TradeRecordCreate):
    id: int
    exit_price: Optional[float] = None 
    pnl: float
    created_at: datetime
    closed_at: Optional[datetime] = None

    model_config = {
        "from_attributes": True
    }

class CloseTradeRequest(BaseModel):
    exit_price: float
    pnl: float