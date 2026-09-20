# config.py
# ─── Channel IDs ───
COUNTING_CHANNEL_ID = 1550477976536088596            # ← put your counting channel ID here
ANNOUNCE_CHANNEL_ID = 1550190762463993926            # ← auto-announce channel (optional)
TICKET_CATEGORY_ID = 1550173868033970197             # ← category where tickets get created (optional, 0 = auto)

# ─── Role IDs ───
STAFF_ROLE_ID = 1550151638877081731                  # ← role ID that can manage tickets + unregister
VERIFIED_ROLE_ID = 1550152298246705272               # ← role given to verified players (optional)

# ─── Ticket Settings ───
TICKET_TYPES = {
    "support": "🛠️ General Support",
    "report": "🚨 Report a Player",
    "appeal": "⚖️ Ban Appeal",
    "other": "❓ Other",
}