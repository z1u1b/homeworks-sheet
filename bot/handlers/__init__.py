from aiogram import Router

from .common import fallback_router, router as common_router
from .homework import router as homework_router
from .homework_add import router as homework_add_router
from .settings import router as settings_router
from .sheet_binding import router as sheet_binding_router
from .sheet_creation import router as sheet_creation_router
from .subject_manage import router as subject_manage_router


def get_root_router() -> Router:
    root = Router()
    # диалог добавления ДЗ — первым: в его состояниях он должен перехватывать
    # сообщения раньше кнопок меню и остальных хендлеров
    root.include_router(homework_add_router)
    root.include_router(common_router)
    root.include_router(homework_router)
    root.include_router(settings_router)
    root.include_router(sheet_binding_router)
    root.include_router(sheet_creation_router)
    root.include_router(subject_manage_router)
    # fallback строго последним — ловит всё, что не обработали остальные
    root.include_router(fallback_router)
    return root
