import requests
import json
import time
import hashlib
import hmac
import os

# 바이낸스 API 엔드포인트
symbols_url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
leverage_url = "https://fapi.binance.com/fapi/v1/leverageBracket"

current_dir = os.path.dirname(os.path.abspath(__file__))  # 현재 파일의 절대 경로
api_file_path = os.path.join(current_dir, "api.txt")  # 파일 경로 결합

with open(api_file_path) as f:
    lines = f.readlines()
    API_KEY = lines[0].strip()
    API_SECRET  = lines[1].strip()

# 요청 헤더에 API 키 추가
headers = {
    'X-MBX-APIKEY': API_KEY
}

def generate_signature(query_string):
    return hmac.new(API_SECRET.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()

def get_valid_symbols():
    response = requests.get(symbols_url)
    if response.status_code == 200:
        data = response.json()
        symbols = [s['symbol'] for s in data['symbols']]
        return symbols
    else:
        print(f"Error fetching symbols: {response.status_code}")
        return []

def get_max_position_by_leverage(symbol):
    # 현재 시간의 timestamp를 밀리초 단위로 가져옴
    timestamp = int(time.time() * 1000)
    query_string = f"symbol={symbol}&timestamp={timestamp}"
    signature = generate_signature(query_string)

    request_url = f"{leverage_url}?{query_string}&signature={signature}"

    try:
        response = requests.get(request_url, headers=headers)  # 헤더 포함

        if response.status_code == 200:
            data = response.json()
            # print(json.dumps(data, indent=4))  # 데이터 구조 출력
            leverage_data = []

            for bracket in data:
                if 'brackets' in bracket:
                    for leverage_bracket in bracket['brackets']:
                        leverage_info = {
                            'leverage': leverage_bracket['initialLeverage'],
                            'max_notional_value': leverage_bracket['notionalCap'],
                            'min_notional_value': leverage_bracket['notionalFloor'],
                        }
                        leverage_data.append(leverage_info)
                else:
                    print("No 'brackets' key found in the data.")

            return leverage_data
        else:
            print(f"Error fetching leverage data: {response.status_code}, {response.text}")  # 에러 메시지 출력
            return None

    except Exception as e:
        print(f"Exception occurred: {e}")
        return None

# 유효한 심볼 리스트를 가져옴
valid_symbols = get_valid_symbols()
# print("Valid Symbols:", valid_symbols)

# 유효한 심볼 중 하나로 레버리지 데이터 요청
# if valid_symbols:
#     symbol = valid_symbols[0]  # 첫 번째 심볼로 테스트
#     print(f"Fetching leverage data for symbol: {symbol}")
#     leverage_brackets = get_max_position_by_leverage(symbol)

#     if leverage_brackets:
#         for bracket in leverage_brackets:
#             leverage = bracket['leverage']
#             max_usdt = bracket['max_notional_value']
#             min_usdt = bracket['min_notional_value']
#             print(f"레버리지 {leverage}배: 최소 {min_usdt} USDT ~ 최대 {max_usdt} USDT 진입 가능")

def cur_leverage_max_amount(cur_price, symbol, leverage, decimal_place_min_qty):
    if valid_symbols:
        modified_symbol = symbol.replace('/', '')
        leverage_brackets = get_max_position_by_leverage(modified_symbol)
        max_amount = 1
        if leverage_brackets:
            for bracket in leverage_brackets:
                if leverage == bracket['leverage'] and cur_price > 0:
                    max_amount = round(bracket['max_notional_value'] / cur_price,decimal_place_min_qty)
                    break
    return max_amount

# print(cur_leverage_max_amount(0.12161,'BIGTIME/USDT',50,3))
