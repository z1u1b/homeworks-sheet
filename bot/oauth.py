"""
OAuth 2.0 от имени пользователя (не сервис-аккаунт), чтобы бот мог создать
Google-таблицу прямо в Google Drive пользователя — тогда не нужен отдельный
шаг "поделиться на почту", таблица и так его.

Настраивается один раз в Google Cloud Console (OAuth consent screen +
Web application client с redirect_uri = <OAUTH_PUBLIC_BASE_URL>/oauth/callback)
и в .env: GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET,
OAUTH_PUBLIC_BASE_URL, OAUTH_CALLBACK_PORT.

Если эти переменные не заданы — /create_sheet просто недоступен, остальной
бот работает как раньше на сервис-аккаунте (см. bot/sheets.py).
"""

import hashlib
import hmac
import logging
import time
from typing import Dict, Optional, Tuple

import gspread
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import Flow

from . import config, db

logger = logging.getLogger(__name__)

# drive.file — доступ только к файлам, созданным/открытым этим приложением
# (не ко всему Drive пользователя); spreadsheets — чтобы Sheets API мог
# создавать и заполнять сам файл.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

_STATE_TTL_SECONDS = 15 * 60  # ссылка авторизации живёт 15 минут

# google-auth-oauthlib>=1.0 включает PKCE по умолчанию (autogenerate_code_verifier=True):
# build_auth_url() создаёт Flow, тот сам генерирует code_verifier и кладёт code_challenge
# в auth-ссылку, но сам Flow тут же выбрасывается. exchange_code() создаёт новый Flow без
# этого verifier'а — и Google отвечает "Missing code verifier". Поэтому verifier нужно
# сохранить где-то между двумя вызовами; бот и aiohttp-сервер работают в одном процессе
# и одном event loop, так что достаточно in-memory словаря с той же TTL, без изменений в БД.
_pkce_verifiers: Dict[str, Tuple[str, int]] = {}  # state -> (code_verifier, created_at)


def _store_code_verifier(state: str, code_verifier: str) -> None:
    now = int(time.time())
    # заодно подчищаем протухшие записи, чтобы словарь не рос бесконечно
    expired = [s for s, (_, ts) in _pkce_verifiers.items() if now - ts > _STATE_TTL_SECONDS]
    for s in expired:
        _pkce_verifiers.pop(s, None)
    _pkce_verifiers[state] = (code_verifier, now)


def _pop_code_verifier(state: str) -> Optional[str]:
    entry = _pkce_verifiers.pop(state, None)
    if entry is None:
        return None
    code_verifier, ts = entry
    if int(time.time()) - ts > _STATE_TTL_SECONDS:
        return None
    return code_verifier



def _redirect_uri() -> str:
    return f"{config.OAUTH_PUBLIC_BASE_URL}/oauth/callback"


def _client_config() -> dict:
    return {
        "web": {
            "client_id": config.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": config.GOOGLE_OAUTH_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [_redirect_uri()],
        }
    }


def _sign_state(chat_id: int, ts: int) -> str:
    payload = f"{chat_id}:{ts}".encode()
    signature = hmac.new(config.BOT_TOKEN.encode(), payload, hashlib.sha256).hexdigest()
    return f"{chat_id}:{ts}:{signature}"


def _verify_state(state: str) -> Optional[int]:
    try:
        chat_id_str, ts_str, signature = state.split(":", 2)
        chat_id, ts = int(chat_id_str), int(ts_str)
    except (ValueError, AttributeError):
        return None
    expected_signature = _sign_state(chat_id, ts).rsplit(":", 1)[1]
    if not hmac.compare_digest(expected_signature, signature):
        return None
    if time.time() - ts > _STATE_TTL_SECONDS:
        return None
    return chat_id


def build_auth_url(chat_id: int) -> str:
    """Ссылка для похода пользователя на Google-экран согласия."""
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=_redirect_uri())
    state = _sign_state(chat_id, int(time.time()))
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",  # без этого Google не вернёт refresh_token повторно авторизовавшемуся
        state=state,
    )
    # PKCE: Flow сам сгенерировал code_verifier (autogenerate_code_verifier=True по
    # умолчанию) — сохраняем его, иначе exchange_code() не сможет обменять code на токен.
    _store_code_verifier(state, flow.code_verifier)
    return auth_url


def exchange_code(code: str, state: str) -> Tuple[int, Optional[str]]:
    """Обменивает code (из /oauth/callback) на токены и сохраняет
    refresh_token в БД. Возвращает (chat_id, email). Бросает ValueError,
    если state не прошёл проверку или Google не выдал refresh_token."""
    chat_id = _verify_state(state)
    if chat_id is None:
        raise ValueError("ссылка авторизации устарела или повреждена, запросите /create_sheet заново")

    code_verifier = _pop_code_verifier(state)
    if code_verifier is None:
        # Процесс бота перезапускался между /create_sheet и переходом по ссылке,
        # либо ссылкой уже воспользовались — code_verifier не пережил рестарт (он
        # только в памяти, см. _pkce_verifiers выше). Без него Google не примет обмен.
        raise ValueError(
            "сессия авторизации не пережила перезапуск бота или уже была использована — "
            "запросите /create_sheet заново"
        )
    flow = Flow.from_client_config(
        _client_config(), scopes=SCOPES, redirect_uri=_redirect_uri(), code_verifier=code_verifier
    )
    flow.fetch_token(code=code)
    creds = flow.credentials

    if not creds.refresh_token:
        raise ValueError(
            "Google не вернул refresh_token. Обычно это значит, что вы уже давали "
            "доступ этому приложению ранее — попробуйте отозвать доступ в "
            "https://myaccount.google.com/permissions и авторизоваться снова."
        )

    db.set_google_auth(chat_id, creds.refresh_token, None)
    return chat_id, None


def get_client_for_user(chat_id: int) -> gspread.Client:
    """gspread-клиент от имени пользователя (не сервис-аккаунта) по
    сохранённому refresh_token. Бросает LookupError, если пользователь
    ещё не авторизовался."""
    refresh_token = db.get_google_refresh_token(chat_id)
    if not refresh_token:
        raise LookupError("пользователь ещё не авторизовался через Google")

    creds = UserCredentials(
        token=None,
        refresh_token=refresh_token,
        client_id=config.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=config.GOOGLE_OAUTH_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    creds.refresh(GoogleAuthRequest())
    return gspread.authorize(creds)
