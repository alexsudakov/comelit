"""Embedded Telegram Mini App support for Comelit."""

from .controller import ComelitMiniAppController
from .views import async_register_miniapp_views

__all__ = ["ComelitMiniAppController", "async_register_miniapp_views"]
