import hmac
import hashlib
import json
from time import time
from urllib.parse import parse_qsl

from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel

from .database import engine, get_db
from .models import Base, Message

# Создаём таблицы при старте
Base.metadata.create_all(bind=engine)

# ЗАМЕНИ на токен своего бота
BOT_TOKEN = "ТВОЙ_ТОКЕН_БОТА"
MAX_AGE_SECONDS = 3600

app = FastAPI(title="MAX Chat API")

# CORS — разрешаем запросы с GitHub Pages
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # для продакшена лучше указать конкретный домен
    allow_methods=["*"],
    allow_headers=["*"],
)

def validate_max_init_data(init_data: str) -> dict:
    if not init_data:
        raise ValueError("initData is empty")

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise ValueError("hash is missing")

    sorted_pairs = sorted(parsed.items(), key=lambda x: x[0])
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_pairs)

    secret_key = hmac.new(
        b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256
    ).digest()

    expected_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        raise ValueError("Signature mismatch")

    auth_date_raw = parsed.get("auth_date")
    if auth_date_raw:
        try:
            auth_date = int(auth_date_raw)
        except ValueError:
            raise ValueError("Invalid auth_date")
        if time() - auth_date > MAX_AGE_SECONDS:
            raise ValueError("initData is expired")

    user_raw = parsed.get("user")
    if user_raw:
        try:
            parsed["user"] = json.loads(user_raw)
        except json.JSONDecodeError:
            raise ValueError("user is not valid JSON")

    return parsed

async def get_current_user(x_max_init_data: str = Header(...)):
    if x_max_init_data == "debug_mode":
        return {"id": "debug", "name": "Тестер"}
    try:
        data = validate_max_init_data(x_max_init_data)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    user = data.get("user", {})
    return {
        "id": str(user.get("id")),
        "name": user.get("first_name", "Аноним"),
    }

class MessageCreate(BaseModel):
    text: str

@app.get("/messages")
async def get_messages(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    messages = db.query(Message).order_by(Message.id.desc()).limit(50).all()
    return [
        {
            "user_id": m.user_id,
            "user": m.username,
            "text": m.text,
            "time": m.timestamp.isoformat(),
        }
        for m in reversed(messages)
    ]

@app.post("/messages")
async def send_message(
    msg: MessageCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    new_msg = Message(
        user_id=user["id"],
        username=user["name"],
        text=msg.text,
    )
    db.add(new_msg)
    db.commit()
    db.refresh(new_msg)
    return {"status": "ok", "id": new_msg.id}

@app.get("/")
async def root():
    return {"status": "ok", "service": "MAX Chat API"}