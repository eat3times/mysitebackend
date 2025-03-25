from datetime import datetime, timedelta
import math
import time
import re
import aiohttp

import ccxt
import numpy as np
import pandas as pd
import asyncio
from asyncio import Task
import websockets
import json

import app.binancestrategyclassback_ws as bs
import app.calamount
import logging
import traceback
import sys
import os
from app.trade_logger import TradeLogger
import threading

from celery import Celery
from fastapi import APIRouter, Depends
from app import trade, models
from sqlalchemy.orm import Session
from app.database import get_db
from fastapi.middleware.cors import CORSMiddleware
from app.crud import get_user_by_id, create_trade_for_user
from pydantic import BaseModel
from celery_config import celery_app
from celery.result import AsyncResult
from celery.exceptions import Ignore
from typing import Dict, List
import redis
from app.global_state import active_tasks

# APIRouter 생성
router = APIRouter()

import telegram
from telegram.ext import CommandHandler, Updater

# Telegram Bot

current_dir = os.path.dirname(os.path.abspath(__file__))  # 현재 파일의 절대 경로

MAX_TELEGRAM_MESSAGE_LENGTH = 4096  # Telegram 메시지 최대 길이

# 로그 파일 생성
log_file_path = os.path.join(current_dir, "error.log") 
logging.basicConfig(filename=log_file_path, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logging.error(f"프로그램 구동 시작")


# 역방향 매매 작동 on off 스위치
posi_R = 'on'

# 수량 N분의 1
divide_switch = 'on'

today_date = datetime.now().strftime("%y%m%d")

redis_client = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

# class 선언
class BinanceWebSocket:
    def __init__(self,symbol):
        self.modified_symbol = symbol.replace('/', '')
        self.symbol = self.modified_symbol.lower()
        self.ws_url = f"wss://fstream.binance.com/ws/{self.symbol}@trade"
        self.price = None
    async def connect(self):
        async with websockets.connect(self.ws_url, ping_interval=10) as websocket:
            while True:
                try:
                    response = await websocket.recv()
                    data = json.loads(response)
                    self.price = float(data['p'])
                    self.quantity = data['q']
                except websockets.exceptions.ConnectionClosed as e:
                    print(f"Connection closed: {e}")
                    await asyncio.sleep(5)
                except websockets.exceptions.WebSocketException as e:
                    print(f"⚠️ 웹소켓 예외 발생: {e}")
                    await asyncio.sleep(5)
                except Exception as e:
                    print(f"An error occurred: {e}")
                    await asyncio.sleep(5)
class coin_trading:
    instances = {} # 공유 리스트
    exchange_cache = {}
    
    def __init__(self,user_id,api_key,api_secret,symbol,period,timeframe,fib_level,leverage,num_of_coins):
        self.user_id = user_id
        self.api_key = api_key
        self.api_secret = api_secret

         # 이미 같은 user_id로 생성된 exchange 인스턴스가 있다면 사용
        if user_id in coin_trading.exchange_cache:
            self.exchange = coin_trading.exchange_cache[user_id]
        else:
            # 없다면 새로 생성하고 캐시에 저장
            exchange_instance = ccxt.binance({
                'apiKey': self.api_key, 
                'secret': self.api_secret,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future'
                },
                'timeout': 30000
            })
            coin_trading.exchange_cache[user_id] = exchange_instance
            self.exchange = exchange_instance
            
        self.symbol = symbol
        self.fib_target = bs.Fib_target(self.symbol)
        self.symbol_len = len(self.symbol)
        self.unit = self.symbol[0:self.symbol_len - 5]
        self.lower_unit = self.unit.lower()
        self.logger = TradeLogger("trading.db",self.user_id)
        self.period = period
        self.timeframe = timeframe
        self.fib_level = fib_level
        self.leverage = leverage
        self.num_of_coins = num_of_coins
        self.modified_symbol = self.symbol.replace('/', '')
        self.period_switch = 'off'
        self.total_pnl = 0
        self.transfer_usdt = 0 
        self.timestamp = int(datetime.now().timestamp() * 1000) 
        self.decimal_place = 0
        self.last_entry_time = 0
        self.lock = None
        self.reboot_detect = False
        self.total_fees = 0
        self.target_cal = 0
        self.liquidation_price = 0
        self.liquidation_price_2 = 0
        self.liquidation_price_R = 0
        self.user_bot = user_bots.get(user_id, {}).get('bot')
        self.user_bot_id = user_bots.get(user_id, {}).get('bot_id')
        self.data_check = None
        self.is_rest = False
        

        # 웹소켓 설정
        self.websocket = BinanceWebSocket(self.symbol)
        self.running = True
        
        # 현재 가격 관련 티커
        self.ticker = self.exchange.fetch_ticker(self.symbol)
        self.cur_price = self.ticker['last']
        if self.decimal_place == 0:
            self.decimal_place = len(str(self.cur_price).split(".")[1])

        # 레버리지 설정
        markets = self.exchange.load_markets()
        market = self.exchange.market(self.symbol)
        resp = self.exchange.fapiPrivate_post_leverage({
            'symbol': market['id'],
            'leverage': self.leverage
        })

        # 각 코인마다 최소 수량에 맞는 소수점아래 자리갯수 구하기
        self.min_qty = markets[self.symbol]['limits']['amount']['min']
        self.decimal_min_qty = self.min_qty
        self.decimal_place_min_qty = len(str(self.decimal_min_qty).split(".")[1])

        # 잔고 관련
        self.balance = self.exchange.fetch_balance()
        self.free_usdt = self.balance['free']['USDT']
        self.total_usdt = self.balance['total']['USDT']

        # 모듈 함수 불러오기
        self.long_target, self.short_target, self.Sub_target, self.reverse_target, self.Sub_rtarget, self.fibRe, self.recommend,\
        self.fib_level ,self.alram_date1, self.alram_date2 , self.TP_1st, self.TP_2nd, self.SL_1st, self.Last_target,\
        self.target_1618, self.target_1414, self.target_1272, self.target_113, self.target_1, self.target_1618_2, self.target_1414_2,\
        self.target_1272_2, self.target_113_2, self.target_1_2, self.new_recommend, self.fibRe2,\
        self.long_target_2, self.short_target_2, self.Sub_target_2, self.Last_target_2,\
        self.TP_1st_2, self.TP_2nd_2, self.SL_1st_2, self.target_2, self.target_2_2,self.target_213,self.target_213_2,\
        self.Sub_TP, self.decimal_place,self.list_1618,self.num_high, self.num_low, self.df = self.fib_target.cal_target_mixed(self.exchange,self.symbol,self.period,self.timeframe,self.fib_level)

        if self.cur_price and self.cur_price > 0:
            self.max_amount = app.calamount.cur_leverage_max_amount(self.cur_price, self.symbol, self.leverage, self.decimal_place_min_qty, self.api_key, self.api_secret)
        else:
            logging.warning(f"cur_price 값이 이상함: {self.cur_price}")

        self.df_datetime = self.df.sort_values(by=["datetime"],ascending=False)
        self.df_date = self.df_datetime.iloc[0,0]

        # 피보나치 레벨
        if self.fib_level == 5:
            self.fib_level_name = 0.886
        elif self.fib_level == 6:
            self.fib_level_name = 0.786
        elif self.fib_level == 13:
            self.fib_level_name = 0.707
        elif self.fib_level == 7:
            self.fib_level_name = 0.618
        elif self.fib_level == 8:
            self.fib_level_name = 0.5
        elif self.fib_level == 9:
            self.fib_level_name = 0.382
        elif self.fib_level == 10:
            self.fib_level_name = 0.236

        # 딕셔너리 자료형
        
        self._position = {"symbol": self.symbol, "type": None, "avgPrice": 0, "amount": 0, "get_amount": 0, "get_half": 0,\
            "TP_1st": 0,"TP_2nd": 0, "SL_1st": 0, "Total":0, "Win":0, "Lose":0, "TP_level" : 1,\
                "fixed_1": 0, "fixed_0": 0, "2" : 0, "1.618" : 0,"1.414" : 0,\
                "1.272" : 0, "1.13" : 0, "times" : 0,\
                "split" : 0, "type_ext": None, "transfer": None, "stoploss": None, "period": 0}
        self._position_2 = {"symbol": self.symbol, "type": None, "avgPrice": 0, "amount": 0, "get_amount": 0, "get_half": 0,\
            "TP_1st": 0,"TP_2nd": 0, "SL_1st": 0, "Total":0, "Win":0, "Lose":0, "TP_level" : 1,\
                "fixed_1": 0, "fixed_0": 0, "2" : 0, "1.618" : 0,\
                "1.414" : 0, "1.272" : 0, "1.13" : 0, "times" : 0,\
                "split" : 0, "type_ext": None, "transfer": None, "stoploss": None}
        self._position_R = {"symbol": self.symbol, "type": None, "pass": None, "avgPrice": 0,"amount": 0, "get_amount": 0, "get_half": 0,\
            "TP_1st": 0,"TP_2nd": 0, "SL_1st": 0, "Total":0, "Win":0, "Lose":0, "TP_level" : 1,\
                "fixed_1": 0, "fixed_0": 0, "1.618" : 0,"1.414" : 0, "1.272" : 0, "1.13" : 0, "times" : 0, "transfer": None, "stoploss": None}
        self.rsi_position = {"type": None, "avgPrice": 0, "amount":0, "TP": 0, "SL":0, "start_rsi" : 0,\
            "start_price": 0, "split": 0, "double_check":0, "check_type": None,"date" : 0,\
            "confirm_rsi" : 0, "confirm_fixed" : 50, "confirm_high": 0, "confirm_low": 0,\
            "confirm_close": 0}

    @property
    def position(self):
        self._position.update({
            "2": self.target_2,
            "1.618": self.target_1618,
            "1.414": self.target_1414,
            "1.272": self.target_1272,
            "1.13": self.target_113
        })
        return self._position

    @position.setter
    def position(self, new_values):
        if isinstance(new_values, dict):
            self._position.update(new_values)  # 기존 딕셔너리에 새로운 값 반영
        else:
            raise ValueError("position 값은 딕셔너리여야 합니다.")

    @property
    def position_2(self):
        self._position_2.update({
            "2": self.target_2_2,
            "1.618": self.target_1618_2,
            "1.414": self.target_1414_2,
            "1.272": self.target_1272_2,
            "1.13": self.target_113_2
        })
        return self._position_2

    @position_2.setter
    def position_2(self, new_values):
        if isinstance(new_values, dict):
            self._position_2.update(new_values)
        else:
            raise ValueError("position_2 값은 딕셔너리여야 합니다.")

    @property
    def position_R(self):
        return self._position_R

    @position_R.setter
    def position_R(self, new_values):
        if isinstance(new_values, dict):
            self._position_R.update(new_values)
        else:
            raise ValueError("position_R 값은 딕셔너리여야 합니다.")
        
    # lock 
    def ensure_lock(self):
        if self.lock is None or not hasattr(self.lock, '_loop') or self.lock._loop != asyncio.get_running_loop():
            self.lock = asyncio.Lock()
    
    # 텔레그램 메세지 슬라이싱
    def send_long_message(self,text):
        """Telegram 메시지를 4096자 이하로 나누어 전송"""
        messages = text.split("\n")
        chunk = ""

        for line in messages:
            if len(chunk) + len(line) + 1 > MAX_TELEGRAM_MESSAGE_LENGTH:
                self.user_bot.sendMessage(chat_id=self.user_bot_id, text=chunk)
                chunk = line
            else:
                chunk += "\n" + line

        if chunk:
            self.user_bot.sendMessage(chat_id=self.user_bot_id, text=chunk)    
    # 비동기 함수 실행 시 예외를 자동으로 처리하는 데코레이터
    def wrap_task(retries=5, delay=5):
        def decorator(func):
            async def wrapper(self, *args, **kwargs):
                attempt = 1
                current_delay = delay  # 원래의 delay 값을 유지하기 위해 새로운 변수 사용

                while attempt <= retries:
                    try:
                        return await func(self, *args, **kwargs)

                    except (ccxt.DDoSProtection, ccxt.NetworkError, ccxt.AuthenticationError,
                            ccxt.ExchangeError, ccxt.RequestTimeout, telegram.error.NetworkError) as e:
                        error_type = type(e).__name__
                        error_message = f"🚨 프로그램 오류 발생!\n\n📌 에러 타입: {error_type}\n💬 내용: {traceback.format_exc()}"

                        logging.error(f"태스크 {func.__name__}에서 예외 발생 (시도 {attempt}/{retries}): {e}\n{traceback.format_exc()}")
                        print(f"{error_type} 발생! {attempt}/{retries} 재시도 중... {e}")
                        
                        if attempt < retries:
                            await asyncio.sleep(current_delay)
                            current_delay *= 2  # 다음 시도에서는 대기 시간 증가
                        else:
                            logging.error(f"{error_type}로 {func.__name__} 실패: {e}\n{traceback.format_exc()}")
                            self.send_long_message(error_message)  # 메시지 길이 제한 대응
                            raise

                    except Exception as e:
                        error_type = type(e).__name__
                        error_message = f"🚨 프로그램 오류 발생!\n\n📌 에러 타입: {error_type}\n💬 내용: {traceback.format_exc()}"
                        
                        logging.error(f"태스크 {func.__name__}에서 예외 발생 (시도 {attempt}/{retries}): {e}\n{traceback.format_exc()}")
                        print(f"✅ 알림 {func.__name__}에서 예외 발생 (시도 {attempt}/{retries}): {e}")

                        if attempt < retries:
                            await asyncio.sleep(current_delay)
                            current_delay *= 2
                        else:
                            logging.error(f"[오류] {func.__name__}에서 {retries}번 재시도 후 실패")
                            self.send_long_message(error_message)  # 메시지 길이 제한 대응
                            raise

                    attempt += 1  # 재시도 횟수 증가

            return wrapper
        return decorator

    # 웹소켓 연결
    @wrap_task()
    async def start_websocket(self):
        await self.websocket.connect()
        

    # 포지션 진입 가능한 최대 수량과 적정 수량 구하기
    @wrap_task()
    async def cal_Unlimited_Max_amount(self):
        while self.running:
            if self.cur_price > 0:
                self.unlimited_max_amount = round(math.floor((self.free_usdt * 100000)/self.cur_price) / 100000 * self.leverage,self.decimal_place_min_qty)
            await asyncio.sleep(0.3)
        return self.unlimited_max_amount
            

    async def cal_amount(self):
        while self.running:
            portion = 0.12
            usdt_trade = self.free_usdt * portion
            amount = math.floor((usdt_trade * 100000)/self.cur_price) / 100000 * self.leverage
            await asyncio.sleep(0.3)
        return round(amount,self.decimal_place_min_qty)

    # 최대 레버리지 진입 가능한 최대 수량의 분할 수량
    @wrap_task()
    async def cal_amount_split(self):
        while self.running:
            portion = 0.12
            if divide_switch == 'on':
                self.split_amount = round((self.max_amount / self.num_of_coins) * portion,self.decimal_place_min_qty)
            else:
                self.split_amount = round(self.max_amount * portion,self.decimal_place_min_qty)
            await asyncio.sleep(0.3)
        return self.split_amount
    
    # 실제 진입 가능한 분할 수량
    @wrap_task()
    async def cal_real_split_amount(self):
        while self.running:
            portion = 0.12
            if self.cur_price > 0 and divide_switch == 'on':
                self.real_amount = (self.leverage * (self.free_usdt / self.num_of_coins)) / self.cur_price
                if self.real_amount <= self.max_amount:
                    self.amount = round(self.real_amount * portion,self.decimal_place_min_qty)
                elif self.real_amount > self.max_amount:
                    self.amount = self.split_amount
            elif self.cur_price > 0 and divide_switch == 'off':
                self.real_amount = (self.leverage * self.free_usdt) / self.cur_price
                if self.real_amount <= self.max_amount:
                    self.amount = round(self.real_amount * portion,self.decimal_place_min_qty)
                elif self.real_amount > self.max_amount:
                    self.amount = self.split_amount
            else:
                self.real_amount = 0
            await asyncio.sleep(0.3)
        return self.amount
    
    # 수수료 계산
    @wrap_task()
    async def cal_fees(self):
        self.fee = 0
        self.retries = 10
        self.attempt = 0
        self.timestamp = self.timestamp - (1000 * 20)
        while self.attempt < self.retries and self.timestamp > 0:
            self.order_structure = self.exchange.fetch_my_trades(self.symbol, since=self.timestamp, limit=100, params={})
            self.fees_usdt = [
                abs(float(i['fee']['cost']))  # 수수료는 보통 음수로 나오니 abs() 적용
                for i in self.order_structure
                if 'fee' in i and 'cost' in i['fee']  # 'fee' 키가 있는지 확인
            ]
            if self.fees_usdt:
                self.fee = round(sum(self.fees_usdt),4)
                if self.fee > 0:
                    return self.fee

            self.attempt += 1
            if self.attempt < self.retries:
                await asyncio.sleep(3)

        self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n발견된 수수료가 없습니다\nfees_usdt : {self.fees_usdt}\ntime : {self.timestamp}')
        return 0
    
    # 포지션 체크
    async def check_position(self):
        try:
            self.balance = self.exchange.fetch_balance()
            self.positions = self.balance["info"]["positions"]
        
            for pos in self.positions:
                if pos["symbol"] == self.modified_symbol and abs(float(pos["positionAmt"])) > 0:
                    print(f"🔥 현재 {self.symbol} 포지션 보유 중!")
                    # 이름별로 포지션 불러오기 (최신 1개씩)
                    self.position_trade   = self.logger.get_trades(limit=1, name="position", symbol=self.symbol, instance_id=self.user_id)
                    self.position_2_trade = self.logger.get_trades(limit=1, name="position_2", symbol=self.symbol, instance_id=self.user_id)
                    self.position_R_trade = self.logger.get_trades(limit=1, name="position_R", symbol=self.symbol, instance_id=self.user_id)

                    self.position   = self.position_trade[0].data if self.position_trade else None
                    self.position_2 = self.position_2_trade[0].data if self.position_2_trade else None
                    self.position_R = self.position_R_trade[0].data if self.position_R_trade else None

                    if self.position:
                        self.period = self.position["period"]
                    return pos  # 포지션 데이터 반환

            print(f"✅ {self.symbol} 포지션 없음")
            return None
        except Exception as e:
            print(f"❌ 포지션 조회 오류: {e}")
            return None
    
    # 심볼 바꾸기
    def update_symbol(self, new_symbol: str):
        self.symbol = new_symbol  # 심볼 업데이트
    
    # 로그 파일 삭제
    def delete_log_file(self):
        """해당 인스턴스의 로그 파일 삭제"""
        print(f"Exit command received for {self.symbol}")
        self.logger.delete_file()
    
    async def send_trade_update(self):
        # 거래 데이터 구성 (여기서 self는 trade 관련 인스턴스)
        # 현재 UTC 시간 가져오기
        utc_now = datetime.utcnow()
        # UTC 시간에 9시간 더해 한국 시간으로 변환
        kst_now = utc_now + timedelta(hours=9)
        self.trade_data = {
            "free_usdt": round(self.free_usdt, 2),
            "unlimited_max_amount": f"{self.unlimited_max_amount} {self.unit}",
            "max_amount": f"{self.max_amount} {self.unit}",
            "split_amount": f"{self.split_amount} {self.unit}",
            "amount": f"{self.amount} {self.unit}",
            "highprice_info": f"{self.alram_date1}  ${self.highprice}",
            "lowprice_info": f"{self.alram_date2}  ${self.lowprice}",
            "fib_info": f"{self.fibRe, self.recommend}",
            "fib_info2": f"{self.fibRe2, self.new_recommend}",
            "target_1618": f"{self.unit} 1.618 값은 : ${self.target_1618}, ${self.target_1618_2}",
            "price_info": f"{self.unit}의 현재가 = ${self.cur_price} 목표 조건 부합 가격 = ${self.targetprice}",
            "timestamp": kst_now.strftime('%Y-%m-%d %H:%M:%S'),
            "TP": self.TP_1st
        }
        # Redis에 trade_data 저장 (예: key: trade_output:abc)
        # redis_client.set(f"trade_output:{self.user_id}:{self.modified_symbol}", json.dumps(self.trade_data))
        message = json.dumps({
            "trade_output": self.trade_data,
            "symbol": self.modified_symbol
        })
        redis_client.publish(f"trade_output_channel:{self.user_id}", message)
    
    # 일정 주기로 데이터들을 업데이트
    @wrap_task()
    async def update_balance(self):
        """잔고를 일정 주기로 업데이트"""
        while True:
            self.last_check_time = time.time() # 시간 체크 (정상작동 유무 판별을 위함)
            # self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ [check_status] self ID: {id(self)}')
            # self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ [check_status] self.last_check_time: {self.last_check_time}')
            self.balance = self.exchange.fetch_balance() # 바이낸스 api
            if self.data_check is not None:
                self.logger.save_trade_dict(symbol=self.symbol,
                    position=self.position,
                    position_2=self.position_2,
                    position_R=self.position_R
                ) # 포지션 딕셔너리 저장
                self.position['period'] = self.period # 봉 개수 저장
            await asyncio.sleep(5)
    
    # 프로그램 정상 작동 유무
    def check_status(self):
        """프로그램 상태 확인"""
        if self.user_id in active_tasks:
            bot_instance = active_tasks.get(self.user_id, {}).get("bot_instance")
            # self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ [check_status] self ID: {id(bot_instance)}')
            # self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ [check_status] bot.last_check_time: {bot_instance.last_check_time}')
            # self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ [check_status] self.last_check_time: {self.last_check_time}')
            now = time.time()
            time_diff = now - bot_instance.last_check_time

            if time_diff > 10:  # 10초 이상 last_check_time이 업데이트 안 되면 정지 상태로 판단
                self.is_running = False
                return self.is_running
            else:
                self.is_running = True
                return self.is_running
    
    # 포지션 진입
    @wrap_task()
    async def enter_position(self):
        while self.running:
            self.ensure_lock()
            async with self.lock:
                if self.websocket.price is not None and self.free_usdt > 0 and self.is_rest == False and self.data_check is not None:

                    # 피보나치 1과 0이 바뀔 때 리셋
                    if self.position_R['fixed_1'] != self.fibRe[4]:
                        self.position_R['fixed_1'] = self.fibRe[4]
                        self.position['fixed_1'] = self.fibRe[4]
                        self.position_R['pass'] = None
                        self.position['times'] = 0
                        self.position_R['times'] = 0
                        self.position_2['times'] = 0
                        if self.position['type'] == "cooling":
                            self.position['type'] = None
                        if self.position_R['type'] == "cooling":
                            self.position_R['type'] = None
                        if self.position_2['type'] == "cooling":
                            self.position_2['type'] = None
                    if self.position_R['fixed_0'] != self.fibRe[11]:
                        self.position_R['fixed_0'] = self.fibRe[11]
                        self.position['fixed_0'] = self.fibRe[11]
                        self.position_R['pass'] = None
                        self.position['times'] = 0
                        self.position_R['times'] = 0
                        self.position_2['times'] = 0
                        if self.position['type'] == "cooling":
                            self.position['type'] = None
                        if self.position_R['type'] == "cooling":
                            self.position_R['type'] = None
                        if self.position_2['type'] == "cooling":
                            self.position_2['type'] = None
                            
                        
                    if self.fibRe[self.fib_level] >= self.cur_price and self.recommend == "롱 추천":
                        self.position_R['pass'] = True
                    if self.fibRe[self.fib_level] <= self.cur_price and self.recommend == "숏 추천":
                        self.position_R['pass'] = True
                    
                    # 0.382 통과했으면 역방향 패스
                    if self.recommend == "롱 추천":
                        self.filt = self.df.iloc[self.num_high+1:,]
                        self.filt_low = self.filt['low'].min()
                        if self.filt['low'].min() <= self.fibRe[9]:
                            self.position_R['pass'] = True
                    if self.recommend == "숏 추천":
                        self.filt = self.df.iloc[self.num_low+1:,]
                        self.filt_high = self.filt['high'].max()
                        if self.filt['high'].max() >= self.fibRe[9]:
                            self.position_R['pass'] = True
                    if self.position_R['pass'] == True and self.recommend == "롱 추천":
                        if self.cur_price >= self.fibRe[11] or self.cur_price <= self.fibRe[4]:
                            self.position_R['pass'] = None
                    if self.position_R['pass'] == True and self.recommend == "숏 추천":
                        if self.cur_price <= self.fibRe[11] or self.cur_price >= self.fibRe[4]:
                            self.position_R['pass'] = None
                    
                    # cooling 설정
                    if self.position['type'] is None and self.position['times'] >= 2:
                        self.position['type'] = "cooling"
                    if self.position_R['type'] is None and self.position_R['times'] >= 2:
                        self.position_R['type'] = "cooling"
                    if self.position_2['type'] is None and self.position_2['times'] >= 2:
                        self.position_2['type'] = "cooling"
                    
                    # 진입 조건
                    if self.position['type'] is None and self.position['type'] != "cooling":
                        # print(f"{self.unit} 진입 조건 가격 검색중")
                        if self.Sub_target <= self.cur_price <= self.long_target and self.recommend == "롱 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                amount=self.amount, 
                                params = {'positionSide': 'LONG',})
                            self.position['type'] = 'long'
                            self.position['amount'] = self.amount
                            self.position['get_amount'] = self.amount
                            self.position['get_half'] = round(self.position['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position['TP_1st'] = self.TP_1st
                            self.position['TP_2nd'] = self.TP_2nd
                            self.position['Total'] = self.position['Total'] + 1
                            self.position['times'] = self.position['times'] + 1
                            self.position['split'] = self.position['split'] + 1
                            print("롱 포지션 진입", self.position)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 롱 포지션 진입 완료 !!!\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                            
                        if self.Sub_target >= self.cur_price >= self.short_target and self.recommend == "숏 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                amount=self.amount, 
                                params = {'positionSide': 'SHORT'})
                            self.position['type'] = 'short'
                            self.position['amount'] = self.amount
                            self.position['get_amount'] = self.amount
                            self.position['get_half'] = round(self.position['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position['TP_1st'] = self.TP_1st
                            self.position['TP_2nd'] = self.TP_2nd
                            self.position['Total'] = self.position['Total'] + 1
                            self.position['times'] = self.position['times'] + 1
                            self.position['split'] = self.position['split'] + 1
                            print("숏 포지션 진입", self.position)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 숏 포지션 진입 완료 !!!\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()


                    ### Reverse target
                    if self.position_R['type'] is None and self.position_R['type'] != "cooling" and self.position_2['type'] is None and posi_R == 'on'\
                        and self.position_R['pass'] is None and self.position['type'] is None:
                        # print(f"{self.unit} 역방향 진입 조건 가격 검색중")
                        if self.cur_price > 0 and time.time() - self.last_entry_time > 5 and self.target_cal > 0:
                            if self.target_cal >= self.cur_price >= self.target_under and self.recommend == "롱 추천": # 아래로 통과
                                self.last_entry_time = time.time()
                                self.position_R['type'] = 'short'
                                self.positions = self.balance['info']['positions']
                                self.timestamp = int(datetime.now().timestamp() * 1000)
                                await asyncio.sleep(0.3)
                                self.exchange.create_market_sell_order(symbol=self.symbol,
                                    amount=self.amount * 2, 
                                    params = {'positionSide': 'SHORT'})                        
                                self.position_R['amount'] = self.amount * 2
                                self.position_R['get_amount'] = self.amount * 2
                                self.position_R['get_half'] = round(self.position_R['get_amount'] / 2,self.decimal_place_min_qty)
                                self.position_R['TP_1st'] = self.fibRe[10]
                                self.position_R['TP_2nd'] = self.fibRe[9]
                                self.position_R['SL_1st'] = self.fibRe[11]
                                self.position_R['Total'] = self.position_R['Total'] + 1
                                self.position_R['times'] = self.position_R['times'] + 1
                                print("역 숏 포지션 진입", self.position_R)
                                self.fees = await self.cal_fees()
                                self.total_fees = round(self.total_fees + self.fees,4)
                                self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 역 숏 포지션 진입 완료 !!!\n수수료 : {self.fees}$')
                                self.balance = self.exchange.fetch_balance()
                            elif self.target_over >= self.cur_price >= self.target_cal and self.recommend == "숏 추천": # 위로 통과
                                self.last_entry_time = time.time()
                                self.position_R['type'] = 'long'
                                self.positions = self.balance['info']['positions']
                                self.timestamp = int(datetime.now().timestamp() * 1000)
                                await asyncio.sleep(0.3)
                                self.exchange.create_market_buy_order(symbol=self.symbol,
                                    amount=self.amount * 2, 
                                    params = {'positionSide': 'LONG',})
                                self.position_R['amount'] = self.amount * 2
                                self.position_R['get_amount'] = self.amount * 2
                                self.position_R['get_half'] = round(self.position_R['get_amount'] / 2,self.decimal_place_min_qty)
                                self.position_R['TP_1st'] = self.fibRe[10]
                                self.position_R['TP_2nd'] = self.fibRe[9]
                                self.position_R['SL_1st'] = self.fibRe[11]
                                self.position_R['Total'] = self.position_R['Total'] + 1
                                self.position_R['times'] = self.position_R['times'] + 1
                                print("역 롱 포지션 진입", self.position_R)
                                self.fees = await self.cal_fees()
                                self.total_fees = round(self.total_fees + self.fees,4)
                                self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 역 롱 포지션 진입 완료 !!!\n수수료 : {self.fees}$')
                                self.balance = self.exchange.fetch_balance()

                    # Extension
                    if self.position['type'] is None and self.cur_price > 0:
                        # 1.272
                        if self.target_1414 <= self.cur_price <= self.target_1272 and self.recommend == "숏 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                amount=self.amount, 
                                params = {'positionSide': 'LONG',})
                            self.position['type'] = 'long_ex'
                            self.position['amount'] = self.amount
                            self.position['get_amount'] = self.amount
                            self.position['get_half'] = round(self.position['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position['TP_1st'] = self.target_113
                            self.position['TP_2nd'] = self.target_1
                            self.position['Total'] = self.position['Total'] + 1
                            self.position['split'] = self.position['split'] + 1
                            self.position['type_ext'] ='1.272'
                            print("1.272 롱 포지션 진입", self.position)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 1.272 롱 포지션 진입 완료 !!!\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                        if self.target_1414 >= self.cur_price >= self.target_1272 and self.recommend == "롱 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                amount=self.amount, 
                                params = {'positionSide': 'SHORT'})
                            self.position['type'] = 'short_ex'
                            self.position['amount'] = self.amount
                            self.position['get_amount'] = self.amount
                            self.position['get_half'] = round(self.position['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position['TP_1st'] = self.target_113
                            self.position['TP_2nd'] = self.target_1
                            self.position['Total'] = self.position['Total'] + 1
                            self.position['split'] = self.position['split'] + 1
                            self.position['type_ext'] ='1.272'
                            print("1.272 숏 포지션 진입", self.position)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 1.272 숏 포지션 진입 완료 !!!\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                    if (self.position['type'] == 'long_ex' or self.position['type'] == 'short_ex') and self.cur_price > 0:
                        # 1.414
                        if self.position['type_ext'] == '1.272' and self.target_1618 <= self.cur_price <= self.target_1414 and self.recommend == "숏 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                amount=self.amount, 
                                params = {'positionSide': 'LONG',})
                            self.position['type'] = 'long_ex'
                            self.position['amount'] = self.amount
                            self.position['get_amount'] = self.amount
                            self.position['get_half'] = round(self.position['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position['TP_1st'] = self.target_1272
                            self.position['TP_2nd'] = self.target_113
                            self.position['Total'] = self.position['Total'] + 1
                            self.position['split'] = self.position['split'] + 1
                            self.position['type_ext'] ='1.414'
                            print("1.414 롱 포지션 진입", self.position)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 1.414 롱 포지션 진입 완료 !!!\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                        if self.position['type_ext'] == '1.272' and self.target_1618 >= self.cur_price >= self.target_1414 and self.recommend == "롱 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                amount=self.amount, 
                                params = {'positionSide': 'SHORT'})
                            self.position['type'] = 'short_ex'
                            self.position['amount'] = self.amount
                            self.position['get_amount'] = self.amount
                            self.position['get_half'] = round(self.position['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position['TP_1st'] = self.target_1272
                            self.position['TP_2nd'] = self.target_113
                            self.position['Total'] = self.position['Total'] + 1
                            self.position['split'] = self.position['split'] + 1
                            self.position['type_ext'] ='1.414'
                            print("1.414 숏 포지션 진입", self.position)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 1.414 숏 포지션 진입 완료 !!!\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                        # 1.618
                        if self.position['type_ext'] == '1.414' and self.target_2 <= self.cur_price <= self.target_1618 and self.recommend == "숏 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                amount=self.position['amount'], 
                                params = {'positionSide': 'LONG',})
                            self.position['type'] = 'long_ex'
                            self.position['amount'] = self.amount
                            self.position['get_amount'] = self.amount
                            self.position['get_half'] = round(self.position['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position['TP_1st'] = self.target_1414
                            self.position['TP_2nd'] = self.target_1272
                            self.position['Total'] = self.position['Total'] + 1
                            self.position['split'] = self.position['split'] + 1
                            print("1.618 롱 포지션 진입", self.position)
                            self.position['type_ext'] ='1.618'
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 1.618 롱 포지션 진입 완료 !!!\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                        if self.position['type_ext'] == '1.414' and self.target_2 >= self.cur_price >= self.target_1618 and self.recommend == "롱 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                amount=self.position['amount'], 
                                params = {'positionSide': 'SHORT'})
                            self.position['type'] = 'short_ex'
                            self.position['amount'] = self.amount
                            self.position['get_amount'] = self.amount
                            self.position['get_half'] = round(self.position['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position['TP_1st'] = self.target_1414
                            self.position['TP_2nd'] = self.target_1272
                            self.position['Total'] = self.position['Total'] + 1
                            self.position['split'] = self.position['split'] + 1
                            self.position['type_ext'] ='1.618'
                            print("1.618 숏 포지션 진입", self.position)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 1.618 숏 포지션 진입 완료 !!!\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                        # 2
                        if self.position['type_ext'] == '1.618' and self.target_213 < self.cur_price < self.target_2 and self.recommend == "숏 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                amount=self.position['amount'], 
                                params = {'positionSide': 'LONG',})
                            self.position['type'] = 'long_ex'
                            self.position['amount'] = self.amount
                            self.position['get_amount'] = self.amount
                            self.position['get_half'] = round(self.position['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position['TP_1st'] = self.target_1618
                            self.position['TP_2nd'] = self.target_1414
                            self.position['Total'] = self.position['Total'] + 1
                            self.position['split'] = self.position['split'] + 1
                            self.position['type_ext'] = '2'
                            print("2 롱 포지션 진입", self.position)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 2 롱 포지션 진입 완료 !!!\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                        if self.position['type_ext'] == '1.618' and self.target_213 > self.cur_price > self.target_2 and self.recommend == "롱 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                amount=self.position['amount'], 
                                params = {'positionSide': 'SHORT'})
                            self.position['type'] = 'short_ex'
                            self.position['amount'] = self.amount
                            self.position['get_amount'] = self.amount
                            self.position['get_half'] = round(self.position['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position['TP_1st'] = self.target_1618
                            self.position['TP_2nd'] = self.target_1414
                            self.position['Total'] = self.position['Total'] + 1
                            self.position['split'] = self.position['split'] + 1
                            self.position['type_ext'] ='2'
                            print("2 숏 포지션 진입", self.position)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 2 숏 포지션 진입 완료 !!!\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                    if self.position['type'] == 'long':
                        print(f"✅ 알림 이미 롱 포지션 보유 중입니다. 익절가격 : {self.position['TP_1st']}")
                        self.positions = self.balance['info']['positions']
                        for posi in self.positions:
                            if posi["symbol"] == self.modified_symbol:
                                if posi['positionSide'] == 'LONG':
                                    self.position['avgPrice'] = float(posi['entryPrice'])
                                    self.position['amount'] = abs(float(posi['positionAmt']))
                                    self.position['get_amount'] = abs(float(posi['positionAmt']))
                                    self.avgprice = float(self.position['avgPrice'])

                                    # 청산가격 코드
                                    self.total_usdt = self.balance['total']['USDT']
                                    self.maintenance_margin = float(posi["maintMargin"])
                                    if self.position['avgPrice'] > 0 and self.position['amount'] > 0:
                                        self.liquidation_price = (self.position['avgPrice'] * self.position['amount'] - self.total_usdt + self.maintenance_margin) / (
                                            self.position['amount'] * (1 - (1 / self.leverage))
                                        )
                                        self.liquidation_price = round(self.liquidation_price * 1.005,self.decimal_place)
                                    if self.avgprice != 0 and self.liquidation_price > 0:
                                        if self.position['TP_level'] == 1:
                                            if 4 > self.position['split'] >= 1 and self.liquidation_price > self.fibRe[4]:
                                                self.position['SL_1st'] = self.liquidation_price
                                            if 4 > self.position['split'] >= 1 and self.liquidation_price < self.fibRe[4]:
                                                self.position['SL_1st'] = self.fibRe[4]
                                        if self.position['TP_level'] == 2:
                                            self.position['SL_1st'] = self.avgprice
                    if self.position['type'] == 'short':
                        print(f"✅ 알림 이미 숏 포지션 보유 중입니다. 익절가격 : {self.position['TP_1st']}")
                        self.positions = self.balance['info']['positions']
                        for posi in self.positions:
                            if posi["symbol"] == self.modified_symbol:
                                if posi['positionSide'] == 'SHORT':
                                    self.position['avgPrice'] = float(posi['entryPrice'])
                                    self.position['amount'] = abs(float(posi['positionAmt']))
                                    self.position['get_amount'] = abs(float(posi['positionAmt']))
                                    self.avgprice = float(self.position['avgPrice'])

                                    # 청산가격 코드
                                    self.total_usdt = self.balance['total']['USDT']
                                    self.maintenance_margin = float(posi["maintMargin"])
                                    if self.position['avgPrice'] > 0 and self.position['amount'] > 0:
                                        self.liquidation_price = (self.position['avgPrice'] * self.position['amount'] + self.total_usdt - self.maintenance_margin) / (
                                            self.position['amount'] * (1 + (1 / self.leverage))
                                        )
                                        self.liquidation_price = round(self.liquidation_price * 0.995,self.decimal_place)
                                    if self.avgprice != 0 and self.liquidation_price > 0:
                                        if self.position['TP_level'] == 1:
                                            if 4 > self.position['split'] >= 1 and self.liquidation_price > self.fibRe[4]:
                                                self.position['SL_1st'] = self.fibRe[4]
                                            if 4 > self.position['split'] >= 1 and self.liquidation_price < self.fibRe[4]:
                                                self.position['SL_1st'] = self.liquidation_price
                                        if self.position['TP_level'] == 2:
                                            self.position['SL_1st'] = self.avgprice
                    if self.position_R['type'] == 'long':
                        print(f"✅ 알림 이미 역 롱 포지션 보유 중입니다. 익절가격 : {self.position_R['TP_1st']}")
                        self.positions = self.balance['info']['positions']
                        for posi in self.positions:
                            if posi["symbol"] == self.modified_symbol:
                                if posi['positionSide'] == 'LONG':
                                    self.position_R['avgPrice'] = float(posi['entryPrice'])
                                    self.position_R['amount'] = abs(float(posi['positionAmt']))
                                    self.position_R['get_amount'] = abs(float(posi['positionAmt']))
                                    self.avgprice_R = float(self.position_R['avgPrice'])

                                    # 청산가격 코드
                                    self.total_usdt = self.balance['total']['USDT']
                                    self.maintenance_margin_R = float(posi["maintMargin"])
                                    if self.position_R['avgPrice'] > 0 and self.position_R['amount'] > 0:
                                        self.liquidation_price_R = (self.position_R['avgPrice'] * self.position_R['amount'] - self.total_usdt + self.maintenance_margin_R) / (
                                            self.position_R['amount'] * (1 - (1 / self.leverage))
                                        )
                                        self.liquidation_price_R = round(self.liquidation_price_R * 1.005,self.decimal_place)
                                    if self.avgprice_R != 0 and self.liquidation_price_R > 0:
                                        if self.position_R['TP_level'] == 1:
                                            if self.liquidation_price_R > self.fibRe[11]:
                                                self.position_R['SL_1st'] = self.liquidation_price_R
                                            if self.liquidation_price_R < self.fibRe[11]:
                                                self.position_R['SL_1st'] = self.fibRe[11]
                                        if self.position_R['TP_level'] == 2:
                                                self.position_R['SL_1st'] = self.avgprice_R
                    if self.position_R['type'] == 'short':
                        print(f"✅ 알림 이미 역 숏 포지션 보유 중입니다. 익절가격 : {self.position_R['TP_1st']}")
                        self.positions = self.balance['info']['positions']
                        for posi in self.positions:
                            if posi["symbol"] == self.modified_symbol:
                                if posi['positionSide'] == 'SHORT':
                                    self.position_R['avgPrice'] = float(posi['entryPrice'])
                                    self.position_R['amount'] = abs(float(posi['positionAmt']))
                                    self.position_R['get_amount'] = abs(float(posi['positionAmt']))
                                    self.avgprice_R = float(self.position_R['avgPrice'])
                                    
                                    # 청산가격 코드
                                    self.total_usdt = self.balance['total']['USDT']
                                    self.maintenance_margin_R = float(posi["maintMargin"])
                                    if self.position_R['avgPrice'] > 0 and self.position_R['amount'] > 0:
                                        self.liquidation_price_R = (self.position_R['avgPrice'] * self.position_R['amount'] + self.total_usdt - self.maintenance_margin_R) / (
                                            self.position_R['amount'] * (1 + (1 / self.leverage))
                                        )
                                        self.liquidation_price_R = round(self.liquidation_price_R * 0.995,self.decimal_place)
                                    if self.avgprice_R != 0 and self.liquidation_price_R > 0:
                                        if self.position_R['TP_level'] == 1:
                                            if self.liquidation_price_R > self.fibRe[11]:
                                                self.position_R['SL_1st'] = self.fibRe[11]
                                            if self.liquidation_price_R < self.fibRe[11]:
                                                self.position_R['SL_1st'] = self.liquidation_price_R
                                        if self.position_R['TP_level'] == 2:
                                                self.position_R['SL_1st'] = self.avgprice_R
                    if self.position['type'] == 'long_ex':
                        print(f"✅ 알림 이미 확장 롱 포지션 보유 중입니다. 익절가격 : {self.position['TP_1st']}")
                        self.positions = self.balance['info']['positions']
                        for posi in self.positions:
                            if posi["symbol"] == self.modified_symbol:
                                if posi['positionSide'] == 'LONG':
                                    self.position['avgPrice'] = float(posi['entryPrice'])
                                    self.position['amount'] = abs(float(posi['positionAmt']))
                                    self.position['get_amount'] = abs(float(posi['positionAmt']))
                                    self.avgprice = float(self.position['avgPrice'])

                                    # 청산가격 코드
                                    self.total_usdt = self.balance['total']['USDT']
                                    self.maintenance_margin = float(posi["maintMargin"])
                                    if self.position['avgPrice'] > 0 and self.position['amount'] > 0:
                                        self.liquidation_price = (self.position['avgPrice'] * self.position['amount'] - self.total_usdt + self.maintenance_margin) / (
                                            self.position['amount'] * (1 - (1 / self.leverage))
                                        )
                                        self.liquidation_price = round(self.liquidation_price * 1.005,self.decimal_place)
                                    if self.avgprice != 0 and self.liquidation_price > 0:
                                        if self.position['TP_level'] == 1:
                                            if 5 > self.position['split'] >= 1 and self.liquidation_price > self.target_213:
                                                self.position['SL_1st'] = self.liquidation_price
                                            if 5 > self.position['split'] >= 1 and self.liquidation_price < self.target_213:
                                                self.position['SL_1st'] = self.target_213
                                        if self.position['TP_level'] == 2:
                                            self.position['SL_1st'] = self.avgprice
                    if self.position['type'] == 'short_ex':
                        print(f"✅ 알림 이미 확장 숏 포지션 보유 중입니다. 익절가격 : {self.position['TP_1st']}")
                        self.positions = self.balance['info']['positions']
                        for posi in self.positions:
                            if posi["symbol"] == self.modified_symbol:
                                if posi['positionSide'] == 'SHORT':
                                    self.position['avgPrice'] = float(posi['entryPrice'])
                                    self.position['amount'] = abs(float(posi['positionAmt']))
                                    self.position['get_amount'] = abs(float(posi['positionAmt']))
                                    self.avgprice = float(self.position['avgPrice'])
                                    # 청산가격 코드
                                    self.total_usdt = self.balance['total']['USDT']
                                    self.maintenance_margin = float(posi["maintMargin"])
                                    if self.position['avgPrice'] > 0 and self.position['amount'] > 0:
                                        self.liquidation_price = (self.position['avgPrice'] * self.position['amount'] + self.total_usdt - self.maintenance_margin) / (
                                            self.position['amount'] * (1 + (1 / self.leverage))
                                        )
                                        self.liquidation_price = round(self.liquidation_price * 0.995,self.decimal_place)
                                    if self.avgprice != 0 and self.liquidation_price > 0:
                                        if self.position['TP_level'] == 1:
                                            if 5 > self.position['split'] >= 1 and self.liquidation_price > self.target_213:
                                                self.position['SL_1st'] = self.target_213
                                            if 5 > self.position['split'] >= 1 and self.liquidation_price < self.target_213:
                                                self.position['SL_1st'] = self.liquidation_price
                                        if self.position['TP_level'] == 2:
                                            self.position['SL_1st'] = self.avgprice
            await asyncio.sleep(0.3)

    # 포지션 진입 (fibRe2)
    @wrap_task()
    async def enter_position_2(self):
        while self.running:
            self.ensure_lock()
            async with self.lock:
                if self.websocket.price is not None and self.free_usdt > 0 and self.is_rest == False and self.data_check is not None:
                    if self.position_2['type'] is None and self.position_2['type'] != "cooling" and self.fibRe2:
                        # print(f"{self.unit} 진입 조건 가격 검색중_2")
                        if self.position['type'] != 'long' and \
                            self.Sub_target_2 <= self.cur_price <= self.long_target_2 and self.new_recommend == "롱 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                amount=self.amount, 
                                params = {'positionSide': 'LONG',})
                            self.position_2['type'] = 'long'
                            self.position_2['amount'] = self.amount
                            self.position_2['get_amount'] = self.amount
                            self.position_2['get_half'] = round(self.position_2['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position_2['TP_1st'] = self.TP_1st_2
                            self.position_2['TP_2nd'] = self.TP_2nd_2
                            self.position_2['Total'] = self.position_2['Total'] + 1
                            self.position_2['times'] = self.position_2['times'] + 1
                            self.position_2['split'] = self.position_2['split'] + 1
                            print("롱 포지션 진입_2", self.position_2)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 롱 포지션 진입 완료 !!!_2\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                        if self.position['type'] != 'short' and \
                            self.Sub_target_2 >= self.cur_price >= self.short_target_2 and self.new_recommend == "숏 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                amount=self.amount, 
                                params = {'positionSide': 'SHORT'})
                            self.position_2['type'] = 'short'
                            self.position_2['amount'] = self.amount
                            self.position_2['get_amount'] = self.amount
                            self.position_2['get_half'] = round(self.position_2['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position_2['TP_1st'] = self.TP_1st_2
                            self.position_2['TP_2nd'] = self.TP_2nd_2
                            self.position_2['Total'] = self.position_2['Total'] + 1
                            self.position_2['times'] = self.position_2['times'] + 1
                            self.position_2['split'] = self.position_2['split'] + 1
                            print("숏 포지션 진입_2", self.position_2)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 숏 포지션 진입 완료 !!!_2\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()

                        
                    # Extension
                    if self.position_2['type'] is None and self.cur_price > 0 and self.target_1618_2 > 0:
                        # 1.272
                        if self.target_1414_2 <= self.cur_price <= self.target_1272_2 and self.recommend == "숏 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                amount=self.amount, 
                                params = {'positionSide': 'LONG',})
                            self.position_2['type'] = 'long_ex'
                            self.position_2['amount'] = self.amount
                            self.position_2['get_amount'] = self.amount
                            self.position_2['get_half'] = round(self.position_2['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position_2['TP_1st'] = self.target_113_2
                            self.position_2['TP_2nd'] = self.target_1_2
                            self.position_2['Total'] = self.position_2['Total'] + 1
                            self.position_2['split'] = self.position_2['split'] + 1
                            self.position_2['type_ext'] ='1.272'
                            print("1.272 롱 포지션 진입_2", self.position_2)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)                        
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 1.272 롱 포지션 진입 완료 !!!_2\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                        if self.target_1414_2 >= self.cur_price >= self.target_1272_2 and self.recommend == "롱 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                amount=self.amount, 
                                params = {'positionSide': 'SHORT'})
                            self.position_2['type'] = 'short_ex'
                            self.position_2['amount'] = self.amount
                            self.position_2['get_amount'] = self.amount
                            self.position_2['get_half'] = round(self.position_2['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position_2['TP_1st'] = self.target_113_2
                            self.position_2['TP_2nd'] = self.target_1_2
                            self.position_2['Total'] = self.position_2['Total'] + 1
                            self.position_2['split'] = self.position_2['split'] + 1
                            self.position_2['type_ext'] ='1.272'
                            print("1.272 숏 포지션 진입_2", self.position_2)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 1.272 숏 포지션 진입 완료 !!!_2\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                    if (self.position_2['type'] == 'long_ex' or self.position_2['type'] == 'short_ex') and self.cur_price > 0:    
                        # 1.414
                        if self.position_2['type_ext'] == '1.272' and self.target_1618_2 <= self.cur_price <= self.target_1414_2 and self.recommend == "숏 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                amount=self.amount, 
                                params = {'positionSide': 'LONG',})
                            self.position_2['type'] = 'long_ex'
                            self.position_2['amount'] = self.amount
                            self.position_2['get_amount'] = self.amount
                            self.position_2['get_half'] = round(self.position_2['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position_2['TP_1st'] = self.target_1272_2
                            self.position_2['TP_2nd'] = self.target_113_2
                            self.position_2['Total'] = self.position_2['Total'] + 1
                            self.position_2['split'] = self.position_2['split'] + 1
                            self.position_2['type_ext'] ='1.414'
                            print("1.414 롱 포지션 진입_2", self.position_2)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 1.414 롱 포지션 진입 완료 !!!_2\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                        if self.position_2['type_ext'] == '1.272' and self.target_1618_2 >= self.cur_price >= self.target_1414_2 and self.recommend == "롱 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                amount=self.amount, 
                                params = {'positionSide': 'SHORT'})
                            self.position_2['type'] = 'short_ex'
                            self.position_2['amount'] = self.amount
                            self.position_2['get_amount'] = self.amount
                            self.position_2['get_half'] = round(self.position_2['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position_2['TP_1st'] = self.target_1272_2
                            self.position_2['TP_2nd'] = self.target_113_2
                            self.position_2['Total'] = self.position_2['Total'] + 1
                            self.position_2['split'] = self.position_2['split'] + 1
                            self.position_2['type_ext'] ='1.414'
                            print("1.414 숏 포지션 진입_2", self.position_2)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 1.414 숏 포지션 진입 완료 !!!_2\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                        # 1.618
                        if self.position_2['type_ext'] == '1.414' and self.target_2_2 <= self.cur_price <= self.target_1618_2 and self.recommend == "숏 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                amount=self.position_2['amount'], 
                                params = {'positionSide': 'LONG',})
                            self.position_2['type'] = 'long_ex'
                            self.position_2['amount'] = self.amount
                            self.position_2['get_amount'] = self.amount
                            self.position_2['get_half'] = round(self.position_2['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position_2['TP_1st'] = self.target_1414_2
                            self.position_2['TP_2nd'] = self.target_1272_2
                            self.position_2['Total'] = self.position_2['Total'] + 1
                            self.position_2['split'] = self.position_2['split'] + 1
                            self.position_2['type_ext'] ='1.618'
                            print("1.618 롱 포지션 진입_2", self.position_2)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 1.618 롱 포지션 진입 완료 !!!_2\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                        if self.position_2['type_ext'] == '1.414' and self.target_2_2 >= self.cur_price >= self.target_1618_2 and self.recommend == "롱 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                amount=self.position_2['amount'], 
                                params = {'positionSide': 'SHORT'})
                            self.position_2['type'] = 'short_ex'
                            self.position_2['amount'] = self.amount
                            self.position_2['get_amount'] = self.amount
                            self.position_2['get_half'] = round(self.position_2['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position_2['TP_1st'] = self.target_1414_2
                            self.position_2['TP_2nd'] = self.target_1272_2
                            self.position_2['Total'] = self.position_2['Total'] + 1
                            self.position_2['split'] = self.position_2['split'] + 1
                            self.position_2['type_ext'] ='1.618'
                            print("1.618 숏 포지션 진입_2", self.position_2)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 1.618 숏 포지션 진입 완료 !!!_2\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                        # 2
                        if self.position_2['type_ext'] == '1.618' and self.target_213_2 < self.cur_price < self.target_2_2 and self.recommend == "숏 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                amount=self.position_2['amount'], 
                                params = {'positionSide': 'LONG',})
                            self.position_2['type'] = 'long_ex'
                            self.position_2['amount'] = self.amount
                            self.position_2['get_amount'] = self.amount
                            self.position_2['get_half'] = round(self.position_2['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position_2['TP_1st'] = self.target_1618
                            self.position_2['TP_2nd'] = self.target_1414
                            self.position['Total'] = self.position_2['Total'] + 1
                            self.position_2['split'] = self.position_2['split'] + 1
                            self.position_2['type_ext'] ='2'
                            print("2 롱 포지션 진입", self.position)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 2 롱 포지션 진입 완료 !!!\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                        if self.position_2['type_ext'] == '1.618' and self.target_213_2 > self.cur_price > self.target_2_2 and self.recommend == "롱 추천":
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                amount=self.position_2['amount'], 
                                params = {'positionSide': 'SHORT'})
                            self.position_2['type'] = 'short_ex'
                            self.position_2['amount'] = self.amount
                            self.position_2['get_amount'] = self.amount
                            self.position_2['get_half'] = round(self.position_2['get_amount'] / 2,self.decimal_place_min_qty)
                            self.position_2['TP_1st'] = self.target_1618
                            self.position_2['TP_2nd'] = self.target_1414
                            self.position_2['Total'] = self.position_2['Total'] + 1
                            self.position_2['split'] = self.position_2['split'] + 1
                            self.position_2['type_ext'] ='2'
                            print("2 숏 포지션 진입", self.position)
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 2 숏 포지션 진입 완료 !!!\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                    if self.position_2['type'] == 'long' and self.fibRe2:
                        print(f"✅ 알림 이미 롱 포지션 보유 중입니다_2. 익절가격 : {self.position_2['TP_1st']}")
                        self.positions = self.balance['info']['positions']
                        for posi in self.positions:
                            if posi["symbol"] == self.modified_symbol:
                                if posi['positionSide'] == 'LONG':
                                    self.position_2['avgPrice'] = float(posi['entryPrice'])
                                    self.position_2['amount'] = abs(float(posi['positionAmt']))
                                    self.position_2['get_amount'] = abs(float(posi['positionAmt']))
                                    self.avgprice_2 = float(self.position_2['avgPrice'])
                                    # 청산가격 코드
                                    self.total_usdt = self.balance['total']['USDT']
                                    self.maintenance_margin_2 = float(posi["maintMargin"])
                                    if self.position_2['avgPrice'] > 0 and self.position_2['amount'] > 0:
                                        self.liquidation_price_2 = (self.position_2['avgPrice'] * self.position_2['amount'] - self.total_usdt + self.maintenance_margin_2) / (
                                            self.position_2['amount'] * (1 - (1 / self.leverage))
                                        )
                                        self.liquidation_price_2= round(self.liquidation_price_2 * 1.005,self.decimal_place)
                                    if self.avgprice_2 != 0 and self.liquidation_price_2 > 0:
                                        if self.position_2['TP_level'] == 1:
                                            if 4 > self.position_2['split'] >= 1 and self.liquidation_price_2 > self.fibRe2[4]:
                                                self.position_2['SL_1st'] = self.liquidation_price_2
                                            if 4 > self.position_2['split'] >= 1 and self.liquidation_price_2 < self.fibRe2[4]:
                                                self.position_2['SL_1st'] = self.fibRe2[4]
                                        if self.position_2['TP_level'] == 2:
                                            self.position_2['SL_1st'] = self.avgprice_2
                                            
                    if self.position_2['type'] == 'short' and self.fibRe2:
                        print(f"✅ 알림 이미 숏 포지션 보유 중입니다_2. 익절가격 : {self.position_2['TP_1st']}")
                        self.positions = self.balance['info']['positions']
                        for posi in self.positions:
                            if posi["symbol"] == self.modified_symbol:
                                if posi['positionSide'] == 'SHORT':
                                    self.position_2['avgPrice'] = float(posi['entryPrice'])
                                    self.position_2['amount'] = abs(float(posi['positionAmt']))
                                    self.position_2['get_amount'] = abs(float(posi['positionAmt']))
                                    self.avgprice_2 = float(self.position_2['avgPrice'])
                                    # 청산가격 코드
                                    self.total_usdt = self.balance['total']['USDT']
                                    self.maintenance_margin_2 = float(posi["maintMargin"])
                                    if self.position_2['avgPrice'] > 0 and self.position_2['amount'] > 0:
                                        self.liquidation_price_2 = (self.position_2['avgPrice'] * self.position_2['amount'] + self.total_usdt - self.maintenance_margin_2) / (
                                            self.position_2['amount'] * (1 + (1 / self.leverage))
                                        )
                                        self.liquidation_price_2= round(self.liquidation_price_2 * 0.995,self.decimal_place)
                                    if self.avgprice_2 != 0 and self.liquidation_price_2 > 0:
                                        if self.position_2['TP_level'] == 1:
                                            if 4 > self.position_2['split'] >= 1 and self.liquidation_price_2 > self.fibRe2[4]:
                                                self.position_2['SL_1st'] = self.fibRe2[4]
                                            if 4 > self.position_2['split'] >= 1 and self.liquidation_price_2 < self.fibRe2[4]:
                                                self.position_2['SL_1st'] = self.liquidation_price_2
                                        if self.position_2['TP_level'] == 2:
                                            self.position_2['SL_1st'] = self.avgprice_2
                    if self.position_2['type'] == 'long_ex':
                        print(f"✅ 알림 이미 확장 롱 포지션 보유 중입니다_2. 익절가격 : {self.position_2['TP_1st']}")
                        self.positions = self.balance['info']['positions']
                        for posi in self.positions:
                            if posi["symbol"] == self.modified_symbol:
                                if posi['positionSide'] == 'LONG':
                                    self.position_2['avgPrice'] = float(posi['entryPrice'])
                                    self.position_2['amount'] = abs(float(posi['positionAmt']))
                                    self.position_2['get_amount'] = abs(float(posi['positionAmt']))
                                    self.avgprice_2 = float(self.position_2['avgPrice'])
                                    # 청산가격 코드
                                    self.total_usdt = self.balance['total']['USDT']
                                    self.maintenance_margin_2 = float(posi["maintMargin"])
                                    if self.position_2['avgPrice'] > 0 and self.position_2['amount'] > 0:
                                        self.liquidation_price_2 = (self.position_2['avgPrice'] * self.position_2['amount'] - self.total_usdt + self.maintenance_margin_2) / (
                                            self.position_2['amount'] * (1 - (1 / self.leverage))
                                        )
                                        self.liquidation_price_2 = round(self.liquidation_price_2 * 1.005,self.decimal_place)
                                    if self.avgprice_2 != 0 and self.liquidation_price_2 > 0:
                                        if self.position_2['TP_level'] == 1:
                                            if 5 > self.position_2['split'] >= 1 and self.liquidation_price_2 > self.target_213_2:
                                                self.position_2['SL_1st'] = self.liquidation_price_2
                                            if 5 > self.position_2['split'] >= 1 and self.liquidation_price_2 < self.target_213_2:
                                                self.position_2['SL_1st'] = self.target_213_2
                                        if self.position_2['TP_level'] == 2:
                                            self.position_2['SL_1st'] = self.avgprice_2
                    if self.position_2['type'] == 'short_ex':
                        print(f"✅ 알림 이미 확장 숏 포지션 보유 중입니다_2. 익절가격 : {self.position_2['TP_1st']}")
                        self.positions = self.balance['info']['positions']
                        for posi in self.positions:
                            if posi["symbol"] == self.modified_symbol:
                                if posi['positionSide'] == 'SHORT':
                                    self.position_2['avgPrice'] = float(posi['entryPrice'])
                                    self.position_2['amount'] = abs(float(posi['positionAmt']))
                                    self.position_2['get_amount'] = abs(float(posi['positionAmt']))
                                    self.avgprice_2 = float(self.position_2['avgPrice'])
                                    # 청산가격 코드
                                    self.total_usdt = self.balance['total']['USDT']
                                    self.maintenance_margin_2 = float(posi["maintMargin"])
                                    if self.position_2['avgPrice'] > 0 and self.position_2['amount'] > 0:
                                        self.liquidation_price_2 = (self.position_2['avgPrice'] * self.position_2['amount'] + self.total_usdt - self.maintenance_margin_2) / (
                                            self.position_2['amount'] * (1 + (1 / self.leverage))
                                        )
                                        self.liquidation_price_2 = round(self.liquidation_price_2 * 0.995,self.decimal_place)
                                    if self.avgprice_2 != 0 and self.liquidation_price_2 > 0:
                                        if self.position_2['TP_level'] == 1:
                                            if 5 > self.position_2['split'] >= 1 and self.liquidation_price_2 > self.target_213_2:
                                                self.position_2['SL_1st'] = self.target_213_2
                                            if 5 > self.position_2['split'] >= 1 and self.liquidation_price_2 < self.target_213_2:
                                                self.position_2['SL_1st'] = self.liquidation_price_2
                                        if self.position_2['TP_level'] == 2:
                                            self.position_2['SL_1st'] = self.avgprice_2
            await asyncio.sleep(0.3)

    # 포지션 정리 (TP)
    @wrap_task()
    async def exit_position_TP(self):
        while self.running:
            self.ensure_lock()
            async with self.lock:
                if self.websocket.price is not None and self.is_rest == False:
                    if (self.position['type'] == 'long' or self.position['type'] == 'long_ex') and self.cur_price > 0 and self.position['amount'] > 0:
                        if self.position['TP_1st'] > 0 and self.cur_price >= self.position['TP_1st'] and self.position['TP_level'] == 1:
                            # 시간대 설정 
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                    amount= round(self.position['amount'] / 2,self.decimal_place_min_qty),
                                    params = {'positionSide': 'LONG',})
                            self.position['TP_level'] = self.position['TP_level'] + 1
                            # self.position['get_amount'] = round(self.position['get_amount'] - self.position['get_half'],3)
                            self.position['Win'] = self.position['Win'] + 0.5
                            self.position['get_half'] = 0
                            print(f"✅ 알림\n{self.unit} 롱 포지션 1차 익절 완료 !!!\nTP : {self.position['TP_1st']}")
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 롱 포지션 1차 익절 완료 !!!\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                            self.position['transfer'] = 'on'
                        elif self.position['TP_2nd'] > 0 and self.cur_price >= self.position['TP_2nd'] and self.position['TP_level'] == 2: 
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                    amount= self.position['amount'],
                                    params = {'positionSide': 'LONG',})
                            if self.position['times'] >= 2:
                                self.position['type'] = "cooling"
                            else:
                                self.position['type'] = None
                            self.position['type_ext'] = None
                            self.position['amount'] = 0
                            self.position['get_amount'] = 0
                            self.position['split'] = 0
                            self.position['TP_1st'] = 0
                            self.position['TP_2nd'] = 0
                            self.position['SL_1st'] = 0
                            self.position['avgPrice'] = 0
                            self.position['TP_level'] = 1
                            self.position['Win'] = self.position['Win'] + 0.5
                            self.liquidation_price = 0
                            print(f"✅ 알림\n{self.unit} 롱 포지션 2차 익절 완료 !!!\nTP : {self.position['TP_2nd']}\n수수료 : {self.fees}$")
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)                     
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 롱 포지션 2차 익절 완료 !!!')      
                            self.balance = self.exchange.fetch_balance()                      
                            self.position['transfer'] = 'on'
                            
                    if (self.position['type'] == 'short' or self.position['type'] == 'short_ex') and self.cur_price > 0 and self.position['amount'] > 0:
                        if self.position['TP_1st'] > 0 and self.cur_price <= self.position['TP_1st'] and self.position['TP_level'] == 1:  
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                    amount= round(self.position['amount'] / 2,self.decimal_place_min_qty),
                                    params = {'positionSide': 'SHORT',})
                            self.position['TP_level'] = self.position['TP_level'] + 1
                            # self.position['get_amount'] = round(self.position['get_amount'] - self.position['get_half'],3)
                            self.position['Win'] = self.position['Win'] + 0.5
                            self.position['get_half'] = 0
                            print(f"✅ 알림\n{self.unit} 숏 포지션 1차 익절 완료 !!!\nTP : {self.position['TP_1st']}")
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 숏 포지션 1차 익절 완료 !!!\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()               
                            self.position['transfer'] = 'on'
                        elif self.position['TP_2nd'] > 0 and self.cur_price <= self.position['TP_2nd'] and self.position['TP_level'] == 2: 
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)             
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                    amount= self.position['amount'],
                                    params = {'positionSide': 'SHORT',})
                            if self.position['times'] >= 2:
                                self.position['type'] = "cooling"
                            else:
                                self.position['type'] = None
                            self.position['type_ext'] = None
                            self.position['amount'] = 0
                            self.position['get_amount'] = 0
                            self.position['split'] = 0
                            self.position['TP_1st'] = 0
                            self.position['TP_2nd'] = 0
                            self.position['SL_1st'] = 0
                            self.position['avgPrice'] = 0
                            self.position['TP_level'] = 1
                            self.position['Win'] = self.position['Win'] + 0.5
                            self.liquidation_price = 0
                            print(f"✅ 알림\n{self.unit} 숏 포지션 2차 익절 완료 !!!\nTP : {self.position['TP_1st']}")
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)                      
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 숏 포지션 2차 익절 완료 !!!\n수수료 : {self.fees}$')            
                            self.balance = self.exchange.fetch_balance()                
                            self.position['transfer'] = 'on'

                    ### Reverse
                    if self.position_R['type'] == 'long' and self.cur_price > 0 and self.position_R['amount'] > 0:
                        if self.position_R['TP_1st'] > 0 and self.cur_price >= self.position_R['TP_1st'] and self.position_R['TP_level'] == 1:  
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                    amount= round(self.position_R['amount'] / 2,self.decimal_place_min_qty),
                                    params = {'positionSide': 'LONG',})
                            self.position_R['TP_level'] = self.position_R['TP_level'] + 1
                            self.position_R['Win'] = self.position_R['Win'] + 0.5
                            self.position_R['get_half'] = 0
                            print(f"✅ 알림\n역 롱 포지션 1차 익절 완료 !!!\nTP : {self.position_R['TP_1st']}")             
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)               
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 역 롱 포지션 1차 익절 완료 !!!\n수수료 : {self.fees}$')       
                            self.balance = self.exchange.fetch_balance()                    
                            self.position_R['transfer'] = 'on'                            
                        elif self.position_R['TP_2nd'] > 0 and self.cur_price >= self.position_R['TP_2nd'] and self.position_R['TP_level'] == 2:
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)                             
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                    amount= self.position_R['amount'],
                                    params = {'positionSide': 'LONG',})
                            if self.position_R['times'] >= 2:
                                self.position_R['type'] = "cooling"
                            else:
                                self.position_R['type'] = None
                            self.position_R['amount'] = 0
                            self.position_R['get_amount'] = 0
                            self.position_R['TP_1st'] = 0
                            self.position_R['TP_2nd'] = 0
                            self.position_R['SL_1st'] = 0
                            self.position_R['avgPrice'] = 0
                            self.position_R['TP_level'] = 1
                            self.position_R['Win'] = self.position_R['Win'] + 0.5
                            self.liquidation_price_R = 0
                            print(f"✅ 알림\n역 롱 포지션 2차 익절 완료 !!!\nTP : {self.position['TP_2nd']}")        
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)                    
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 역 롱 포지션 2차 익절 완료 !!!\n수수료 : {self.fees}$') 
                            self.balance = self.exchange.fetch_balance()                           
                            self.position_R['transfer'] = 'on'

                    if self.position_R['type'] == 'short' and self.cur_price > 0 and self.position_R['amount'] > 0:
                        if self.position_R['TP_1st'] > 0 and self.cur_price <= self.position_R['TP_1st'] and self.position_R['TP_level'] == 1: 
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                    amount= round(self.position_R['amount'] / 2,self.decimal_place_min_qty),
                                    params = {'positionSide': 'SHORT',})
                            self.position_R['TP_level'] = self.position_R['TP_level'] + 1
                            self.position_R['Win'] = self.position_R['Win'] + 0.5
                            self.position_R['get_half'] = 0
                            print(f"✅ 알림\n역 숏 포지션 1차 익절 완료 !!!\nTP : {self.position_R['TP_1st']}")      
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)                     
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 역 숏 포지션 1차 익절 완료 !!!\n수수료 : {self.fees}$')    
                            self.balance = self.exchange.fetch_balance()                        
                            self.position_R['transfer'] = 'on'

                        elif self.position_R['TP_2nd'] > 0 and self.cur_price <= self.position_R['TP_2nd'] and self.position_R['TP_level'] == 2: 
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                    amount= self.position_R['amount'],
                                    params = {'positionSide': 'SHORT',})
                            if self.position_R['times'] >= 2:
                                self.position_R['type'] = "cooling"
                            else:
                                self.position_R['type'] = None
                            self.position_R['amount'] = 0
                            self.position_R['get_amount'] = 0
                            self.position_R['TP_1st'] = 0
                            self.position_R['TP_2nd'] = 0
                            self.position_R['SL_1st'] = 0
                            self.position_R['avgPrice'] = 0
                            self.position_R['TP_level'] = 1
                            self.position_R['Win'] = self.position_R['Win'] + 0.5
                            self.liquidation_price_R = 0
                            print(f"✅ 알림\n역 숏 포지션 2차 익절 완료 !!!\nTP : {self.position_R['TP_1st']}")     
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)                       
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 역 숏 포지션 2차 익절 완료 !!!\n수수료 : {self.fees}$')     
                            self.balance = self.exchange.fetch_balance()                      
                            self.position_R['transfer'] = 'on'
                    
                    ### fibRe2
                    if (self.position_2['type'] == 'long' or self.position_2['type'] == 'long_ex') and self.position_2['TP_1st'] > 0 and self.cur_price > 0 and self.position_2['amount'] > 0:
                        if self.position_2['TP_1st'] > 0 and self.cur_price >= self.position_2['TP_1st'] and self.position_2['TP_level'] == 1: 
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)                            
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                    amount= round(self.position_2['amount'] / 2,self.decimal_place_min_qty),
                                    params = {'positionSide': 'LONG',})
                            self.position_2['TP_level'] = self.position_2['TP_level'] + 1
                            # self.position['get_amount'] = round(self.position['get_amount'] - self.position['get_half'],3)
                            self.position_2['Win'] = self.position_2['Win'] + 0.5
                            self.position_2['get_half'] = 0
                            print(f"✅ 알림\n{self.unit} 롱 포지션 1차 익절 완료 !!!_2\nTP : {self.position_2['TP_1st']}")    
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)                        
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 롱 포지션 1차 익절 완료 !!!_2\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                            self.position_2['transfer'] = 'on'
                            
                        elif self.position_2['TP_2nd'] > 0 and self.cur_price >= self.position_2['TP_2nd'] and self.position_2['TP_level'] == 2:
                            self.timestamp = int(datetime.now().timestamp() * 1000) 
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                    amount= self.position_2['amount'],
                                    params = {'positionSide': 'LONG',})
                            if self.position_2['times'] >= 2:
                                self.position_2['type'] = "cooling"
                            else:
                                self.position_2['type'] = None
                            self.position_2['type_ext'] = None
                            self.position_2['amount'] = 0
                            self.position_2['get_amount'] = 0
                            self.position_2['split'] = 0
                            self.position_2['TP_1st'] = 0
                            self.position_2['TP_2nd'] = 0
                            self.position_2['SL_1st'] = 0
                            self.position_2['avgPrice'] = 0
                            self.position_2['TP_level'] = 1
                            self.position_2['Win'] = self.position_2['Win'] + 0.5
                            self.liquidation_price_2 = 0
                            print(f"✅ 알림\n{self.unit} 롱 포지션 2차 익절 완료 !!!_2\nTP : {self.position_2['TP_2nd']}")    
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)                        
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 롱 포지션 2차 익절 완료 !!!_2\n수수료 : {self.fees}$') 
                            self.balance = self.exchange.fetch_balance()                           
                            self.position_2['transfer'] = 'on'
                    if (self.position_2['type'] == 'short' or self.position_2['type'] == 'short_ex') and self.position_2['TP_1st'] > 0 and self.cur_price > 0 and self.position_2['amount'] > 0:
                        if self.position_2['TP_1st'] > 0 and self.cur_price <= self.position_2['TP_1st'] and self.position_2['TP_level'] == 1: 
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                    amount= round(self.position_2['amount'] / 2,self.decimal_place_min_qty),
                                    params = {'positionSide': 'SHORT',})
                            self.position_2['TP_level'] = self.position_2['TP_level'] + 1
                            # self.position['get_amount'] = round(self.position['get_amount'] - self.position['get_half'],3)
                            self.position_2['Win'] = self.position_2['Win'] + 0.5
                            self.position_2['get_half'] = 0
                            print(f"✅ 알림\n{self.unit} 숏 포지션 1차 익절 완료 !!!_2\nTP : {self.position_2['TP_1st']}")     
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)                       
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 숏 포지션 1차 익절 완료 !!!_2\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()                      
                            self.position_2['transfer'] = 'on'

                        elif self.position_2['TP_2nd'] > 0 and self.cur_price <= self.position_2['TP_2nd'] and self.position_2['TP_level'] == 2:
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)                         
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                    amount= self.position_2['amount'],
                                    params = {'positionSide': 'SHORT',})
                            if self.position_2['times'] >= 2:
                                self.position_2['type'] = "cooling"
                            else:
                                self.position_2['type'] = None
                            self.position_2['type_ext'] = None
                            self.position_2['amount'] = 0
                            self.position_2['get_amount'] = 0
                            self.position_2['split'] = 0
                            self.position_2['TP_1st'] = 0
                            self.position_2['TP_2nd'] = 0
                            self.position_2['SL_1st'] = 0
                            self.position_2['avgPrice'] = 0
                            self.position_2['TP_level'] = 1
                            self.position_2['Win'] = self.position_2['Win'] + 0.5
                            self.liquidation_price_2 = 0
                            print(f"✅ 알림\n{self.unit} 숏 포지션 2차 익절 완료 !!!_2\nTP : {self.position_2['TP_1st']}")   
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)                         
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 숏 포지션 2차 익절 완료 !!!_2\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()                           
                            self.position_2['transfer'] = 'on'
            await asyncio.sleep(0.3)
            
    # 포지션 정리 (SL)
    @wrap_task()
    async def exit_position_SL(self):
        while self.running:
            self.ensure_lock()
            async with self.lock:
                if self.websocket.price is not None and self.is_rest == False:
                    if self.position['type'] == 'long' and self.position['amount'] > 0 and self.position['SL_1st'] > 0 and self.cur_price > 0:
                        if round(self.position['SL_1st'] / 2,self.decimal_place) <= self.cur_price <= self.position['SL_1st']: 
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                    amount= self.position['amount'],
                                    params = {'positionSide': 'LONG',})
                            if self.position['times'] >= 2:
                                self.position['type'] = "cooling"
                            if self.position['times'] == 1:
                                self.position['type'] = "half_cooling"
                            else:
                                self.position['type'] = None
                            self.position['amount'] = 0
                            self.position['get_amount'] = 0
                            self.position['get_half'] = 0
                            self.position['split'] = 0
                            self.position['SL_1st'] = 0
                            self.position['TP_1st'] = 0
                            self.position['TP_2nd'] = 0
                            self.position['avgPrice'] = 0
                            self.position['type_ext'] = None
                            self.position['TP_level'] = 1
                            self.position['Lose'] = self.position['Lose'] + 1
                            self.liquidation_price = 0
                            print(f"✅ 알림롱 포지션 손절 완료 !!!{self.fib_level}")
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 롱 포지션 손절 완료 ㅠㅠ\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                            self.position['stoploss'] = 'on'
                    elif self.position['type'] == 'short' and self.position['amount'] > 0 and self.position['SL_1st'] > 0 and self.cur_price > 0:
                        if round(self.position['SL_1st'] * 2,self.decimal_place) >= self.cur_price >= self.position['SL_1st']: 
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3) 
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                    amount= self.position['amount'],
                                    params = {'positionSide': 'SHORT',})
                            if self.position['times'] >= 2:
                                self.position['type'] = "cooling"
                            if self.position['times'] == 1:
                                self.position['type'] = "half_cooling"
                            else:
                                self.position['type'] = None
                            self.position['amount'] = 0
                            self.position['get_amount'] = 0
                            self.position['get_half'] = 0
                            self.position['split'] = 0
                            self.position['SL_1st'] = 0
                            self.position['TP_1st'] = 0
                            self.position['TP_2nd'] = 0
                            self.position['avgPrice'] = 0
                            self.position['type_ext'] = None
                            self.position['TP_level'] = 1
                            self.position['Lose'] = self.position['Lose'] + 1
                            self.liquidation_price_R = 0
                            print(f"✅ 알림 숏 포지션 손절 완료 !!!{self.fib_level}")
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 숏 포지션 손절 완료 ㅠㅠ\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                            self.position['stoploss'] = 'on'

                    ### Reverse
                    if self.position_R['type'] == 'long' and self.cur_price > 0 and self.position_R['amount'] > 0 and self.position_R['SL_1st'] > 0:
                        if round(self.position_R['SL_1st'] / 2,self.decimal_place) <= self.cur_price <= self.position_R['SL_1st']: 
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                    amount= self.position_R['amount'],
                                    params = {'positionSide': 'LONG',})
                            if self.position_R['times'] >= 2:
                                self.position_R['type'] = "cooling"
                            if self.position_R['times'] == 1:
                                self.position_R['type'] = "half_cooling"
                            else:
                                self.position_R['type'] = None
                            self.position_R['amount'] = 0
                            self.position_R['get_amount'] = 0
                            self.position_R['get_half'] = 0
                            self.position_R['SL_1st'] = 0
                            self.position_R['TP_1st'] = 0
                            self.position_R['TP_2nd'] = 0
                            self.position_R['avgPrice'] = 0
                            self.position_R['TP_level'] = 1
                            self.position_R['Lose'] = self.position_R['Lose'] + 1
                            self.liquidation_price_R = 0
                            print(f"✅ 알림역 롱 포지션 손절 완료 !!!{self.fib_level}")  
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)                          
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 역 롱 포지션 손절 완료 ㅠㅠ\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                            self.position_R['stoploss'] = 'on'
                    elif self.position_R['type'] == 'short' and self.cur_price > 0 and self.position_R['amount'] > 0 and self.position_R['SL_1st'] > 0:
                        if round(self.position_R['SL_1st'] * 2,self.decimal_place) >= self.cur_price >= self.position_R['SL_1st']: 
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                    amount= self.position_R['amount'],
                                    params = {'positionSide': 'SHORT',})
                            if self.position_R['times'] >= 2:
                                self.position_R['type'] = "cooling"
                            if self.position_R['times'] == 1:
                                self.position_R['type'] = "half_cooling"
                            else:
                                self.position_R['type'] = None
                            self.position_R['amount'] = 0
                            self.position_R['get_amount'] = 0
                            self.position_R['get_half'] = 0
                            self.position_R['SL_1st'] = 0
                            self.position_R['TP_1st'] = 0
                            self.position_R['TP_2nd'] = 0
                            self.position_R['avgPrice'] = 0
                            self.position_R['TP_level'] = 1
                            self.position_R['Lose'] = self.position_R['Lose'] + 1
                            self.liquidation_price_R = 0
                            print(f"✅ 알림역 숏 포지션 손절 완료 !!!{self.fib_level}")   
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)                        
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 역 숏 포지션 손절 완료 ㅠㅠ\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                            self.position_R['stoploss'] = 'on'

                    ### fibRe2
                    if self.position_2['type'] == 'long' and self.cur_price > 0 and self.position_2['amount'] > 0 and self.position_2['SL_1st'] > 0:
                        if round(self.position_2['SL_1st'] / 2,self.decimal_place) <= self.cur_price <= self.position_2['SL_1st']:
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_sell_order(symbol=self.symbol,
                                    amount= self.position_2['amount'],
                                    params = {'positionSide': 'LONG',})
                            if self.position_2['times'] >= 2:
                                self.position_2['type'] = "cooling"
                            if self.position_2['times'] == 1:
                                self.position_2['type'] = "half_cooling"
                            else:
                                self.position_2['type'] = None
                            self.position_2['amount'] = 0
                            self.position_2['get_amount'] = 0
                            self.position_2['get_half'] = 0
                            self.position_2['split'] = 0
                            self.position_2['SL_1st'] = 0
                            self.position_2['TP_1st'] = 0
                            self.position_2['TP_2nd'] = 0
                            self.position_2['avgPrice'] = 0
                            self.position_2['type_ext'] = None
                            self.position_2['TP_level'] = 1
                            self.position_2['Lose'] = self.position_2['Lose'] + 1
                            self.liquidation_price_2 = 0
                            print(f"✅ 알림롱 포지션 손절 완료 !!!_2{self.fib_level}")
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 롱 포지션 손절 완료 ㅠㅠ_2\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                            self.position_2['stoploss'] = 'on'
                    elif self.position_2['type'] == 'short' and self.position_2['amount'] > 0 and self.position_2['SL_1st'] > 0 and self.cur_price > 0:
                        if round(self.position_2['SL_1st'] * 2,self.decimal_place) >= self.cur_price >= self.position_2['SL_1st']: 
                            self.timestamp = int(datetime.now().timestamp() * 1000)
                            await asyncio.sleep(0.3)
                            self.exchange.create_market_buy_order(symbol=self.symbol,
                                    amount= self.position_2['amount'],
                                    params = {'positionSide': 'SHORT',})
                            if self.position_2['times'] >= 2:
                                self.position_2['type'] = "cooling"
                            if self.position_2['times'] == 1:
                                self.position_2['type'] = "half_cooling"
                            else:
                                self.position_2['type'] = None
                            self.position_2['amount'] = 0
                            self.position_2['get_amount'] = 0
                            self.position_2['get_half'] = 0
                            self.position_2['split'] = 0
                            self.position_2['SL_1st'] = 0
                            self.position_2['TP_1st'] = 0
                            self.position_2['TP_2nd'] = 0
                            self.position_2['avgPrice'] = 0
                            self.position_2['type_ext'] = None
                            self.position_2['TP_level'] = 1
                            self.position_2['Lose'] = self.position_2['Lose'] + 1
                            self.liquidation_price_2 = 0
                            print(f"✅ 알림 숏 포지션 손절 완료 !!!_2{self.fib_level}")
                            self.fees = await self.cal_fees()
                            self.total_fees = round(self.total_fees + self.fees,4)
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 숏 포지션 손절 완료 ㅠㅠ_2\n수수료 : {self.fees}$')
                            self.balance = self.exchange.fetch_balance()
                            self.position_2['stoploss'] = 'on'
            await asyncio.sleep(0.3)

    # 포지션 분할 진입
    @wrap_task()
    async def split_purchasing(self):
        while self.running:
            self.ensure_lock()
            async with self.lock:
                if self.websocket.price is not None and self.is_rest == False:
                    if self.position['type'] != None and self.position['split'] <= 2 and self.position['amount'] > 0 and self.cur_price > 0:
                        if self.position['type'] == 'long':
                            print("롱 분할 매수 대기중")
                            if self.Sub_target > self.cur_price > self.Last_target and self.position['split'] == 1:
                                self.timestamp = int(datetime.now().timestamp() * 1000)
                                await asyncio.sleep(0.3)
                                self.exchange.create_market_buy_order(symbol=self.symbol,
                                amount=self.position['amount'], 
                                params = {'positionSide': 'LONG',})
                                self.position['TP_1st'] = self.long_target
                                self.position['TP_2nd'] = self.TP_1st
                                print("롱 2차 진입완료 !!!", self.position)
                                self.fees = await self.cal_fees()
                                self.total_fees = round(self.total_fees + self.fees,4)
                                self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 롱 2차 진입완료 !!!\n수수료 : {self.fees}$')
                                self.balance = self.exchange.fetch_balance()
                                self.position['split'] = self.position['split'] + 1
                            if self.Last_target > 0 and self.Last_target > self.cur_price and self.position['split'] == 2:
                                self.timestamp = int(datetime.now().timestamp() * 1000)
                                await asyncio.sleep(0.3)
                                self.exchange.create_market_buy_order(symbol=self.symbol,
                                    amount=self.position['amount'], 
                                    params = {'positionSide': 'LONG',})
                                self.position['TP_1st'] = self.fibRe[13]
                                self.position['TP_2nd'] = self.long_target
                                self.position['split'] = self.position['split'] + 1
                                print("롱 3차 진입완료 !!!", self.position)
                                self.fees = await self.cal_fees()
                                self.total_fees = round(self.total_fees + self.fees,4)
                                self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 롱 3차 진입완료 !!!\n수수료 : {self.fees}$')
                                self.balance = self.exchange.fetch_balance()
                        if self.position['type'] == 'short':
                            print("숏 분할 매수 대기중")
                            if self.Sub_target < self.cur_price < self.Last_target and self.position['split'] == 1:
                                self.timestamp = int(datetime.now().timestamp() * 1000)
                                await asyncio.sleep(0.3)
                                self.exchange.create_market_sell_order(symbol=self.symbol,
                                    amount=self.position['amount'], 
                                    params = {'positionSide': 'SHORT'})
                                self.position['TP_1st'] = self.short_target
                                self.position['TP_2nd'] = self.TP_1st
                                print("숏 2차 진입완료 !!!", self.position)
                                self.fees = await self.cal_fees()
                                self.total_fees = round(self.total_fees + self.fees,4)
                                self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 숏 2차 진입완료 !!!\n수수료 : {self.fees}$')
                                self.balance = self.exchange.fetch_balance()
                                self.position['split'] = self.position['split'] + 1
                            if self.Last_target > 0 and self.Last_target < self.cur_price and self.position['split'] == 2:
                                self.timestamp = int(datetime.now().timestamp() * 1000)
                                await asyncio.sleep(0.3)
                                self.exchange.create_market_sell_order(symbol=self.symbol,
                                    amount=self.position['amount'], 
                                    params = {'positionSide': 'SHORT'})
                                self.position['TP_1st'] = self.fibRe[13]
                                self.position['TP_2nd'] = self.short_target
                                self.position['split'] = self.position['split'] + 1
                                print("숏 3차 진입완료 !!!", self.position)
                                self.fees = await self.cal_fees()
                                self.total_fees = round(self.total_fees + self.fees,4)
                                self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 숏 3차 진입완료 !!!\n수수료 : {self.fees}$')
                                self.balance = self.exchange.fetch_balance()

                    ### fibRe2
                    if self.position_2['type'] != None and self.position_2['split'] <= 2 and self.position_2['amount'] > 0 and self.cur_price > 0:
                        if self.position_2['type'] == 'long':
                            print("fibRe2 롱 분할 매수 대기중")
                            if self.Sub_target_2 > self.cur_price > self.Last_target_2 and self.position_2['split'] == 1:
                                self.timestamp = int(datetime.now().timestamp() * 1000)
                                await asyncio.sleep(0.3)
                                self.exchange.create_market_buy_order(symbol=self.symbol,
                                amount=self.position_2['amount'], 
                                params = {'positionSide': 'LONG',})
                                self.position_2['TP_1st'] = self.long_target_2
                                self.position_2['TP_2nd'] = self.TP_1st_2
                                print("롱 2차 진입완료 !!!_2", self.position_2)
                                self.fees = await self.cal_fees()
                                self.total_fees = round(self.total_fees + self.fees,4)
                                self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 롱 2차 진입완료 !!!_2\n수수료 : {self.fees}$')
                                self.balance = self.exchange.fetch_balance()
                                self.position_2['split'] = self.position_2['split'] + 1
                            if self.Last_target_2 > 0 and self.Last_target_2 > self.cur_price and self.position_2['split'] == 2:
                                self.timestamp = int(datetime.now().timestamp() * 1000)
                                await asyncio.sleep(0.3)
                                self.exchange.create_market_buy_order(symbol=self.symbol,
                                    amount=self.position_2['amount'], 
                                    params = {'positionSide': 'LONG',})
                                self.position_2['TP_1st'] = self.fibRe2[13]
                                self.position_2['TP_2nd'] = self.long_target_2
                                self.position_2['split'] = self.position_2['split'] + 1
                                print("롱 3차 진입완료 !!!_2", self.position_2)
                                self.fees = await self.cal_fees()
                                self.total_fees = round(self.total_fees + self.fees,4)
                                self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 롱 3차 진입완료 !!!_2\n수수료 : {self.fees}$')
                                self.balance = self.exchange.fetch_balance()
                        if self.position_2['type'] == 'short':
                            print("fibRe2 숏 분할 매수 대기중")
                            if self.Sub_target_2 < self.cur_price < self.Last_target_2 and self.position_2['split'] == 1:
                                self.timestamp = int(datetime.now().timestamp() * 1000)
                                await asyncio.sleep(0.3)
                                self.exchange.create_market_sell_order(symbol=self.symbol,
                                    amount=self.position_2['amount'], 
                                    params = {'positionSide': 'SHORT'})
                                self.position_2['TP_1st'] = self.short_target_2
                                self.position_2['TP_2nd'] = self.TP_1st_2
                                print("숏 2차 진입완료 !!!_2", self.position_2)
                                self.fees = await self.cal_fees()
                                self.total_fees = round(self.total_fees + self.fees,4)
                                self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 숏 2차 진입완료 !!!_2\n수수료 : {self.fees}$')
                                self.balance = self.exchange.fetch_balance()
                                self.position_2['split'] = self.position_2['split'] + 1
                            if self.Last_target_2 > 0 and self.Last_target_2 < self.cur_price and self.position_2['split'] == 2:
                                self.timestamp = int(datetime.now().timestamp() * 1000)
                                await asyncio.sleep(0.3)
                                self.exchange.create_market_sell_order(symbol=self.symbol,
                                    amount=self.position_2['amount'], 
                                    params = {'positionSide': 'SHORT'})
                                self.position_2['TP_1st'] = self.fibRe2[13]
                                self.position_2['TP_2nd'] = self.short_target_2
                                self.position_2['split'] = self.position_2['split'] + 1
                                print("숏 3차 진입완료 !!!_2", self.position_2)
                                self.fees = await self.cal_fees()
                                self.total_fees = round(self.total_fees + self.fees,4)
                                self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.unit} 숏 3차 진입완료 !!!_2\n수수료 : {self.fees}$')
                                self.balance = self.exchange.fetch_balance()
            await asyncio.sleep(0.3)
    @wrap_task()
    async def other_task(self):
        while self.running:
            # 실현손익 분할전송
            if self.position['transfer'] == 'on' and self.timestamp > 0:
                self.retries = 5
                for attempt in range(self.retries):
                    self.order_structure = self.exchange.fetch_my_trades(self.symbol, since=self.timestamp, limit=100, params={})
                    self.pnl_usdt = [
                        float(i['info'].get('realizedPnl', 0))
                        for i in self.order_structure
                        if ( 
                            (i['info']['positionSide'] == 'LONG' and i['info']['side'] == 'SELL')
                            or (i['info']['positionSide'] == 'SHORT' and i['info']['side'] == 'BUY')
                        )
                    ]
                    if self.pnl_usdt and sum(self.pnl_usdt) > 0:
                        self.total_pnl = round(sum(self.pnl_usdt), 4)    
                        self.total_pnl = round(self.total_pnl - self.total_fees,4)
                        active_tasks[self.user_id]["realizedPnl"] = round(active_tasks[self.user_id]["realizedPnl"] + self.total_pnl,4)
                        self.transfer_usdt = round(self.total_pnl / 3,4)
                        if self.transfer_usdt > 0:
                            self.exchange.transfer('USDT', self.transfer_usdt,'future','spot')
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.transfer_usdt}$ 전송완료 !!!\
                            \n실현손익 : {self.total_pnl}$\n차감된 수수료 : {self.total_fees}$\n오늘 총 실현손익 : {active_tasks[self.user_id]["realizedPnl"]}$')
                            self.total_pnl = 0 
                            self.transfer_usdt = 0
                            self.total_fees = 0
                            self.position['transfer'] = None
                        break
                    if attempt < self.retries - 1:
                        await asyncio.sleep(2)
                else:
                    self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n발견된 실현손익이 없습니다\npnl_usdt : {self.pnl_usdt}\
                    \n실현손익 : {self.total_pnl}$\n오늘 총 실현손익 : {active_tasks[self.user_id]["realizedPnl"]}$\ntime : {self.timestamp}')
                    self.total_fees = 0
                    self.position['transfer'] = None
            if self.position_2['transfer'] == 'on' and self.timestamp > 0:
                self.retries = 5
                for attempt in range(self.retries):
                    self.order_structure = self.exchange.fetch_my_trades(self.symbol, since=self.timestamp, limit=100, params={})
                    self.pnl_usdt = [
                        float(i['info'].get('realizedPnl', 0))
                        for i in self.order_structure
                        if ( 
                            (i['info']['positionSide'] == 'LONG' and i['info']['side'] == 'SELL')
                            or (i['info']['positionSide'] == 'SHORT' and i['info']['side'] == 'BUY')
                        )
                    ]
                    if self.pnl_usdt and sum(self.pnl_usdt) > 0:
                        self.total_pnl = round(sum(self.pnl_usdt), 4)    
                        self.total_pnl = round(self.total_pnl - self.total_fees,4)
                        active_tasks[self.user_id]["realizedPnl"] = round(active_tasks[self.user_id]["realizedPnl"] + self.total_pnl,4)
                        self.transfer_usdt = round(self.total_pnl / 3,4)
                        if self.transfer_usdt > 0:
                            self.exchange.transfer('USDT', self.transfer_usdt,'future','spot')
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.transfer_usdt}$ 전송완료 !!!\
                            \n실현손익 : {self.total_pnl}$\n차감된 수수료 : {self.total_fees}$\n오늘 총 실현손익 : {active_tasks[self.user_id]["realizedPnl"]}$')
                            self.total_pnl = 0 
                            self.transfer_usdt = 0
                            self.total_fees = 0
                            self.position_2['transfer'] = None
                        break
                    if attempt < self.retries - 1:
                        await asyncio.sleep(2)
                else:
                    self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n발견된 실현손익이 없습니다\npnl_usdt : {self.pnl_usdt}\
                    \n실현손익 : {self.total_pnl}$\n오늘 총 실현손익 : {active_tasks[self.user_id]["realizedPnl"]}$\ntime : {self.timestamp}')
                    self.total_fees = 0
                    self.position_2['transfer'] = None
            if self.position_R['transfer'] == 'on' and self.timestamp > 0:
                self.retries = 5
                for attempt in range(self.retries):
                    self.order_structure = self.exchange.fetch_my_trades(self.symbol, since=self.timestamp, limit=100, params={})
                    self.pnl_usdt = [
                        float(i['info'].get('realizedPnl', 0))
                        for i in self.order_structure
                        if ( 
                            (i['info']['positionSide'] == 'LONG' and i['info']['side'] == 'SELL')
                            or (i['info']['positionSide'] == 'SHORT' and i['info']['side'] == 'BUY')
                        )
                    ]
                    if self.pnl_usdt and sum(self.pnl_usdt) > 0:
                        self.total_pnl = round(sum(self.pnl_usdt), 4)    
                        self.total_pnl = round(self.total_pnl - self.total_fees,4)
                        active_tasks[self.user_id]["realizedPnl"] = round(active_tasks[self.user_id]["realizedPnl"] + self.total_pnl,4)
                        self.transfer_usdt = round(self.total_pnl / 3,4)
                        if self.transfer_usdt > 0:
                            self.exchange.transfer('USDT', self.transfer_usdt,'future','spot')
                            self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n{self.transfer_usdt}$ 전송완료 !!!\
                            \n실현손익 : {self.total_pnl}$\n차감된 수수료 : {self.total_fees}$\n오늘 총 실현손익 : {active_tasks[self.user_id]["realizedPnl"]}$')
                            self.total_pnl = 0 
                            self.transfer_usdt = 0
                            self.total_fees = 0
                            self.position_R['transfer'] = None
                        break
                    if attempt < self.retries - 1:
                        await asyncio.sleep(2)
                else:
                    self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n발견된 실현손익이 없습니다\npnl_usdt : {self.pnl_usdt}\
                    \n실현손익 : {self.total_pnl}$\n오늘 총 실현손익 : {active_tasks[self.user_id]["realizedPnl"]}$\ntime : {self.timestamp}')
                    self.total_fees = 0
                    self.position_R['transfer'] = None
            # 손절 금액 알림 메세지
            if self.position['stoploss'] == 'on' and self.timestamp > 0:
                self.retries = 5
                for attempt in range(self.retries):
                    self.order_structure = self.exchange.fetch_my_trades(self.symbol, since=self.timestamp, limit=100, params={})
                    self.pnl_usdt = [
                        float(i['info'].get('realizedPnl', 0))
                        for i in self.order_structure
                        if ( 
                            (i['info']['positionSide'] == 'LONG' and i['info']['side'] == 'SELL')
                            or (i['info']['positionSide'] == 'SHORT' and i['info']['side'] == 'BUY')
                        )
                    ]
                    if self.pnl_usdt:
                        self.total_pnl = round(sum(self.pnl_usdt), 4)    
                        self.total_pnl = round(self.total_pnl - self.total_fees,4)
                        active_tasks[self.user_id]["realizedPnl"] = round(active_tasks[self.user_id]["realizedPnl"] + self.total_pnl,4)
                        self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n손절금액 : {self.total_pnl}$ ㅠㅠ\
                        \n오늘 총 실현손익 : {active_tasks[self.user_id]["realizedPnl"]}$\n차감된 총 수수료 : {self.total_fees}$')
                        self.total_pnl = 0
                        self.total_fees = 0
                        self.position['stoploss'] = None
                        if self.position['type'] == "half_cooling":
                            self.position['type'] = None
                        break
                    if attempt < self.retries - 1:
                        await asyncio.sleep(2)
                else:
                    self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n발견된 손실금액이 없습니다\npnl_usdt : {self.pnl_usdt}\
                    \n실현손익 : {self.total_pnl}$\n오늘 총 실현손익 : {active_tasks[self.user_id]["realizedPnl"]}$\ntime : {self.timestamp}')
                    if self.position['type'] == "half_cooling":
                        self.position['type'] = None
                    self.total_fees = 0
                    self.position['stoploss'] = None
            if self.position_2['stoploss'] == 'on' and self.timestamp > 0:
                self.retries = 5
                for attempt in range(self.retries):
                    self.order_structure = self.exchange.fetch_my_trades(self.symbol, since=self.timestamp, limit=100, params={})
                    self.pnl_usdt = [
                        float(i['info'].get('realizedPnl', 0))
                        for i in self.order_structure
                        if ( 
                            (i['info']['positionSide'] == 'LONG' and i['info']['side'] == 'SELL')
                            or (i['info']['positionSide'] == 'SHORT' and i['info']['side'] == 'BUY')
                        )
                    ]
                    if self.pnl_usdt:
                        self.total_pnl = round(sum(self.pnl_usdt), 4)    
                        self.total_pnl = round(self.total_pnl - self.total_fees,4)
                        active_tasks[self.user_id]["realizedPnl"] = round(active_tasks[self.user_id]["realizedPnl"] + self.total_pnl,4)
                        self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n손절금액 : {self.total_pnl}$ ㅠㅠ\
                        \n오늘 총 실현손익 : {active_tasks[self.user_id]["realizedPnl"]}$\n차감된 총 수수료 : {self.total_fees}$')
                        self.total_pnl = 0
                        self.total_fees = 0
                        self.position_2['stoploss'] = None
                        if self.position_2['type'] == "half_cooling":
                            self.position_2['type'] = None
                        break
                    if attempt < self.retries - 1:
                        await asyncio.sleep(2)
                else:
                    self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n발견된 손실금액이 없습니다\npnl_usdt : {self.pnl_usdt}\
                    \n실현손익 : {self.total_pnl}$\n오늘 총 실현손익 : {active_tasks[self.user_id]["realizedPnl"]}$\ntime : {self.timestamp}')
                    if self.position_2['type'] == "half_cooling":
                        self.position_2['type'] = None
                    self.total_fees = 0
                    self.position_2['stoploss'] = None
            if self.position_R['stoploss'] == 'on' and self.timestamp > 0:
                self.retries = 5
                for attempt in range(self.retries):
                    self.order_structure = self.exchange.fetch_my_trades(self.symbol, since=self.timestamp, limit=100, params={})
                    self.pnl_usdt = [
                        float(i['info'].get('realizedPnl', 0))
                        for i in self.order_structure
                        if ( 
                            (i['info']['positionSide'] == 'LONG' and i['info']['side'] == 'SELL')
                            or (i['info']['positionSide'] == 'SHORT' and i['info']['side'] == 'BUY')
                        )
                    ]
                    if self.pnl_usdt:
                        self.total_pnl = round(sum(self.pnl_usdt), 4)    
                        self.total_pnl = round(self.total_pnl - self.total_fees,4)
                        active_tasks[self.user_id]["realizedPnl"] = round(active_tasks[self.user_id]["realizedPnl"] + self.total_pnl,4)
                        self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n손절금액 : {self.total_pnl}$ ㅠㅠ\
                        \n오늘 총 실현손익 : {active_tasks[self.user_id]["realizedPnl"]}$\n차감된 총 수수료 : {self.total_fees}$')
                        self.total_pnl = 0
                        self.total_fees = 0
                        self.position_R['stoploss'] = None
                        if self.position_R['type'] == "half_cooling":
                            self.position_R['type'] = None
                        break
                    if attempt < self.retries - 1:
                        await asyncio.sleep(2)
                else:
                    self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n발견된 손실금액이 없습니다\npnl_usdt : {self.pnl_usdt}\
                    \n실현손익 : {self.total_pnl}$\n오늘 총 실현손익 : {active_tasks[self.user_id]["realizedPnl"]}$\ntime : {self.timestamp}')
                    if self.position_R['type'] == "half_cooling":
                        self.position_R['type'] = None
                    self.total_fees = 0
                    self.position_R['stoploss'] = None
            await asyncio.sleep(0.5)
    # 실행문
    @wrap_task()
    async def start(self):
        while self.running:
            if self.websocket.price is not None:
                self.cur_price = round(self.websocket.price,self.decimal_place)
                coin_trading.instances[self.user_id] = {'symbol': self.symbol}
                self.free_usdt = self.balance['free']['USDT']
                self.total_usdt = self.balance['total']['USDT']
                # print(coin_trading.instances)

                # 현재 UTC 시간 가져오기
                utc_now = datetime.utcnow()

                # UTC 시간에 9시간 더해 한국 시간으로 변환
                kst_now = utc_now + timedelta(hours=9)

                self.long_target, self.short_target, self.Sub_target, self.reverse_target, self.Sub_rtarget, self.fibRe, self.recommend,\
                self.fib_level ,self.alram_date1, self.alram_date2 , self.TP_1st, self.TP_2nd, self.SL_1st, self.Last_target,\
                self.target_1618, self.target_1414, self.target_1272, self.target_113, self.target_1, self.target_1618_2, self.target_1414_2,\
                self.target_1272_2, self.target_113_2, self.target_1_2, self.new_recommend, self.fibRe2,\
                self.long_target_2, self.short_target_2, self.Sub_target_2, self.Last_target_2,\
                self.TP_1st_2, self.TP_2nd_2, self.SL_1st_2, self.target_2, self.target_2_2,self.target_213,self.target_213_2,\
                self.Sub_TP, self.decimal_place,self.list_1618,self.num_high, self.num_low, self.df = self.fib_target.cal_target_mixed(self.exchange,self.symbol,self.period,self.timeframe,self.fib_level)
                
                # 역방향 가격 세팅
                self.target_cal = (self.Sub_rtarget + self.reverse_target)/2
                self.target_cal_gap = self.target_cal * 0.005
                self.target_over = self.target_cal + self.target_cal_gap
                self.target_under = self.target_cal - self.target_cal_gap

                self.df_datetime = self.df.sort_values(by=["datetime"],ascending=False)
                self.df_date = self.df_datetime.iloc[0,0]

                if self.rsi_position['date'] == 0:
                    if self.period_switch == 'off':
                        self.period_switch = 'on'
                        self.rsi_position['date'] = self.df_date
                if self.rsi_position['date'] < self.df_date:
                    if self.period_switch == 'off':
                        self.period_switch = 'on'
                        self.rsi_position['date'] = self.df_date
                if self.df_date >= self.rsi_position['date'] and self.period_switch == 'on':
                    self.period += 1
                    self.period_switch = 'off'

            
                if self.recommend == "롱 추천":
                    self.targetprice = self.long_target
                    self.highprice =  self.fibRe[11]
                    self.lowprice =  self.fibRe[4]
                else:
                    self.targetprice = self.short_target
                    self.highprice =  self.fibRe[4]
                    self.lowprice =  self.fibRe[11]

                if self.reboot_detect == True:
                    self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n프로그램을 재부팅 완료.{self.period}')
                    self.reboot_detect = False
                
                if self.user_id in active_tasks:
                    self.is_rest = active_tasks[self.user_id].get("rest_time")
                
                # 이전 거래 확인
                if self.data_check is None:
                    self.check_pos = await self.check_position() # 현재 포지션 보유 유무 확인
                    if self.check_pos:
                        self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n보유중인 {self.unit} 포지션이 있습니다.')
                        self.data_check = True
                    else:
                        self.user_bot.sendMessage(chat_id=self.user_bot_id, text= f'✅ 알림\n보유중인 {self.unit} 포지션이 없습니다.')
                        self.data_check = False
                if self.free_usdt > 0 and self.is_rest == False:
                    pass
                elif self.is_rest == True:
                    print('매매 휴식중...')
                else:
                    print('사용 가능한 잔고가 없습니다.')
                    await asyncio.sleep(5)
                # print(f"⚠️ 현재 실행 중인 인스턴스 id: {id(self)} {self.symbol}")
                await self.send_trade_update()
            await asyncio.sleep(0.3)
            
    # 텔레그램 봇 조건 메세지
    def condition(self,update,context):
        context.bot.send_message(chat_id=update.effective_chat.id,\
        text=f"✅ 전략 조건 알림\n{self.alram_date1}\n{self.alram_date2}\
            \n1({self.fibRe[4]})\n0.886({self.fibRe[5]})\n0.786({self.fibRe[6]})\n0.618({self.fibRe[7]})\n0.5({self.fibRe[8]})\
            \n0.382({self.fibRe[9]})\n0.236({self.fibRe[10]})\n0({self.fibRe[11]})\n{self.recommend}\
            되돌림 포인트 : {self.fib_level_name}\
            \n[포지션] : {self.position}\n[역포지션] : {self.position_R}\
            \n[포지션2] : {self.position_2}\n[fibRe2] : {self.fibRe2}\n {self.period} {self.timeframe}\n청산가격 : {self.liquidation_price}, {self.liquidation_price_2}_2, {self.liquidation_price_R}_R\
            \n📥 /btc 핸들러에서 참조한 인스턴스 id: {id(self)}")
    
    def onoff(self, update, context):
        """텔레그램 상태 확인 명령"""
        self.check_status()
        
        if self.is_running:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"✅ 알림\n프로그램 정상 작동 중 입니다"
            )

        else:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⚠️ 경고\n프로그램이 응답하지 않습니다. 문제가 발생한 것 같습니다."
            )

    def exit(self,update,context):
        context.bot.send_message(chat_id=update.effective_chat.id,\
        text=f"✅ 알림\n프로그램이 정상 종료되었습니다.")
        # for instance in coin_trading.instances:
        #     instance.delete_log_file()
        os._exit(0)
    
    def reboot(self,update,context):
        context.bot.send_message(chat_id=update.effective_chat.id,\
        text=f"✅ 알림\n프로그램을 재부팅 하겠습니다.")
        self.reboot_detect = True
        python = sys.executable  # 현재 실행 중인 파이썬 실행 파일 경로
        os.execv(python, ["python"] + sys.argv)

    def change_period(self,update,context):
        try:
        # 명령어에서 숫자 부분 추출
            self.new_period = int(context.args[0])  # /에서 숫자만 추출
            context.bot.send_message(chat_id=update.effective_chat.id,\
            text=f"✅ 알림\n{self.unit} period 값 {self.period} -> {self.new_period}(으)로 변경완료.")
            self.period = self.new_period
        except (IndexError, ValueError):
        # 숫자가 없거나 잘못된 경우 처리
            context.bot.send_message(chat_id=update.effective_chat.id,\
            text=f"✅ 알림\n올바른 숫자를 입력해주세요. 예: /coin_ 10.")
    
    def change_leverage(self,update,context):
        try:
        # 명령어에서 숫자 부분 추출
            self.new_leverage = int(context.args[0])  # /에서 숫자만 추출
            context.bot.send_message(chat_id=update.effective_chat.id,\
            text=f"✅ 알림\n{self.unit} leverage 값 {self.leverage} -> {self.new_leverage}(으)로 변경완료.")
            self.leverage = self.new_leverage
            market = self.exchange.market(self.symbol)
            resp = self.exchange.fapiPrivate_post_leverage({
            'symbol': market['id'],
            'leverage': self.leverage
            })
        except (IndexError, ValueError):
        # 숫자가 없거나 잘못된 경우 처리
            context.bot.send_message(chat_id=update.effective_chat.id,\
            text=f"✅ 알림\n올바른 숫자를 입력해주세요. 예: /coin_ 10.")

    def rest_time(self,update,context):
        context.bot.send_message(chat_id=update.effective_chat.id,\
        text=f"✅ 알림\n매매 휴식이 시작되었습니다")
        active_tasks[self.user_id]["rest_time"] = True
    
    def work_time(self,update,context):
        if self.is_rest == True:
            context.bot.send_message(chat_id=update.effective_chat.id,\
            text=f"✅ 알림\n매매 휴식이 종료되었습니다")
            active_tasks[self.user_id]["rest_time"] = False
        else:
            context.bot.send_message(chat_id=update.effective_chat.id,\
            text=f"✅ 알림\n매매 휴식중이 아닙니다.")
    
    def help(self,update,context):
        context.bot.send_message(chat_id=update.effective_chat.id,\
        text=f"✅ 알림\n/onoff : 프로그램 작동 여부\n/coin : 코인 거래 세부 정보\n/coin_ number : period 개수 변경\n/coinx number : 레버리지 변경\n/exit : 프로그램 종료\n/reboot : 프로그램 재부팅\n/rest : 프로그램 휴식\n/work : 프로그램 휴식 종료")

    def handler(self):
        """
        텔레그램 핸들러 등록
        항상 active_tasks[user_id]["bot_instance"]를 참조하도록 래핑된 핸들러 등록
        중복 방지를 위해 기존 핸들러 제거 후 재등록
        """
        dispatcher = user_bots.get(self.user_id, {}).get("dispatcher")
        def create_wrapped_handler(method_name):
            # 최신 인스턴스를 active_tasks에서 가져와 실행
            def handler_func(update, context):
                bot_instance = active_tasks.get(self.user_id, {}).get("bot_instance")
                if bot_instance:
                    method = getattr(bot_instance, method_name, None)
                    if method:
                        method(update, context)
                    else:
                        context.bot.send_message(chat_id=update.effective_chat.id,
                                                text=f"⚠️ '{method_name}' 핸들러를 찾을 수 없습니다.")
            return handler_func

        # 커맨드와 함수 이름 매핑
        command_map = {
            f"{self.unit.lower()}": "condition",
            "onoff": "onoff",
            "exit": "exit",
            "reboot": "reboot",
            f"{self.unit.lower()}_": "change_period",
            f"{self.unit.lower()}x": "change_leverage",
            "rest": "rest_time",
            "work": "work_time",
            "help": "help",
        }

        # 이미 등록된 핸들러 제거 및 새로 등록
        for command, method_name in command_map.items():
            handler = CommandHandler(command, create_wrapped_handler(method_name))
            try:
                dispatcher.remove_handler(handler)
            except:
                pass  # 제거 실패는 무시
            dispatcher.add_handler(handler)


    async def run(self, user_id: str, symbol_request: Dict):
        websocket_task = asyncio.create_task(self.start_websocket())
        cal_task_1 = asyncio.create_task(self.cal_Unlimited_Max_amount())
        cal_task_2 = asyncio.create_task(self.cal_amount_split())
        cal_task_3 = asyncio.create_task(self.cal_real_split_amount())
        trading_task_0 = asyncio.create_task(self.start())
        trading_task_1 = asyncio.create_task(self.enter_position())
        trading_task_2 = asyncio.create_task(self.enter_position_2())
        trading_task_3 = asyncio.create_task(self.split_purchasing())
        trading_task_4 = asyncio.create_task(self.exit_position_TP())
        trading_task_5 = asyncio.create_task(self.exit_position_SL())
        trading_task_6 = asyncio.create_task(self.other_task())
        trading_task_7 = asyncio.create_task(self.update_balance())
        await asyncio.gather(websocket_task, cal_task_1, cal_task_2, cal_task_3,\
                             trading_task_0, trading_task_1, trading_task_2,\
                             trading_task_3,trading_task_4,trading_task_5,trading_task_6,trading_task_7)


# BACKEND
class SymbolItem(BaseModel):
    symbol: str
    barCount: int
    timeframe: str
    leverage: int

class SymbolRequest(BaseModel):
    symbols: List[SymbolItem]

# 비동기 트레이딩 시작 API 엔드포인트

user_bots = {}  # 사용자별 봇 정보를 저장할 딕셔너리

# 현재 사용자 자동매매 상태 조회
@router.get("/trade_status/{user_id}")
async def get_trade_status(user_id: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == user_id).first()
    if not user:
        return {"message": "User not found", "is_trading": False}

    return {"is_trading": user.is_trading}  # 사용자 매매 상태 반환


# 작업 상태 확인 엔드포인트
@router.get("/task_status/{task_id}")
async def get_task_status(task_id: str):
    task = AsyncResult(task_id, app=celery_app)
    if task.state == "PENDING":
        return {"status": "pending"}
    elif task.state == "SUCCESS":
        return {"status": "success", "result": task.result}
    elif task.state == "FAILURE":
        return {"status": "failure", "error": task.result}  # 실패 시 에러 메시지
    return {"status": task.state}


@router.get("/futures_position/{user_id}")
async def get_position(user_id: str):
    first_coin = coin_trading(user_id,'ETH/USDT',500,'4h',7,20)
    second_coin = coin_trading(user_id,'BTC/USDT',500,'4h',7,20)
    position1 = await first_coin.check_position()  # 비동기 함수 호출
    position2 = await second_coin.check_position()  # 비동기 함수 호출
    return {
        "positions": {
            "ETH/USDT": position1 if position1 else "Position not found",
            "BTC/USDT": position2 if position1 else "Position not found"
        }
    }

# 심볼 변환 함수
def format_symbol(symbol):
    """Symbol에 / 를 추가해주는 함수"""
    return f"{symbol[:-4]}/{symbol[-4:]}"  # BTCUSDT -> BTC/USDT

def start_telegram(user_id: str, telegram_token: str, telegram_bot_id: str):
    """사용자별로 새로운 Updater 객체를 만들고 시작하는 함수"""
    
    bot = telegram.Bot(
        token=telegram_token,
        request=telegram.utils.request.Request(
            connect_timeout=10,  # 연결 대기 시간
            read_timeout=20,      # 읽기 대기 시간
            con_pool_size=30
        )
    )

    updater = Updater(bot=bot, use_context=True)
    dispatcher = updater.dispatcher

    user_bots[user_id] = {
        'bot': bot,
        'bot_id': telegram_bot_id,
        'updater': updater,
        'dispatcher': dispatcher  # ✅ 저장
    }
    user_bot_data = {'bot_id': telegram_bot_id, 'telegram_token': telegram_token}  # 사용자별 봇 정보를 저장
    redis_client.set(f"user_bot:{user_id}", json.dumps(user_bot_data))

    updater.start_polling()  # 텔레그램 봇 폴링 시작

@celery_app.task(bind=True)
def start_trading_task(self, user_id: str, symbols: List[SymbolItem], telegram_token: str, telegram_bot_id: str, binance_key: str, binance_secret: str):
    """
    Celery 작업으로 개별 사용자의 자동매매 실행
    """

    if user_id not in user_bots:
        print(f"❌ [ERROR] user_id {user_id}의 텔레그램 봇 정보가 없습니다.")
        start_telegram(user_id, telegram_token, telegram_bot_id)
        user_bot_data = redis_client.get(f"user_bot:{user_id}")
    else:
        print(f"✅ [DEBUG] {user_id} 텔레그램 봇이 이미 실행 되었습니다.")
    
    # user_bot_data = json.loads(user_bot_data)
    # user_telegram_token = user_bot_data["telegram_token"]
    # user_bot_id = user_bot_data["bot_id"]
    user_bot = user_bots.get(user_id, {}).get('bot')
    user_bot_id = user_bots.get(user_id, {}).get('bot_id')

    
    # 비동기 작업이 이미 존재하는지 확인
    if user_id in active_tasks:
        user_bot.sendMessage(chat_id=user_bot_id, text= f"⚠️ [{user_id}] 이미 자동매매가 진행 중입니다.")
        return {"status": "failed", "error": "자동매매 이미 실행 중"}
    
    # 비동기 작업 실행
    loop = asyncio.new_event_loop()  # 새로운 이벤트 루프 생성
    asyncio.set_event_loop(loop)  # 새로 생성한 이벤트 루프를 현재 스레드에 설정
    
    # 백그라운드 루프 실행
    threading.Thread(target=loop.run_forever, daemon=True).start()

    trading_tasks = []
    num_of_coins = len(symbols)
    for symbol in symbols:
        formatted_symbol = format_symbol(symbol["symbol"])
        bar_count = int(symbol.get("barCount", 500))
        timeframe = symbol.get("timeframe", "4h")
        leverage = int(symbol.get("leverage", 20))
        
        coin_trader = coin_trading(user_id, binance_key, binance_secret,
                                formatted_symbol, bar_count, timeframe, 7, leverage, num_of_coins)
        coin_trader.handler()
        task = asyncio.run_coroutine_threadsafe(coin_trader.run(user_id, {"symbol": symbol}), loop)
        trading_tasks.append(task)

    print(f"✅ [{user_id}] 자동매매 시작...")
    user_bot.sendMessage(chat_id=user_bot_id, text= f'✅ 알림\n[{user_id}]의 자동매매 프로그램이 시작되었습니다.\
    \n시작 잔고 : {round(coin_trader.total_usdt,2)}$')

    # Celery 작업과 asyncio Task 저장
    active_tasks.setdefault(user_id, {}).update({
        "bot_instance": coin_trader,
        "celery_task": self.request.id,
        "asyncio_tasks": trading_tasks,
        "loop": loop,
        "realizedPnl": 0,
        "rest_time": False
        })

    return {"status": "completed", "user_id": user_id, "symbols": symbols}
    
    # except Exception as e:
    #     print(f"❌ [{user_id}] {symbols} 자동매매 오류: {str(e)}")
    #     return {"status": "failed", "error": str(e)}

@celery_app.task(bind=True)
def stop_trading_task(self, user_id: str):
    """
    Celery 작업으로 개별 사용자의 자동매매 중지
    """
    if user_id not in active_tasks:
        print(f"❌ [{user_id}] 자동매매 작업이 실행 중이지 않습니다.")
        return {"status": "failed", "message": "자동매매 작업이 실행 중이지 않습니다."}
    
    user_bot = user_bots.get(user_id, {}).get('bot')
    user_bot_id = user_bots.get(user_id, {}).get('bot_id')

    task_info = active_tasks[user_id]
    celery_task_id = task_info.get("celery_task")
    asyncio_tasks = task_info.get("asyncio_task")
    loop = task_info.get("loop")

    # 🔥 1. Celery 작업 중지 (강제 종료)
    if celery_task_id:
        celery_task = AsyncResult(celery_task_id)
        if celery_task.state in ["PENDING", "STARTED", "RETRY"]:
            celery_task.revoke(terminate=True, signal="SIGTERM")
            print(f"⚠️ [{user_id}] Celery 작업 강제 종료")

    # 🔥 2. asyncio 작업 중지 (비동기 작업 취소)
    if asyncio_tasks:
        for task in asyncio_tasks:
            if not task.done():
                task.cancel()
                try:
                    loop.run_until_complete(task)  # 취소 확실하게 기다림
                except asyncio.CancelledError:
                    print(f"✅ [{user_id}] 비동기 작업 취소 완료")


    # 이벤트 루프 중지
    if loop and loop.is_running():
        loop.call_soon_threadsafe(loop.stop)
        user_bot.sendMessage(chat_id=user_bot_id, text= f"✅ [{user_id}] 프로그램 종료")
        print(f"⚠️ [{user_id}] asyncio 루프 중지 완료")

    # 🔥 3. active_tasks에서 제거
    if user_id in active_tasks:
        bot_instance = active_tasks[user_id].get("bot_instance")
        if bot_instance:
            del bot_instance  # 메모리에서 삭제 요청
        del active_tasks[user_id]

    print(f"✅ [{user_id}] 자동매매 작업이 종료되었습니다.")
    return {"status": "completed", "message": "자동매매 작업 종료됨"}


FUTURES_API_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"

async def get_binance_symbols():
    """Binance에서 사용 가능한 선물 심볼 목록 가져오기 (비동기)"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(FUTURES_API_URL) as response:
                response.raise_for_status()
                data = await response.json()
                symbols = {s["symbol"] for s in data["symbols"] if s["symbol"].endswith(("USDT"))}
                return symbols
    except Exception as e:
        print(f"❌ [ERROR] Binance 심볼 가져오기 실패: {e}")
        return set()


@router.get("/symbols")
async def get_symbols():
    """프론트엔드에서 사용할 심볼 목록 반환 (자동완성 기능)"""
    binance_symbols = await get_binance_symbols()
    return {"symbols": list(binance_symbols)}

# 자동매매 시작
@router.post("/start_trade/{user_id}")
async def start_trade(user_id: str, symbols: List[SymbolItem], db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == user_id).first()
    if not user:
        return {"message": "User not found"}

    if user.is_trading:
        return {"message": "이미 자동매매가 진행 중입니다."}
    
    # if user_id in active_tasks:
    #     return {"message": "이미 자동매매가 실행 중입니다."}
    
    # Telegram Bot 정보 가져오기
    telegram_token = user.telegram_token
    telegram_bot_id = user.telegram_bot_id
    binance_key= user.binance_key
    binance_secret= user.binance_secret
    binance_symbols = await get_binance_symbols()

    if not telegram_token or not telegram_bot_id:
        print(f"✅ [DEBUG] Telegram token이나 bot ID가 없습니다.")
        return {"message": "Telegram token이나 bot ID가 없습니다."}
    
    user.is_trading = True
    db.commit()

    # 심볼 검증 및 필터링
    valid_items = {}
    for item in symbols:
        sym_upper = item.symbol.strip().upper()
        if re.match(r"^[A-Z0-9]+(USDT|BTC|ETH)$", sym_upper) and sym_upper in binance_symbols:
            # 같은 심볼이 있으면 마지막 객체가 남게 됨 (필요에 따라 처리 방법 선택)
            valid_items[sym_upper] = item

    filtered_symbols = list(valid_items.values())
    # Celery 작업 인수를 JSON 직렬화 가능한 형태로 변환
    symbols_data = [item.dict() for item in filtered_symbols]

    if not filtered_symbols:
        return {"message": "유효한 심볼이 없습니다. Binance에서 지원하는 심볼만 입력해주세요."}


    start_task = start_trading_task.apply_async(args=[user_id, symbols_data, user.telegram_token, user.telegram_bot_id, user.binance_key, user.binance_secret])
    
    return {"message": "자동매매 시작", "task_id": start_task.id}

# 자동매매 중지
@router.post("/stop_trade/{user_id}")
async def stop_trade(user_id: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == user_id).first()
    if not user:
        return {"message": "User not found"}

    if not user.is_trading:
        return {"message": "자동매매가 실행 중이 아닙니다."}

    user.is_trading = False
    db.commit()
    
    # Redis에 저장된 trade_output 데이터를 삭제합니다.
    # keys = redis_client.keys(f"trade_output:{user_id}:*")
    # for key in keys:
    #     redis_client.delete(key)

    # Celery 작업 시작
    stop_task = stop_trading_task.apply_async(args=[user_id])
    return {"message": "자동매매 중지 요청이 완료되었습니다.", "task_id": stop_task.id}

@router.get("/trade_output/{user_id}")
async def get_trade_output(user_id: str, symbol: str = None):
    if symbol:
        output = redis_client.get(f"trade_output:{user_id}:{symbol}")
    else:
        output = redis_client.get(f"trade_output:{user_id}")
    if output:
        return {"trade_output": json.loads(output)}
    else:
        return {"trade_output": None}

if __name__ == "__main__":
    print("📢 Trade 모듈 실행됨!") 