import aiosqlite

DB_PATH = "data/tournament.db"

async def init_db():
    """Create all tables if they don't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            discord_name TEXT,
            steam_id TEXT UNIQUE,
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

# ---------- Player helpers ----------
async def add_player(user_id: int, discord_name: str, steam_id: str, verified: bool = False):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            '''INSERT INTO players (user_id, discord_name, steam_id, verified)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   steam_id = excluded.steam_id,
                   verified = excluded.verified''',
            (user_id, discord_name, steam_id, int(verified))
        )
        await db.commit()

async def get_player(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT * FROM players WHERE user_id = ?', (user_id,)) as cur:
            return await cur.fetchone()

async def get_all_players():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT user_id, discord_name, steam_id, verified FROM players') as cur:
            return await cur.fetchall()

# ---------- Match helpers ----------
async def add_match(winner_id: int, loser_id: int, score: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT INTO matches (player1_id, player2_id, winner_id, score) VALUES (?, ?, ?, ?)',
            (winner_id, loser_id, winner_id, score)
        )
        await db.commit()

async def get_recent_matches(limit: int = 50):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT id, player1_id, player2_id, winner_id, score, played_at '
            'FROM matches ORDER BY played_at DESC LIMIT ?',
            (limit,)
        ) as cur:
            return await cur.fetchall()

# ---------- XP helpers ----------
async def get_leaderboard(guild_id: int, limit: int = 20):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT user_id, xp, level FROM xp WHERE guild_id = ? ORDER BY xp DESC LIMIT ?',
            (guild_id, limit)
        ) as cur:
            return await cur.fetchall()
# ─── DELETE PLAYER ───
async def delete_player(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM players WHERE user_id = ?', (user_id,))
        await db.commit()


# ─── CHECK IF PLAYER EXISTS ───
async def player_exists(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT 1 FROM players WHERE user_id = ?', (user_id,)) as cur:
            return await cur.fetchone() is not None


# ─── ADD MATCH (safer version) ───
async def add_match(winner_id: int, loser_id: int, score: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT INTO matches (player1_id, player2_id, winner_id, score) '
            'VALUES (?, ?, ?, ?)',
            (winner_id, loser_id, winner_id, score)
        )
        await db.commit()


# ─── GET MATCH HISTORY FOR A USER ───
async def get_match_history(user_id: int, limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            '''SELECT id, player1_id, player2_id, winner_id, score, played_at
               FROM matches
               WHERE player1_id = ? OR player2_id = ?
               ORDER BY played_at DESC LIMIT ?''',
            (user_id, user_id, limit)
        ) as cur:
            return await cur.fetchall()