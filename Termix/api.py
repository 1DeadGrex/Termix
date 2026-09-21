# api.py
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional
from urllib.parse import quote
import httpx
import os
import re
import aiosqlite
from dotenv import load_dotenv

from utils import database as db

load_dotenv()

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
STEAM_API_KEY = os.getenv("STEAM_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://wgzdxhaeou.apps.bot-hosting.cloud")
FRONTEND_URL = os.getenv("FRONTEND_URL", BASE_URL)
DISCORD_INVITE = os.getenv("DISCORD_INVITE", "https://discord.gg/b73rAp5Sug")


# ─────────────────────────────────────────────
# Bot reference (set by app.py at startup)
# ─────────────────────────────────────────────
_bot = None

def set_bot(bot_instance):
    """Called from app.py to give the API access to the running Discord bot."""
    global _bot
    _bot = bot_instance


# ─────────────────────────────────────────────
# Lifespan (startup + shutdown)
# ─────────────────────────────────────────────
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

# ─────────────────────────────────────────────
# CORS
# ─────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: tighten to ["https://yoursite.com"] in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────
@app.get("/")
async def root():
    return {"status": "ok", "service": "CS2 Tournament API"}


# ─────────────────────────────────────────────
# Players
# ─────────────────────────────────────────────
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


# ─────────────────────────────────────────────
# Matches
# ─────────────────────────────────────────────
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


# ─────────────────────────────────────────────
# Leaderboard (guild_id optional)
# ─────────────────────────────────────────────
@app.get("/api/leaderboard")
async def leaderboard(guild_id: Optional[int] = None, limit: int = 20):
    """
    Leaderboard endpoint.
    - With guild_id: top players in that guild.
    - Without: global top — XP summed across all guilds per user.
    """
    if guild_id:
        rows = await db.get_leaderboard(guild_id, limit)
    else:
        # Global top — sum XP across all guilds per user
        async with aiosqlite.connect(db.DB_PATH) as conn:
            async with conn.execute(
                "SELECT user_id, SUM(xp) AS total_xp, MAX(level) AS level "
                "FROM xp GROUP BY user_id ORDER BY total_xp DESC LIMIT ?",
                (limit,)
            ) as cur:
                rows = await cur.fetchall()

    return [
        {"rank": i, "user_id": r[0], "xp": r[1], "level": r[2]}
        for i, r in enumerate(rows, 1)
    ]


# ─────────────────────────────────────────────
# Manual register (optional — used by website)
# ─────────────────────────────────────────────
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


# ─────────────────────────────────────────────
# Ban check — used by frontend clearance scan
# ─────────────────────────────────────────────
@app.get("/api/bans/{user_id}")
async def check_ban(user_id: int):
    """
    Check if a user is banned.
    404 if not banned (frontend treats this as 'clear').
    200 with ban record if banned.
    """
    async with aiosqlite.connect(db.DB_PATH) as conn:
        async with conn.execute(
            "SELECT user_id, reason, banned_by, banned_at FROM bans WHERE user_id = ?",
            (user_id,)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Not banned")

    return {
        "user_id": row[0],
        "reason": row[1],
        "banned_by": row[2],
        "banned_at": row[3],
    }


# ─────────────────────────────────────────────
# Discord presence — is the user in the server?
# ─────────────────────────────────────────────
@app.get("/api/discord/{user_id}")
async def discord_presence(user_id: int, guild_id: Optional[int] = None):
    """
    Check if a Discord user is a member of the guild the bot is in.
    Returns {"in_guild": true/false, ...}.
    """
    if _bot is None:
        raise HTTPException(status_code=503, detail="Bot not available")

    guild = None
    if guild_id:
        guild = _bot.get_guild(guild_id)
    else:
        guild = _bot.guilds[0] if _bot.guilds else None

    if guild is None:
        raise HTTPException(status_code=503, detail="Bot not in any guild")

    member = guild.get_member(user_id)
    if member is None:
        # Cache miss — try a live fetch (requires Server Members intent)
        try:
            member = await guild.fetch_member(user_id)
        except Exception:
            member = None

    return {
        "in_guild": member is not None,
        "user_id": user_id,
        "guild_id": guild.id,
    }


# ─────────────────────────────────────────────
# Steam OpenID — Step 1: redirect to Steam
# ─────────────────────────────────────────────
@app.get("/auth/steam")
async def steam_login(discord_id: int):
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


# ─────────────────────────────────────────────
# Steam OpenID — Step 2: handle callback
# ─────────────────────────────────────────────
@app.get("/auth/steam/callback")
async def steam_callback(discord_id: int, request: Request):
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

    # Fetch profile (works even without API key — XML fallback)
    profile = await fetch_steam_profile(steam_id64)
    persona = (profile or {}).get("personaname") or "Unknown"
    avatar = (profile or {}).get("avatarfull") or ""

    print(f"[steam] linked {discord_id} → {steam_id64} ({persona})")

    await db.add_player(
        user_id=discord_id,
        discord_name=persona if persona != "Unknown" else f"Steam: {steam_id64}",
        steam_id=steam_id64,
        verified=True,
    )

    # Redirect to styled success page, passing name + avatar via query params
    qp = f"steam_id={steam_id64}&name={quote(persona)}"
    if avatar:
        qp += f"&avatar={quote(avatar, safe='')}"

    return RedirectResponse(f"{BASE_URL}/register-success?{qp}")


# ─────────────────────────────────────────────
# Steam profile fetch — API key optional
# ─────────────────────────────────────────────
async def fetch_steam_profile(steam_id: str) -> Optional[dict]:
    """
    Fetch Steam profile data.
    1. If STEAM_API_KEY is set → official Web API (JSON).
    2. Otherwise (or if API fails) → public XML profile (no key required).
    """
    # 1) Official API (only if key present)
    if STEAM_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/",
                    params={"key": STEAM_API_KEY, "steamids": steam_id},
                )
            players = r.json().get("response", {}).get("players", [])
            if players:
                return players[0]
        except Exception as e:
            print(f"[steam] Web API fetch failed: {e}")

    # 2) Public XML fallback (no key)
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            r = await client.get(
                f"https://steamcommunity.com/profiles/{steam_id}/?xml=1",
                headers={"User-Agent": "Mozilla/5.0 (TermixBot/1.0)"},
            )
        if r.status_code == 200:
            xml = r.text
            persona = _xml_extract(xml, "steamID")
            avatar = _xml_extract(xml, "avatarFull")
            if persona:
                return {
                    "personaname": persona,
                    "avatarfull": avatar or "",
                    "steamid": steam_id,
                }
    except Exception as e:
        print(f"[steam] XML fetch failed: {e}")

    return None


def _xml_extract(xml: str, tag: str) -> Optional[str]:
    """Extract a tag value from Steam's XML (CDATA or plain)."""
    m = re.search(
        rf"<{tag}>\s*<!\[CDATA\[(.*?)\]\]>\s*</{tag}>",
        xml, re.DOTALL | re.IGNORECASE
    )
    if m:
        return m.group(1).strip()
    m = re.search(
        rf"<{tag}>\s*(.*?)\s*</{tag}>",
        xml, re.DOTALL | re.IGNORECASE
    )
    if m:
        return m.group(1).strip()
    return None


# ─────────────────────────────────────────────
# Plain success endpoint (fallback, JSON)
# ─────────────────────────────────────────────
@app.get("/auth/success")
async def auth_success():
    return {"message": "✅ Steam account linked! You can close this tab."}


# ─────────────────────────────────────────────
# Styled success page
# ─────────────────────────────────────────────
@app.get("/register-success", response_class=HTMLResponse)
async def register_success(
    steam_id: Optional[str] = None,
    name: Optional[str] = None,
    avatar: Optional[str] = None,
):
    display_name = name if name and name != "Unknown" else "Player"
    steam_line = f'<div class="steam-id">Steam ID: {steam_id}</div>' if steam_id else ""
    avatar_attr = f' data-avatar="{avatar}"' if avatar else ""

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>CLEARANCE GRANTED — TERMIX CS2</title>
        <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' height='16' fill='%230a0906'/%3E%3Crect x='3' y='3' width='10' height='3' fill='%23ffb000'/%3E%3Crect x='6.5' y='3' width='3' height='10' fill='%23ffb000'/%3E%3C/svg%3E">
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=VT323&display=swap" rel="stylesheet">
        <style>
            :root{{
                --bg:#0a0906; --panel:#13100a; --panel2:#1a1508; --ink:#171207;
                --line:#332b16; --line2:#4d3f1d; --deep:#7a5c0d;
                --amber:#ffb000; --amber2:#ffd75e;
                --txt:#e8dfc4; --mut:#9b8c66; --dim:#6e6244;
                --red:#ff5238; --green:#5ce07f;
                --disp:'Press Start 2P',monospace; --mono:'VT323',monospace;
            }}
            *{{margin:0;padding:0;box-sizing:border-box}}
            body{{
                min-height:100vh;
                display:flex;
                align-items:center;
                justify-content:center;
                background:var(--bg);
                color:var(--txt);
                font:20px/1.45 var(--mono);
                padding:34px 18px;
                overflow-x:hidden;
            }}
            ::selection{{background:var(--amber);color:#140f02}}
            a{{color:var(--amber)}}

            .fx-scan{{position:fixed;inset:0;z-index:900;pointer-events:none;background:repeating-linear-gradient(0deg,rgba(0,0,0,.20) 0 1px,transparent 1px 3px)}}
            .fx-vig{{position:fixed;inset:0;z-index:900;pointer-events:none;background:radial-gradient(ellipse 120% 100% at 50% 45%,transparent 60%,rgba(0,0,0,.5) 100%)}}
            .fx-noise{{position:fixed;inset:0;z-index:901;pointer-events:none;opacity:.10;mix-blend-mode:overlay;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='140' height='140' filter='url(%23n)' opacity='0.6'/%3E%3C/svg%3E");animation:noiseShift .35s steps(3) infinite}}
            @keyframes noiseShift{{0%{{background-position:0 0}}33%{{background-position:-34px 12px}}66%{{background-position:22px -28px}}100%{{background-position:0 0}}}}
            #roll{{position:fixed;left:0;right:0;height:90px;top:-15%;z-index:902;pointer-events:none;background:linear-gradient(180deg,transparent,rgba(255,215,120,.09),transparent);animation:rollA 7s linear infinite}}
            @keyframes rollA{{0%{{top:-15%}}100%{{top:110%}}}}
            #boot{{position:fixed;inset:0;z-index:1000;background:#000;display:grid;place-items:center;color:var(--amber);font:14px var(--disp);letter-spacing:2px;animation:bootGone .35s ease .9s forwards}}
            @keyframes bootGone{{to{{opacity:0;visibility:hidden}}}}
            @keyframes blink{{50%{{opacity:0}}}}
            @keyframes led{{0%,55%{{opacity:1}}56%,100%{{opacity:.2}}}}

            .osd{{position:fixed;z-index:905;pointer-events:none;font:20px var(--mono);color:var(--amber2);letter-spacing:2px;text-shadow:0 0 7px rgba(255,176,0,.35);opacity:.9}}
            .osd.tl{{top:14px;left:18px}}
            .osd.tr{{top:14px;right:18px;text-align:right}}
            .osd.bl{{bottom:12px;left:18px;color:var(--dim)}}
            .rec{{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--red);animation:blink 1s steps(1) infinite;margin-right:7px;vertical-align:1px}}

            .wrap{{position:relative;z-index:10;width:min(600px,100%);animation:crtIn .5s both}}
            @keyframes crtIn{{0%{{opacity:0;transform:scaleY(.75)}}45%{{opacity:.7;transform:scaleY(1.03)}}70%{{opacity:.85;transform:scaleY(.99)}}100%{{opacity:1;transform:none}}}}
            .panel{{background:var(--panel);border:1px solid var(--line);box-shadow:0 0 0 1px #000,0 24px 60px rgba(0,0,0,.7)}}
            .panel-h{{display:flex;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid var(--line);background:var(--panel2);font:17px var(--mono);letter-spacing:3px;color:var(--mut);text-transform:uppercase}}
            .panel-h .sq{{width:8px;height:8px;background:var(--amber);flex:none;animation:blink 1.3s steps(1) infinite}}
            .panel-h .right{{margin-left:auto;color:var(--dim);letter-spacing:1px}}

            .marquee{{border-bottom:1px solid var(--line);background:#0e0c06;overflow:hidden}}
            .mq-track{{display:flex;width:max-content;animation:mq 24s linear infinite}}
            .mq-track span{{white-space:nowrap;padding:6px 0;font:18px var(--mono);letter-spacing:2px;color:var(--mut)}}
            .mq-track .hot{{color:var(--amber)}}
            @keyframes mq{{to{{transform:translateX(-50%)}}}}

            .body{{padding:26px 24px 28px;text-align:center}}
            .granted{{font:clamp(15px,4.6vw,23px) var(--disp);color:var(--amber);line-height:1.55;letter-spacing:1px;text-shadow:2px 0 rgba(255,60,60,.25),-2px 0 rgba(60,220,255,.25),0 0 18px rgba(255,176,0,.22);margin-bottom:8px}}
            .sub{{font:19px var(--mono);letter-spacing:3px;color:var(--dim);margin-bottom:22px}}

            .dossier{{display:grid;grid-template-columns:150px 1fr;gap:18px;align-items:stretch;background:var(--ink);border:1px solid var(--line2);padding:16px;text-align:left}}
            .frame{{position:relative;width:150px;height:150px;background:#000;border:1px solid var(--line2);overflow:hidden}}
            .frame img{{width:100%;height:100%;object-fit:cover;display:block;filter:grayscale(.35) sepia(.85) saturate(2.1) hue-rotate(-12deg) contrast(1.22) brightness(.86);animation:crtFlick 5s infinite}}
            @keyframes crtFlick{{0%,91%,94%,98%,100%{{opacity:1}}92%{{opacity:.84}}96%{{opacity:.92}}}}
            .f-scan{{position:absolute;inset:0;pointer-events:none;background:repeating-linear-gradient(0deg,rgba(0,0,0,.3) 0 2px,transparent 2px 4px)}}
            .f-tag{{position:absolute;left:6px;bottom:6px;font:14px var(--mono);letter-spacing:1px;color:var(--amber2);background:rgba(10,8,3,.75);border:1px solid var(--line2);padding:1px 6px}}

            .idrows{{display:flex;flex-direction:column;justify-content:center;min-width:0}}
            .kv{{display:flex;gap:12px;padding:8px 0;border-bottom:1px dashed var(--line);font:20px var(--mono);align-items:baseline}}
            .kv:last-child{{border-bottom:none}}
            .kv b{{color:var(--dim);font-weight:normal;letter-spacing:2px;min-width:110px;font-size:16px;flex:none}}
            .kv .val{{color:var(--txt);letter-spacing:1px;word-break:break-all;min-width:0}}
            .kv .val.ok{{color:var(--green)}}
            .kv .val.who{{color:var(--amber2);font-size:22px}}
            .idrow{{display:flex;align-items:center;gap:8px;min-width:0;flex:1}}
            .mini{{flex:none;background:var(--panel2);border:1px solid var(--line2);color:var(--mut);font:15px var(--mono);letter-spacing:1px;padding:3px 8px;cursor:pointer;transition:border-color .12s,color .12s}}
            .mini:hover{{border-color:var(--amber);color:var(--amber)}}

            .status{{display:inline-flex;align-items:center;gap:9px;color:var(--green);border:1px solid #1d3a24;background:#0d1a10;font:16px var(--mono);letter-spacing:3px;padding:5px 13px;margin-top:20px}}
            .led{{width:8px;height:8px;background:var(--green);animation:led 1.6s steps(1) infinite;flex:none}}

            .cta{{margin-top:22px}}
            .btn{{display:inline-flex;align-items:center;justify-content:center;gap:10px;font:20px/1.25 var(--mono);letter-spacing:2px;padding:13px 24px;cursor:pointer;border:2px solid;text-decoration:none;text-align:center}}
            .btn-solid{{background:var(--amber);color:#140f02;border-color:var(--amber2) var(--deep) var(--deep) var(--amber2)}}
            .btn-solid:hover{{background:var(--amber2);box-shadow:0 0 26px rgba(255,176,0,.35)}}
            .btn-solid:active{{border-color:var(--deep) var(--amber2) var(--amber2) var(--deep);transform:translate(1px,1px)}}
            .hint{{margin-top:12px;font:16px var(--mono);color:var(--dim);letter-spacing:1px}}

            .foot{{border-top:1px solid var(--line);padding:9px 16px;font:15px var(--mono);color:var(--dim);letter-spacing:1px;display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}}
            .cur{{display:inline-block;width:9px;height:15px;background:var(--amber);animation:blink 1s steps(1) infinite;vertical-align:-2px}}

            @media (max-width:540px){{
                .dossier{{grid-template-columns:1fr;justify-items:center}}
                .frame{{width:132px;height:132px}}
                .idrows{{width:100%}}
                .osd.bl{{display:none}}
            }}
            @media (prefers-reduced-motion:reduce){{
                #boot{{display:none}}
                #roll,.fx-noise,.frame img,.mq-track,.panel-h .sq,.rec,.led,.cur,.wrap{{animation:none!important}}
            }}
        </style>
    </head>
    <body>
        <div id="boot" aria-hidden="true">TERMIX OS · SIGNAL LOCK <span class="cur"></span></div>
        <div class="fx-scan" aria-hidden="true"></div>
        <div class="fx-vig" aria-hidden="true"></div>
        <div class="fx-noise" aria-hidden="true"></div>
        <div id="roll" aria-hidden="true"></div>

        <div class="osd tl" aria-hidden="true"><span class="rec"></span>REC</div>
        <div class="osd tr" aria-hidden="true">► PLAY<br><span id="osdClock">SP 0:00:00</span></div>
        <div class="osd bl" aria-hidden="true">CH·04 // TERMIX UPLINK // SP MODE</div>

        <div class="wrap">
            <div class="panel">
                <div class="panel-h">
                    <span class="sq"></span>REGISTER.EXE — CLEARANCE SCAN
                    <span class="right">RESULT: PASS</span>
                </div>
                <div class="marquee" aria-hidden="true"><div class="mq-track">
                    <span class="hot">★★★ STEAM LINK ESTABLISHED ★★★</span><span>&nbsp;OPERATIVE VERIFIED · CLEARANCE GRANTED ·&nbsp;</span><span class="hot">GLHF ★</span><span>&nbsp;·&nbsp;</span>
                    <span class="hot">★★★ STEAM LINK ESTABLISHED ★★★</span><span>&nbsp;OPERATIVE VERIFIED · CLEARANCE GRANTED ·&nbsp;</span><span class="hot">GLHF ★</span><span>&nbsp;·&nbsp;</span>
                </div></div>

                <div class="body">
                    <div class="granted">✓ ACCESS GRANTED</div>
                    <div class="sub">// STEAM ↔ DISCORD LINK ESTABLISHED //</div>

                    <div class="dossier">
                        <div class="frame">
                            <img id="avatar" alt="Steam avatar" data-avatar="{avatar or ''}" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' height='16' fill='%230a0906'/%3E%3Crect x='5' y='2' width='6' height='7' fill='%23ffb000'/%3E%3Crect x='6' y='4' width='1' height='1' fill='%230a0906'/%3E%3Crect x='9' y='4' width='1' height='1' fill='%230a0906'/%3E%3Crect x='7' y='6' width='2' height='1' fill='%230a0906'/%3E%3Crect x='3' y='10' width='10' height='6' fill='%237a5c0d'/%3E%3C/svg%3E">
                            <div class="f-scan"></div>
                            <span class="f-tag" id="camTag">ID·CAM</span>
                        </div>
                        <div class="idrows">
                            <div class="kv"><b>CODENAME</b><span class="val who">{display_name}</span></div>
                            <div class="kv"><b>STEAM ID64</b><span class="idrow"><span class="val" id="sidVal">{steam_id if steam_id else "NOT-LINKED"}</span><button class="mini" id="copyBtn" type="button">COPY</button></span></div>
                            <div class="kv"><b>STATUS</b><span class="val ok">VERIFIED ✓</span></div>
                        </div>
                    </div>

                    <div class="status"><i class="led"></i>ELIGIBLE — CS2 1V1 TOURNAMENT</div>

                    <div class="cta">
                        <a class="btn btn-solid" href="{DISCORD_INVITE}">PROCEED TO REGISTRATION FOR TOURNAMENT ►</a>
                        <div class="hint">keep this tab open until check-in · see you on the grid</div>
                    </div>
                </div>

                <div class="foot">
                    <span>TERMIX // GRID v2.4.1</span>
                    <span>UPLINK OK © 2025 <span class="cur"></span></span>
                </div>
            </div>
        </div>

        <script>
        'use strict';
        (function(){{
            var q = new URLSearchParams(location.search);
            var sid = q.get('steam_id') || '';
            var img = document.getElementById('avatar');
            var tag = document.getElementById('camTag');
            var copyBtn = document.getElementById('copyBtn');

            /* VHS tape counter */
            var t0 = Date.now();
            var clock = document.getElementById('osdClock');
            function pad(n){{ return (n < 10 ? '0' : '') + n; }}
            setInterval(function(){{
                var s = Math.floor((Date.now() - t0) / 1000);
                clock.textContent = 'SP ' + Math.floor(s / 3600) + ':' + pad(Math.floor(s % 3600 / 60)) + ':' + pad(s % 60);
            }}, 1000);

            /* copy steam id */
            if (copyBtn) {{
                if (!sid) {{ copyBtn.style.display = 'none'; }}
                copyBtn.addEventListener('click', function(){{
                    var done = function(){{ copyBtn.textContent = 'COPIED'; setTimeout(function(){{ copyBtn.textContent = 'COPY'; }}, 1200); }};
                    if (navigator.clipboard && navigator.clipboard.writeText) {{
                        navigator.clipboard.writeText(sid).then(done, done);
                    }} else {{
                        var ta = document.createElement('textarea');
                        ta.value = sid;
                        document.body.appendChild(ta);
                        ta.select();
                        try {{ document.execCommand('copy'); }} catch(e){{}}
                        ta.remove();
                        done();
                    }}
                }});
            }}

            /* ── AVATAR: server-provided first, CORS proxies as fallback ── */
            var serverAvatar = img.getAttribute('data-avatar') || q.get('avatar') || '';

            function setAvatar(url){{
                var probe = new Image();
                probe.onload = function(){{ img.src = url; tag.textContent = 'LIVE FEED'; tag.style.color = '#5ce07f'; }};
                probe.onerror = function(){{}};
                probe.src = url;
            }}
            function extract(txt){{
                var m = txt.match(/<avatarFull>\\s*<!\\[CDATA\\[([\\s\\S]*?)\\]\\]>\\s*<\\/avatarFull>/i) ||
                        txt.match(/<avatarFull>\\s*(https[^<\\s]+)\\s*<\\/avatarFull>/i);
                return m ? m[1] : null;
            }}

            if (serverAvatar && /^https?:/i.test(serverAvatar)) {{
                /* Fast path — the server already fetched it for us */
                setAvatar(serverAvatar);
            }} else if (sid && /^\\d{{15,20}}$/.test(sid)) {{
                /* Fallback — client-side fetch via CORS relays */
                var target = 'https://steamcommunity.com/profiles/' + sid + '/?xml=1';
                var relays = [
                    'https://api.allorigins.win/raw?url=' + encodeURIComponent(target),
                    'https://api.codetabs.com/v1/proxy?quest=' + encodeURIComponent(target)
                ];
                (function attempt(i){{
                    if (i >= relays.length) {{ tag.textContent = 'NO SIGNAL'; return; }}
                    var opts = (window.AbortSignal && AbortSignal.timeout) ? {{ signal: AbortSignal.timeout(6500) }} : {{}};
                    fetch(relays[i], opts)
                        .then(function(r){{ return r.ok ? r.text() : Promise.reject(); }})
                        .then(function(txt){{
                            var u = extract(txt);
                            if (u) {{ setAvatar(u); }} else {{ throw new Error('no-avatar'); }}
                        }})
                        .catch(function(){{ attempt(i + 1); }});
                }})(0);
            }} else {{
                tag.textContent = 'NO SIGNAL';
            }}
        }})();
        </script>
    </body>
    </html>
    """
