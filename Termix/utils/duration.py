import re

# Matches things like: 1d, 24hr, 30m, 45s, 10min, 5sec, 2days, 1w
TIME_REGEX = re.compile(
    r'(\d+)\s*(w|week|weeks|d|day|days|h|hr|hrs|hour|hours|m|min|mins|minute|minutes|s|sec|secs|second|seconds)',
    re.IGNORECASE
)

UNIT_TO_SECONDS = {
    'w': 604800, 'week': 604800, 'weeks': 604800,
    'd': 86400, 'day': 86400, 'days': 86400,
    'h': 3600, 'hr': 3600, 'hrs': 3600, 'hour': 3600, 'hours': 3600,
    'm': 60, 'min': 60, 'mins': 60, 'minute': 60, 'minutes': 60,
    's': 1, 'sec': 1, 'secs': 1, 'second': 1, 'seconds': 1,
}

def parse_duration(text: str) -> int | None:
    """
    Parse a duration string like '1d', '24hr', '1h30m', '2 days 5 hours' into seconds.
    Returns None if invalid.
    """
    text = text.strip().lower().replace(' ', '')
    matches = TIME_REGEX.findall(text)
    if not matches:
        return None

    total = 0
    for value, unit in matches:
        total += int(value) * UNIT_TO_SECONDS[unit.lower()]
    return total if total > 0 else None

def format_duration(seconds: int) -> str:
    """Convert seconds back to a readable string like '1d 2h 30m'."""
    units = [('d', 86400), ('h', 3600), ('m', 60), ('s', 1)]
    parts = []
    for name, size in units:
        if seconds >= size:
            count, seconds = divmod(seconds, size)
            parts.append(f'{count}{name}')
    return ' '.join(parts) if parts else '0s'