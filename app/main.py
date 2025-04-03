from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from datetime import datetime, timedelta
from jose import JWTError, jwt
from app import models, schemas, auth, database, crud, trade
from app.database import get_db
from app.trade import router as trade_router
from sqlalchemy import func
from sqlalchemy.orm import Session
import json
from app.global_state import active_tasks
import asyncio
import aioredis
from pydantic import BaseModel
import ccxt

app = FastAPI()

# 라우터를 FastAPI 인스턴스에 추가
app.include_router(trade_router)

# CORS 미들웨어 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 출처에서 요청 허용
    allow_credentials=True,
    allow_methods=["*"],  # 모든 HTTP 메소드 허용
    allow_headers=["*"],  # 모든 HTTP 헤더 허용
)

# OAuth2PasswordBearer는 Authorization 헤더에서 Bearer 토큰을 가져오는 역할을 합니다.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# Redis Pub/Sub 기반 WebSocket 엔드포인트
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    # aioredis 2.x 버전 사용: from_url 함수를 이용해 Redis 클라이언트 생성
    redis = aioredis.from_url("redis://localhost", encoding="utf-8", decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"trade_output_channel:{user_id}")
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message:
                await websocket.send_text(message['data'])
            else:
                await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        print(f"WebSocket 연결이 종료되었습니다: {user_id}")
    except Exception as e:
        print(f"WebSocket 연결 오류: {repr(e)}")
    finally:
        await pubsub.unsubscribe(f"trade_output_channel:{user_id}")
        await pubsub.close()
        await redis.close()

# JWT 토큰을 검증하는 함수
def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        username: str = payload.get("sub")
        user_id = payload.get("id")
        if username is None or user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
        return {"username": username, "id": user_id}
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")

# 인증이 필요한 API 예시
@app.get("/protected")
def protected_route(current_user: str = Depends(get_current_user)):
    return {"message": f"Hello {current_user}, you have access to this protected route!"}

# 데이터베이스 테이블 생성
@app.on_event("startup")
def on_startup():
    models.Base.metadata.create_all(bind=database.engine)

# 회원가입 API
@app.post("/register", response_model=schemas.User)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    return auth.register_user(user, db)

# 로그인 API
@app.post("/login")
def login(user: schemas.UserLogin, db: Session = Depends(get_db)):
    return auth.login_user(user, db)

@app.get("/")
def read_root():
    return {"message": "Welcome to My site"}

@app.get("/users/{user_id}", response_model=schemas.UserInfo)
def get_user_profile(user_id: str, db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)):
    current_user = get_current_user(token)
    if current_user['username'] != user_id:
        raise HTTPException(status_code=403, detail="권한이 없습니다.")
    
    user = db.query(models.User).filter(models.User.username == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    return {
        "email": user.email,
        "telegram_token": user.telegram_token,
        "telegram_bot_id": user.telegram_bot_id
    }

@app.put("/users/{user_id}/telegram")
def update_telegram_settings(
    user_id: str,
    data: dict,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
):
    current_user = get_current_user(token)
    if current_user['username'] != user_id:
        raise HTTPException(status_code=403, detail="권한이 없습니다.")
    
    user = db.query(models.User).filter(models.User.username == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    user.telegram_token = data.get("telegram_token")
    user.telegram_bot_id = data.get("telegram_bot_id")
    db.commit()
    return {"message": "텔레그램 설정이 저장되었습니다."}

@app.get("/users/{user_id}/apikeys")
def get_user_apikeys(user_id: str, db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)):
    current_user = get_current_user(token)
    if current_user['username'] != user_id:
        raise HTTPException(status_code=403, detail="권한이 없습니다.")
    keys = crud.get_api_keys(db, user_id)
    if not keys:
        raise HTTPException(status_code=404, detail="API 키를 찾을 수 없습니다.")
    return keys

@app.put("/users/{user_id}/apikeys")
def update_user_apikeys(
    user_id: str,
    data: schemas.APIKeyUpdate,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
):
    current_user = get_current_user(token)
    if current_user['username'] != user_id:
        raise HTTPException(status_code=403, detail="권한이 없습니다.")
    success = crud.update_api_keys(db, user_id, data.access_key, data.secret_key)
    if not success:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    return {"message": "API 키가 성공적으로 수정되었습니다."}

class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

@app.put("/users/{user_id}/password")
def change_password(
    user_id: str,
    passwords: PasswordChangeRequest,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme)
):
    current_user = get_current_user(token)
    if current_user['username'] != user_id:
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    user = db.query(models.User).filter(models.User.username == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    if not auth.verify_password(passwords.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="현재 비밀번호가 올바르지 않습니다.")

    user.hashed_password = auth.hash_password(passwords.new_password)
    db.commit()
    return {"message": "비밀번호가 변경되었습니다."}

# 거래내역 부분
@app.get("/users/{user_id}/trades", response_model=list[schemas.TradeRecordOut])
def get_user_trades(user_id: str, db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)):
    current_user = get_current_user(token)
    if current_user['username'] != user_id:
        raise HTTPException(status_code=403, detail="권한이 없습니다.")
    return crud.get_trade_records(db, current_user['id'])

@app.delete("/users/{user_id}/trades/{trade_id}")
def delete_trade(user_id: str, trade_id: int, db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)):
    # 1) 로그인 / 권한 체크
    current_user = get_current_user(token)
    if current_user["username"] != user_id:
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    # 2) 해당 trade_id가 실제로 user_id에 속하는지 확인
    record = db.query(models.TradeRecord).filter(
        models.TradeRecord.id == trade_id,
        models.TradeRecord.user_id == current_user["id"]
    ).first()

    if not record:
        raise HTTPException(status_code=404, detail="해당 거래내역을 찾을 수 없습니다.")

    # 3) 삭제 수행
    db.delete(record)
    db.commit()
    return {"message": "삭제 성공"}

def get_binance_balance(api_key: str, secret: str):
    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': secret,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future'
        }
    })

    try:
        balance = exchange.fetch_balance()
        usdt_balance = balance['total'].get('USDT', 0.0)
        return round(usdt_balance, 2)
    except Exception as e:
        print("❌ 잔고 조회 실패:", e)
        return None
    
@app.get("/users/{user_id}/account-summary")
def get_account_summary(user_id: str, db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)):
    current_user = get_current_user(token)
    if current_user["username"] != user_id:
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    user = db.query(models.User).filter(models.User.username == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    # 실시간 잔고 가져오기
    balance = get_binance_balance(user.binance_key, user.binance_secret)

    return {
        "balance": balance,
        "realized_pnl": round(user.total_pnl or 0.0, 2),
    }