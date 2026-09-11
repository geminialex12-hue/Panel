import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import Base, engine, get_db
from models import User, Profile


app = FastAPI(
    title="StandKnife API",
    version="1.0.0",
    description="Backend for StandKnife Telegram competitive platform",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
INIT_DATA_MAX_AGE = 86400


class TelegramAuth(BaseModel):
    init_data: str = Field(min_length=1, max_length=10000)


class RegistrationData(BaseModel):
    nickname: str = Field(
        min_length=2,
        max_length=32,
    )

    game_id: str = Field(
        min_length=1,
        max_length=64,
    )


def validate_telegram_init_data(
    init_data: str,
) -> dict:
    if not BOT_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="BOT_TOKEN is not configured",
        )

    try:
        parsed = dict(parse_qsl(init_data))
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid Telegram initData",
        )

    received_hash = parsed.pop("hash", None)

    if not received_hash:
        raise HTTPException(
            status_code=401,
            detail="Telegram hash missing",
        )

    auth_date = parsed.get("auth_date")

    if not auth_date:
        raise HTTPException(
            status_code=401,
            detail="Telegram auth_date missing",
        )

    try:
        if time.time() - int(auth_date) > INIT_DATA_MAX_AGE:
            raise HTTPException(
                status_code=401,
                detail="Telegram initData expired",
            )
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Invalid auth_date",
        )

    data_check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted(parsed.items())
    )

    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode(),
        hashlib.sha256,
    ).digest()

    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(
        calculated_hash,
        received_hash,
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid Telegram signature",
        )

    if "user" not in parsed:
        raise HTTPException(
            status_code=401,
            detail="Telegram user missing",
        )

    try:
        telegram_user = json.loads(parsed["user"])
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=401,
            detail="Invalid Telegram user data",
        )

    if "id" not in telegram_user:
        raise HTTPException(
            status_code=401,
            detail="Telegram user ID missing",
        )

    return telegram_user


async def get_current_user(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization required",
        )

    if not authorization.startswith("Telegram "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization scheme",
        )

    init_data = authorization.removeprefix(
        "Telegram "
    )

    telegram_user = validate_telegram_init_data(
        init_data
    )

    result = await db.execute(
        select(User).where(
            User.telegram_id == telegram_user["id"]
        )
    )

    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User is not registered",
        )

    if user.is_banned:
        raise HTTPException(
            status_code=403,
            detail="User is banned",
        )

    return user


@app.on_event("startup")
async def startup():
    async with engine.begin() as connection:
        await connection.run_sync(
            Base.metadata.create_all
        )


@app.get("/")
async def root():
    return {
        "name": "StandKnife API",
        "status": "online",
        "version": "1.0.0",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok"
    }


@app.post("/api/auth/telegram")
async def telegram_auth(
    data: TelegramAuth,
    db: AsyncSession = Depends(get_db),
):
    telegram_user = validate_telegram_init_data(
        data.init_data
    )

    telegram_id = telegram_user["id"]

    result = await db.execute(
        select(User).where(
            User.telegram_id == telegram_id
        )
    )

    user = result.scalar_one_or_none()

    if not user:
        user = User(
            telegram_id=telegram_id,
            username=telegram_user.get("username"),
            first_name=telegram_user.get("first_name"),
            accepted_terms=False,
        )

        db.add(user)
        await db.commit()
        await db.refresh(user)

        return {
            "registered": False,
            "user_id": user.id,
            "telegram_id": user.telegram_id,
            "message": "Registration required",
        }

    return {
        "registered": user.profile is not None,
        "user_id": user.id,
        "telegram_id": user.telegram_id,
    }


@app.post("/api/auth/register")
async def register(
    data: RegistrationData,
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authorization required",
        )

    if not authorization.startswith("Telegram "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization scheme",
        )

    telegram_user = validate_telegram_init_data(
        authorization.removeprefix("Telegram ")
    )

    result = await db.execute(
        select(User).where(
            User.telegram_id == telegram_user["id"]
        )
    )

    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User account not found",
        )

    if user.profile:
        raise HTTPException(
            status_code=409,
            detail="Profile already exists",
        )

    user.accepted_terms = True

    profile = Profile(
        user_id=user.id,
        game_nickname=data.nickname,
        game_id=data.game_id,
        elo=1000,
    )

    db.add(profile)

    await db.commit()
    await db.refresh(profile)

    return {
        "success": True,
        "message": "Registration completed",
        "profile": {
            "nickname": profile.game_nickname,
            "game_id": profile.game_id,
            "elo": profile.elo,
            "rank": "SILVER",
        },
    }


@app.get("/api/profile")
async def profile(
    user: User = Depends(get_current_user),
):
    if not user.profile:
        raise HTTPException(
            status_code=404,
            detail="Profile not found",
        )

    profile = user.profile

    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "nickname": profile.game_nickname,
        "game_id": profile.game_id,
        "elo": profile.elo,
        "wins": profile.wins,
        "losses": profile.losses,
        "kills": profile.kills,
        "deaths": profile.deaths,
        "premium": profile.premium,
    }


@app.get("/api/stats")
async def stats(
    user: User = Depends(get_current_user),
):
    if not user.profile:
        raise HTTPException(
            status_code=404,
            detail="Profile not found",
        )

    profile = user.profile
    games = profile.wins + profile.losses

    winrate = (
        round(profile.wins / games * 100, 1)
        if games
        else 0
    )

    kd = (
        round(profile.kills / profile.deaths, 2)
        if profile.deaths
        else float(profile.kills)
    )

    return {
        "games": games,
        "wins": profile.wins,
        "losses": profile.losses,
        "winrate": winrate,
        "kills": profile.kills,
        "deaths": profile.deaths,
        "kd": kd,
        "elo": profile.elo,
    }
