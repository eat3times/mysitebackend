from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from datetime import datetime, timedelta
from jose import JWTError, jwt
from app import models, schemas, auth, database, crud, trade
from app.database import get_db
from app.trade import router as trade_router
from sqlalchemy.orm import Session
import json
from app.global_state import active_tasks
import asyncio
import aioredis

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
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
        return username
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