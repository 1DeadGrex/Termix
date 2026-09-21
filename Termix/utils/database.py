# utils/database.py
import os
import aiosqlite

# ── Path resolution ──
_THIS_FILE = os.path.abspath(__file__)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_FILE))
DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "tournament.db")
print(f"📁 DB location: {DB_PATH}")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            discord_name TEXT,
            steam_id TEXT,
            verified INTEGER DEFAULT 0,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player1_id INTEGER,
            player2_id INTEGER,
            winner_id INTEGER,
            score TEXT,
            played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS xp (
            user_id INTEGER,
            guild_id INTEGER,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, guild_id)
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS bans (
            user_id INTEGER PRIMARY KEY,
            reason TEXT,
            banned_by INTEGER,
            banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        await db.commit()


# ── Players ──
async def add_player(user_id, discord_name, steam_id, verified=False):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            '''INSERT INTO players (user_id, discord_name, steam_id, verified)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   discord_name = excluded.discord_name,
                   steam_id = excluded.steam_id,
                   verified = excluded.verified''',
            (user_id, discord_name, steam_id, int(bool(verified)))
        )
        await db.commit()


async def get_player(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            'SELECT user_id, discord_name, steam_id, verified, registered_at '
            'FROM players WHERE user_id = ?', (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_all_players():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            'SELECT user_id, discord_name, steam_id, verified FROM players'
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def delete_player(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM players WHERE user_id = ?', (user_id,))
        await db.commit()


# ── Matches ──
async def add_match(winner_id, loser_id, score):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT INTO matches (player1_id, player2_id, winner_id, score) '
            'VALUES (?, ?, ?, ?)',
            (winner_id, loser_id, winner_id, score)
        )
        await db.commit()


async def get_recent_matches(limit=50):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            'SELECT id, player1_id, player2_id, winner_id, score, played_at '
            'FROM matches ORDER BY played_at DESC LIMIT ?',
            (limit,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_match_history(user_id, limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            '''SELECT id, player1_id, player2_id, winner_id, score, played_at
               FROM matches
               WHERE player1_id = ? OR player2_id = ?
               ORDER BY played_at DESC LIMIT ?''',
            (user_id, user_id, limit)
        ) as cur:
            return await cur.fetchall()


# ── XP / Leaderboard ──
async def get_leaderboard(guild_id, limit=20):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            'SELECT user_id, xp, level FROM xp WHERE guild_id = ? '
            'ORDER BY xp DESC LIMIT ?',
            (guild_id, limit)
        ) as cur:
            rows = await cur.fetchall()
    return [
        {"rank": i, "user_id": r["user_id"], "xp": r["xp"], "level": r["level"]}
        for i, r in enumerate(rows, 1)
    ]


async def get_global_leaderboard(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            'SELECT user_id, SUM(xp) AS total_xp, MAX(level) AS level '
            'FROM xp GROUP BY user_id ORDER BY total_xp DESC LIMIT ?',
            (limit,)
        ) as cur:
            rows = await cur.fetchall()
    return [
        {"rank": i, "user_id": r["user_id"], "xp": r["total_xp"] or 0,
         "level": r["level"] or 1}
        for i, r in enumerate(rows, 1)
    ]
