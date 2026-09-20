# api.py
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
import httpx
import os
from dotenv import load_dotenv

from utils import database as db

load_dotenv()

# ─── Config from env ───
STEAM_API_KEY = os.getenv("STEAM_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


# ─── Lifespan (startup + shutdown) ───
@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    print("✅ API started, DB initialized")
    yield
    print("🛑 API shutting down")


app = FastAPI(
    title="CS2 Tournament API",
    version="1.0.0",
    lifespan=lifespan
)

# ─── CORS ───
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # change to your domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Health check ───
@app.get("/")
async def root():
    return {"status": "ok", "service": "CS2 Tournament API"}


# ─── Players ───
@app.get("/api/players")
async def list_players():
    rows = await db.get_all_players()
    return [
        {
            "user_id": r[0],
            "discord_name": r[1],
            "steam_id": r[2],
            "verified": bool(r[3]) if len(r) > 3 else False,
        }
        for r in rows
    ]


@app.get("/api/players/{user_id}")
async def get_player(user_id: int):
    row = await db.get_player(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Player not found")
    return {
        "user_id": row[0],
        "discord_name": row[1],
        "steam_id": row[2],
        "verified": bool(row[3]),
        "registered_at": row[4] if len(row) > 4 else None,
    }


# ─── Matches ───
@app.get("/api/matches")
async def list_matches(limit: int = Query(50, ge=1, le=200)):
    rows = await db.get_recent_matches(limit)
    return [
        {
            "id": r[0],
            "player1_id": r[1],
            "player2_id": r[2],
            "winner_id": r[3],
            "score": r[4],
            "played_at": r[5],
        }
        for r in rows
    ]


# ─── Leaderboard ───
@app.get("/api/leaderboard")
async def leaderboard(guild_id: int, limit: int = 20):
    rows = await db.get_leaderboard(guild_id, limit)
    return [
        {"rank": i, "user_id": r[0], "xp": r[1], "level": r[2]}
        for i, r in enumerate(rows, 1)
    ]


# ─── Manual register (used by website form, optional) ───
class RegisterPayload(BaseModel):
    user_id: int
    discord_name: str
    steam_id: str


@app.post("/api/register")
async def register(payload: RegisterPayload):
    await db.add_player(
        user_id=payload.user_id,
        discord_name=payload.discord_name,
        steam_id=payload.steam_id,
        verified=False,
    )
    return {"status": "registered", "user_id": payload.user_id}


# ─── Steam OpenID ───
@app.get("/auth/steam")
async def steam_login(discord_id: int):
    """Redirect user to Steam to verify their account."""
    return_to = f"{BASE_URL}/auth/steam/callback?discord_id={discord_id}"
    steam_url = (
        "https://steamcommunity.com/openid/login"
        "?openid.ns=http://specs.openid.net/auth/2.0"
        "&openid.mode=checkid_setup"
        f"&openid.return_to={return_to}"
        f"&openid.realm={BASE_URL}"
        "&openid.identity=http://specs.openid.net/auth/2.0/identifier_select"
        "&openid.claimed_id=http://specs.openid.net/auth/2.0/identifier_select"
    )
    return RedirectResponse(steam_url)


@app.get("/auth/steam/callback")
async def steam_callback(discord_id: int, request: Request):
    """Steam redirects here. Verify signature, extract Steam ID, save."""
    params = dict(request.query_params)
    params["openid.mode"] = "check_authentication"

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            "https://steamcommunity.com/openid/login",
            data=params,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if "is_valid:true" not in r.text:
        raise HTTPException(status_code=400, detail="Steam authentication failed")

    claimed_id = params.get("openid.claimed_id", "")
    steam_id64 = claimed_id.rsplit("/", 1)[-1]

    if not steam_id64.isdigit():
        raise HTTPException(status_code=400, detail="Invalid Steam ID")

    profile = await fetch_steam_profile(steam_id64)
    persona = profile.get("personaname", "Unknown") if profile else "Unknown"

    await db.add_player(
        user_id=discord_id,
        discord_name=f"Steam: {persona}",
        steam_id=steam_id64,
        verified=True,
    )

    return RedirectResponse(f"{FRONTEND_URL}/register-success?steam_id={steam_id64}")


@app.get("/auth/success")
async def auth_success():
    return {"message": "✅ Steam account linked! You can close this tab."}


async def fetch_steam_profile(steam_id: str):
    """Fetch profile from Steam Web API (optional but nice)."""
    if not STEAM_API_KEY:
        return None
    url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                url, params={"key": STEAM_API_KEY, "steamids": steam_id}
            )
        data = r.json()
        players = data.get("response", {}).get("players", [])
        return players[0] if players else None
    except Exception as e:
        print(f"Steam profile fetch failed: {e}")
        return None
