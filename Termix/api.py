# api.py
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional
from urllib.parse import quote
import httpx
import html as html_lib
import os
import re
import discord
from dotenv import load_dotenv

import config
from utils import database as db

load_dotenv()

STEAM_API_KEY = os.getenv("STEAM_API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "https://wgzdxhaeou.apps.bot-hosting.cloud")
FRONTEND_URL = os.getenv("FRONTEND_URL", BASE_URL)
DISCORD_INVITE = os.getenv("DISCORD_INVITE", "https://discord.gg/K8VndtvrHq")
ADMIN_KEY = os.getenv("ADMIN_KEY", "changeme123")

if ADMIN_KEY == "changeme123":
    print("⚠️  ADMIN_KEY is still the default — set a strong value in env vars!")

_bot = None


def set_bot(bot_instance):
    global _bot
    _bot = bot_instance
    print(f"✅ API: bot reference registered ({type(bot_instance).__name__})")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    print("✅ API started, DB initialized")
    yield
    print("🛑 API shutting down")


app = FastAPI(title="CS2 Tournament API", version="2.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_admin(request: Request):
    key = request.headers.get("X-Admin-Key") or request.query_params.get("key")
    if key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key")


# ─────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────
@app.get("/")
async def root():
    return {"status": "ok", "service": "CS2 Tournament API", "bot_ready": _bot is not None}


@app.get("/api/admin/check")
async def admin_check(request: Request):
    require_admin(request)
    return {"status": "ok", "admin": True}


# ─────────────────────────────────────────────
# Players
# ─────────────────────────────────────────────
@app.get("/api/players")
async def list_players():
    return await db.get_all_players()


@app.get("/api/players/{user_id}")
async def get_player(user_id: int):
    row = await db.get_player(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Player not found")
    return row


# ─────────────────────────────────────────────
# Matches
# ─────────────────────────────────────────────
@app.get("/api/matches")
async def list_matches(limit: int = Query(50, ge=1, le=200)):
    return await db.get_recent_matches(limit)


# ─────────────────────────────────────────────
# Leaderboard
# ─────────────────────────────────────────────
@app.get("/api/leaderboard")
async def leaderboard(guild_id: Optional[int] = None, limit: int = 20):
    if guild_id:
        return await db.get_leaderboard(guild_id, limit)
    return await db.get_global_leaderboard(limit)


# ─────────────────────────────────────────────
# Manual register
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
# Ban lookup
# ─────────────────────────────────────────────
@app.get("/api/bans/{user_id}")
async def check_ban(user_id: int):
    ban = await db.get_ban(user_id)
    if not ban:
        raise HTTPException(status_code=404, detail="Not banned")
    return ban


# ─────────────────────────────────────────────
# Discord presence
# ─────────────────────────────────────────────
@app.get("/api/discord/{user_id}")
async def discord_presence(user_id: int, guild_id: Optional[int] = None):
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
        try:
            member = await guild.fetch_member(user_id)
        except Exception:
            member = None

    return {"in_guild": member is not None, "user_id": user_id, "guild_id": guild.id}


# ─────────────────────────────────────────────
# Tournaments — public read
# ─────────────────────────────────────────────
@app.get("/api/tournaments")
async def list_tournaments():
    return await db.get_all_tournaments()


@app.get("/api/tournaments/{tid}")
async def get_tournament(tid: int):
    t = await db.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return t


# ─────────────────────────────────────────────
# Tournaments — admin write
# ─────────────────────────────────────────────
class TournamentPayload(BaseModel):
    name: str
    description: str = ""
    mode: str = "1v1"
    status: str = "draft"
    prize_pool: int = 0
    prize_extra: str = ""
    prize_split: str = ""
    entry_fee: str = ""
    rounds: str = ""
    starts_at: str = ""
    max_slots: int = 32
    rules_url: str = ""
    prize_image_url: str = ""
    prize_market_url: str = ""


@app.post("/api/tournaments")
async def create_tournament(payload: TournamentPayload, request: Request):
    require_admin(request)
    if payload.status not in ("draft", "open", "live", "completed", "cancelled"):
        raise HTTPException(status_code=400, detail="Invalid status")
    if payload.mode not in ("1v1", "2v2", "5v5"):
        raise HTTPException(status_code=400, detail="Invalid mode")
    tid = await db.create_tournament(payload.dict())
    return {"status": "created", "id": tid}


@app.put("/api/tournaments/{tid}")
async def update_tournament(tid: int, payload: TournamentPayload, request: Request):
    require_admin(request)
    existing = await db.get_tournament(tid)
    if not existing:
        raise HTTPException(status_code=404, detail="Tournament not found")
    await db.update_tournament(tid, payload.dict())
    return {"status": "updated", "id": tid}


@app.delete("/api/tournaments/{tid}")
async def delete_tournament(tid: int, request: Request):
    require_admin(request)
    existing = await db.get_tournament(tid)
    if not existing:
        raise HTTPException(status_code=404, detail="Tournament not found")
    await db.delete_tournament(tid)
    return {"status": "deleted", "id": tid}


class StatusPayload(BaseModel):
    status: str


@app.post("/api/tournaments/{tid}/status")
async def set_tournament_status(tid: int, payload: StatusPayload, request: Request):
    require_admin(request)
    if payload.status not in ("draft", "open", "live", "completed", "cancelled"):
        raise HTTPException(status_code=400, detail="Invalid status")
    existing = await db.get_tournament(tid)
    if not existing:
        raise HTTPException(status_code=404, detail="Tournament not found")
    await db.set_tournament_status(tid, payload.status)
    return {"status": "ok", "id": tid, "new_status": payload.status}


# ─────────────────────────────────────────────
# Tournament announcement → Discord
# ─────────────────────────────────────────────
@app.post("/api/tournaments/{tid}/announce")
async def announce_tournament(tid: int, request: Request):
    require_admin(request)
    if _bot is None:
        raise HTTPException(status_code=503, detail="Bot not connected — try again in a few seconds")
    t = await db.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")

    ch_id = getattr(config, "ANNOUNCE_CHANNEL_ID", 0) or 0
    channel = None
    if ch_id:
        channel = _bot.get_channel(ch_id)
        if channel is None:
            try:
                channel = await _bot.fetch_channel(ch_id)
            except Exception:
                channel = None
    if channel is None:
        raise HTTPException(status_code=503, detail="Announcement channel not reachable (check ANNOUNCE_CHANNEL_ID in config.py)")

    try:
        desc_lines = []
        if t.get("description"):
            desc_lines.append(t["description"])
        desc_lines.append("")
        desc_lines.append(f"**Mode:** {str(t.get('mode','')).upper()}")
        desc_lines.append(f"**Status:** {str(t.get('status','')).upper()}")
        if t.get("starts_at"):
            desc_lines.append(f"**Starts:** {t['starts_at']}")
        if t.get("rounds"):
            desc_lines.append(f"**Format:** {t['rounds']}")
        if t.get("entry_fee"):
            desc_lines.append(f"**Entry:** {t['entry_fee']}")
        if t.get("prize_pool") or t.get("prize_extra"):
            parts = []
            if t.get("prize_pool"):
                parts.append(f"${t['prize_pool']}")
            if t.get("prize_extra"):
                parts.append(t["prize_extra"])
            desc_lines.append(f"**Prize Pool:** {' + '.join(parts)}")
        if t.get("prize_split"):
            desc_lines.append(f"**Split:** {t['prize_split']}")
        if t.get("max_slots"):
            desc_lines.append(f"**Slots:** {t.get('registered', 0)}/{t['max_slots']}")

        embed = discord.Embed(
            title=f"🎮 {t['name']}",
            description="\n".join(desc_lines),
            color=0xFFB000,
        )
        if t.get("prize_image_url"):
            try:
                embed.set_image(url=t["prize_image_url"])
            except Exception:
                pass
        if t.get("rules_url"):
            embed.add_field(name="Rules", value=t["rules_url"], inline=False)
        embed.set_footer(text="Register with /register in Discord")
        await channel.send(embed=embed)
    except discord.Forbidden:
        raise HTTPException(status_code=403, detail="Bot lacks permission to send in the announcement channel")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to post: {e}")

    return {"status": "posted", "channel_id": channel.id, "tournament_id": tid}


# ─────────────────────────────────────────────
# Tournament registrations
# ─────────────────────────────────────────────
class TournamentRegisterPayload(BaseModel):
    discord_id: int
    discord_username: str = ""
    mode: str = "1v1"


@app.post("/api/tournaments/{tid}/register")
async def register_for_tournament(tid: int, payload: TournamentRegisterPayload):
    t = await db.get_tournament(tid)
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")

    if t["status"] != "open":
        raise HTTPException(status_code=400, detail=f"Registration closed (status: {t['status']})")

    ban = await db.get_ban(payload.discord_id)
    if ban:
        raise HTTPException(status_code=403, detail=f"Banned: {ban.get('reason', 'no reason given')}")

    rid = await db.register_for_tournament(
        tid, payload.discord_id, payload.discord_username, payload.mode
    )
    if rid is None:
        raise HTTPException(status_code=409, detail="Already registered for this tournament")

    return {"status": "registered", "registration_id": rid}


@app.get("/api/tournaments/{tid}/registrations")
async def list_registrations(tid: int, request: Request):
    require_admin(request)
    return await db.get_tournament_registrations(tid)


@app.post("/api/tournaments/{tid}/registrations/{rid}")
async def update_registration(tid: int, rid: int, payload: StatusPayload, request: Request):
    require_admin(request)
    if payload.status not in ("pending", "approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid status")
    await db.set_registration_status(rid, payload.status)
    return {"status": "ok", "registration_id": rid, "new_status": payload.status}


# ─────────────────────────────────────────────
# Steam OpenID
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


@app.get("/auth/steam/callback")
async def steam_callback(discord_id: int, request: Request):
    params = dict(request.query_params)
    params["openid.mode"] = "check_authentication"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                "https://steamcommunity.com/openid/login",
                data=params,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except Exception:
        return _vhs_error("VERIFY FAILED", "Could not reach Steam. Try again.")

    if "is_valid:true" not in r.text:
        return _vhs_error("VERIFY FAILED", "Steam rejected this login attempt.")

    claimed_id = params.get("openid.claimed_id", "")
    steam_id64 = claimed_id.rsplit("/", 1)[-1]
    if not steam_id64.isdigit():
        return _vhs_error("VERIFY FAILED", "No SteamID64 in Steam's response.")

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

    qp = f"steam_id={steam_id64}&name={quote(persona)}"
    if avatar:
        qp += f"&avatar={quote(avatar, safe='')}"

    return RedirectResponse(f"{BASE_URL}/register-success?{qp}")


async def fetch_steam_profile(steam_id: str) -> Optional[dict]:
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
                return {"personaname": persona, "avatarfull": avatar or "", "steamid": steam_id}
    except Exception as e:
        print(f"[steam] XML fetch failed: {e}")
    return None


def _xml_extract(xml: str, tag: str) -> Optional[str]:
    m = re.search(rf"<{tag}>\s*<!\[CDATA\[(.*?)\]\]>\s*</{tag}>", xml, re.DOTALL | re.IGNORECASE)
    if m: return m.group(1).strip()
    m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", xml, re.DOTALL | re.IGNORECASE)
    if m: return m.group(1).strip()
    return None


@app.get("/auth/success")
async def auth_success():
    return {"message": "✅ Steam account linked! You can close this tab."}


def _vhs_page(*, title, heading, sub, display_name="Player", steam_id="",
              avatar="", status_text="ELIGIBLE — CS2 1V1 TOURNAMENT",
              status_class="status-ok",
              cta_text="PROCEED TO REGISTRATION FOR TOURNAMENT ►",
              cta_href="", extra_note=""):
    esc_avatar = html_lib.escape(avatar, quote=True)
    esc_name = html_lib.escape(display_name)
    esc_steam = html_lib.escape(steam_id) if steam_id else "NOT-LINKED"
    is_err = status_class == "status-err"
    result_label = "RESULT: FAIL" if is_err else "RESULT: PASS"
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_lib.escape(title)} — TERMIX CS2</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=VT323&display=swap" rel="stylesheet">
<style>:root{{--bg:#0a0906;--panel:#13100a;--amber:#ffb000;--amber2:#ffd75e;--red:#ff5238;--green:#5ce07f;--txt:#e8dfc4;--dim:#6e6244;--line:#332b16}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{min-height:100vh;display:flex;align-items:center;justify-content:center;background:var(--bg);color:var(--txt);font:20px/1.45 'VT323',monospace;padding:34px 18px}}
.panel{{background:var(--panel);border:1px solid var(--line);max-width:600px;width:100%;padding:32px;text-align:center}}
h1{{font:22px 'Press Start 2P',monospace;color:{'var(--red)' if is_err else 'var(--amber)'};margin-bottom:14px}}
p{{color:var(--dim);margin-bottom:20px}}
a{{display:inline-block;background:var(--amber);color:#140f02;text-decoration:none;padding:14px 24px;font-family:'Press Start 2P',monospace;font-size:10px;letter-spacing:2px;margin-top:14px}}
</style></head><body><div class="panel"><h1>{heading}</h1><p>{sub}</p>
<p>Code: {esc_name} · Steam: {esc_steam}</p>
<a href="{cta_href or DISCORD_INVITE}">{cta_text}</a></div></body></html>"""


@app.get("/register-success", response_class=HTMLResponse)
async def register_success(steam_id: Optional[str] = None, name: Optional[str] = None, avatar: Optional[str] = None):
    return _vhs_page(
        title="CLEARANCE GRANTED", heading="✓ ACCESS GRANTED",
        sub="// STEAM ↔ DISCORD LINK ESTABLISHED //",
        display_name=name if name and name != "Unknown" else "Player",
        steam_id=steam_id or "", avatar=avatar or "",
    )


def _vhs_error(title: str, message: str, status_code: int = 400):
    return HTMLResponse(
        _vhs_page(title=title, heading="✗ ACCESS DENIED",
                  sub=f"// {html_lib.escape(message).upper()} //",
                  status_text="CLEARANCE FAILED — TRY AGAIN OR CONTACT STAFF",
                  status_class="status-err",
                  cta_text="RETURN TO DISCORD ►"),
        status_code=status_code,
    )
