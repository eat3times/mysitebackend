from sqlalchemy.orm import Session
from app import models, schemas

def get_user_by_id(db, user_id: int):
    # 사용자 정보를 가져오는 함수
    return db.query(models.User).filter(models.User.id == user_id).first()

def create_trade_for_user(db, user_id: int, trade_data: dict):
    # 사용자별 거래를 기록하는 함수
    trade = models.Trade(user_id=user_id, **trade_data)
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade