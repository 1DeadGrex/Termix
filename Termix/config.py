# config.py
# ─── Channel IDs ───
GUILD_ID = 1550146103628931264                    # your main server ID (optional but recommended)
COUNTING_CHANNEL_ID = 1550477976536088596            # ← put your counting channel ID here
ANNOUNCE_CHANNEL_ID = 1550190762463993926            # ← auto-announce channel (optional)
TICKET_CATEGORY_ID = 1550173868033970197             # ← category where tickets get created (optional, 0 = auto)
SUPPORT_CHANNEL_ID = 1550173868033970197   # used by /ticket to redirect users
LEADERBOARD_CHANNEL_ID = 1552679666027069465   # auto-leaderboard channel

# ─── Voice channel auto-create ───
JOIN_TO_CREATE_VC_ID   = 1550146105382010993   # users join this VC → private VC is created
TEMP_VC_CATEGORY_ID    = 1550149884466831390                    # optional: category to place temp VCs in (0 = same as source)

# category IDs
MATCH_MEMBER_CATEGORY_ID = 1550174233521295460    # optional category only match-members can see
# ─── Role IDs ───
STAFF_ROLE_ID = 1550151638877081731                  # ← role ID that can manage tickets + unregister
VERIFIED_ROLE_ID = 1550152298246705272               # ← role given to verified players (optional)
MATCH_MEMBER_ROLE_ID = 1550152298246705272   # role granted on approval

# ─── Ticket Settings ───
TICKET_TYPES = {
    "support": "🛠️ General Support",
    "report": "🚨 Report a Player",
    "appeal": "⚖️ Ban Appeal",
    "other": "❓ Other",
}
