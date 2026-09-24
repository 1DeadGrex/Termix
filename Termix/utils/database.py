# utils/database.py — Turso (hosted SQLite over HTTP)
import os
import asyncio
import libsql_client

_raw_url = os.getenv("TURSO_URL", "https://termix-sk11led-1deadgrex.aws-ap-south-1.turso.io")
TURSO_TOKEN = os.getenv("TURSO_TOKEN", "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJnaWQiOiJhY2I3YmU1NC1jMTgxLTQzZDAtOTc2MS1mYTcwNTYxOGZkZjUiLCJpYXQiOjE3ODk5Njk5MDIsImtpZCI6IlppQ1d2ZDFMMThsRXJlRVo5UFdubDJsRUdGd21YMFdfV0s4ZjR2WW1md28iLCJyaWQiOiI5YzYyMjcxNC0yNWQ2LTQxYTYtYTE1YS05YzZmMTc2ODZiNzcifQ.RKK8hu0AsKHedxca8XUOMIJEPHGLrKOQwEUOmhcp3PnB70ZFO3q3KNYzV9P-CcRcI6h8FG7KrWSSIMHmmf_uAg")

TURSO_URL = (
    _raw_url.replace("libsql://", "https://")
             .replace("wss://", "https://")
             .rstrip("/")
)

print(f"🗄️  TURSO_URL raw  : {_raw_url!r}")
print(f"🗄️  TURSO_URL used : {TURSO_URL!r}")
print(f"🗄️  TURSO_TOKEN    : {'set (' + str(len(TURSO_TOKEN)) + ' chars)' if TURSO_TOKEN else 'MISSING'}")

if not TURSO_URL or not TURSO_TOKEN:
    print("⚠️  Turso credentials missing — database calls will fail.")

DB_PATH = TURSO_URL or "turso"
DB_TIMEOUT = 8.0


def _client():
    return libsql_client.create_client(url=TURSO_URL, auth_token=TURSO_TOKEN)


async def _execute(c, sql, args=None, timeout=DB_TIMEOUT):
    return await asyncio.wait_for(c.execute(sql, args or []), timeout)


async def _ensure_column(c, table, column, coltype):
    try:
        await c.execute(f'ALTER TABLE {table} ADD COLUMN {column} {coltype}')
        print(f"✅ Schema: added {table}.{column}")
    except Exception:
        pass


# ─────────────────────────────────────────────
# Init
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
            match_name TEXT DEFAULT '',
            match_map TEXT DEFAULT '',
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
        await c.execute('''CREATE TABLE IF NOT EXISTS tournaments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            mode TEXT NOT NULL DEFAULT '1v1',
            status TEXT NOT NULL DEFAULT 'draft',
            prize_pool INTEGER DEFAULT 0,
            prize_extra TEXT DEFAULT '',
            prize_split TEXT,
            entry_fee TEXT,
            rounds TEXT,
            starts_at TEXT,
            max_slots INTEGER DEFAULT 32,
            rules_url TEXT,
            prize_image_url TEXT DEFAULT '',
            prize_market_url TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        await c.execute('''CREATE TABLE IF NOT EXISTS tournament_registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id INTEGER NOT NULL,
            discord_id INTEGER NOT NULL,
            discord_username TEXT,
            mode TEXT,
            status TEXT DEFAULT 'pending',
            registered_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        await c.execute('''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )''')
        await c.execute('''CREATE TABLE IF NOT EXISTS voice_channels (
            channel_id INTEGER PRIMARY KEY,
            owner_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')

        # Migrations for old DBs
        await _ensure_column(c, "matches", "match_name", "TEXT DEFAULT ''")
        await _ensure_column(c, "matches", "match_map", "TEXT DEFAULT ''")
        await _ensure_column(c, "tournaments", "prize_extra", "TEXT DEFAULT ''")
        await _ensure_column(c, "tournaments", "prize_image_url", "TEXT DEFAULT ''")
        await _ensure_column(c, "tournaments", "prize_market_url", "TEXT DEFAULT ''")


# ─────────────────────────────────────────────
# Settings
# ─────────────────────────────────────────────
async def set_setting(key: str, value: str):
    async with _client() as c:
        await c.execute(
            '''INSERT INTO settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value''',
            [key, value],
        )


async def get_setting(key: str):
    async with _client() as c:
        result = await c.execute('SELECT value FROM settings WHERE key = ?', [key])
        if not result.rows:
            return None
        return result.rows[0][0]


async def delete_setting(key: str):
    async with _client() as c:
        await c.execute('DELETE FROM settings WHERE key = ?', [key])


# ─────────────────────────────────────────────
# Voice channels (temp VCs)
# ─────────────────────────────────────────────
async def add_temp_vc(channel_id: int, owner_id: int):
    async with _client() as c:
        await c.execute(
            '''INSERT INTO voice_channels (channel_id, owner_id) VALUES (?, ?)
               ON CONFLICT(channel_id) DO UPDATE SET owner_id = excluded.owner_id''',
            [channel_id, owner_id],
        )


async def get_temp_vc_by_owner(owner_id: int):
    async with _client() as c:
        result = await c.execute(
            'SELECT channel_id, owner_id FROM voice_channels WHERE owner_id = ? LIMIT 1',
            [owner_id],
        )
        if not result.rows:
            return None
        return {"channel_id": result.rows[0][0], "owner_id": result.rows[0][1]}


async def get_temp_vc_owner(channel_id: int):
    async with _client() as c:
        result = await c.execute(
            'SELECT owner_id FROM voice_channels WHERE channel_id = ?',
            [channel_id],
        )
        if not result.rows:
            return None
        return result.rows[0][0]


async def remove_temp_vc(channel_id: int):
    async with _client() as c:
        await c.execute('DELETE FROM voice_channels WHERE channel_id = ?', [channel_id])


async def get_all_temp_vcs():
    async with _client() as c:
        result = await c.execute('SELECT channel_id, owner_id FROM voice_channels')
        return [{"channel_id": r[0], "owner_id": r[1]} for r in result.rows]


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
            "user_id": r[0], "discord_name": r[1], "steam_id": r[2],
            "verified": bool(r[3]), "registered_at": r[4],
        }


async def get_all_players():
    async with _client() as c:
        result = await c.execute('SELECT user_id, discord_name, steam_id, verified FROM players')
        return [
            {"user_id": r[0], "discord_name": r[1], "steam_id": r[2], "verified": bool(r[3])}
            for r in result.rows
        ]


async def delete_player(user_id):
    async with _client() as c:
        await c.execute('DELETE FROM players WHERE user_id = ?', [user_id])


# ─────────────────────────────────────────────
# Matches
# ─────────────────────────────────────────────
async def add_match(winner_id, loser_id, score, match_name="", match_map=""):
    async with _client() as c:
        await c.execute(
            '''INSERT INTO matches
               (player1_id, player2_id, winner_id, score, match_name, match_map)
               VALUES (?, ?, ?, ?, ?, ?)''',
            [winner_id, loser_id, winner_id, score, match_name or "", match_map or ""],
        )


async def get_recent_matches(limit=50):
    async with _client() as c:
        sql = (
            'SELECT id, player1_id, player2_id, winner_id, score, match_name, match_map, played_at '
            'FROM matches ORDER BY played_at DESC, id DESC '
            f'LIMIT {int(limit)}'
        )
        result = await _execute(c, sql)
        return [
            {
                "id": r[0], "player1_id": r[1], "player2_id": r[2],
                "winner_id": r[3], "score": r[4],
                "match_name": r[5] or "", "match_map": r[6] or "",
                "played_at": r[7],
            }
            for r in result.rows
        ]


async def get_match_history(user_id, limit=10):
    async with _client() as c:
        sql = (
            '''SELECT id, player1_id, player2_id, winner_id, score, match_name, match_map, played_at
               FROM matches
               WHERE player1_id = ? OR player2_id = ?
               ORDER BY played_at DESC, id DESC '''
            f'LIMIT {int(limit)}'
        )
        result = await _execute(c, sql, [user_id, user_id])
        return [tuple(r) for r in result.rows]


# ─────────────────────────────────────────────
# XP / Leaderboard
# ─────────────────────────────────────────────
async def get_leaderboard(guild_id, limit=20):
    async with _client() as c:
        sql = (
            'SELECT user_id, xp, level FROM xp WHERE guild_id = ? '
            f'ORDER BY xp DESC LIMIT {int(limit)}'
        )
        result = await _execute(c, sql, [guild_id])
        return [
            {"rank": i, "user_id": r[0], "xp": r[1], "level": r[2]}
            for i, r in enumerate(result.rows, 1)
        ]


async def get_global_leaderboard(limit=10):
    async with _client() as c:
        sql = (
            'SELECT user_id, SUM(xp) AS total_xp, MAX(level) AS level '
            'FROM xp GROUP BY user_id ORDER BY total_xp DESC '
            f'LIMIT {int(limit)}'
        )
        result = await _execute(c, sql)
        return [
            {"rank": i, "user_id": r[0], "xp": r[1] or 0, "level": r[2] or 1}
            for i, r in enumerate(result.rows, 1)
        ]


async def add_xp(user_id, guild_id, amount=10):
    async with _client() as c:
        await _execute(
            c,
            '''INSERT INTO xp (user_id, guild_id, xp) VALUES (?, ?, ?)
               ON CONFLICT(user_id, guild_id) DO UPDATE SET xp = xp + ?''',
            [user_id, guild_id, amount, amount],
        )
        result = await _execute(c,
            'SELECT xp FROM xp WHERE user_id = ? AND guild_id = ?',
            [user_id, guild_id])
        xp = result.rows[0][0] if result.rows else amount
        level = int((xp / 100) ** 0.5)
        await _execute(c,
            'UPDATE xp SET level = ? WHERE user_id = ? AND guild_id = ?',
            [level, user_id, guild_id])
        return xp, level


# ─────────────────────────────────────────────
# Wins / Winstreak stats
# ─────────────────────────────────────────────
async def get_wins_leaderboard(limit=10):
    async with _client() as c:
        sql = (
            'SELECT winner_id, COUNT(*) AS wins FROM matches '
            'GROUP BY winner_id ORDER BY wins DESC, winner_id ASC '
            f'LIMIT {int(limit)}'
        )
        result = await _execute(c, sql)
        return [{"user_id": r[0], "wins": int(r[1] or 0)} for r in result.rows]


async def get_winstreaks(limit=10):
    """Current winstreak per player — walks each player's match history from newest."""
    async with _client() as c:
        result = await c.execute(
            'SELECT winner_id, player1_id, player2_id '
            'FROM matches ORDER BY played_at DESC, id DESC'
        )
        rows = result.rows

    history = {}
    for winner_id, p1, p2 in rows:
        loser_id = p2 if winner_id == p1 else p1
        history.setdefault(winner_id, []).append(True)
        history.setdefault(loser_id, []).append(False)

    streaks = {}
    for uid, results in history.items():
        streak = 0
        for r in results:
            if r:
                streak += 1
            else:
                break
        if streak > 0:
            streaks[uid] = streak

    top = sorted(streaks.items(), key=lambda x: -x[1])[:limit]
    return [{"user_id": uid, "streak": s} for uid, s in top]


# ─────────────────────────────────────────────
# Bans
# ─────────────────────────────────────────────
async def add_ban(user_id, reason, banned_by):
    async with _client() as c:
        await c.execute(
            '''INSERT INTO bans (user_id, reason, banned_by) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   reason = excluded.reason,
                   banned_by = excluded.banned_by''',
            [user_id, reason, banned_by],
        )


async def remove_ban(user_id):
    async with _client() as c:
        await c.execute('DELETE FROM bans WHERE user_id = ?', [user_id])


async def get_ban(user_id):
    async with _client() as c:
        result = await c.execute(
            'SELECT user_id, reason, banned_by, banned_at FROM bans WHERE user_id = ?',
            [user_id],
        )
        if not result.rows:
            return None
        r = result.rows[0]
        return {"user_id": r[0], "reason": r[1], "banned_by": r[2], "banned_at": r[3]}


# ─────────────────────────────────────────────
# Tournaments
# ─────────────────────────────────────────────
async def create_tournament(data: dict) -> int:
    async with _client() as c:
        result = await c.execute(
            '''INSERT INTO tournaments
               (name, description, mode, status, prize_pool, prize_extra,
                prize_split, entry_fee, rounds, starts_at, max_slots, rules_url,
                prize_image_url, prize_market_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            [
                data.get("name", "Untitled"),
                data.get("description", ""),
                data.get("mode", "1v1"),
                data.get("status", "draft"),
                int(data.get("prize_pool", 0) or 0),
                data.get("prize_extra", ""),
                data.get("prize_split", ""),
                data.get("entry_fee", ""),
                data.get("rounds", ""),
                data.get("starts_at", ""),
                int(data.get("max_slots", 32) or 32),
                data.get("rules_url", ""),
                data.get("prize_image_url", ""),
                data.get("prize_market_url", ""),
            ],
        )
        return result.last_insert_rowid


async def update_tournament(tid: int, data: dict):
    async with _client() as c:
        await c.execute(
            '''UPDATE tournaments SET
                name=?, description=?, mode=?, status=?, prize_pool=?,
                prize_extra=?, prize_split=?, entry_fee=?, rounds=?,
                starts_at=?, max_slots=?, rules_url=?,
                prize_image_url=?, prize_market_url=?,
                updated_at=CURRENT_TIMESTAMP
               WHERE id=?''',
            [
                data.get("name", "Untitled"),
                data.get("description", ""),
                data.get("mode", "1v1"),
                data.get("status", "draft"),
                int(data.get("prize_pool", 0) or 0),
                data.get("prize_extra", ""),
                data.get("prize_split", ""),
                data.get("entry_fee", ""),
                data.get("rounds", ""),
                data.get("starts_at", ""),
                int(data.get("max_slots", 32) or 32),
                data.get("rules_url", ""),
                data.get("prize_image_url", ""),
                data.get("prize_market_url", ""),
                tid,
            ],
        )


async def delete_tournament(tid: int):
    async with _client() as c:
        await c.execute('DELETE FROM tournament_registrations WHERE tournament_id = ?', [tid])
        await c.execute('DELETE FROM tournaments WHERE id = ?', [tid])


async def set_tournament_status(tid: int, status: str):
    async with _client() as c:
        await c.execute(
            'UPDATE tournaments SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            [status, tid],
        )


async def get_tournament(tid: int):
    async with _client() as c:
        result = await c.execute(
            'SELECT id, name, description, mode, status, prize_pool, prize_extra, '
            'prize_split, entry_fee, rounds, starts_at, max_slots, rules_url, '
            'prize_image_url, prize_market_url, created_at, updated_at '
            'FROM tournaments WHERE id = ?',
            [tid],
        )
        if not result.rows:
            return None
        r = result.rows[0]
        return {
            "id": r[0], "name": r[1], "description": r[2] or "",
            "mode": r[3], "status": r[4], "prize_pool": r[5] or 0,
            "prize_extra": r[6] or "", "prize_split": r[7] or "",
            "entry_fee": r[8] or "", "rounds": r[9] or "",
            "starts_at": r[10] or "", "max_slots": r[11] or 32,
            "rules_url": r[12] or "", "prize_image_url": r[13] or "",
            "prize_market_url": r[14] or "",
            "created_at": r[15], "updated_at": r[16],
        }


async def get_all_tournaments():
    async with _client() as c:
        result = await c.execute(
            '''SELECT t.id, t.name, t.description, t.mode, t.status,
                      t.prize_pool, t.prize_extra, t.prize_split, t.entry_fee,
                      t.rounds, t.starts_at, t.max_slots, t.rules_url,
                      t.prize_image_url, t.prize_market_url,
                      (SELECT COUNT(*) FROM tournament_registrations r
                       WHERE r.tournament_id = t.id AND r.status != 'rejected') AS reg_count
               FROM tournaments t
               ORDER BY
                 CASE t.status
                   WHEN 'live' THEN 1 WHEN 'open' THEN 2
                   WHEN 'draft' THEN 3 WHEN 'completed' THEN 4
                   ELSE 5 END,
                 t.starts_at ASC'''
        )
        return [
            {
                "id": r[0], "name": r[1], "description": r[2] or "",
                "mode": r[3], "status": r[4],
                "prize_pool": r[5] or 0, "prize_extra": r[6] or "",
                "prize_split": r[7] or "", "entry_fee": r[8] or "",
                "rounds": r[9] or "", "starts_at": r[10] or "",
                "max_slots": r[11] or 32, "rules_url": r[12] or "",
                "prize_image_url": r[13] or "", "prize_market_url": r[14] or "",
                "registered": r[15] or 0,
            }
            for r in result.rows
        ]


async def register_for_tournament(tid: int, discord_id: int, username: str, mode: str):
    async with _client() as c:
        existing = await c.execute(
            'SELECT id FROM tournament_registrations WHERE tournament_id = ? AND discord_id = ?',
            [tid, discord_id],
        )
        if existing.rows:
            return None
        result = await c.execute(
            '''INSERT INTO tournament_registrations
               (tournament_id, discord_id, discord_username, mode)
               VALUES (?, ?, ?, ?)''',
            [tid, discord_id, username or "", mode],
        )
        return result.last_insert_rowid


async def get_tournament_registrations(tid: int):
    async with _client() as c:
        result = await c.execute(
            'SELECT id, discord_id, discord_username, mode, status, registered_at '
            'FROM tournament_registrations WHERE tournament_id = ? '
            'ORDER BY registered_at DESC',
            [tid],
        )
        return [
            {"id": r[0], "discord_id": r[1], "discord_username": r[2] or "",
             "mode": r[3] or "", "status": r[4] or "pending", "registered_at": r[5]}
            for r in result.rows
        ]


async def set_registration_status(rid: int, status: str):
    async with _client() as c:
        await c.execute(
            'UPDATE tournament_registrations SET status = ? WHERE id = ?',
            [status, rid],
        )
