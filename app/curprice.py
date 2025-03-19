import asyncio
import threading
import websockets
import json

class BinanceWebSocket:
    def __init__(self, symbol):
        self.symbol = symbol.lower().replace("/", "")  # BTC/USDT -> btcusdt
        self.price = None  # 실시간 가격 저장
        self.running = False

    async def connect(self):
        """바이낸스 웹소켓 연결"""
        url = f"wss://fstream.binance.com/ws/{self.symbol}@trade"
        self.running = True
        async with websockets.connect(url) as websocket:
            while self.running:
                try:
                    data = json.loads(await websocket.recv())
                    self.price = float(data['p'])  # 가격 업데이트
                except Exception as e:
                    print(f"웹소켓 오류: {e}")
                    self.price = None

    def start_websocket(self):
        """웹소켓을 별도 스레드에서 실행"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.connect())

    def run_in_thread(self):
        """웹소켓을 백그라운드에서 실행"""
        thread = threading.Thread(target=self.start_websocket, daemon=True)
        thread.start()

    def stop_websocket(self):
        """웹소켓 종료"""
        self.running = False
