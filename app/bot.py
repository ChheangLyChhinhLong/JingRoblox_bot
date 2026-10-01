import asyncio
import html
import io
import logging
from decimal import Decimal
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import Settings
from app.payments import KHPayClient
from app.security import decrypt_stock
from app.store import Store

logger = logging.getLogger(__name__)
router = Router()
pending_stock_upload: dict[int, str] = {}


def keyboard(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def money(amount: Any) -> str:
    return f"${Decimal(str(amount)):.2f}"


def menu(settings: Settings, user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🛍 ទិញទំនិញ", callback_data="shop")],
        [InlineKeyboardButton(text="📦 ប្រវត្តិការទិញ", callback_data="history")],
        [InlineKeyboardButton(text="💬 ជំនួយ", callback_data="support")],
    ]
    if user_id in settings.admin_ids:
        rows.append([InlineKeyboardButton(text="⚙️ គ្រប់គ្រងស្តុក", callback_data="admin")])
    return keyboard(rows)


def back_button(target: str = "home") -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="⬅️ ត្រឡប់", callback_data=target)]


async def deliver_order(bot: Bot, store: Store, settings: Settings, order_id: str, chat_id: int) -> None:
    credentials = await store.fulfill_order(order_id)
    if not credentials:
        return
    details = "\n".join(f"<code>{html.escape(decrypt_stock(value, settings.stock_encryption_key))}</code>" for value in credentials)
    await bot.send_message(
        chat_id,
        f"✅ បានបញ្ជាក់ការទូទាត់។ គណនីរបស់អ្នក៖\n\n{details}",
        parse_mode="HTML",
    )
    await store.mark_delivered(order_id)


def register_handlers(
    dispatcher: Dispatcher,
    bot: Bot,
    store: Store,
    payments: KHPayClient,
    settings: Settings,
) -> None:
    @router.message(CommandStart())
    async def start(message: Message) -> None:
        await message.answer("សូមស្វាគមន៍! សូមជ្រើសរើសមុខងារ។", reply_markup=menu(settings, message.from_user.id))

    @router.callback_query(F.data == "home")
    async def home(callback: CallbackQuery) -> None:
        await callback.answer()
        await callback.message.edit_text(
            "សូមស្វាគមន៍! សូមជ្រើសរើសមុខងារ។", reply_markup=menu(settings, callback.from_user.id)
        )

    @router.callback_query(F.data == "shop")
    async def shop(callback: CallbackQuery) -> None:
        await callback.answer()
        categories = await store.categories()
        rows = [[InlineKeyboardButton(text=item["name"], callback_data=f"c:{item['id']}")] for item in categories]
        rows.append(back_button())
        await callback.message.edit_text("សូមជ្រើសរើសប្រភេទទំនិញ៖", reply_markup=keyboard(rows))

    @router.callback_query(F.data.startswith("c:"))
    async def category(callback: CallbackQuery) -> None:
        await callback.answer()
        products = await store.products(callback.data[2:])
        rows = [
            [InlineKeyboardButton(text=f"{item['name']} · {money(item['price'])}", callback_data=f"p:{item['id']}")]
            for item in products
        ]
        rows.extend([back_button("shop"), back_button()])
        await callback.message.edit_text("សូមជ្រើសរើសផលិតផល៖", reply_markup=keyboard(rows))

    @router.callback_query(F.data.startswith("p:"))
    async def product(callback: CallbackQuery) -> None:
        await callback.answer()
        product_data = await store.product(callback.data[2:])
        if not product_data:
            await callback.message.edit_text("ផលិតផលនេះមិនមានទៀតទេ។", reply_markup=keyboard([back_button("shop")]))
            return
        rows = [
            [InlineKeyboardButton(text=f"ទិញ 1 · {money(product_data['price'])}", callback_data=f"b:{product_data['id']}:1")],
            [InlineKeyboardButton(text="ទិញ 2", callback_data=f"b:{product_data['id']}:2"), InlineKeyboardButton(text="ទិញ 3", callback_data=f"b:{product_data['id']}:3")],
            back_button("shop"),
        ]
        description = product_data.get("description") or ""
        await callback.message.edit_text(
            f"<b>{html.escape(product_data['name'])}</b>\n{html.escape(description)}\n\nតម្លៃ៖ {money(product_data['price'])}",
            parse_mode="HTML",
            reply_markup=keyboard(rows),
        )

    @router.callback_query(F.data.startswith("b:"))
    async def buy(callback: CallbackQuery) -> None:
        await callback.answer("កំពុងបង្កើតការទូទាត់...")
        _, product_id, quantity_text = callback.data.split(":")
        order = None
        try:
            order = await store.reserve_order(callback.from_user.id, product_id, int(quantity_text))
            payment = await payments.create_payment(str(order["total"]), str(order["id"]))
            await store.set_payment(order["id"], payment["transaction_id"], payment["payment_url"])
        except Exception:
            logger.exception("Could not create checkout for Telegram user %s", callback.from_user.id)
            if order:
                await store.release_order(str(order["id"]))
            await callback.message.answer("មិនអាចបង្កើតការទូទាត់បានទេ។ សូមព្យាយាមម្ដងទៀត។", reply_markup=menu(settings, callback.from_user.id))
            return
        rows = [
            [InlineKeyboardButton(text="💳 ទូទាត់តាម KHPAY", url=payment["payment_url"])],
            [InlineKeyboardButton(text="✅ ខ្ញុំបានទូទាត់ · ពិនិត្យ", callback_data=f"q:{order['id']}")],
            back_button(),
        ]
        await callback.message.answer(
            f"ការបញ្ជាទិញ `{order['id']}` · {money(order['total'])}\n\nសូមទូទាត់ រួចចុចប៊ូតុងពិនិត្យ។ Bot នឹងពិនិត្យដោយស្វ័យប្រវត្តិផងដែរ។",
            parse_mode="Markdown",
            reply_markup=keyboard(rows),
        )

    @router.callback_query(F.data.startswith("q:"))
    async def check_order(callback: CallbackQuery) -> None:
        await callback.answer("Checking payment…")
        order_id = callback.data[2:]
        try:
            result = await (
                store.client.table("orders")
                .select("transaction_id,chat_id,status")
                .eq("id", order_id)
                .eq("chat_id", callback.from_user.id)
                .maybe_single()
                .execute()
            )
            data = result.data
            if not data:
                await callback.message.answer("រកមិនឃើញការបញ្ជាទិញទេ។")
                return
            if data["status"] == "paid":
                await deliver_order(bot, store, settings, order_id, callback.from_user.id)
                return
            payment = await payments.check_payment(data["transaction_id"])
            status = payment.get("status")
            if status == "paid":
                await deliver_order(bot, store, settings, order_id, callback.from_user.id)
            elif status in {"expired", "failed"}:
                await store.release_order(order_id, status)
                await callback.message.answer("ការទូទាត់នេះផុតកំណត់ហើយ។ សូមបញ្ជាទិញម្ដងទៀត។", reply_markup=menu(settings, callback.from_user.id))
            else:
                await callback.message.answer("មិនទាន់ទទួលបានការទូទាត់ទេ។ សូមបញ្ចប់ការទូទាត់តាម KHPAY។")
        except Exception:
            logger.exception("Payment check failed for order %s", order_id)
            await callback.message.answer("មិនអាចពិនិត្យការទូទាត់បានទេ។ សូមព្យាយាមម្ដងទៀតបន្តិចក្រោយ។")

    @router.callback_query(F.data == "history")
    async def history(callback: CallbackQuery) -> None:
        await callback.answer()
        orders = await store.order_history(callback.from_user.id)
        if not orders:
            text = "អ្នកមិនទាន់មានការបញ្ជាទិញទេ។"
        else:
            text = "ការបញ្ជាទិញថ្មីៗ៖\n" + "\n".join(
                f"• {item['id'][:8]} · {money(item['total'])} · {item['status']}" for item in orders
            )
        await callback.message.edit_text(text, reply_markup=keyboard([back_button()]))

    @router.callback_query(F.data == "support")
    async def support(callback: CallbackQuery) -> None:
        await callback.answer()
        if settings.support_username:
            rows = [[InlineKeyboardButton(text="បើកការជជែកជាមួយជំនួយ", url=f"https://t.me/{settings.support_username.lstrip('@')}")], back_button()]
            await callback.message.edit_text("សូមទាក់ទងក្រុមជំនួយ៖", reply_markup=keyboard(rows))
        else:
            await callback.message.edit_text("សូមទាក់ទងអ្នកគ្រប់គ្រងហាង។", reply_markup=keyboard([back_button()]))

    @router.callback_query(F.data == "admin")
    async def admin(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            await callback.message.edit_text("អ្នកមិនមានសិទ្ធិប្រើប្រាស់ទេ។", reply_markup=keyboard([back_button()]))
            return
        result = await store.client.table("products").select("id,name").eq("active", True).execute()
        lines = []
        for item in result.data:
            stock = await store.client.rpc("available_stock_count", {"p_product_id": item["id"]}).execute()
            lines.append(f"• {item['name']}: {stock.data} available")
        rows = [
            [InlineKeyboardButton(text="📥 បញ្ចូលស្តុក (.txt)", callback_data="admin:upload")],
            [InlineKeyboardButton(text="📊 ស្ថិតិការលក់", callback_data="admin:sales")],
            back_button(),
        ]
        await callback.message.edit_text(
            "ស្តុកដែលនៅសល់\n" + ("\n".join(lines) or "មិនមានផលិតផលសកម្មទេ។"),
            reply_markup=keyboard(rows),
        )

    @router.callback_query(F.data == "admin:upload")
    async def choose_stock_product(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            return
        result = await store.client.table("products").select("id,name").eq("active", True).order("sort_order").execute()
        rows = [[InlineKeyboardButton(text=item["name"], callback_data=f"au:{item['id']}")] for item in result.data]
        rows.append(back_button("admin"))
        await callback.message.edit_text("ជ្រើសរើសផលិតផលសម្រាប់បញ្ចូលស្តុក៖", reply_markup=keyboard(rows))

    @router.callback_query(F.data.startswith("au:"))
    async def request_stock_file(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            return
        pending_stock_upload[callback.from_user.id] = callback.data[3:]
        await callback.message.answer(
            "សូមផ្ញើឯកសារ .txt ដែលមាន username:password មួយក្នុងមួយជួរ។",
            reply_markup=keyboard([back_button("admin:cancel-upload")]),
        )

    @router.callback_query(F.data == "admin:cancel-upload")
    async def cancel_stock_file(callback: CallbackQuery) -> None:
        pending_stock_upload.pop(callback.from_user.id, None)
        await callback.answer("បានបោះបង់")
        await callback.message.edit_text("បានបោះបង់ការបញ្ចូលស្តុក។", reply_markup=keyboard([back_button("admin")]))

    @router.message(F.document)
    async def import_stock_file(message: Message) -> None:
        if not message.from_user or message.from_user.id not in settings.admin_ids:
            return
        product_id = pending_stock_upload.get(message.from_user.id)
        if not product_id:
            return
        document = message.document
        if not document.file_name or not document.file_name.lower().endswith(".txt") or (document.file_size or 0) > 1_000_000:
            await message.answer("សូមប្រើឯកសារ .txt ទំហំមិនលើស 1 MB។", reply_markup=keyboard([back_button("admin:cancel-upload")]))
            return
        try:
            buffer = io.BytesIO()
            await bot.download(document.file_id, destination=buffer)
            credentials = [line.strip() for line in buffer.getvalue().decode("utf-8").splitlines() if line.strip()]
            if not credentials or any(
                ":" not in item or not item.split(":", 1)[0] or not item.split(":", 1)[1]
                for item in credentials
            ):
                raise ValueError("Each line must contain username:password")
            added = await store.import_stock(product_id, credentials, settings.stock_encryption_key)
        except (UnicodeDecodeError, ValueError) as exc:
            await message.answer(f"ឯកសារមិនត្រឹមត្រូវ៖ {html.escape(str(exc))}", reply_markup=keyboard([back_button("admin:cancel-upload")]))
            return
        except Exception:
            logger.exception("Stock import failed for product %s", product_id)
            await message.answer("មិនអាចបញ្ចូលស្តុកបានទេ។ សូមព្យាយាមម្ដងទៀត។")
            return
        pending_stock_upload.pop(message.from_user.id, None)
        await message.answer(f"បានបញ្ចូលស្តុកថ្មីចំនួន {added}។", reply_markup=keyboard([back_button("admin")]))

    @router.callback_query(F.data == "admin:sales")
    async def sales_summary(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            return
        summary = await store.sales_summary()
        text = (
            f"ស្ថិតិការលក់\nការបញ្ជាទិញដែលបានបង់៖ {summary['paid_orders']}\n"
            f"ចំណូលសរុប៖ {money(summary['total_revenue'])}\n"
            f"ចំណូលថ្ងៃនេះ៖ {money(summary['today_revenue'])}"
        )
        await callback.message.edit_text(text, reply_markup=keyboard([back_button("admin")]))

    dispatcher.include_router(router)


async def reconcile_payments(bot: Bot, store: Store, payments: KHPayClient, settings: Settings) -> None:
    while True:
        try:
            for order in await store.pending_orders():
                try:
                    payment = await payments.check_payment(order["transaction_id"])
                    status = payment.get("status")
                    if status == "paid":
                        await deliver_order(bot, store, settings, order["id"], int(order["chat_id"]))
                    elif status in {"expired", "failed"}:
                        await store.release_order(order["id"], status)
                except Exception:
                    logger.exception("Reconciliation failed for order %s", order["id"])
            for order in await store.undelivered_orders():
                try:
                    await deliver_order(bot, store, settings, order["id"], int(order["chat_id"]))
                except Exception:
                    logger.exception("Delivery retry failed for order %s", order["id"])
        except Exception:
            logger.exception("Could not load pending orders")
        await asyncio.sleep(settings.poll_interval_seconds)
