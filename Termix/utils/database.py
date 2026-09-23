# utils/database.py — Turso (hosted SQLite over HTTP)
import os
import libsql_client

# ── Config ──
_raw_url = os.getenv("TURSO_URL", "")
TURSO_TOKEN = os.getenv("TURSO_TOKEN", "")

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

# Backward-compat export
DB_PATH = TURSO_URL or "turso"


def _client():
    """Fresh libsql HTTP client per call. Cheap — no persistent connection."""
    return libsql_client.create_client(url=TURSO_URL, auth_token=TURSO_TOKEN)


# ─────────────────────────────────────────────
# Init
# ─────────────────────────────────────────────
async def init_db():
    async with _client() as c:
        # Players
        await c.execute('''CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            discord_name TEXT,
            steam_id TEXT,
            verified INTEGER DEFAULT 0,
            registered_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        # Matches
        await c.execute('''CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player1_id INTEGER,
            player2_id INTEGER,
            winner_id INTEGER,
            score TEXT,
            played_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        # XP
        await c.execute('''CREATE TABLE IF NOT EXISTS xp (
            user_id INTEGER,
            guild_id INTEGER,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, guild_id)
        )''')
        # Bans
        await c.execute('''CREATE TABLE IF NOT EXISTS bans (
            user_id INTEGER PRIMARY KEY,
            reason TEXT,
            banned_by INTEGER,
            banned_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        # Tournaments
        await c.execute('''CREATE TABLE IF NOT EXISTS tournaments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            mode TEXT NOT NULL DEFAULT '1v1',
            status TEXT NOT NULL DEFAULT 'draft',
            prize_pool INTEGER DEFAULT 0,
            prize_split TEXT,
            entry_fee TEXT,
            rounds TEXT,
            starts_at TEXT,
            max_slots INTEGER DEFAULT 32,
            rules_url TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        # Registrations
        await c.execute('''CREATE TABLE IF NOT EXISTS tournament_registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id INTEGER NOT NULL,
            discord_id INTEGER NOT NULL,
            discord_username TEXT,
            mode TEXT,
            status TEXT DEFAULT 'pending',
            registered_at TEXT DEFAULT CURRENT_TIMESTAMP
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


# ─────────────────────────────────────────────
# Tournaments
# ─────────────────────────────────────────────
async def create_tournament(data: dict) -> int:
    async with _client() as c:
        result = await c.execute(
            '''INSERT INTO tournaments
               (name, description, mode, status, prize_pool, prize_split,
                entry_fee, rounds, starts_at, max_slots, rules_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            [
                data.get("name", "Untitled"),
                data.get("description", ""),
                data.get("mode", "1v1"),
                data.get("status", "draft"),
                int(data.get("prize_pool", 0) or 0),
                data.get("prize_split", ""),
                data.get("entry_fee", ""),
                data.get("rounds", ""),
                data.get("starts_at", ""),
                int(data.get("max_slots", 32) or 32),
                data.get("rules_url", ""),
            ],
        )
        return result.last_insert_rowid


async def update_tournament(tid: int, data: dict):
    async with _client() as c:
        await c.execute(
            '''UPDATE tournaments SET
                name=?, description=?, mode=?, status=?, prize_pool=?,
                prize_split=?, entry_fee=?, rounds=?, starts_at=?, max_slots=?,
                rules_url=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=?''',
            [
                data.get("name", "Untitled"),
                data.get("description", ""),
                data.get("mode", "1v1"),
                data.get("status", "draft"),
                int(data.get("prize_pool", 0) or 0),
                data.get("prize_split", ""),
                data.get("entry_fee", ""),
                data.get("rounds", ""),
                data.get("starts_at", ""),
                int(data.get("max_slots", 32) or 32),
                data.get("rules_url", ""),
                tid,
            ],
        )


async def delete_tournament(tid: int):
    async with _client() as c:
        await c.execute(
            'DELETE FROM tournament_registrations WHERE tournament_id = ?', [tid]
        )
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
            'SELECT id, name, description, mode, status, prize_pool, prize_split, '
            'entry_fee, rounds, starts_at, max_slots, rules_url, '
            'created_at, updated_at '
            'FROM tournaments WHERE id = ?',
            [tid],
        )
        if not result.rows:
            return None
        r = result.rows[0]
        return {
            "id": r[0],
            "name": r[1],
            "description": r[2] or "",
            "mode": r[3],
            "status": r[4],
            "prize_pool": r[5] or 0,
            "prize_split": r[6] or "",
            "entry_fee": r[7] or "",
            "rounds": r[8] or "",
            "starts_at": r[9] or "",
            "max_slots": r[10] or 32,
            "rules_url": r[11] or "",
            "created_at": r[12],
            "updated_at": r[13],
        }


async def get_all_tournaments():
    async with _client() as c:
        result = await c.execute(
            '''SELECT t.id, t.name, t.description, t.mode, t.status,
                      t.prize_pool, t.prize_split, t.entry_fee, t.rounds,
                      t.starts_at, t.max_slots, t.rules_url,
                      (SELECT COUNT(*) FROM tournament_registrations r
                       WHERE r.tournament_id = t.id
                         AND r.status != 'rejected') AS reg_count
               FROM tournaments t
               ORDER BY
                 CASE t.status
                   WHEN 'live'      THEN 1
                   WHEN 'open'      THEN 2
                   WHEN 'draft'     THEN 3
                   WHEN 'completed' THEN 4
                   ELSE 5
                 END,
                 t.starts_at ASC'''
        )
        return [
            {
                "id": r[0],
                "name": r[1],
                "description": r[2] or "",
                "mode": r[3],
                "status": r[4],
                "prize_pool": r[5] or 0,
                "prize_split": r[6] or "",
                "entry_fee": r[7] or "",
                "rounds": r[8] or "",
                "starts_at": r[9] or "",
                "max_slots": r[10] or 32,
                "rules_url": r[11] or "",
                "registered": r[12] or 0,
            }
            for r in result.rows
        ]


async def register_for_tournament(tid: int, discord_id: int, username: str, mode: str):
    async with _client() as c:
        # Reject duplicates
        existing = await c.execute(
            'SELECT id FROM tournament_registrations '
            'WHERE tournament_id = ? AND discord_id = ?',
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
            {
                "id": r[0],
                "discord_id": r[1],
                "discord_username": r[2] or "",
                "mode": r[3] or "",
                "status": r[4] or "pending",
                "registered_at": r[5],
            }
            for r in result.rows
        ]


async def set_registration_status(rid: int, status: str):
    async with _client() as c:
        await c.execute(
            'UPDATE tournament_registrations SET status = ? WHERE id = ?',
            [status, rid],
        )
