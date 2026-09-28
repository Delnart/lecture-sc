import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from app.db.db_setup import init_db

from aiohttp import web

import os
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if sys.platform != "win32":
    try:
        import uvloop
        uvloop.install()
        print("⚡ uvloop активовано для максимальної швидкодії")
    except ImportError:
        pass

from app.routers.controller_router import router as controller_router
from app.db.db_requests import load_admins_cache


async def init_db_with_retry(retries: int = 5, delay: float = 3.0):
    """
    Neon може мати cold start ~1–2 сек після авто-призупинення.
    Пробуємо підключитись кілька разів перед тим як впасти.
    """
    for attempt in range(1, retries + 1):
        try:
            await init_db()
            print(f"✅ БД ініціалізована (спроба {attempt})")
            return
        except Exception as e:
            print(f"⚠️ Спроба {attempt}/{retries} — помилка БД: {e}")
            if attempt < retries:
                await asyncio.sleep(delay)
            else:
                raise


async def handle_ping(request):
    """Простий endpoint для Render та UptimeRobot"""
    return web.Response(text="Bot is alive!")


async def start_web_server():
    """Запускає веб-сервер aiohttp у фоні для Render"""
    app = web.Application()
    app.router.add_get('/', handle_ping)
    app.router.add_get('/ping', handle_ping)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌐 Web server started on port {port}")


async def main():
    bot = Bot(
       token=BOT_TOKEN,
       default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    dp = Dispatcher()
    dp.include_router(controller_router)

    print("Ініціалізація БД...")
    await init_db_with_retry()

    try:
        await load_admins_cache()
        print("⚡ Кеш адміністраторів прогріто")
    except Exception as e:
        print(f"⚠️ Помилка прогріву кешу адмінів: {e}")

    print("Запуск веб-сервера (для Render)...")
    await start_web_server()

    print("Запуск бота...")
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types()
    )


if __name__ == "__main__":
   logging.basicConfig(level=logging.INFO, stream=sys.stdout)

   try:
       asyncio.run(main())
   except KeyboardInterrupt:
       print("Bot stopped")

