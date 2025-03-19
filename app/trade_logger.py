import json
import os
from datetime import datetime

class TradeLogger:
    def __init__(self, filename):
        self.filename = filename
        self.directory = os.path.join(os.path.dirname(__file__), "logs")  # logs 폴더에 저장하도록 설정
        os.makedirs(self.directory, exist_ok=True)  # 폴더가 없으면 생성

        # 저장할 파일 경로 설정
        self.filename = os.path.join(self.directory, filename)
        self.trades = self.load_trades()

    def load_trades(self):
        """ 이전 거래 기록 불러오기 """
        if os.path.exists(self.filename):
            with open(self.filename, "r") as file:
                return json.load(file)
        return []

    def save_trade(self, symbol, side, amount, price, status, period):
        """ 거래 기록 저장 """
        trade = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "period": period,
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "avgpric": price,
            "type": status
        }
        self.trades.append(trade)
        
        with open(self.filename, "w") as file:
            json.dump(self.trades, file, indent=4)
    
    def save_trade_dict(self, trade_data,trade_data2,trade_data3):
        """ 거래 기록 저장 """
        # trade_data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # trade_data["name"] = 'position'
        # trade_data2["name"] = 'position_2'
        # trade_data3["name"] = 'position_R'
        
        self.trades = [trade_data, trade_data2, trade_data3]
        
        with open(self.filename, "w") as file:
            json.dump(self.trades, file, indent=4)

    def delete_file(self):
        """ 저장된 파일 삭제 """
        if os.path.exists(self.filename):
            os.remove(self.filename)
            print(f"✅ 파일 {self.filename}가 삭제되었습니다.")
        else:
            print(f"❌ 파일 {self.filename}이 존재하지 않습니다.")
    
    def get_trades(self):
        """저장된 거래 내역 반환"""
        return self.trades

    def print_trade_history(self):
        """ 저장된 거래 내역 출력 """
        if not self.trades:
            print("이전 거래 기록이 없습니다.")
            self.save_data = False
            return self.save_data
        else:
            print("거래 기록이 있습니다")
            self.save_data = True
            return self.save_data