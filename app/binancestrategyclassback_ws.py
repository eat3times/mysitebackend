import datetime
import ccxt
import pandas as pd
import pprint
import logging
import time
from app.fibonacci import fib
import os
import asyncio
import websockets
import json
import app.curprice

# current_dir = os.path.dirname(os.path.abspath(__file__))  # 현재 파일의 절대 경로
# api_file_path = os.path.join(current_dir, "api.txt")  # 파일 경로 결합

# with open(api_file_path) as f:
#     lines = f.readlines()
#     api_key = lines[0].strip()
#     secret  = lines[1].strip()

# exchange = ccxt.binance(config={
#     'apiKey': api_key, 
#     'secret': secret,
#     'enableRateLimit': True,
#     'options': {
#         'defaultType': 'future'
#     }
# })
class Fib_target:
    def __init__(self,symbol):
        self.recommend_list = ['추천 포지션','추천 포지션']
        self.recommend = "추천 포지션"
        self.list_213 = []
        self.list_2 = []
        self.list_1618 = []
        self.list_1414 = []
        self.list_1272 = []
        self.list_113 = []
        self.list_1 = []
        self.list_0 = []
        self.list_1_switch = 'off'

        self.list_213_2 = []
        self.list_2_2 = []
        self.list_1618_2 = []
        self.list_1414_2 = []
        self.list_1272_2 = []
        self.list_113_2 = []
        self.list_1_2 = []
        self.list_0_2 = []

        self.list_next_re = []
        self.list_next_re_date = []

        self.second_fib = 'None'
        self.second_switch = 'None'

        self.fibRe2 = []
        self.target_1618 = 0
        self.target_213_2 = 0
        self.target_2_2 = 0
        self.target_1618_2 = 0
        self.target_1414_2 = 0
        self.target_1272_2 = 0
        self.target_113_2 = 0
        self.target_1_2 = 0
        self.Sub_TP = 0
        self.long_target_2 = self.short_target_2 = self.Sub_target_2 = self.Last_target_2 = self.TP_1st_2 = self.TP_2nd_2 = self.SL_1st_2 = 0
        self.decimal_place = 0
        self.symbol = symbol
        self.websocket = app.curprice.BinanceWebSocket(self.symbol)
        self.websocket.run_in_thread()
    def fetch_ohlcv_with_retries(self,exchange, symbol, timeframe, period, retries=5, delay=1):
        """
        OHLCV 데이터를 가져오는 함수 (재시도 및 오류 처리 포함).
        
        :param exchange: CCXT 거래소 객체
        :param symbol: 코인 심볼 (예: 'BTC/USDT')
        :param timeframe: 데이터의 시간 간격 (예: '1m', '1h')
        :param period: 요청할 데이터 개수 (예: 500)
        :param retries: 최대 재시도 횟수
        :param delay: 초기 지연 시간 (초)
        :return: OHLCV 데이터 리스트
        """
        self.symbol = symbol
        self.period = period
        self.timeframe = timeframe
        for attempt in range(retries):
            try:
                self.ohlcv = exchange.fetch_ohlcv(self.symbol, self.timeframe, since=None, limit=self.period)
                return self.ohlcv
            except ccxt.RequestTimeout as e:
                logging.warning(f"[{attempt + 1}/{retries}] 요청 시간 초과: {e}, 재시도 중...")
            except ccxt.DDoSProtection as e:
                logging.warning(f"[{attempt + 1}/{retries}] DDoS 보호 활성화: {e}, 재시도 중...")
            except ccxt.NetworkError as e:
                logging.warning(f"[{attempt + 1}/{retries}] 네트워크 오류: {e}, {delay}초 후 재시도...")
                if '502' in str(e):
                    logging.warning(f"Bad Gateway (502): {e}, {delay}초 후 재시도...")
                time.sleep(delay)
                delay *= 2  # 지수 백오프
            except ccxt.ExchangeError as e:
                if hasattr(e, 'response') and e.response.status_code == 429:
                    logging.warning(f"[{attempt + 1}/{retries}] 요청 제한 초과 (429): {e}, {delay}초 후 재시도...")
                    time.sleep(delay)
                    delay *= 2  # 지수 백오프
                else:
                    logging.error(f"거래소 오류: {e}")
                    raise
            except Exception as e:
                logging.error(f"[{attempt + 1}/{retries}] 알 수 없는 오류 발생: {e}")
                raise
            time.sleep(delay)
            delay *= 2  # 지수 백오프
        raise Exception("최대 재시도 횟수 초과")
    def cal_target_mixed(self,exchange,symbol,period,timeframe,fib_level):
        self.symbol = symbol
        self.period = period
        self.timeframe = timeframe

        try:
            self.btc = self.fetch_ohlcv_with_retries(exchange,self.symbol,self.timeframe,self.period, retries=5, delay=1)
        except Exception as e:
            logging.error(f"OHLCV 데이터를 가져오는 중 오류 발생: {e}")
            return
        
        if self.decimal_place == 0:
            self.ticker = exchange.fetch_ticker(self.symbol)
            self.cur_price = self.ticker['last']
            self.decimal_place = len(str(self.cur_price).split(".")[1])
        if self.websocket.price is not None:
            self.cur_price = round(self.websocket.price, self.decimal_place)
        else:
            self.ticker = exchange.fetch_ticker(self.symbol)
            self.cur_price = self.ticker['last']

        self.df = pd.DataFrame(data=self.btc, columns=['datetime', 'open', 'high', 'low', 'close', 'volume'])
        self.df['datetime'] = pd.to_datetime(self.df['datetime'], unit='ms') + datetime.timedelta(hours=9)
        # self.df.set_index('datetime', inplace=True)
        self.ATH = self.df.sort_values(by=["high"],ascending=False)
        self.ATL = self.df.sort_values(by=["low"],ascending=True)

        # 최고점 최저점 찾는 문장
        ##########################3##
        self.highest = max(self.df.iloc[:,2]) 
        self.num_high = 0 
        for i in self.df.iloc[:,2]:
            if i != self.highest:
                self.num_high += 1
            elif i == self.highest:
                break

        self.lowest = min(self.df.iloc[:,3])
        self.num_low = 0
        for i in self.df.iloc[:,3]:
            if i != self.lowest:
                self.num_low += 1
            elif i == self.lowest:
                break

        if self.second_switch == 'None' and self.ATH.iloc[0,0] > self.ATL.iloc[0,0] and self.cur_price > 0:
            self.alram_date1 = "최고가의 날짜 = {0}".format(self.ATH.iloc[0,0])
            self.alram_date2 = "최저가의 날짜 = {0}".format(self.ATL.iloc[0,0])
            self.fibRe = fib(self.ATL.iloc[0,3],self.ATH.iloc[0,2],self.decimal_place)
            self.recommend = "롱 추천"
            self.new_recommend = "숏 추천"
            self.long_target = self.fibRe[fib_level]
            self.short_target = self.fibRe[fib_level]
            self.Sub_target = self.fibRe[fib_level - 1]
            self.Last_target = self.fibRe[fib_level - 2]
            self.Sub_rtarget = self.fibRe[fib_level + 4]
            self.reverse_target = self.fibRe[fib_level + 3]
            self.TP_1st = self.fibRe[fib_level + 1]
            self.TP_2nd = self.fibRe[fib_level + 2]
            self.SL_1st = self.fibRe[4]

            # 추천 포지션 리스트
            if self.recommend_list[0] != self.recommend:
                # print('포지션 리스트 변경 완료')
                self.recommend_list[0] = self.recommend
                if self.list_1618 and len(self.list_1618) == 1:
                    # print('포지션 리스트 추가 완료')
                    self.list_213.append(self.list_213[0])
                    self.list_2.append(self.list_2[0])
                    self.list_1618.append(self.list_1618[0])
                    self.list_1414.append(self.list_1414[0])
                    self.list_1272.append(self.list_1272[0])
                    self.list_113.append(self.list_113[0])
                    self.list_1.append(self.list_1[0])
                    # 추천 포지션이 변경될 때 원래 있던 익스텐션 값을 리스트 2번째로 옮김
                if self.list_next_re:
                    self.list_next_re.clear()
                    self.list_next_re_date.clear()
                if self.list_next_re and self.second_fib == 'on':
                    self.second_fib = 'None'
                if self.second_switch == 'on':
                    self.second_switch = 'None'

            if not self.list_1618:
                self.list_213.append(self.fibRe[14])
                self.list_2.append(self.fibRe[12])
                self.list_1618.append(self.fibRe[0])
                self.list_1414.append(self.fibRe[1])
                self.list_1272.append(self.fibRe[2])
                self.list_113.append(self.fibRe[3])
                self.list_1.append(self.fibRe[4])
                self.list_0.append(self.fibRe[11])

            # print(f'target : {self.target_1618},list : {self.list_1618},len : {len(self.list_1618)}, 롱')
            

            if self.list_1618 and len(self.list_1618) == 1:
                self.target_213 = self.list_213[0]
                self.target_2 = self.list_2[0]
                self.target_1618 = self.list_1618[0]
                self.target_1414 = self.list_1414[0]
                self.target_1272 = self.list_1272[0]
                self.target_113 = self.list_113[0]
                self.target_1 = self.list_1[0]
            
            # 1 값이 계속 변경될 때 연장값
            if self.list_1618 and len(self.list_2) == 1 and self.list_1[0] != self.fibRe[4]\
                and self.list_1_switch == 'off':
                self.list_213[0] = self.fibRe[14]
                self.list_2[0] = self.fibRe[12]
                self.list_1618[0] = self.fibRe[0]
                self.list_1414[0] = self.fibRe[1]
                self.list_1272[0] = self.fibRe[2]
                self.list_113[0] = self.fibRe[3]
                self.list_1[0] = self.fibRe[4]
                self.list_0[0] = self.fibRe[11]
                self.list_1_switch == 'on'

            # 추천 포지션이 동일하게 유지되면서 피보나치 0 값을 계속 돌파할 때 익스텐션 값 새로고침 및 되돌림 스위치가 on일 때 다음 피보나치 되돌림 최신화를 위한 세컨드 스위치 on
            if self.list_1618 and len(self.list_2) == 1 and self.list_1618[0] != self.fibRe[0] \
                and self.list_1[0] == self.fibRe[4]:

                self.list_213[0] = self.fibRe[14]
                self.list_2[0] = self.fibRe[12]
                self.list_1618[0] = self.fibRe[0]
                self.list_1414[0] = self.fibRe[1]
                self.list_1272[0] = self.fibRe[2]
                self.list_113[0] = self.fibRe[3]
                self.list_1[0] = self.fibRe[4]
                self.list_0[0] = self.fibRe[11]

                if self.second_fib == 'on' and self.second_switch =='None':
                    self.second_switch = 'on'

            
            # 포지션이 변경 될 때 2번째로 옮겨진 익스텐션 값들이 타겟값이 됨
            # 1번째 값은 현재 익스텐션 값으로 변경
            if self.list_1618 and len(self.list_1618) == 2:
                self.target_213 = self.list_213[1]
                self.target_2 = self.list_2[1]
                self.target_1618 = self.list_1618[1]
                self.target_1414 = self.list_1414[1]
                self.target_1272 = self.list_1272[1]
                self.target_113 = self.list_113[1]
                self.target_1 = self.list_1[1]
                self.list_213[0] = self.fibRe[14]
                self.list_2[0] = self.fibRe[12]
                self.list_1618[0] = self.fibRe[0]
                self.list_1414[0] = self.fibRe[1]
                self.list_1272[0] = self.fibRe[2]
                self.list_113[0] = self.fibRe[3]
                self.list_1[0] = self.fibRe[4]
            
            #현재가가 두번째 피보의 0.886을 돌파할 시 이전에 저장된 익스텐션값삭제   
            if self.list_2 and len(self.list_2) == 2 and self.recommend == '롱 추천' and self.cur_price <= self.fibRe[5]:
                del self.list_213[1]
                del self.list_2[1]
                del self.list_1618[1]
                del self.list_1414[1]
                del self.list_1272[1]
                del self.list_113[1]
                del self.list_1[1]
                self.target_213 = self.list_213[0]
                self.target_2 = self.list_2[0]
                self.target_1618 = self.list_1618[0]
                self.target_1414 = self.list_1414[0]
                self.target_1272 = self.list_1272[0]
                self.target_113 = self.list_113[0]
                self.target_1 = self.list_1[0]
                # self.list_1_switch == 'off'
            

        if self.second_switch == 'None' and self.ATH.iloc[0,0] < self.ATL.iloc[0,0] and self.cur_price > 0:
            self.alram_date1 = "최고가의 날짜 = {0}".format(self.ATH.iloc[0,0])
            self.alram_date2 = "최저가의 날짜 = {0}".format(self.ATL.iloc[0,0])
            self.fibRe = fib(self.ATH.iloc[0,2],self.ATL.iloc[0,3],self.decimal_place)
            self.recommend = "숏 추천"
            self.new_recommend = "롱 추천"
            self.long_target= self.fibRe[fib_level]
            self.short_target = self.fibRe[fib_level]
            self.Sub_target = self.fibRe[fib_level - 1]
            self.Sub_rtarget = self.fibRe[fib_level + 4]
            self.Last_target = self.fibRe[fib_level - 2]
            self.reverse_target = self.fibRe[fib_level + 3]
            self.TP_1st = self.fibRe[fib_level + 1]
            self.TP_2nd = self.fibRe[fib_level + 2]
            self.SL_1st = self.fibRe[4]

            if self.recommend_list[0] != self.recommend:
                # print('포지션 리스트 변경 완료')
                self.recommend_list[0] = self.recommend
                if self.list_1618 and len(self.list_1618) == 1:
                    # print('포지션 리스트 추가 완료')
                    self.list_213.append(self.list_213[0])
                    self.list_2.append(self.list_2[0])
                    self.list_1618.append(self.list_1618[0])
                    self.list_1414.append(self.list_1414[0])
                    self.list_1272.append(self.list_1272[0])
                    self.list_113.append(self.list_113[0])
                    self.list_1.append(self.list_1[0])
                if self.list_next_re:
                    self.list_next_re.clear()
                    self.list_next_re_date.clear()
                if self.list_next_re and self.second_fib == 'on':
                    self.second_fib = 'None'
                if self.second_switch == 'on':
                    self.second_switch = 'None'

            if not self.list_1618:
                self.list_213.append(self.fibRe[14])
                self.list_2.append(self.fibRe[12])
                self.list_1618.append(self.fibRe[0])
                self.list_1414.append(self.fibRe[1])
                self.list_1272.append(self.fibRe[2])
                self.list_113.append(self.fibRe[3])
                self.list_1.append(self.fibRe[4])
                self.list_0.append(self.fibRe[11])

            # print(f'target : {self.target_1618},list : {self.list_1618},len : {len(self.list_1618)}, 숏')
            
            if self.list_1618 and len(self.list_1618) == 1:
                self.target_213 = self.list_213[0]
                self.target_2 = self.list_2[0]
                self.target_1618 = self.list_1618[0]
                self.target_1414 = self.list_1414[0]
                self.target_1272 = self.list_1272[0]
                self.target_113 = self.list_113[0]
                self.target_1 = self.list_1[0]
            
            if self.list_1618 and len(self.list_2) == 1 and self.list_1[0] != self.fibRe[4]\
                and self.list_1_switch == 'off':
                self.list_213[0] = self.fibRe[14]
                self.list_2[0] = self.fibRe[12]
                self.list_1618[0] = self.fibRe[0]
                self.list_1414[0] = self.fibRe[1]
                self.list_1272[0] = self.fibRe[2]
                self.list_113[0] = self.fibRe[3]
                self.list_1[0] = self.fibRe[4]
                self.list_0[0] = self.fibRe[11]
                self.list_1_switch == 'on'
            
            if self.list_1618 and len(self.list_2) == 1 and self.list_1618[0] != self.fibRe[0] \
                and self.list_1[0] == self.fibRe[4]:
                self.list_213[0] = self.fibRe[14]
                self.list_2[0] = self.fibRe[12]
                self.list_1618[0] = self.fibRe[0]
                self.list_1414[0] = self.fibRe[1]
                self.list_1272[0] = self.fibRe[2]
                self.list_113[0] = self.fibRe[3]
                self.list_1[0] = self.fibRe[4]
                self.list_0[0] = self.fibRe[11]

            if self.list_1618 and len(self.list_1618) == 2:
                self.target_213 = self.list_213[1]
                self.target_2 = self.list_2[1]
                self.target_1618 = self.list_1618[1]
                self.target_1414 = self.list_1414[1]
                self.target_1272 = self.list_1272[1]
                self.target_113 = self.list_113[1]
                self.target_1 = self.list_1[1]
                self.list_213[0] = self.fibRe[14]
                self.list_2[0] = self.fibRe[12]
                self.list_1618[0] = self.fibRe[0]
                self.list_1414[0] = self.fibRe[1]
                self.list_1272[0] = self.fibRe[2]
                self.list_113[0] = self.fibRe[3]
                self.list_1[0] = self.fibRe[4]

            #현재가가 두번째 피보의 0.886을 돌파할 시 이전에 저장된 익스텐션값삭제
            if self.list_2 and len(self.list_2) == 2 and self.recommend == '숏 추천' and self.cur_price >= self.fibRe[5]:
                del self.list_213[1]
                del self.list_2[1]
                del self.list_1618[1]
                del self.list_1414[1]
                del self.list_1272[1]
                del self.list_113[1]
                del self.list_1[1]
                self.target_213 = self.list_213[0]
                self.target_2 = self.list_2[0]
                self.target_1618 = self.list_1618[0]
                self.target_1414 = self.list_1414[0]
                self.target_1272 = self.list_1272[0]
                self.target_113 = self.list_113[0]
                self.target_1 = self.list_1[0]

        # fibRe2
        if self.recommend == "롱 추천" and self.cur_price > 0:
            self.filt = self.df.iloc[self.num_high+1:,] # 최고점부터 계산 시작
            self.filt_low = self.filt['low'].min()
            if self.filt['low'].min() <= self.fibRe[8]:
                self.filt2 = self.filt[self.filt['low'] <= self.fibRe[8]] # 원하는 되돌림 값 이하인 봉들의 집합
                self.filt3 = self.filt2.sort_values(by=['low'],ascending=True)
                self.next_re = self.filt3.iloc[0,3]
                self.next_re_date = self.filt3.iloc[0,0]
                if not self.list_next_re:
                    if len(self.list_next_re) < 2:
                        self.list_next_re.append(self.next_re)
                        self.list_next_re.append('short')
                        self.list_next_re_date.append(self.next_re_date)
                if self.list_next_re:
                    self.list_next_re[0] = self.next_re
                    self.list_next_re[1] = 'short'
                    self.list_next_re_date[0] = self.next_re_date
                if self.next_re > 0 and self.next_re <= self.fibRe[8] and self.next_re == self.filt['low'].min():
                    self.new_recommend = "숏 추천"
                    self.fibRe2 = fib(self.ATH.iloc[0,2],self.next_re,self.decimal_place)
                    self.short_target_2 = self.fibRe2[fib_level]
                    self.Sub_target_2 = self.fibRe2[fib_level - 1]
                    self.Sub_rtarget_2 = self.fibRe2[fib_level + 4]
                    self.Last_target_2 = self.fibRe2[fib_level - 2]
                    self.reverse_target_2 = self.fibRe2[fib_level + 3]
                    self.TP_1st_2 = self.fibRe2[fib_level + 1]
                    self.TP_2nd_2 = self.fibRe2[fib_level + 2]
                    self.SL_1st_2 = self.fibRe2[4]
                    self.Sub_TP = self.fibRe2[9]
                if self.list_next_re and self.second_fib == 'None':
                    self.second_fib = 'on'

            if self.filt['low'].min() > self.fibRe[8]:
                self.fibRe2 = []
            # print(self.second_fib)

            if self.recommend_list[1] != self.new_recommend:
                # print('포지션 리스트_2 변경 완료')
                self.recommend_list[1] = self.new_recommend
                if self.second_fib == 'on':
                    self.second_fib = 'None'
                if self.list_2_2 and len(self.list_1618_2) == 1:
                    self.list_213_2.clear()
                    self.list_2_2.clear()
                    self.list_1618_2.clear()
                    self.list_1414_2.clear()
                    self.list_1272_2.clear()
                    self.list_113_2.clear()
                    self.list_1_2.clear()
                    self.list_0_2.clear()
                    self.target_213_2 = 0
                    self.target_2_2 = 0
                    self.target_1618_2 = 0
                    self.target_1414_2 = 0
                    self.target_1272_2 = 0
                    self.target_113_2 = 0
                    self.target_1_2 = 0
            # fibRe2의 마지막 되돌림이 있는 상태로 다음 fibRe 피보나치가 이전 피보와 같은 방향으로 생성될 때 되돌림 값 유지
            if self.list_next_re and self.list_next_re_date:
                print(self.list_next_re[0],self.list_next_re_date[0],self.second_fib)

            # 피보 생성이 같은 롱추천으로 지속 될 때 fibRe[11](피보나치 0) 과 fibRe2[4](피보나치1)를 비교해보자

            if not self.list_1618_2 and self.fibRe2:
                self.list_213_2.append(self.fibRe2[14])
                self.list_2_2.append(self.fibRe2[12])
                self.list_1618_2.append(self.fibRe2[0])
                self.list_1414_2.append(self.fibRe2[1])
                self.list_1272_2.append(self.fibRe2[2])
                self.list_113_2.append(self.fibRe2[3])
                self.list_1_2.append(self.fibRe2[4])
                self.list_0_2.append(self.fibRe2[11])
            # print(f'target_2 : {self.target_1618_2},list_2 : {self.list_1618_2},len : {len(self.list_1618_2)}, 숏')

            # 첫 fibRe2에서 연장값이 저장된 후 현재가가 fibRe의 0값을 돌파해서 추천 포지션이 유지될 때
            if self.list_1618_2 and self.target_1618_2 > 0 and not self.fibRe2 and len(self.list_1618_2) == 1 and self.cur_price >= self.list_1_2[0]:
                self.list_213_2.append(self.list_213_2[0])
                self.list_2_2.append(self.list_2_2[0])
                self.list_1618_2.append(self.list_1618_2[0])
                self.list_1414_2.append(self.list_1414_2[0])
                self.list_1272_2.append(self.list_1272_2[0])
                self.list_113_2.append(self.list_113_2[0])
                self.list_1_2.append(self.list_1_2[0])
                self.list_0_2.append(self.list_0_2[0])

            if self.list_1618_2 and len(self.list_1618_2) == 1:
                self.target_213_2 = self.list_213_2[0]
                self.target_2_2 = self.list_2_2[0]
                self.target_1618_2 = self.list_1618_2[0]
                self.target_1414_2 = self.list_1414_2[0]
                self.target_1272_2 = self.list_1272_2[0]
                self.target_113_2 = self.list_113_2[0]
                self.target_1_2 = self.list_1_2[0]

            # 추천 포지션이 동일하게 유지되면서 피보나치 0 값을 계속 돌파할 때 익스텐션 값 새로고침
            if self.fibRe2 and self.list_1618_2 and len(self.list_2_2) == 1 and self.list_0_2[0] != self.fibRe2[11]\
                and self.list_1_2[0] == self.fibRe2[4]:
                self.list_213_2[0] = self.fibRe2[14]
                self.list_2_2[0] = self.fibRe2[12]
                self.list_1618_2[0] = self.fibRe2[0]
                self.list_1414_2[0] = self.fibRe2[1]
                self.list_1272_2[0] = self.fibRe2[2]
                self.list_113_2[0] = self.fibRe2[3]
                self.list_1_2[0] = self.fibRe2[4]
                self.list_0_2[0] = self.fibRe2[11]
            
            if self.fibRe2 and self.list_1618_2 and len(self.list_1618_2) == 2:
                self.list_213_2[0] = self.fibRe2[14]
                self.list_2_2[0] = self.fibRe2[12]
                self.list_1618_2[0] = self.fibRe2[0]
                self.list_1414_2[0] = self.fibRe2[1]
                self.list_1272_2[0] = self.fibRe2[2]
                self.list_113_2[0] = self.fibRe2[3]
                self.list_1_2[0] = self.fibRe2[4]

            if self.list_1618_2 and len(self.list_1618_2) == 2:
                self.target_213_2 = self.list_213_2[1]
                self.target_2_2 = self.list_2_2[1]
                self.target_1618_2 = self.list_1618_2[1]
                self.target_1414_2 = self.list_1414_2[1]
                self.target_1272_2 = self.list_1272_2[1]
                self.target_113_2 = self.list_113_2[1]
                self.target_1_2 = self.list_1_2[1]

            #현재가가 두번째 피보의 0.5을 돌파할 시 이전에 저장된 익스텐션값삭제
            if self.list_2_2 and len(self.list_2_2) == 2 and self.recommend == '롱 추천' and self.cur_price <= self.fibRe[8]:
                del self.list_213_2[1]
                del self.list_2_2[1]
                del self.list_1618_2[1]
                del self.list_1414_2[1]
                del self.list_1272_2[1]
                del self.list_113_2[1]
                del self.list_1_2[1]
                self.target_213_2 = self.list_213_2[0]
                self.target_2_2 = self.list_2_2[0]
                self.target_1618_2 = self.list_1618_2[0]
                self.target_1414_2 = self.list_1414_2[0]
                self.target_1272_2 = self.list_1272_2[0]
                self.target_113_2 = self.list_113_2[0]
                self.target_1_2 = self.list_1_2[0]

        if self.recommend == "숏 추천" and self.cur_price > 0:
            self.filt = self.df.iloc[self.num_low+1:,]
            self.filt_high = self.filt['high'].max()
            if self.filt['high'].max() >= self.fibRe[8]:
                self.filt2 = self.filt[self.filt['high'] >= self.fibRe[8]]
                self.filt3 = self.filt2.sort_values(by=['high'],ascending=False)
                self.next_re = self.filt3.iloc[0,2]
                self.next_re_date = self.filt3.iloc[0,0]
                if not self.list_next_re:
                    if len(self.list_next_re) < 2:
                        self.list_next_re.append(self.next_re)
                        self.list_next_re.append('long')
                        self.list_next_re_date.append(self.next_re_date)
                if self.list_next_re:
                    self.list_next_re[0] = self.next_re
                    self.list_next_re[1] = 'long'
                    self.list_next_re_date[0] = self.next_re_date
                if self.next_re > 0 and self.next_re >= self.fibRe[8] and self.next_re == self.filt['high'].max():
                    self.new_recommend = "롱 추천"
                    self.fibRe2 = fib(self.ATL.iloc[0,3],self.next_re,self.decimal_place)
                    self.long_target_2 = self.fibRe2[fib_level]
                    self.Sub_target_2 = self.fibRe2[fib_level - 1]
                    self.Sub_rtarget_2 = self.fibRe2[fib_level + 4]
                    self.Last_target_2 = self.fibRe2[fib_level - 2]
                    self.reverse_target_2 = self.fibRe2[fib_level + 3]
                    self.TP_1st_2 = self.fibRe2[fib_level + 1]
                    self.TP_2nd_2 = self.fibRe2[fib_level + 2]
                    self.SL_1st_2 = self.fibRe2[4]
                    self.Sub_TP = self.fibRe2[9]
                if self.list_next_re and self.second_fib == 'None':
                    self.second_fib = 'on'
            if self.filt['high'].max() < self.fibRe[8]:
                self.fibRe2 = []

            if self.recommend_list[1] != self.new_recommend:
                # print('포지션 리스트_2 변경 완료')
                self.recommend_list[1] = self.new_recommend
                if self.second_fib == 'on':
                    self.second_fib = 'None'
                if self.list_2_2 and len(self.list_1618_2) == 1:
                    self.list_213_2.clear()
                    self.list_2_2.clear()
                    self.list_1618_2.clear()
                    self.list_1414_2.clear()
                    self.list_1272_2.clear()
                    self.list_113_2.clear()
                    self.list_1_2.clear()
                    self.list_0_2.clear()
                    self.target_213_2 = 0
                    self.target_2_2 = 0
                    self.target_1618_2 = 0
                    self.target_1414_2 = 0
                    self.target_1272_2 = 0
                    self.target_113_2 = 0
                    self.target_1_2 = 0
            if self.list_next_re and self.list_next_re_date:
                print(self.list_next_re[0],self.list_next_re_date[0],self.second_fib)

            if not self.list_1618_2 and self.fibRe2:
                self.list_213_2.append(self.fibRe2[14])
                self.list_2_2.append(self.fibRe2[12])
                self.list_1618_2.append(self.fibRe2[0])
                self.list_1414_2.append(self.fibRe2[1])
                self.list_1272_2.append(self.fibRe2[2])
                self.list_113_2.append(self.fibRe2[3])
                self.list_1_2.append(self.fibRe2[4])
                self.list_0_2.append(self.fibRe2[11])
            # print(f'target_2 : {self.target_1618_2},list_2 : {self.list_1618_2},len : {len(self.list_1618_2)}, 롱')

            # 첫 fibRe2에서 연장값이 저장된 후 현재가가 fibRe의 0값을 돌파해서 추천 포지션이 유지될 때
            if self.list_1618_2 and self.target_1618_2 > 0 and not self.fibRe2 and len(self.list_1618_2) == 1 and self.cur_price <= self.list_1_2[0]:
                self.list_213_2.append(self.list_213_2[0])
                self.list_2_2.append(self.list_2_2[0])
                self.list_1618_2.append(self.list_1618_2[0])
                self.list_1414_2.append(self.list_1414_2[0])
                self.list_1272_2.append(self.list_1272_2[0])
                self.list_113_2.append(self.list_113_2[0])
                self.list_1_2.append(self.list_1_2[0])

            if self.list_1618_2 and len(self.list_1618_2) == 1:
                self.target_213_2 = self.list_213_2[0]
                self.target_2_2 = self.list_2_2[0]
                self.target_1618_2 = self.list_1618_2[0]
                self.target_1414_2 = self.list_1414_2[0]
                self.target_1272_2 = self.list_1272_2[0]
                self.target_113_2 = self.list_113_2[0]
                self.target_1_2 = self.list_1_2[0]

            if self.fibRe2 and self.list_1618_2 and len(self.list_2_2) == 1 and self.list_0_2[0] != self.fibRe2[11]\
                and self.list_1_2[0] == self.fibRe2[4]:
                self.list_213_2[0] = self.fibRe2[14]
                self.list_2_2[0] = self.fibRe2[12]
                self.list_1618_2[0] = self.fibRe2[0]
                self.list_1414_2[0] = self.fibRe2[1]
                self.list_1272_2[0] = self.fibRe2[2]
                self.list_113_2[0] = self.fibRe2[3]
                self.list_1_2[0] = self.fibRe2[4]
                self.list_0_2[0] = self.fibRe2[11]


            if self.list_1618_2 and len(self.list_1618_2) == 2:
                self.target_213_2 = self.list_213_2[1]
                self.target_2_2 = self.list_2_2[1]
                self.target_1618_2 = self.list_1618_2[1]
                self.target_1414_2 = self.list_1414_2[1]
                self.target_1272_2 = self.list_1272_2[1]
                self.target_113_2 = self.list_113_2[1]
                self.target_1_2 = self.list_1_2[1]
                
            if self.fibRe2 and self.list_1618_2 and len(self.list_1618_2) == 2:
                self.list_213_2[0] = self.fibRe2[14]
                self.list_2_2[0] = self.fibRe2[12]
                self.list_1618_2[0] = self.fibRe2[0]
                self.list_1414_2[0] = self.fibRe2[1]
                self.list_1272_2[0] = self.fibRe2[2]
                self.list_113_2[0] = self.fibRe2[3]
                self.list_1_2[0] = self.fibRe2[4]
            
            # #현재가가 두번째 피보의 0.5을 돌파할 시 이전에 저장된 익스텐션값삭제
            if self.list_2_2 and len(self.list_2_2) == 2 and self.recommend == '숏 추천' and self.cur_price >= self.fibRe[8]:
                del self.list_213_2[1]
                del self.list_2_2[1]
                del self.list_1618_2[1]
                del self.list_1414_2[1]
                del self.list_1272_2[1]
                del self.list_113_2[1]
                del self.list_1_2[1]
                self.target_213_2 = self.list_213_2[0]
                self.target_2_2 = self.list_2_2[0]
                self.target_1618_2 = self.list_1618_2[0]
                self.target_1414_2 = self.list_1414_2[0]
                self.target_1272_2 = self.list_1272_2[0]
                self.target_113_2 = self.list_113_2[0]
                self.target_1_2 = self.list_1_2[0]

        # next_re 다음 고점 저점 값 찾기
        if self.list_next_re:
            self.c = self.df[self.df["datetime"] >= self.list_next_re_date[0]]
            self.ATH2 = self.c.sort_values(by=["high"],ascending=False)
            self.ATL2 = self.c.sort_values(by=["low"],ascending=True)
            self.new_high = self.ATH2.iloc[0,2]
            self.new_low = self.ATL2.iloc[0,3]

        # 두번째 피보나치 생성부터는 되돌림 값을 1로 만듬
        if self.list_next_re and self.second_switch == 'on' and self.ATH.iloc[0,0] > self.ATL2.iloc[0,0] and self.cur_price > 0:
            self.alram_date1 = "최고가의 날짜 = {0}".format(self.ATH.iloc[0,0])
            self.alram_date2 = "최저가의 날짜 = {0}".format(self.ATL2.iloc[0,0])
            self.fibRe = fib(self.ATL2.iloc[0,3],self.ATH.iloc[0,2],self.decimal_place)
            self.recommend = "롱 추천"
            self.new_recommend = "숏 추천"
            self.long_target = self.fibRe[fib_level]
            self.short_target = self.fibRe[fib_level]
            self.Sub_target = self.fibRe[fib_level - 1]
            self.Last_target = self.fibRe[fib_level - 2]
            self.Sub_rtarget = self.fibRe[fib_level + 4]
            self.reverse_target = self.fibRe[fib_level + 3]
            self.TP_1st = self.fibRe[fib_level + 1]
            self.TP_2nd = self.fibRe[fib_level + 2]
            self.SL_1st = self.fibRe[4]

            # 추천 포지션 리스트
            if self.recommend_list[0] != self.recommend:
                # print('포지션 리스트 변경 완료')
                self.recommend_list[0] = self.recommend
                if self.list_1618 and len(self.list_1618) == 1:
                    # print('포지션 리스트 추가 완료')
                    self.list_213.append(self.list_213[0])
                    self.list_2.append(self.list_2[0])
                    self.list_1618.append(self.list_1618[0])
                    self.list_1414.append(self.list_1414[0])
                    self.list_1272.append(self.list_1272[0])
                    self.list_113.append(self.list_113[0])
                    self.list_1.append(self.list_1[0])
                if self.list_next_re:
                    self.list_next_re.clear()
                    self.list_next_re_date.clear()
                if self.second_fib == 'on':
                    self.second_fib = 'None'
                if self.second_switch == 'on':
                    self.second_switch = 'None'

            if not self.list_1618:
                self.list_213.append(self.fibRe[14])
                self.list_2.append(self.fibRe[12])
                self.list_1618.append(self.fibRe[0])
                self.list_1414.append(self.fibRe[1])
                self.list_1272.append(self.fibRe[2])
                self.list_113.append(self.fibRe[3])
                self.list_1.append(self.fibRe[4])
                self.list_0.append(self.fibRe[11])

            if self.list_1618 and len(self.list_1618) == 1:
                self.target_213 = self.list_213[0]
                self.target_2 = self.list_2[0]
                self.target_1618 = self.list_1618[0]
                self.target_1414 = self.list_1414[0]
                self.target_1272 = self.list_1272[0]
                self.target_113 = self.list_113[0]
                self.target_1 = self.list_1[0]
            
            if self.list_1618 and len(self.list_2) == 1 and self.list_1[0] != self.fibRe[4]\
                and self.list_1_switch == 'off':
                self.list_213[0] = self.fibRe[14]
                self.list_2[0] = self.fibRe[12]
                self.list_1618[0] = self.fibRe[0]
                self.list_1414[0] = self.fibRe[1]
                self.list_1272[0] = self.fibRe[2]
                self.list_113[0] = self.fibRe[3]
                self.list_1[0] = self.fibRe[4]
                self.list_0[0] = self.fibRe[11]
                self.list_1_switch == 'on'

            if self.list_1618 and len(self.list_2) == 1 and self.list_1618[0] != self.fibRe[0] \
                and self.list_1[0] == self.fibRe[4]:

                self.list_213[0] = self.fibRe[14]
                self.list_2[0] = self.fibRe[12]
                self.list_1618[0] = self.fibRe[0]
                self.list_1414[0] = self.fibRe[1]
                self.list_1272[0] = self.fibRe[2]
                self.list_113[0] = self.fibRe[3]
                self.list_1[0] = self.fibRe[4]
                self.list_0[0] = self.fibRe[11]

            if self.list_1618 and len(self.list_1618) == 2:
                self.target_213 = self.list_213[1]
                self.target_2 = self.list_2[1]
                self.target_1618 = self.list_1618[1]
                self.target_1414 = self.list_1414[1]
                self.target_1272 = self.list_1272[1]
                self.target_113 = self.list_113[1]
                self.target_1 = self.list_1[1]
                self.list_213[0] = self.fibRe[14]
                self.list_2[0] = self.fibRe[12]
                self.list_1618[0] = self.fibRe[0]
                self.list_1414[0] = self.fibRe[1]
                self.list_1272[0] = self.fibRe[2]
                self.list_113[0] = self.fibRe[3]
                self.list_1[0] = self.fibRe[4]
            
            #현재가가 두번째 피보의 0.886을 돌파할 시 이전에 저장된 익스텐션값삭제   
            if self.list_2 and len(self.list_2) == 2 and self.recommend == '롱 추천' and self.cur_price <= self.fibRe[5]:
                del self.list_213[1]
                del self.list_2[1]
                del self.list_1618[1]
                del self.list_1414[1]
                del self.list_1272[1]
                del self.list_113[1]
                del self.list_1[1]
                self.target_213 = self.list_213[0]
                self.target_2 = self.list_2[0]
                self.target_1618 = self.list_1618[0]
                self.target_1414 = self.list_1414[0]
                self.target_1272 = self.list_1272[0]
                self.target_113 = self.list_113[0]
                self.target_1 = self.list_1[0]
                # self.list_1_switch == 'off'

        if self.list_next_re and self.second_switch == 'on' and  self.ATH2.iloc[0,0] < self.ATL.iloc[0,0] and self.cur_price > 0:
            self.alram_date1 = "최고가의 날짜 = {0}".format(self.ATH2.iloc[0,0])
            self.alram_date2 = "최저가의 날짜 = {0}".format(self.ATL.iloc[0,0])
            self.fibRe = fib(self.ATH2.iloc[0,2],self.ATL.iloc[0,3],self.decimal_place)
            self.recommend = "숏 추천"
            self.new_recommend = "롱 추천"
            self.long_target= self.fibRe[fib_level]
            self.short_target = self.fibRe[fib_level]
            self.Sub_target = self.fibRe[fib_level - 1]
            self.Sub_rtarget = self.fibRe[fib_level + 4]
            self.Last_target = self.fibRe[fib_level - 2]
            self.reverse_target = self.fibRe[fib_level + 3]
            self.TP_1st = self.fibRe[fib_level + 1]
            self.TP_2nd = self.fibRe[fib_level + 2]
            self.SL_1st = self.fibRe[4]

            if self.recommend_list[0] != self.recommend:
                # print('포지션 리스트 변경 완료')
                self.recommend_list[0] = self.recommend
                if self.list_1618 and len(self.list_1618) == 1:
                    # print('포지션 리스트 추가 완료')
                    self.list_213.append(self.list_213[0])
                    self.list_2.append(self.list_2[0])
                    self.list_1618.append(self.list_1618[0])
                    self.list_1414.append(self.list_1414[0])
                    self.list_1272.append(self.list_1272[0])
                    self.list_113.append(self.list_113[0])
                    self.list_1.append(self.list_1[0])
                if self.list_next_re:
                    self.list_next_re.clear()
                    self.list_next_re_date.clear()
                if self.second_fib == 'on':
                    self.second_fib = 'None'
                if self.second_switch == 'on':
                    self.second_switch = 'None'

            if not self.list_1618:
                self.list_213.append(self.fibRe[14])
                self.list_2.append(self.fibRe[12])
                self.list_1618.append(self.fibRe[0])
                self.list_1414.append(self.fibRe[1])
                self.list_1272.append(self.fibRe[2])
                self.list_113.append(self.fibRe[3])
                self.list_1.append(self.fibRe[4])
                self.list_0.append(self.fibRe[11])
            
            if self.list_1618 and len(self.list_1618) == 1:
                self.target_213 = self.list_213[0]
                self.target_2 = self.list_2[0]
                self.target_1618 = self.list_1618[0]
                self.target_1414 = self.list_1414[0]
                self.target_1272 = self.list_1272[0]
                self.target_113 = self.list_113[0]
                self.target_1 = self.list_1[0]
            
            if self.list_1618 and len(self.list_2) == 1 and self.list_1[0] != self.fibRe[4]\
                and self.list_1_switch == 'off':
                self.list_213[0] = self.fibRe[14]
                self.list_2[0] = self.fibRe[12]
                self.list_1618[0] = self.fibRe[0]
                self.list_1414[0] = self.fibRe[1]
                self.list_1272[0] = self.fibRe[2]
                self.list_113[0] = self.fibRe[3]
                self.list_1[0] = self.fibRe[4]
                self.list_0[0] = self.fibRe[11]
                self.list_1_switch == 'on'
            
            if self.list_1618 and len(self.list_2) == 1 and self.list_1618[0] != self.fibRe[0] \
                and self.list_1[0] == self.fibRe[4]:
                self.list_213[0] = self.fibRe[14]
                self.list_2[0] = self.fibRe[12]
                self.list_1618[0] = self.fibRe[0]
                self.list_1414[0] = self.fibRe[1]
                self.list_1272[0] = self.fibRe[2]
                self.list_113[0] = self.fibRe[3]
                self.list_1[0] = self.fibRe[4]
                self.list_0[0] = self.fibRe[11]

            if self.list_1618 and len(self.list_1618) == 2:
                self.target_213 = self.list_213[1]
                self.target_2 = self.list_2[1]
                self.target_1618 = self.list_1618[1]
                self.target_1414 = self.list_1414[1]
                self.target_1272 = self.list_1272[1]
                self.target_113 = self.list_113[1]
                self.target_1 = self.list_1[1]
                self.list_213[0] = self.fibRe[14]
                self.list_2[0] = self.fibRe[12]
                self.list_1618[0] = self.fibRe[0]
                self.list_1414[0] = self.fibRe[1]
                self.list_1272[0] = self.fibRe[2]
                self.list_113[0] = self.fibRe[3]
                self.list_1[0] = self.fibRe[4]

            #현재가가 두번째 피보의 0.886을 돌파할 시 이전에 저장된 익스텐션값삭제
            if self.list_2 and len(self.list_2) == 2 and self.recommend == '숏 추천' and self.cur_price >= self.fibRe[5]:
                del self.list_213[1]
                del self.list_2[1]
                del self.list_1618[1]
                del self.list_1414[1]
                del self.list_1272[1]
                del self.list_113[1]
                del self.list_1[1]
                self.target_213 = self.list_213[0]
                self.target_2 = self.list_2[0]
                self.target_1618 = self.list_1618[0]
                self.target_1414 = self.list_1414[0]
                self.target_1272 = self.list_1272[0]
                self.target_113 = self.list_113[0]
                self.target_1 = self.list_1[0]


        return self.long_target, self.short_target, self.Sub_target, self.reverse_target, self.Sub_rtarget, self.fibRe, self.recommend,\
            fib_level ,self.alram_date1, self.alram_date2 , self.TP_1st, self.TP_2nd, self.SL_1st, self.Last_target,\
            self.target_1618, self.target_1414, self.target_1272, self.target_113, self.target_1, self.target_1618_2, self.target_1414_2,\
            self.target_1272_2, self.target_113_2, self.target_1_2, self.new_recommend, self.fibRe2,\
            self.long_target_2, self.short_target_2, self.Sub_target_2, self.Last_target_2,\
            self.TP_1st_2, self.TP_2nd_2, self.SL_1st_2, self.target_2, self.target_2_2,self.target_213,self.target_213_2,self.Sub_TP,self.decimal_place,\
            self.list_1618, self.num_high, self.num_low, self.df

if __name__ == "__main__":
    print("📢 strategy 모듈 실행됨!") 