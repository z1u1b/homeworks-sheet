from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from .. import config

# /whoami должен оставаться доступным всем — иначе новый человек не сможет
# узнать свой chat_id, чтобы попросить администратора добавить его в
# ALLOWED_CHAT_IDS. Остальные команды (включая /start) для чужих chat_id
# блокируются полностью.
_ALWAYS_ALLOWED_COMMANDS = {"/whoami"}


class AllowlistMiddleware(BaseMiddleware):
    """Блокирует все команды для chat_id вне ALLOWED_CHAT_IDS.

    Если ALLOWED_CHAT_IDS пуст (не задан в .env) — allowlist выключен,
    пропускает всех, чтобы не ломать локальную разработку без .env.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not config.ALLOWED_CHAT_IDS:
            return await handler(event, data)

        # У Message есть .chat, а у CallbackQuery — нет: чат лежит в
        # event.message.chat (иначе все inline-кнопки молча игнорировались бы).
        if isinstance(event, CallbackQuery):
            chat = event.message.chat if event.message else None
            chat_id = chat.id if chat else event.from_user.id
        else:
            chat = getattr(event, "chat", None)
            chat_id = chat.id if chat else None

        if chat_id in config.ALLOWED_CHAT_IDS:
            return await handler(event, data)

        if isinstance(event, Message):
            first_word = (event.text or "").split()[0].split("@")[0] if event.text else ""
            if first_word in _ALWAYS_ALLOWED_COMMANDS:
                return await handler(event, data)
            await event.answer(
                "Доступ к боту ограничен. Узнайте свой chat_id командой /whoami "
                "и попросите администратора добавить вас."
            )
            return None

        # Callback-запросы (инлайн-клавиатуры) от чужих chat_id просто игнорируем.
        return None
