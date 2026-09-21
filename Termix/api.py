"""
api.py — Termix web API.
Runs in the SAME process as the Discord bot (app.py). The bot registers
itself here via set_bot() so endpoints can query live Discord state.
"""

import os
import json
import asyncio
import logging
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from typing import Optional

import aiosqlite
import discord
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

from utils.database import (
    DB_PATH,
    init_db,
    add_player,
    get_player,
    get_all_players,
    get_recent_matches,
    get_leaderboard,
    get_global_leaderboard,
)

log = logging.getLogger("termix.api")

# ── Bot handle ──
_bot = None


def set_bot(bot) -> None:
    global _bot
    _bot = bot
    log.info("API: bot reference registered (%s)", type(bot).__name__)


# ── Lifespan ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    log.info("API: database ready at %s", DB_PATH)
    yield


fastapi_app = FastAPI(title="Termix API", version="2.1", lifespan=lifespan)
app = fastapi_app  # alias so `uvicorn api:app` also works

fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ──
@fastapi_app.get("/")
async def health():
    return {"status": "ok", "bot_ready": _bot is not None}


# ── Players ──
@fastapi_app.get("/api/players")
async def list_players():
    return await get_all_players()


@fastapi_app.get("/api/players/{user_id}")
async def read_player(user_id: int):
    p = await get_player(user_id)
    if not p:
        raise HTTPException(status_code=404, detail="player not found")
    return p


@fastapi_app.post("/api/register")
async def manual_register(user_id: int, discord_name: str, steam_id: str, verified: int = 0):
    await add_player(user_id, discord_name, steam_id, verified)
    return {"status": "ok", "user_id": user_id}


# ── Matches ──
@fastapi_app.get("/api/matches")
async def list_matches(limit: int = Query(default=50, le=100)):
    return await get_recent_matches(limit)


# ── Leaderboard (guild optional) ──
@fastapi_app.get("/api/leaderboard")
async def leaderboard(
    guild_id: Optional[int] = Query(default=None),
    limit: int = Query(default=10, le=50),
):
    if guild_id is not None:
        return await get_leaderboard(guild_id, limit)
    return await get_global_leaderboard(limit)


# ── Discord presence ──
@fastapi_app.get("/api/discord/{user_id}")
async def discord_presence(user_id: int):
    if _bot is None or not getattr(_bot, "is_ready", lambda: False)():
        raise HTTPException(
            status_code=503,
            detail="bot not ready yet — still connecting, retry in a few seconds",
        )

    for guild in _bot.guilds:
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.NotFound:
                member = None
            except discord.HTTPException as e:
                log.warning("fetch_member(%s) failed: %s", user_id, e)
                member = None
        if member is not None:
            return {"in_guild": True, "user_id": user_id, "guild_id": guild.id}

    return {"in_guild": False}


# ── Ban lookup ──
@fastapi_app.get("/api/bans/{user_id}")
async def ban_lookup(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT reason, banned_by, banned_at FROM bans "
            "WHERE user_id = ? ORDER BY banned_at DESC LIMIT 1",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no ban on record")
    return {
        "reason": row["reason"],
        "banned_by": row["banned_by"],
        "banned_at": row["banned_at"],
    }


# ── Steam OpenID ──
STEAM_OPENID = "https://steamcommunity.com/openid/login"


def _base_url() -> str:
    return os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")


def _page(title: str, msg: str, ok: bool = False) -> str:
    color = "#57e389" if ok else "#ff5238"
    return f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>TERMIX — {title}</title>
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=VT323&display=swap" rel=stylesheet>
<style>body{{background:#0b0907;color:#ffb000;font:22px/1.6 VT323,monospace;display:grid;place-items:center;min-height:100vh;margin:0;padding:18px}}
div{{border:3px solid {color};padding:26px 32px;box-shadow:8px 8px 0 #000;max-width:90vw}}
h1{{font:14px 'Press Start 2P',monospace;color:{color};margin:0 0 14px}}</style></head>
<body><div><h1>{title}</h1><p>{msg}</p></div></body></html>"""


async def fetch_steam_profile(steam_id: str) -> dict:
    key = os.getenv("STEAM_API_KEY", "")
    if not key:
        return {}

    url = (
        "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
        f"?key={key}&steamids={steam_id}"
    )

    def _get() -> dict:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    try:
        data = await asyncio.to_thread(_get)
        players = data.get("response", {}).get("players", [])
        return players[0] if players else {}
    except Exception as e:
        log.warning("steam profile fetch failed: %s", e)
        return {}


@fastapi_app.get("/auth/steam")
async def auth_steam(discord_id: int):
    base = _base_url()
    params = {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "checkid_setup",
        "openid.return_to": f"{base}/auth/steam/callback?discord_id={discord_id}",
        "openid.realm": base,
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    }
    return RedirectResponse(STEAM_OPENID + "?" + urllib.parse.urlencode(params))


@fastapi_app.get("/auth/steam/callback")
async def auth_steam_callback(request: Request):
    form = dict(request.query_params)
    form["openid.mode"] = "check_authentication"

    def _verify() -> str:
        data = urllib.parse.urlencode(form).encode()
        req = urllib.request.Request(STEAM_OPENID, data=data)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode("utf-8", "replace")

    try:
        body = await asyncio.to_thread(_verify)
    except Exception:
        return HTMLResponse(
            _page("VERIFY FAILED", "Could not reach Steam. Try again."),
            status_code=502,
        )

    if "is_valid:true" not in body:
        return HTMLResponse(
            _page("VERIFY FAILED", "Steam rejected this login attempt."),
            status_code=400,
        )

    claimed = request.query_params.get("openid.claimed_id", "")
    steam_id = claimed.rstrip("/").rsplit("/", 1)[-1]
    if not steam_id.isdigit():
        return HTMLResponse(
            _page("VERIFY FAILED", "No SteamID64 in Steam's response."),
            status_code=400,
        )

    try:
        discord_id = int(request.query_params.get("discord_id", "0"))
    except ValueError:
        discord_id = 0

    if discord_id <= 0:
        return HTMLResponse(
            _page("MISSING DISCORD ID", "Open /register in Discord instead."),
            status_code=400,
        )

    profile = await fetch_steam_profile(steam_id)
    name = profile.get("personaname") or f"steam_{steam_id[-4:]}"
    await add_player(discord_id, name, steam_id, 1)

    return RedirectResponse(_base_url() + "/register-success")


@fastapi_app.get("/register-success")
async def register_success():
    return HTMLResponse(
        _page("VERIFIED ✓", "Steam linked. You're on the roster — see you at check-in.", ok=True)
    )

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
