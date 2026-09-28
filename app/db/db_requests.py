from sqlalchemy import select, insert, update, delete
from app.db.db_setup import engine, admin_list, user_list, blocked_users, SUPER_ADMINS


async def add_user(tg_id: int, username: str, name: str,
                   university: str = None, faculty: str = None,
                   group_name: str = None, format: str = "Офлайн") -> None:
    """
    Inserts a new user record into the user_list database table.

    Parameters:
    tg_id (int): The unique Telegram identifier of the user.
    username (str): The Telegram username of the user.
    name (str): The full real name of the user (ПІБ).
    university (str, optional): The user's university.
    faculty (str, optional): The specific faculty or department.
    group_name (str, optional): The academic group of the user.
    format (str, optional): Attendance format ("Офлайн" or "Онлайн").

    Returns:
    None
    """
    async with engine.begin() as conn:
        insert_statement = insert(user_list).values(
            telegram_id=tg_id,
            username=username,
            name=name,
            university=university,
            faculty=faculty,
            group_name=group_name,
            format=format,
        )
        await conn.execute(insert_statement)


async def get_user(tg_id: int):
    """
    Retrieves a complete user record from the database using their Telegram ID.

    Parameters:
    tg_id (int): The unique Telegram identifier of the user to search for.

    Returns:
    sqlalchemy.engine.row.Row: A row object containing all user data if found.
    None: If no user with the specified tg_id exists in the database.
    """
    async with engine.begin() as conn:
        select_statement = select(user_list).where(user_list.c.telegram_id == tg_id)
        result = await conn.execute(select_statement)
        return result.fetchone()


async def get_all_users():
    """
    Fetches all registered users from the user_list database table.

    Returns:
    list: A list of sqlalchemy.engine.row.Row objects representing all users.
    """
    async with engine.begin() as conn:
        select_statement = select(user_list)
        result = await conn.execute(select_statement)
        return result.fetchall()


async def get_users_by_identifiers(identifiers: list[str]) -> tuple[list, list[str]]:
    """
    Знаходить користувачів за списком @username або числових Telegram ID.

    Повертає:
    (found_users: list, not_found_identifiers: list[str])
    """
    all_users = await get_all_users()

    by_id = {u.telegram_id: u for u in all_users}
    by_username = {}
    for u in all_users:
        if u.username:
            clean_u = u.username.lstrip("@").lower()
            by_username[clean_u] = u

    found_users = []
    found_ids = set()
    not_found = []

    for raw_id in identifiers:
        token = str(raw_id).strip()
        if not token:
            continue

        matched = None
        if token.isdigit():
            tg_id = int(token)
            matched = by_id.get(tg_id)
        else:
            clean_token = token.lstrip("@").lower()
            matched = by_username.get(clean_token)

        if matched:
            if matched.telegram_id not in found_ids:
                found_users.append(matched)
                found_ids.add(matched.telegram_id)
        else:
            not_found.append(token)

    return found_users, not_found


async def get_non_fiot_users() -> list:
    """
    Повертає всіх зареєстрованих користувачів, чия група не належить до ФІОТ.
    """
    from app.utils.group_validator import is_fiot_group

    all_users = await get_all_users()
    non_fiot = []
    for u in all_users:
        if not is_fiot_group(u.group_name) or (u.faculty and "ФІОТ" not in u.faculty.upper()):
            non_fiot.append(u)
    return non_fiot


async def get_users_by_format(format_name: str) -> list:
    """
    Повертає список користувачів за вказаним форматом участі ('Офлайн' або 'Онлайн').
    """
    async with engine.begin() as conn:
        select_statement = select(user_list).where(user_list.c.format == format_name)
        result = await conn.execute(select_statement)
        return result.fetchall()


async def cancel_users_registration(users_to_cancel: list) -> list[int]:
    """
    Видаляє вказаних користувачів із таблиці user_list (скасування реєстрації).
    НЕ вносить їх до списку blocked_users, тобто вони можуть зареєструватись знову.

    Параметри:
    users_to_cancel: список об'єктів користувачів або список числових telegram_id.

    Повертає список успішно видалених telegram_id.
    """
    from app.utils.google_sheets import delete_user_from_sheet
    import asyncio

    cancelled_ids = []
    async with engine.begin() as conn:
        for u in users_to_cancel:
            uid = u.telegram_id if hasattr(u, "telegram_id") else int(u)
            uname = getattr(u, "username", None)
            del_stmt = delete(user_list).where(user_list.c.telegram_id == uid)
            await conn.execute(del_stmt)
            cancelled_ids.append(uid)
            asyncio.create_task(delete_user_from_sheet(uid, username=uname))

    return cancelled_ids


async def block_user(tg_id: int, username: str = None, name: str = None,
                     attempted_group: str = None, reason: str = "Спроба реєстрації з іншого факультету") -> None:
    """
    Додає користувача до списку заблокованих (якщо ще не додано).
    Також видаляє його з user_list, якщо він був зареєстрований, і видаляє рядок з Google Таблиці.
    """
    from app.utils.google_sheets import delete_user_from_sheet
    import asyncio

    async with engine.begin() as conn:
        check_stmt = select(blocked_users).where(blocked_users.c.telegram_id == tg_id)
        exists = (await conn.execute(check_stmt)).fetchone()
        if not exists:
            insert_stmt = insert(blocked_users).values(
                telegram_id=tg_id,
                username=username,
                name=name or "Не вказано",
                attempted_group=attempted_group,
                reason=reason
            )
            await conn.execute(insert_stmt)

        del_user_stmt = delete(user_list).where(user_list.c.telegram_id == tg_id)
        await conn.execute(del_user_stmt)
        asyncio.create_task(delete_user_from_sheet(tg_id, username=username))


async def is_user_blocked(tg_id: int) -> bool:
    """
    Перевіряє, чи заблокований користувач для участі в заході.
    """
    async with engine.begin() as conn:
        stmt = select(blocked_users.c.telegram_id).where(blocked_users.c.telegram_id == tg_id)
        result = await conn.execute(stmt)
        return result.fetchone() is not None


async def get_blocked_users() -> list:
    """
    Повертає список усіх заблокованих користувачів.
    """
    async with engine.begin() as conn:
        stmt = select(blocked_users)
        result = await conn.execute(stmt)
        return result.fetchall()


async def unblock_user(identifier: str | int) -> tuple[bool, str, int | None]:
    """
    Розблоковує користувача за Telegram ID або @username.

    Повертає:
    (success: bool, message: str, unblocked_tg_id: int | None)
    """
    token = str(identifier).strip()
    if not token:
        return False, "Порожній ідентифікатор.", None

    async with engine.begin() as conn:
        matched = None
        if token.isdigit():
            tg_id = int(token)
            stmt = select(blocked_users).where(blocked_users.c.telegram_id == tg_id)
            matched = (await conn.execute(stmt)).fetchone()
        else:
            clean_username = token.lstrip("@").lower()
            stmt = select(blocked_users)
            all_blocked = (await conn.execute(stmt)).fetchall()
            for b in all_blocked:
                if b.username and b.username.lstrip("@").lower() == clean_username:
                    matched = b
                    break

        if not matched:
            return False, f"Користувача <code>{token}</code> не знайдено серед заблокованих.", None

        del_stmt = delete(blocked_users).where(blocked_users.c.telegram_id == matched.telegram_id)
        await conn.execute(del_stmt)

        user_desc = f"{matched.name} (@{matched.username})" if matched.username else f"{matched.name} (ID: {matched.telegram_id})"
        return True, f"Користувача <b>{user_desc}</b> успішно розблоковано! ✅", matched.telegram_id


async def update_user_field(tg_id: int, field_name: str, new_value) -> None:
    """
    Updates a specific field in the user's database record.

    Parameters:
    tg_id (int): The unique Telegram identifier of the user.
    field_name (str): The exact name of the database column to change.
    new_value: The new value to insert into the specified column.

    Returns: None
    """
    allowed_fields = ["username", "name", "university", "faculty", "group_name", "format"]

    if field_name not in allowed_fields:
        raise ValueError(f"Field '{field_name}' is not allowed to be updated.")

    async with engine.begin() as conn:
        update_data = {field_name: new_value}
        update_statement = (
            update(user_list)
            .where(user_list.c.telegram_id == tg_id)
            .values(**update_data)
        )
        await conn.execute(update_statement)


_admin_cache: set[int] = set()
_admins_loaded: bool = False


async def load_admins_cache() -> set[int]:
    """
    Завантажує ID усіх активних адмінів у пам'ять для O(1) перевірок.
    """
    global _admin_cache, _admins_loaded
    async with engine.begin() as conn:
        select_statement = select(admin_list.c.telegram_id).where(admin_list.c.is_active == True)
        result = await conn.execute(select_statement)
        db_admins = {row[0] for row in result.fetchall()}
        _admin_cache = db_admins | set(SUPER_ADMINS)
        _admins_loaded = True
        return _admin_cache


async def is_admin(user_id: int) -> bool:
    """
    Швидка перевірка ролі адміністратора без звернення до БД (0.001 мс).
    """
    if user_id in SUPER_ADMINS:
        return True
    if not _admins_loaded:
        await load_admins_cache()
    return user_id in _admin_cache
