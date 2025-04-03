from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from .database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_trading = Column(Boolean, default=False)
    telegram_token = Column(String, nullable=True)  # 텔레그램 봇 토큰
    telegram_bot_id = Column(String, nullable=True)  # 텔레그램 챗 ID
    binance_key = Column(String, nullable=True)  # 텔레그램 봇 토큰
    binance_secret = Column(String, nullable=True)  # 텔레그램 챗 ID
    total_usdt = Column(Float, default=0.0)
    total_pnl = Column(Float, default=0.0)

class TradeRecord(Base):
    __tablename__ = "trade_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    symbol = Column(String)
    side = Column(String)  # "LONG"/"BUY" or "SHORT"/"SELL"
    entry_price = Column(Float)
    exit_price = Column(Float, nullable=True)
    quantity = Column(Float)
    leverage = Column(Integer)
    pnl = Column(Float, default=0.0)
    created_at = Column(DateTime, default=func.now())  # 주문 체결 시점
    closed_at = Column(DateTime, nullable=True)        # 청산 시점
    order_id = Column(String, nullable=True) 