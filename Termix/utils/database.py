# utils/database.py — Turso (hosted SQLite over HTTP)
import os
import libsql_client

# ── Config ──
_raw_url = os.getenv("TURSO_URL", "https://termix-sk11led-1deadgrex.aws-ap-south-1.turso.io")
TURSO_TOKEN = os.getenv("TURSO_TOKEN", "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJqdGkiOiIwOWVlZnJWX0VmR2F2QzRPclVtTEdnIiwib3JnX2lkIjoxMDAwMjUwNDI5fQ.iLLvapn6248Y5WHvVYMiEVjL-nlBWOUoHHN_mlg2gkN0BGibEsThMdisWIpIWUvkee8wX_Xy60ztjSUUDah9CA")

# Force HTTP transport (WSS is often blocked by bot hosts)
TURSO_URL = (
    _raw_url.replace("libsql://", "https://")
             .replace("wss://", "https://")
             .rstrip("/")
)

# ── Startup diagnostics ──
print(f"🗄️  TURSO_URL raw  : {_raw_url!r}")
print(f"🗄️  TURSO_URL used : {TURSO_URL!r}")
print(f"🗄️  TURSO_TOKEN    : {'set (' + str(len(TURSO_TOKEN)) + ' chars)' if TURSO_TOKEN else 'MISSING'}")

if not TURSO_URL or not TURSO_TOKEN:
    print("⚠️  Turso credentials missing — database calls will fail.")

# Keep for backward-compat with old code that imports DB_PATH
DB_PATH = TURSO_URL or "turso"


def _client():
    """Create a fresh libsql HTTP client. Cheap — no persistent connection."""
    return libsql_client.create_client(url=TURSO_URL, auth_token=TURSO_TOKEN)


# ─────────────────────────────────────────────
# Init — create tables if missing
# ─────────────────────────────────────────────
async def init_db():
    async with _client() as c:
        await c.execute('''CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            discord_name TEXT,
            steam_id TEXT,
            verified INTEGER DEFAULT 0,
            registered_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        await c.execute('''CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player1_id INTEGER,
            player2_id INTEGER,
            winner_id INTEGER,
            score TEXT,
            played_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        await c.execute('''CREATE TABLE IF NOT EXISTS xp (
            user_id INTEGER,
            guild_id INTEGER,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, guild_id)
        )''')
        await c.execute('''CREATE TABLE IF NOT EXISTS bans (
            user_id INTEGER PRIMARY KEY,
            reason TEXT,
            banned_by INTEGER,
            banned_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')


# ─────────────────────────────────────────────
# Players
# ─────────────────────────────────────────────
async def add_player(user_id, discord_name, steam_id, verified=False):
    async with _client() as c:
        await c.execute(
            '''INSERT INTO players (user_id, discord_name, steam_id, verified)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   discord_name = excluded.discord_name,
                   steam_id     = excluded.steam_id,
                   verified     = excluded.verified''',
            [user_id, discord_name, steam_id, int(bool(verified))],
        )


async def get_player(user_id):
    async with _client() as c:
        result = await c.execute(
            'SELECT user_id, discord_name, steam_id, verified, registered_at '
            'FROM players WHERE user_id = ?',
            [user_id],
        )
        if not result.rows:
            return None
        r = result.rows[0]
        return {
            "user_id": r[0],
            "discord_name": r[1],
            "steam_id": r[2],
            "verified": bool(r[3]),
            "registered_at": r[4],
        }


async def get_all_players():
    async with _client() as c:
        result = await c.execute(
            'SELECT user_id, discord_name, steam_id, verified FROM players'
        )
        return [
            {
                "user_id": r[0],
                "discord_name": r[1],
                "steam_id": r[2],
                "verified": bool(r[3]),
            }
            for r in result.rows
        ]


async def delete_player(user_id):
    async with _client() as c:
        await c.execute('DELETE FROM players WHERE user_id = ?', [user_id])


# ─────────────────────────────────────────────
# Matches
# ─────────────────────────────────────────────
async def add_match(winner_id, loser_id, score):
    async with _client() as c:
        await c.execute(
            'INSERT INTO matches (player1_id, player2_id, winner_id, score) '
            'VALUES (?, ?, ?, ?)',
            [winner_id, loser_id, winner_id, score],
        )


async def get_recent_matches(limit=50):
    async with _client() as c:
        result = await c.execute(
            'SELECT id, player1_id, player2_id, winner_id, score, played_at '
            'FROM matches ORDER BY played_at DESC LIMIT ?',
            [limit],
        )
        return [
            {
                "id": r[0],
                "player1_id": r[1],
                "player2_id": r[2],
                "winner_id": r[3],
                "score": r[4],
                "played_at": r[5],
            }
            for r in result.rows
        ]


async def get_match_history(user_id, limit=10):
    async with _client() as c:
        result = await c.execute(
            '''SELECT id, player1_id, player2_id, winner_id, score, played_at
               FROM matches
               WHERE player1_id = ? OR player2_id = ?
               ORDER BY played_at DESC LIMIT ?''',
            [user_id, user_id, limit],
        )
        return [tuple(r) for r in result.rows]


# ─────────────────────────────────────────────
# XP / Leaderboard
# ─────────────────────────────────────────────
async def get_leaderboard(guild_id, limit=20):
    async with _client() as c:
        result = await c.execute(
            'SELECT user_id, xp, level FROM xp WHERE guild_id = ? '
            'ORDER BY xp DESC LIMIT ?',
            [guild_id, limit],
        )
        return [
            {"rank": i, "user_id": r[0], "xp": r[1], "level": r[2]}
            for i, r in enumerate(result.rows, 1)
        ]


async def get_global_leaderboard(limit=10):
    async with _client() as c:
        result = await c.execute(
            'SELECT user_id, SUM(xp) AS total_xp, MAX(level) AS level '
            'FROM xp GROUP BY user_id ORDER BY total_xp DESC LIMIT ?',
            [limit],
        )
        return [
            {"rank": i, "user_id": r[0], "xp": r[1] or 0, "level": r[2] or 1}
            for i, r in enumerate(result.rows, 1)
        ]


async def add_xp(user_id, guild_id, amount=10):
    async with _client() as c:
        await c.execute(
            '''INSERT INTO xp (user_id, guild_id, xp)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id, guild_id)
               DO UPDATE SET xp = xp + ?''',
            [user_id, guild_id, amount, amount],
        )
        result = await c.execute(
            'SELECT xp FROM xp WHERE user_id = ? AND guild_id = ?',
            [user_id, guild_id],
        )
        xp = result.rows[0][0] if result.rows else amount
        level = int((xp / 100) ** 0.5)
        await c.execute(
            'UPDATE xp SET level = ? WHERE user_id = ? AND guild_id = ?',
            [level, user_id, guild_id],
        )
        return xp, level


# ─────────────────────────────────────────────
# Bans
# ─────────────────────────────────────────────
async def add_ban(user_id, reason, banned_by):
    async with _client() as c:
        await c.execute(
            '''INSERT INTO bans (user_id, reason, banned_by)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   reason   = excluded.reason,
                   banned_by = excluded.banned_by''',
            [user_id, reason, banned_by],
        )


async def remove_ban(user_id):
    async with _client() as c:
        await c.execute('DELETE FROM bans WHERE user_id = ?', [user_id])


async def get_ban(user_id):
    async with _client() as c:
        result = await c.execute(
            'SELECT user_id, reason, banned_by, banned_at '
            'FROM bans WHERE user_id = ?',
            [user_id],
        )
        if not result.rows:
            return None
        r = result.rows[0]
        return {
            "user_id": r[0],
            "reason": r[1],
            "banned_by": r[2],
            "banned_at": r[3],
        }
