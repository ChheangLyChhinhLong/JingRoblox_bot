import asyncio
import html
import io
import logging
from decimal import Decimal, InvalidOperation
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
pending_admin_input: dict[int, tuple[str, str | None]] = {}


def keyboard(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def money(amount: Any) -> str:
    return f"${Decimal(str(amount)):.2f}"


def category_icon(name: str) -> str:
    lowered_name = name.casefold()
    if "roblox" in lowered_name or "robux" in lowered_name:
        return "💎"
    if "gamepass" in lowered_name:
        return "🎮"
    if "premium" in lowered_name or "tool" in lowered_name:
        return "⚡️"
    return "🛍"


def welcome_text(user: Any) -> str:
    username = f"@{html.escape(user.username)}" if user.username else "មិនមាន"
    return (
        f"🙏🏻 <b>សូមស្វាគមន៍ {html.escape(user.first_name)}!</b> ⚡️\n\n"
        "<b>ព័ត៌មានគណនី</b>\n"
        f"├─ 🆔 <b>ID</b>: <code>{user.id}</code>\n"
        f"└─ 👤 <b>ឈ្មោះ</b>: {username}\n\n"
        "🛍 <b>ប្រភេទផលិតផលក្នុងហាង</b>\n"
        "├─ 💎 <b>Roblox Gift Cards</b> (កូដកាតស្វ័យប្រវត្តិ)\n"
        "├─ 🎮 <b>Gamepass Gift</b> (Admin ជូនក្នុងហ្គេមផ្ទាល់)\n"
        "└─ ⚡️ <b>គណនី Premium &amp; Tools</b>\n\n"
        "💬 <b>សូមចុចប៊ូតុងខាងក្រោមដើម្បីចាប់ផ្តើម៖</b>"
    )


def quantity_limit(stock: int) -> int:
    return max(0, min(3, stock))


def menu(settings: Settings, user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🛍 ហាងលក់", callback_data="shop")],
        [InlineKeyboardButton(text="📦 ប្រវត្តិការទិញ", callback_data="history")],
        [InlineKeyboardButton(text="💬 ជំនួយ", callback_data="support")],
    ]
    if user_id in settings.admin_ids:
        rows.append([InlineKeyboardButton(text="⚙️ គ្រប់គ្រងហាង", callback_data="admin")])
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
        await message.answer(
            welcome_text(message.from_user),
            parse_mode="HTML",
            reply_markup=menu(settings, message.from_user.id),
        )

    @router.callback_query(F.data == "home")
    async def home(callback: CallbackQuery) -> None:
        await callback.answer()
        await callback.message.edit_text(
            welcome_text(callback.from_user),
            parse_mode="HTML",
            reply_markup=menu(settings, callback.from_user.id),
        )

    @router.callback_query(F.data == "shop")
    async def shop(callback: CallbackQuery) -> None:
        await callback.answer()
        categories = await store.categories()
        if not categories:
            await callback.message.edit_text(
                "បច្ចុប្បន្នមិនមានប្រភេទទំនិញទេ។ សូមពិនិត្យម្ដងទៀតពេលក្រោយ។",
                reply_markup=keyboard([back_button()]),
            )
            return
        rows = [
            [
                InlineKeyboardButton(
                    text=f"{category_icon(item['name'])} {item['name']}",
                    callback_data=f"c:{item['id']}",
                )
            ]
            for item in categories
        ]
        rows.append(back_button())
        text = (
            "🛍 <b>សូមជ្រើសរើសប្រភេទផលិតផល</b>\n"
            "───────────────────\n"
            "សូមជ្រើសរើស Catalog ណាមួយខាងក្រោមដើម្បីមើល Package ទំនិញ៖"
        )
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard(rows))

    @router.callback_query(F.data.startswith("c:"))
    async def category(callback: CallbackQuery) -> None:
        await callback.answer()
        category_id = callback.data[2:]
        category_data = await store.category(category_id)
        if not category_data:
            await callback.message.edit_text(
                "ប្រភេទផលិតផលនេះមិនមានទៀតទេ។",
                reply_markup=keyboard([back_button("shop")]),
            )
            return
        products = await store.products(category_id)
        if not products:
            await callback.message.edit_text(
                f"{category_icon(category_data['name'])} <b>{html.escape(category_data['name'])}</b>\n"
                "───────────────────\n"
                "ប្រភេទនេះមិនទាន់មាន Package ទេ។",
                parse_mode="HTML",
                reply_markup=keyboard([back_button("shop")]),
            )
            return
        stock_counts = await asyncio.gather(*(store.available_stock(item["id"]) for item in products))
        rows = []
        for item, stock in zip(products, stock_counts):
            stock_label = f"Stock: {stock}" if stock else "អស់ស្តុក"
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"📦 {item['name']} · {money(item['price'])} ({stock_label})",
                        callback_data=f"p:{item['id']}",
                    )
                ]
            )
        rows.append(back_button("shop"))
        description = (category_data.get("description") or "").strip()
        intro = html.escape(description) if description else "សូមជ្រើសរើស Package ខាងក្រោម៖"
        text = (
            f"{category_icon(category_data['name'])} <b>{html.escape(category_data['name'])}</b>\n"
            "───────────────────\n"
            f"{intro}\n\nសូមជ្រើសរើស Package ខាងក្រោម៖"
        )
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard(rows))

    @router.callback_query(F.data.startswith("p:"))
    async def product(callback: CallbackQuery) -> None:
        await callback.answer()
        product_data = await store.product(callback.data[2:])
        if not product_data:
            await callback.message.edit_text("ផលិតផលនេះមិនមានទៀតទេ។", reply_markup=keyboard([back_button("shop")]))
            return
        await show_product(callback.message, product_data, 1)

    async def show_product(message: Message, product_data: dict[str, Any], quantity: int) -> None:
        stock = await store.available_stock(product_data["id"])
        max_quantity = quantity_limit(stock)
        quantity = min(max(quantity, 1), max_quantity) if max_quantity else 0
        category_data = await store.category(product_data["category_id"])
        rows: list[list[InlineKeyboardButton]] = []
        if max_quantity:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="➖" if quantity > 1 else "·",
                        callback_data=f"qty:{product_data['id']}:{quantity - 1}" if quantity > 1 else "noop",
                    ),
                    InlineKeyboardButton(text=f"Qty: {quantity}", callback_data="noop"),
                    InlineKeyboardButton(
                        text="➕" if quantity < max_quantity else "·",
                        callback_data=f"qty:{product_data['id']}:{quantity + 1}" if quantity < max_quantity else "noop",
                    ),
                ]
            )
            total = Decimal(str(product_data["price"])) * quantity
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"💳 បង់ប្រាក់ • {money(total)}",
                        callback_data=f"b:{product_data['id']}:{quantity}",
                    )
                ]
            )
        else:
            rows.append([InlineKeyboardButton(text="អស់ស្តុក", callback_data="noop")])
        rows.append(back_button(f"c:{product_data['category_id']}"))
        category_title = f"{category_icon(category_data['name'])} {html.escape(category_data['name'])}\n" if category_data else ""
        description = html.escape(product_data.get("description") or "មិនមានព័ត៌មានបន្ថែម។")
        text = (
            f"{category_title}"
            "🛒 <b>បញ្ជាក់ការបញ្ជាទិញ</b>\n"
            "───────────────────\n"
            f"• ផលិតផល: {html.escape(product_data['name'])}\n"
            f"• តម្លៃឯកតា: {money(product_data['price'])}\n"
            f"• ស្តុកមាន: {stock}\n\n"
            f"{description}\n"
            "───────────────────"
        )
        await message.edit_text(
            text, parse_mode="HTML", reply_markup=keyboard(rows)
        )

    @router.callback_query(F.data.startswith("qty:"))
    async def change_quantity(callback: CallbackQuery) -> None:
        await callback.answer()
        _, product_id, quantity_text = callback.data.split(":")
        product_data = await store.product(product_id)
        if not product_data:
            await callback.message.edit_text("ផលិតផលនេះមិនមានទៀតទេ។", reply_markup=keyboard([back_button("shop")]))
            return
        await show_product(callback.message, product_data, int(quantity_text))

    @router.callback_query(F.data == "noop")
    async def no_action(callback: CallbackQuery) -> None:
        await callback.answer()

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
        result = await store.client.table("products").select("id,name").eq("active", True).order("sort_order").execute()
        lines = []
        for item in result.data:
            stock = await store.available_stock(item["id"])
            lines.append(f"• {html.escape(item['name'])}: {stock} នៅសល់")
        rows = [
            [InlineKeyboardButton(text="🗂 គ្រប់គ្រង Catalog និង Package", callback_data="admin:catalogs")],
            [InlineKeyboardButton(text="📥 បញ្ចូលស្តុក (.txt)", callback_data="admin:upload")],
            [InlineKeyboardButton(text="📊 ស្ថិតិការលក់", callback_data="admin:sales")],
            back_button(),
        ]
        await callback.message.edit_text(
            "⚙️ <b>ផ្ទាំងគ្រប់គ្រងហាង</b>\n"
            "ស្តុកដែលនៅសល់\n"
            + ("\n".join(lines) or "មិនមានផលិតផលសកម្មទេ។"),
            parse_mode="HTML",
            reply_markup=keyboard(rows),
        )

    @router.callback_query(F.data == "admin:catalogs")
    async def admin_catalogs(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            return
        result = await store.client.table("categories").select("id,name").eq("active", True).order("sort_order").execute()
        rows = [
            [InlineKeyboardButton(text=f"{category_icon(item['name'])} {item['name']}", callback_data=f"ac:{item['id']}")]
            for item in result.data
        ]
        rows.extend(
            [
                [InlineKeyboardButton(text="➕ បន្ថែម Catalog", callback_data="admin:category-add")],
                back_button("admin"),
            ]
        )
        await callback.message.edit_text(
            "🗂 <b>គ្រប់គ្រង Catalog</b>\nជ្រើសរើស Catalog ដើម្បីកែប្រែ ឬបន្ថែម Package៖",
            parse_mode="HTML",
            reply_markup=keyboard(rows),
        )

    @router.callback_query(F.data == "admin:category-add")
    async def add_category_prompt(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            return
        pending_admin_input[callback.from_user.id] = ("category_add", None)
        await callback.message.edit_text(
            "ផ្ញើព័ត៌មាន Catalog តាមទម្រង់៖ <code>ឈ្មោះ | ព័ត៌មានលម្អិត</code>",
            parse_mode="HTML",
            reply_markup=keyboard([back_button("admin:cancel-input")]),
        )

    @router.callback_query(F.data.startswith("ac:"))
    async def admin_category(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            return
        category_id = callback.data[3:]
        category_data = await store.category(category_id)
        if not category_data:
            await callback.message.edit_text("រកមិនឃើញ Catalog ទេ។", reply_markup=keyboard([back_button("admin:catalogs")]))
            return
        result = await store.client.table("products").select("id,name").eq("category_id", category_id).eq("active", True).order("sort_order").execute()
        rows = [
            [InlineKeyboardButton(text=f"📦 {item['name']}", callback_data=f"ap:{item['id']}")]
            for item in result.data
        ]
        rows.extend(
            [
                [InlineKeyboardButton(text="➕ បន្ថែម Package", callback_data=f"admin:product-add:{category_id}")],
                [InlineKeyboardButton(text="✏️ កែ Catalog", callback_data=f"admin:category-edit:{category_id}")],
                [InlineKeyboardButton(text="🗑 បិទ Catalog", callback_data=f"admin:category-disable:{category_id}")],
                back_button("admin:catalogs"),
            ]
        )
        await callback.message.edit_text(
            f"🗂 <b>{html.escape(category_data['name'])}</b>\n{html.escape(category_data.get('description') or '')}",
            parse_mode="HTML",
            reply_markup=keyboard(rows),
        )

    @router.callback_query(F.data.startswith("ap:"))
    async def admin_product(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            return
        product_data = await store.product(callback.data[3:])
        if not product_data:
            await callback.message.edit_text("រកមិនឃើញ Package ទេ។", reply_markup=keyboard([back_button("admin:catalogs")]))
            return
        stock = await store.available_stock(product_data["id"])
        rows = [
            [InlineKeyboardButton(text="✏️ កែ Package", callback_data=f"admin:product-edit:{product_data['id']}")],
            [InlineKeyboardButton(text="📥 បញ្ចូលស្តុក (.txt)", callback_data=f"au:{product_data['id']}")],
            [InlineKeyboardButton(text="🗑 បិទ Package", callback_data=f"admin:product-disable:{product_data['id']}")],
            back_button(f"ac:{product_data['category_id']}"),
        ]
        await callback.message.edit_text(
            f"📦 <b>{html.escape(product_data['name'])}</b>\n"
            f"តម្លៃ៖ {money(product_data['price'])}\n"
            f"ស្តុកនៅសល់៖ {stock}\n\n"
            f"{html.escape(product_data.get('description') or '')}",
            parse_mode="HTML",
            reply_markup=keyboard(rows),
        )

    @router.callback_query(F.data.startswith("admin:product-add:"))
    async def add_product_prompt(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            return
        category_id = callback.data.removeprefix("admin:product-add:")
        pending_admin_input[callback.from_user.id] = ("product_add", category_id)
        await callback.message.edit_text(
            "ផ្ញើព័ត៌មាន Package តាមទម្រង់៖ <code>ឈ្មោះ | តម្លៃ | ព័ត៌មានលម្អិត</code>",
            parse_mode="HTML",
            reply_markup=keyboard([back_button("admin:cancel-input")]),
        )

    @router.callback_query(F.data.startswith("admin:category-edit:"))
    async def edit_category_prompt(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            return
        category_id = callback.data.removeprefix("admin:category-edit:")
        pending_admin_input[callback.from_user.id] = ("category_edit", category_id)
        await callback.message.edit_text(
            "ផ្ញើឈ្មោះ និងព័ត៌មានថ្មីតាមទម្រង់៖ <code>ឈ្មោះ | ព័ត៌មានលម្អិត</code>",
            parse_mode="HTML",
            reply_markup=keyboard([back_button("admin:cancel-input")]),
        )

    @router.callback_query(F.data.startswith("admin:product-edit:"))
    async def edit_product_prompt(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            return
        product_id = callback.data.removeprefix("admin:product-edit:")
        pending_admin_input[callback.from_user.id] = ("product_edit", product_id)
        await callback.message.edit_text(
            "ផ្ញើឈ្មោះ តម្លៃ និងព័ត៌មានថ្មីតាមទម្រង់៖ <code>ឈ្មោះ | តម្លៃ | ព័ត៌មានលម្អិត</code>",
            parse_mode="HTML",
            reply_markup=keyboard([back_button("admin:cancel-input")]),
        )

    @router.callback_query(F.data.startswith("admin:category-disable:"))
    async def confirm_category_disable(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            return
        category_id = callback.data.removeprefix("admin:category-disable:")
        rows = [
            [InlineKeyboardButton(text="✅ បិទ Catalog", callback_data=f"adc:{category_id}")],
            back_button(f"ac:{category_id}"),
        ]
        await callback.message.edit_text("បិទ Catalog នេះ និងផលិតផលសកម្មរបស់វា?", reply_markup=keyboard(rows))

    @router.callback_query(F.data.startswith("adc:"))
    async def disable_category(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            return
        category_id = callback.data[4:]
        await store.client.table("categories").update({"active": False}).eq("id", category_id).execute()
        await store.client.table("products").update({"active": False}).eq("category_id", category_id).execute()
        await callback.message.edit_text("បានបិទ Catalog និងផលិតផលរបស់វា។", reply_markup=keyboard([back_button("admin:catalogs")]))

    @router.callback_query(F.data.startswith("admin:product-disable:"))
    async def confirm_product_disable(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            return
        product_id = callback.data.removeprefix("admin:product-disable:")
        rows = [
            [InlineKeyboardButton(text="✅ បិទ Package", callback_data=f"adp:{product_id}")],
            back_button(f"ap:{product_id}"),
        ]
        await callback.message.edit_text("បិទ Package នេះ?", reply_markup=keyboard(rows))

    @router.callback_query(F.data.startswith("adp:"))
    async def disable_product(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            return
        product_id = callback.data[4:]
        await store.client.table("products").update({"active": False}).eq("id", product_id).execute()
        await callback.message.edit_text("បានបិទ Package។", reply_markup=keyboard([back_button("admin:catalogs")]))

    @router.callback_query(F.data == "admin:cancel-input")
    async def cancel_admin_input(callback: CallbackQuery) -> None:
        pending_admin_input.pop(callback.from_user.id, None)
        await callback.answer("បានបោះបង់")
        await callback.message.edit_text("បានបោះបង់។", reply_markup=keyboard([back_button("admin:catalogs")]))

    @router.message(F.text)
    async def receive_admin_input(message: Message) -> None:
        if not message.from_user or message.from_user.id not in settings.admin_ids:
            return
        pending = pending_admin_input.get(message.from_user.id)
        if not pending:
            return
        action, target_id = pending
        text = (message.text or "").strip()
        try:
            if action in {"category_add", "category_edit"}:
                name, separator, description = text.partition("|")
                if not name.strip():
                    raise ValueError("សូមបញ្ចូលឈ្មោះ Catalog។")
                values = {"name": name.strip(), "description": description.strip() if separator else ""}
                if action == "category_add":
                    await store.client.table("categories").insert(values).execute()
                else:
                    await store.client.table("categories").update(values).eq("id", target_id).execute()
            elif action in {"product_add", "product_edit"}:
                fields = [part.strip() for part in text.split("|", 2)]
                if len(fields) != 3:
                    raise ValueError("សូមប្រើទម្រង់ ឈ្មោះ | តម្លៃ | ព័ត៌មានលម្អិត។")
                name, price_text, description = fields
                try:
                    price = Decimal(price_text)
                except InvalidOperation:
                    raise ValueError("តម្លៃមិនត្រឹមត្រូវទេ។") from None
                if not name or price <= 0:
                    raise ValueError("ឈ្មោះ និងតម្លៃត្រូវតែត្រឹមត្រូវ ហើយតម្លៃត្រូវធំជាង 0។")
                values = {"name": name, "price": str(price), "description": description}
                if action == "product_add":
                    values["category_id"] = target_id
                    await store.client.table("products").insert(values).execute()
                else:
                    await store.client.table("products").update(values).eq("id", target_id).execute()
            else:
                return
        except (InvalidOperation, ValueError) as exc:
            await message.answer(
                f"ព័ត៌មានមិនត្រឹមត្រូវ៖ {html.escape(str(exc))}",
                reply_markup=keyboard([back_button("admin:cancel-input")]),
            )
            return
        except Exception:
            logger.exception("Admin catalog update failed for user %s", message.from_user.id)
            await message.answer("មិនអាចរក្សាទុកបានទេ។ សូមព្យាយាមម្ដងទៀត។")
            return
        pending_admin_input.pop(message.from_user.id, None)
        target = "admin:catalogs" if action.startswith("category") else "admin"
        await message.answer("បានរក្សាទុកដោយជោគជ័យ។", reply_markup=keyboard([back_button(target)]))

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
            "សូមផ្ញើឯកសារ .txt ដែលមាន Code ឬ username:password មួយក្នុងមួយជួរ។",
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
            if not credentials:
                raise ValueError("Each line must contain a code or username:password")
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
