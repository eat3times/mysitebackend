from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, JSON
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()

class Trade(Base):
    __tablename__ = 'trades'

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    name = Column(String, nullable=False)
    symbol = Column(String, nullable=False) 
    data = Column(JSON, nullable=False)
    instance_id = Column(String, nullable=False)

class TradeLogger:
    def __init__(self, db_path, instance_id):
        self.engine = create_engine(f"sqlite:///{db_path}")
        self.Session = sessionmaker(bind=self.engine)
        self.instance_id = instance_id

        Base.metadata.create_all(self.engine)

    def save_trade_dict(self, symbol, **trade_dicts):
        session = self.Session()

        for name, trade_data in trade_dicts.items():
            trade = Trade(
                name=name,
                symbol=symbol,
                data=trade_data,
                instance_id=self.instance_id
            )
            session.add(trade)

        session.commit()
        session.close()

    def get_trades(self, limit=10, name=None, instance_id=None, symbol=None):
        session = self.Session()
        instance_id = instance_id or self.instance_id

        query = session.query(Trade).filter_by(instance_id=instance_id)
        if name:
            query = query.filter_by(name=name)
        if symbol:
            query = query.filter_by(symbol=symbol)

        trades = query.order_by(Trade.timestamp.desc()).limit(limit).all()
        session.close()
        return trades

    def print_trade_history(self):
        trades = self.get_trades()
        if not trades:
            print("이전 거래 기록이 없습니다.")
            return False
        print("거래 기록:")
        for trade in trades:
            print(f"{trade.timestamp} | {trade.name} | {trade.data} | Instance: {trade.instance_id}")
        return True

    def delete_all_trades(self):
        session = self.Session()
        session.query(Trade).delete()
        session.commit()
        session.close()