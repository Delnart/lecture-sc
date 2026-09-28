import os
from dotenv import load_dotenv
load_dotenv()
SHEET_URL = os.getenv("SHEET_URL", "")
# Захист від того, що користувач ввів лише ID замість повного посилання
if SHEET_URL and not SHEET_URL.startswith("http"):
    SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_URL}"
if not SHEET_URL:
    SHEET_URL = "https://docs.google.com/spreadsheets/"

from app.data.bot_state import global_state
from aiogram.utils.keyboard import InlineKeyboardBuilder


def create_main_keyboard(is_existing_user=None) -> InlineKeyboardBuilder:
    """
    Creates the main keyboard for regular users.
    :param is_existing_user: user DB row (or None if not registered)
    :return: InlineKeyboardBuilder
    """
    builder = InlineKeyboardBuilder()
    if not is_existing_user:
        builder.button(text="📝 Зареєструватись", callback_data="registration")
    else:
        builder.button(text="🪪 Мій профіль", callback_data="profile")
    builder.button(text="❓ Часті питання", callback_data="handle_questions")
    builder.adjust(1)
    return builder


def create_main_admin_keyboard(blocked_count: int = 0, non_fiot_count: int = 0) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Зареєструватись", callback_data="registration")
    builder.button(text="🪪 Профіль", callback_data="profile")
    builder.button(text="❓ Часті питання", callback_data="handle_questions")
    builder.button(text="📊 Google таблиця", url=SHEET_URL)

    status = "✅ ВІДКРИТА" if global_state["registration_open"] else "❌ ЗАКРИТА"
    if status == "✅ ВІДКРИТА":
        reg_btn_text = "🔐 Закрити реєстрацію"
    else:
        reg_btn_text = "🔓 Відкрити реєстрацію"

    builder.button(text=reg_btn_text, callback_data="admin_stop_registration")

    non_fiot_btn_text = f"👥 Не з ФІОТ ({non_fiot_count})" if non_fiot_count > 0 else "👥 Не з ФІОТ"
    builder.button(text=non_fiot_btn_text, callback_data="admin_view_non_fiot")

    builder.button(text="📨 Написати учасникам", callback_data="admin_write_participants")
    builder.button(text="❌ Скасувати реєстрацію", callback_data="admin_cancel_reg_menu")

    blocked_btn_text = f"🚫 Заблоковані ({blocked_count})" if blocked_count > 0 else "🚫 Заблоковані"
    builder.button(text=blocked_btn_text, callback_data="admin_view_blocked")
    builder.adjust(1)
    return builder
