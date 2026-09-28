from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import MetaData, Table, Column, BigInteger, String, Boolean
from sqlalchemy import select, insert


import os
from dotenv import load_dotenv

load_dotenv()
BD_ENGINE = os.getenv("BD_ENGINE")
if not BD_ENGINE:
    # Захист: якщо забули додати змінну в Render, падаємо з чіткою помилкою
    raise ValueError("❌ ПОМИЛКА: Не встановлена змінна оточення BD_ENGINE (база даних)!")

# Якщо користувач скопіював стандартний URL з Neon (postgresql://...), 
# автоматично замінюємо його на асинхронний драйвер (postgresql+asyncpg://...)
if BD_ENGINE.startswith("postgresql://"):
    BD_ENGINE = BD_ENGINE.replace("postgresql://", "postgresql+asyncpg://", 1)

# Асинхронний драйвер asyncpg не розуміє параметр sslmode=require, 
# йому потрібен параметр ssl=require. Тому автозамінюємо.
BD_ENGINE = BD_ENGINE.replace("sslmode=", "ssl=")

# Деякі хмарні БД (як Neon чи Supabase) можуть додавати channel_binding у рядок,
# який не підтримується asyncpg. Вирізаємо його:
import re
BD_ENGINE = re.sub(r'([?&])channel_binding=[^&]+(?:&|$)', r'\1', BD_ENGINE).rstrip('?&')

super_admins_env = os.getenv("SUPER_ADMINS", "")
SUPER_ADMINS = [int(x.strip()) for x in super_admins_env.split(",") if x.strip()]
# Використовуємо стандартний пул з pool_pre_ping=True.
# Це дозволяє зберігати з'єднання відкритими для швидкості (немає затримок на підключення),
# але перед кожним запитом SQLAlchemy перевіряє, чи живе з'єднання.
# Якщо Neon призупинив роботу і розірвав з'єднання, воно буде автоматично перепідключено.
engine = create_async_engine(
    BD_ENGINE,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=15,
    max_overflow=25,
    pool_timeout=10,
)
meta = MetaData()

admin_list = Table(
    "admin_list",
    meta,
    Column("telegram_id", BigInteger, primary_key=True),
    Column("name", String, nullable=False),
    Column("is_active", Boolean, default=True)
)

user_list = Table(
    "user_list",
    meta,
    Column("telegram_id", BigInteger, primary_key=True),
    Column("username", String, nullable=True),
    Column("name", String, nullable=False),       # ПІБ
    Column("university", String, nullable=True),  # КПІ або інший
    Column("faculty", String, nullable=True),     # факультет
    Column("group_name", String, nullable=True),  # група
    Column("format", String, nullable=True, default="Офлайн"),  # Формат: Офлайн або Онлайн
)

blocked_users = Table(
    "blocked_users",
    meta,
    Column("telegram_id", BigInteger, primary_key=True),
    Column("username", String, nullable=True),
    Column("name", String, nullable=True),
    Column("attempted_group", String, nullable=True),
    Column("reason", String, nullable=True),
)


async def init_db():
    """
    database initialization. Start of all tables
    :return: None
    """
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(meta.create_all)

        # Автоматична міграція: додаємо колонку format, якщо вона відсутня
        try:
            await conn.execute(text("ALTER TABLE user_list ADD COLUMN IF NOT EXISTS format VARCHAR DEFAULT 'Офлайн';"))
        except Exception:
            pass

        # if no admins
        check_admins = await conn.execute(select(admin_list))
        if check_admins.fetchone() is None:
            insert_statements = [
                insert(admin_list).values(telegram_id=admin_id, name=f"Admin_{i+1}", is_active=True)
                for i, admin_id in enumerate(SUPER_ADMINS)
            ]
            for statement in insert_statements:
                await conn.execute(statement)
