"""
Проверка подлинности initData, которую присылает Telegram WebApp.

Без этой проверки любой человек мог бы открыть devtools, вписать
произвольный tg_id в запрос к /api/status или /api/redeem и получить
чужой уровень доступа / активировать код на чужой аккаунт.
Алгоритм — официальный, из документации Telegram:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-web-app
"""

import hashlib
import hmac
import json
import time
from typing import Optional
from urllib.parse import parse_qsl

# initData считаем протухшей через это время (секунды). 24 часа с запасом.
MAX_AUTH_AGE = 24 * 60 * 60


def validate_init_data(init_data: str, bot_token: str) -> Optional[dict]:
    """Возвращает распарсенные данные (включая dict user), либо None если подпись неверна."""
    if not init_data:
        return None

    try:
        pairs = parse_qsl(init_data, strict_parsing=True)
    except ValueError:
        return None

    data = dict(pairs)
    received_hash = data.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        return None

    auth_date = data.get("auth_date")
    if auth_date:
        try:
            if time.time() - int(auth_date) > MAX_AUTH_AGE:
                return None
        except ValueError:
            pass

    user = None
    if "user" in data:
        try:
            user = json.loads(data["user"])
        except (json.JSONDecodeError, TypeError):
            user = None

    return {"user": user, "auth_date": auth_date, "raw": data}


def extract_tg_user(init_data: str, bot_token: str) -> Optional[dict]:
    """Короткий путь: сразу вернуть dict пользователя или None, если подпись не сошлась."""
    result = validate_init_data(init_data, bot_token)
    if not result or not result.get("user"):
        return None
    return result["user"]