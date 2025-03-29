from sqlalchemy.orm import Session
from app import models, schemas

def get_user_by_id(db, user_id: str):
    # 사용자 정보를 가져오는 함수
    return db.query(models.User).filter(models.User.id == user_id).first()

def create_trade_for_user(db, user_id: str, trade_data: dict):
    # 사용자별 거래를 기록하는 함수
    trade = models.Trade(user_id=user_id, **trade_data)
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade

# api key 관련
def get_api_keys(db: Session, user_id: str):
    user = db.query(models.User).filter(models.User.username == user_id).first()
    if user:
        return {
            "access_key": user.binance_key,
            "secret_key": user.binance_secret
        }
    return None

def update_api_keys(db: Session, user_id: str, access_key: str, secret_key: str):
    user = db.query(models.User).filter(models.User.username == user_id).first()
    if user:
        user.binance_key = access_key
        user.binance_secret = secret_key
        db.commit()
        return True
    return False

# 거래내역 부분
def create_trade_record(db: Session, trade: schemas.TradeRecordCreate):
    db_trade = models.TradeRecord(**trade.dict())
    db.add(db_trade)
    db.commit()
    db.refresh(db_trade)
    return db_trade

def get_trade_records(db: Session, user_id: str):
    return db.query(models.TradeRecord).filter(models.TradeRecord.user_id == user_id).order_by(models.TradeRecord.timestamp.desc()).all()
