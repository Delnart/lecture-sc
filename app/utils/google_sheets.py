import gspread
import asyncio
import os
import json
from dotenv import load_dotenv

load_dotenv()


from datetime import datetime

_cached_sheet = None

def get_sheet():
    """
    Підключається до Google Sheets.
    """
    global _cached_sheet
    if _cached_sheet is not None:
        return _cached_sheet

    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        gc = gspread.service_account_from_dict(json.loads(creds_json))
    else:
        gc = gspread.service_account(filename="app/data/credentials.json")

    sheet_url_or_id = os.getenv("SHEET_URL", "")
    
    if not sheet_url_or_id:
        _cached_sheet = gc.open(os.getenv("LOG_SHEET_NAME"))
        return _cached_sheet
        
    try:
        if not sheet_url_or_id.startswith("http"):
            _cached_sheet = gc.open_by_key(sheet_url_or_id)
        else:
            _cached_sheet = gc.open_by_url(sheet_url_or_id)
    except gspread.exceptions.SpreadsheetNotFound:
        _cached_sheet = gc.open(os.getenv("LOG_SHEET_NAME"))

    return _cached_sheet


def _append_row_sync(row_data: list):
    sh = get_sheet()
    # Автоматично беремо перший аркуш у файлі
    ws = sh.sheet1
    # Використовуємо table_range="A1" та insert_data_option="INSERT_ROWS", 
    # щоб Google Sheets гарантовано створив новий рядок, а не перезаписував існуючий порожній
    ws.append_row(
        row_data, 
        table_range="A1", 
        value_input_option="USER_ENTERED", 
        insert_data_option="INSERT_ROWS"
    )


async def add_user_to_sheet(tg_id: int, username: str, name: str,
                            university: str = None, faculty: str = None,
                            group_name: str = None, format: str = "Офлайн"):
    try:
        from zoneinfo import ZoneInfo
        kyiv_tz = ZoneInfo("Europe/Kyiv")
        timestamp = datetime.now(kyiv_tz).strftime("%d.%m.%Y %H:%M:%S")
        
        # Формат колонок:
        # A: Позначка часу
        # B: ПІБ
        # C: Юзернейм
        # D: Університет
        # E: Факультет
        # F: Група
        # G: Формат участі (Офлайн / Онлайн)
        # H: Правила
        # I: tg_id (потрібен боту для оновлення профілю)
        row = [
            timestamp, 
            name, 
            username, 
            university, 
            faculty, 
            group_name, 
            format,
            "Так", 
            str(tg_id)
        ]
        row = [item if item is not None else "" for item in row]

        # Автоматично записуємо у перший аркуш таблиці
        await asyncio.to_thread(_append_row_sync, row)
        print(f"✅ Користувача {name} успішно додано в Sheets!")
    except Exception as e:
        print(f"❌ ПОМИЛКА додавання користувача в Sheets: {e}")


def _update_user_sync(tg_id: str, field: str, new_value):
    sh = get_sheet()
    ws = sh.sheet1
    try:
        # Шукаємо tg_id у 9-й колонці (I), або у 8-й (H) для зворотної сумісності
        cell = None
        try:
            cell = ws.find(str(tg_id), in_column=9)
        except Exception:
            pass
        if not cell:
            try:
                cell = ws.find(str(tg_id), in_column=8)
            except Exception:
                pass

        if cell:
            col_map = {
                "name":       "B",
                "username":   "C",
                "university": "D",
                "faculty":    "E",
                "group_name": "F",
                "format":     "G",
            }
            if field in col_map:
                cell_label = f"{col_map[field]}{cell.row}"
                write_value = new_value if new_value is not None else ""
                ws.update_acell(cell_label, write_value)
                print(f"✅ Sheets: Оновлено ID {tg_id}, поле {field} -> {write_value}")
        else:
            print(f"⚠️ Sheets: Користувача {tg_id} не знайдено для оновлення.")
    except Exception as e:
        print(f"❌ Sheets: Помилка оновлення користувача: {e}")


async def update_user_in_sheet(tg_id: int, field: str, new_value):
    await asyncio.to_thread(_update_user_sync, str(tg_id), field, new_value)


def _delete_user_sync(tg_id: str, username: str = None):
    sh = get_sheet()
    ws = sh.sheet1
    try:
        cell = None
        try:
            cell = ws.find(str(tg_id), in_column=9)
        except Exception:
            pass
        if not cell:
            try:
                cell = ws.find(str(tg_id), in_column=8)
            except Exception:
                pass
        if not cell and username:
            clean_username = username.lstrip("@").strip()
            if clean_username:
                cell = ws.find(clean_username, in_column=3)
        if cell:
            ws.delete_rows(cell.row)
            print(f"✅ Sheets: Видалено рядок для ID {tg_id}")
        else:
            print(f"⚠️ Sheets: Користувача {tg_id} не знайдено для видалення.")
    except Exception as e:
        print(f"❌ Sheets: Помилка видалення рядка для ID {tg_id}: {e}")


async def delete_user_from_sheet(tg_id: int, username: str = None):
    await asyncio.to_thread(_delete_user_sync, str(tg_id), username)
