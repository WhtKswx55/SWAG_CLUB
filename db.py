import asyncio
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "swagclub.db"

SUB_PERIOD_DAYS = 30
GRACE_DAYS = 3

LEVELS = {
    0: {"name": "ZERO ACCESS", "min_months": None, "max_months": None, "early_days": 0},
    1: {"name": "Member", "min_months": 0, "max_months": 2, "early_days": 7},
    2: {"name": "Drop Hunter", "min_months": 2, "max_months": 6, "early_days": 14},
    3: {"name": "Insider", "min_months": 6, "max_months": 12, "early_days": 14},
    4: {"name": "Legend / Architect", "min_months": 12, "max_months": None, "early_days": 14},
}

LEVEL_ORDER = [1, 2, 3, 4]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _parse(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_sync() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect()) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                tg_id             INTEGER PRIMARY KEY,
                username          TEXT,
                first_name        TEXT,
                subscribed_since  TEXT,
                active_until      TEXT,
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id                 INTEGER NOT NULL,
                amount                INTEGER,
                currency              TEXT,
                months                INTEGER,
                telegram_charge_id    TEXT,
                paid_at               TEXT NOT NULL
            )
            """
        )


async def init_db() -> None:
    await asyncio.to_thread(_init_sync)


def compute_level(
    subscribed_since: Optional[datetime],
    active_until: Optional[datetime],
    now: Optional[datetime] = None,
) -> dict:
    now = now or _now()

    if not active_until or not subscribed_since or now > active_until:
        return {
            "level": 0,
            "level_name": LEVELS[0]["name"],
            "has_access": False,
            "early_days": 0,
            "tenure_months": 0,
            "active_until": _iso(active_until),
            "days_left": 0,
            "next_level": None,
            "months_to_next_level": None,
        }

    tenure_days = (now - subscribed_since).days
    tenure_months = tenure_days // SUB_PERIOD_DAYS

    level = 1
    for lvl in LEVEL_ORDER:
        meta = LEVELS[lvl]
        if tenure_months >= meta["min_months"] and (
            meta["max_months"] is None or tenure_months < meta["max_months"]
        ):
            level = lvl
            break

    next_level = None
    months_to_next_level = None
    if level < 4:
        next_level = level + 1
        next_meta = LEVELS[next_level]
        months_to_next_level = max(0, next_meta["min_months"] - tenure_months)

    return {
        "level": level,
        "level_name": LEVELS[level]["name"],
        "has_access": True,
        "early_days": LEVELS[level]["early_days"],
        "tenure_months": tenure_months,
        "active_until": _iso(active_until),
        "days_left": max(0, (active_until - now).days),
        "next_level": (LEVELS[next_level]["name"] if next_level else None),
        "months_to_next_level": months_to_next_level,
    }


def _get_or_create_user_sync(
    tg_id: int, username: Optional[str], first_name: Optional[str]
) -> sqlite3.Row:
    with closing(_connect()) as conn, conn:
        row = conn.execute(
            "SELECT * FROM users WHERE tg_id = ?", (tg_id,)
        ).fetchone()
        now = _iso(_now())
        if row is None:
            conn.execute(
                "INSERT INTO users (tg_id, username, first_name, subscribed_since, active_until, created_at, updated_at) "
                "VALUES (?, ?, ?, NULL, NULL, ?, ?)",
                (tg_id, username, first_name, now, now),
            )
            row = conn.execute(
                "SELECT * FROM users WHERE tg_id = ?", (tg_id,)
            ).fetchone()
        else:
            conn.execute(
                "UPDATE users SET username = ?, first_name = ?, updated_at = ? WHERE tg_id = ?",
                (username, first_name, now, tg_id),
            )
        return row


async def get_or_create_user(
    tg_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
) -> dict:
    row = await asyncio.to_thread(
        _get_or_create_user_sync, tg_id, username, first_name
    )
    return dict(row)


async def get_user_status(
    tg_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
) -> dict:
    user = await get_or_create_user(tg_id, username, first_name)
    subscribed_since = _parse(user["subscribed_since"])
    active_until = _parse(user["active_until"])
    return compute_level(subscribed_since, active_until)


async def get_status(
    tg_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
) -> dict:
    return await get_user_status(tg_id, username, first_name)


def _extend_subscription_sync(
    tg_id: int,
    months: int,
    amount: Optional[int],
    currency: Optional[str],
    charge_id: Optional[str],
    username: Optional[str],
    first_name: Optional[str],
) -> dict:
    now = _now()
    with closing(_connect()) as conn, conn:
        row = conn.execute(
            "SELECT * FROM users WHERE tg_id = ?", (tg_id,)
        ).fetchone()
        now_iso = _iso(now)

        if row is None:
            conn.execute(
                "INSERT INTO users (tg_id, username, first_name, subscribed_since, active_until, created_at, updated_at) "
                "VALUES (?, ?, ?, NULL, NULL, ?, ?)",
                (tg_id, username, first_name, now_iso, now_iso),
            )
            row = conn.execute(
                "SELECT * FROM users WHERE tg_id = ?", (tg_id,)
            ).fetchone()

        prev_subscribed_since = _parse(row["subscribed_since"])
        prev_active_until = _parse(row["active_until"])

        keeps_streak = (
            prev_subscribed_since is not None
            and prev_active_until is not None
            and (now - prev_active_until).days <= GRACE_DAYS
        )

        if keeps_streak:
            subscribed_since = prev_subscribed_since
            extend_from = max(prev_active_until, now)
        else:
            subscribed_since = now
            extend_from = now

        new_active_until = extend_from + timedelta(
            days=SUB_PERIOD_DAYS * months
        )

        conn.execute(
            "UPDATE users SET subscribed_since = ?, active_until = ?, username = ?, first_name = ?, updated_at = ? "
            "WHERE tg_id = ?",
            (
                _iso(subscribed_since),
                _iso(new_active_until),
                username,
                first_name,
                now_iso,
                tg_id,
            ),
        )

        conn.execute(
            "INSERT INTO payments (tg_id, amount, currency, months, telegram_charge_id, paid_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tg_id, amount, currency, months, charge_id, now_iso),
        )

        status = compute_level(subscribed_since, new_active_until, now)
        status["streak_kept"] = keeps_streak
        return status


async def extend_subscription(
    tg_id: int,
    months: int = 1,
    amount: Optional[int] = None,
    currency: Optional[str] = None,
    charge_id: Optional[str] = None,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
) -> dict:
    return await asyncio.to_thread(
        _extend_subscription_sync,
        tg_id,
        months,
        amount,
        currency,
        charge_id,
        username,
        first_name,
    )