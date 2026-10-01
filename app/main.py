import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from aiogram import Bot, Dispatcher
from fastapi import FastAPI
from supabase import acreate_client

from app.bot import reconcile_payments, register_handlers
from app.config import get_settings
from app.payments import KHPayClient
from app.store import Store

logging.basicConfig(level=logging.INFO)
settings = get_settings()
bot = Bot(settings.bot_token)
dispatcher = Dispatcher()
payments = KHPayClient(settings.khpay_api_key, settings.khpay_base_url)


@asynccontextmanager
async def lifespan(_: FastAPI):
    supabase = await acreate_client(settings.supabase_url, settings.supabase_service_role_key)
    store = Store(supabase)
    register_handlers(dispatcher, bot, store, payments, settings)
    polling_task = asyncio.create_task(dispatcher.start_polling(bot))
    reconcile_task = asyncio.create_task(reconcile_payments(bot, store, payments, settings))
    try:
        yield
    finally:
        polling_task.cancel()
        reconcile_task.cancel()
        await asyncio.gather(polling_task, reconcile_task, return_exceptions=True)
        await bot.session.close()
        await payments.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
