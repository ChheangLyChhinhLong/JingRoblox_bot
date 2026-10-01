import asyncio
import json
import logging
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation

import uvicorn
from aiogram import Bot, Dispatcher
from fastapi import FastAPI, HTTPException, Request
from supabase import acreate_client

from app.bot import delete_payment_message, deliver_order, reconcile_payments, register_handlers
from app.config import get_settings
from app.payments import KHPayClient, verify_webhook_signature
from app.store import Store

logging.basicConfig(level=logging.INFO)
settings = get_settings()
bot = Bot(settings.bot_token)
dispatcher = Dispatcher()
payments = KHPayClient(settings.khpay_api_key, settings.khpay_base_url, settings.khpay_webhook_url)


@asynccontextmanager
async def lifespan(_: FastAPI):
    supabase = await acreate_client(settings.supabase_url, settings.supabase_service_role_key)
    store = Store(supabase)
    app.state.store = store
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


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/health", methods=["GET", "HEAD"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook/khpay")
async def khpay_webhook(request: Request) -> dict[str, bool | str]:
    if not settings.khpay_webhook_secret:
        raise HTTPException(status_code=503, detail="KHPAY webhook secret is not configured")

    raw_body = await request.body()
    signature = request.headers.get("x-webhook-signature", "")
    if not signature:
        signature = request.headers.get("x-khpay-signature", "")
    if not verify_webhook_signature(raw_body, signature, settings.khpay_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    event = payload.get("event")
    if event == "webhook.test":
        return {"received": True, "status": "test"}

    event_status = {
        "payment.paid": "paid",
        "payment.expired": "expired",
        "payment.failed": "failed",
    }.get(event)
    event_data = payload.get("data")
    if not isinstance(event_data, dict):
        event_data = payload
    reported_status = event_data.get("status") or payload.get("status")
    if isinstance(reported_status, str):
        reported_status = reported_status.lower()
    expected_status = event_status or (
        reported_status if reported_status in {"paid", "expired", "failed"} else None
    )
    if not expected_status:
        return {"received": True, "status": "ignored"}

    transaction_id = event_data.get("transaction_id") or payload.get("transaction_id")
    if not isinstance(transaction_id, str) or not transaction_id:
        raise HTTPException(status_code=400, detail="Missing transaction_id")

    store: Store = request.app.state.store
    order = await store.order_by_transaction(transaction_id)
    if not order:
        return {"received": True, "status": "unknown_transaction"}
    if order["status"] not in {"pending", "paid"}:
        return {"received": True, "status": "order_already_closed"}

    try:
        payment = await payments.check_payment(transaction_id)
    except Exception:
        logging.getLogger(__name__).exception("KHPAY status verification failed for %s", transaction_id)
        raise HTTPException(status_code=503, detail="Could not verify payment with KHPAY") from None
    if payment.get("status") != expected_status:
        return {"received": True, "status": "awaiting_api_confirmation"}

    if expected_status == "paid":
        try:
            expected_amount = Decimal(str(order["total"]))
            confirmed_amount = Decimal(str(payment["amount"]))
            webhook_amount = event_data.get("amount")
            if confirmed_amount != expected_amount or (
                webhook_amount is not None and Decimal(str(webhook_amount)) != expected_amount
            ):
                raise HTTPException(status_code=400, detail="Payment amount does not match the order")
        except (InvalidOperation, KeyError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid payment amount") from None
        await deliver_order(bot, store, settings, order["id"], int(order["chat_id"]))
    else:
        await delete_payment_message(bot, store, order["id"])
        await store.release_order(order["id"], expected_status)

    return {"received": True, "status": expected_status}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
