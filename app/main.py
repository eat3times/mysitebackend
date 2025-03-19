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

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    try:
        while True:
            # 클라이언트로부터 메세지를 기다림
            data = await websocket.receive_text()
            
            # 서버가 처리한 결과를 JSON 형식으로 클라이언트에 전송
            response_data = {
                "message": f"Hello {user_id}, your message: {data}",
                "user_id": user_id
            }
            await websocket.send_text(json.dumps(response_data))  # JSON으로 전송
    except WebSocketDisconnect:
        print(f"User {user_id} disconnected")

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
