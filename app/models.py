from sqlalchemy import Column, Integer, String, Boolean
from app.database import Base

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