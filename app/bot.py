import asyncio
import base64
import html
import io
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

import qrcode
import cloudinary.uploader
from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Message

from app.config import Settings
from app.payments import KHPayClient, aba_mobile_deeplink, aba_mobile_redirect_url
from app.security import decrypt_stock
from app.store import Store

logger = logging.getLogger(__name__)
router = Router()
pending_stock_upload: dict[int, str] = {}
pending_admin_input: dict[int, tuple[str, str | None]] = {}
welcome_message_ids: dict[int, int] = {}


def keyboard(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def edit_text_message(
    message: Message,
    text: str,
    *,
    parse_mode: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    if message.text is None:
        try:
            await message.delete()
        except TelegramBadRequest:
            logger.debug("Could not delete old photo message %s", message.message_id)
        return await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
    return await message.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)


async def delete_replaced_message(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        logger.debug("Could not delete replaced message %s", message.message_id)


def money(amount: Any) -> str:
    return f"${Decimal(str(amount)):.2f}"


def payment_caption(product_name: str, quantity: int, amount: Any, transaction_ref: str) -> str:
    total = f"{Decimal(str(amount)):.2f}"
    return (
        f"💳 <b>Pay ${total}</b>\n\n"
        f"🛍 <b>Product:</b> {html.escape(product_name)} x{quantity}\n"
        f"💰 <b>Total:</b> ${total}\n"
        f"🟢 <b>Remaining to pay:</b> ${total}\n"
        f"🏷 <b>Ref:</b> <code>{html.escape(transaction_ref)}</code>\n"
        "⏱ <b>Scan KHQR to complete payment.</b>\n"
        "⏰ <b>You have 15 minutes to pay. The QR refreshes itself.</b>"
    )


def copy(language: str, khmer: str, english: str) -> str:
    return english if language == "en" else khmer


def welcome_text(user: Any, language: str = "km", categories: list[dict[str, Any]] | None = None) -> str:
    username = f"@{html.escape(user.username)}" if user.username else "មិនមាន"
    category_rows = []
    for index, item in enumerate(categories or []):
        branch = "└─" if index == len(categories or []) - 1 else "├─"
        category_name = html.escape(str(item.get("name") or ""))
        description = html.escape(str(item.get("description") or "").strip())
        description_text = f" ({description})" if description else ""
        category_rows.append(f"{branch} 🛍 <b>{category_name}</b>{description_text}")
    category_list = "\n".join(category_rows) or copy(
        language,
        "└─ មិនទាន់មាន Catalog ទេ",
        "└─ No catalogs available yet",
    )
    if language == "en":
        username = f"@{html.escape(user.username)}" if user.username else "Not set"
        return (
            f"🙏🏻 <b>Welcome, {html.escape(user.first_name)}!</b> ⚡️\n\n"
            "<b>Account information</b>\n"
            f"├─ 🆔 <b>ID</b>: <code>{user.id}</code>\n"
            f"└─ 👤 <b>Name</b>: {username}\n\n"
            f"🛍 <b>Store categories</b>\n{category_list}\n\n"
            "💬 <b>Choose an option below to get started:</b>"
        )
    return (
        f"🙏🏻 <b>សូមស្វាគមន៍ {html.escape(user.first_name)}!</b> ⚡️\n\n"
        "<b>ព័ត៌មានគណនី</b>\n"
        f"├─ 🆔 <b>ID</b>: <code>{user.id}</code>\n"
        f"└─ 👤 <b>ឈ្មោះ</b>: {username}\n\n"
        f"🛍 <b>ប្រភេទផលិតផលក្នុងហាង</b>\n{category_list}\n\n"
        "💬 <b>សូមចុចប៊ូតុងខាងក្រោមដើម្បីចាប់ផ្តើម៖</b>"
    )


def quantity_limit(stock: int) -> int:
    return max(0, min(3, stock))


def parse_product_caption(caption: str) -> tuple[str, str, str]:
    if caption.lstrip().startswith("/"):
        raise ValueError("សូមផ្ញើ Caption ដោយមិនដាក់សញ្ញា / នៅខាងមុខ។")
    fields = [field.strip() for field in caption.split("|", 2)]
    if len(fields) != 3 or not fields[0] or not fields[1]:
        raise ValueError("សូមប្រើទម្រង់ ឈ្មោះ | តម្លៃ | ព័ត៌មានលម្អិត។")
    try:
        price = Decimal(fields[1])
    except InvalidOperation:
        raise ValueError("តម្លៃមិនត្រឹមត្រូវទេ។") from None
    if not price.is_finite() or price <= 0:
        raise ValueError("តម្លៃត្រូវតែធំជាង 0។")
    return fields[0], str(price), fields[2]


def parse_stock_add(text: str) -> tuple[str, list[str]] | None:
    header, separator, stock_text = text.partition("|")
    parts = header.strip().split()
    if not parts or parts[0].lower() != "addstock":
        return None
    if len(parts) != 2 or not separator:
        raise ValueError("សូមប្រើទម្រង់ addstock <product_id> | code1, code2។")
    credentials = [item.strip() for item in stock_text.replace("\n", ",").split(",") if item.strip()]
    if not credentials:
        raise ValueError("សូមបញ្ចូល Code យ៉ាងហោចណាស់មួយ។")
    return parts[1], credentials


def description_preview(description: str, language: str = "km") -> str:
    lines = [line.strip() for line in description.splitlines() if line.strip()]
    if not lines:
        return copy(language, "មិនមានព័ត៌មានបន្ថែម។", "No additional details.")
    if len(lines) > 3:
        lines = [*lines[:3], "• ..."]
    return html.escape("\n".join(lines))


def payment_qr(payment: dict[str, Any]) -> BufferedInputFile | str:
    qr_string = payment.get("qr_string")
    if qr_string:
        image = qrcode.make(str(qr_string))
        output = io.BytesIO()
        image.save(output, format="PNG")
        return BufferedInputFile(output.getvalue(), filename="payment-qr.png")
    image_url = payment.get("qr_image_url")
    if image_url:
        return image_url
    image_data = payment.get("qr_image_base64") or payment.get("image_base64") or payment.get("qr_image")
    if image_data:
        if image_data.startswith("data:image"):
            image_data = image_data.split(",", 1)[-1]
        return BufferedInputFile(base64.b64decode(image_data), filename="payment-qr.png")
    payload = (
        payment.get("qr_payload")
        or payment.get("qr_string")
        or payment.get("qr_code")
        or payment.get("qr_data")
        or payment.get("qr")
        or payment.get("khqr")
    )
    if not payload:
        raise ValueError("KHPAY response is missing QR data")
    image = qrcode.make(str(payload))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return BufferedInputFile(output.getvalue(), filename="payment-qr.png")


async def upload_product_image(bot: Bot, settings: Settings, file_id: str) -> str:
    if not all((settings.cloudinary_cloud_name, settings.cloudinary_api_key, settings.cloudinary_api_secret)):
        raise RuntimeError("Cloudinary credentials are not configured")
    image_stream = io.BytesIO()
    await bot.download(file_id, destination=image_stream)
    image_stream.seek(0)
    result = await asyncio.to_thread(
        cloudinary.uploader.upload,
        image_stream,
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        resource_type="image",
        folder="products",
    )
    secure_url = result.get("secure_url")
    if not isinstance(secure_url, str) or not secure_url.startswith("https://"):
        raise ValueError("Cloudinary did not return a secure HTTPS image URL")
    return secure_url


def menu(settings: Settings, user_id: int, language: str = "km") -> InlineKeyboardMarkup:
    labels = {
        "shop": copy(language, "🛍 ហាងលក់", "🛍 Shop"),
        "orders": copy(language, "🛒 ការបញ្ជាទិញ", "🛒 My orders"),
        "guide": copy(language, "🎥 របៀបទិញ", "🎥 How to buy"),
        "language": copy(language, "🌐 ភាសា", "🌐 Language"),
        "support": copy(language, "💬 ជំនួយ", "💬 Support"),
    }
    rows = [
        [InlineKeyboardButton(text=labels["shop"], callback_data="shop")],
        [InlineKeyboardButton(text=labels["orders"], callback_data="history")],
        [InlineKeyboardButton(text=labels["guide"], callback_data="how_to_buy")],
        [
            InlineKeyboardButton(text=labels["language"], callback_data="language"),
            InlineKeyboardButton(text=labels["support"], callback_data="support"),
        ],
    ]
    if user_id in settings.admin_ids:
        rows.append(
            [InlineKeyboardButton(text=copy(language, "⚙️ គ្រប់គ្រងហាង", "⚙️ Store admin"), callback_data="admin")]
        )
    return keyboard(rows)


def back_button(target: str = "home", language: str = "km") -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(
            text=copy(language, "⬅️ ត្រឡប់", "⬅️ Back"),
            callback_data=target,
        )
    ]


def admin_category_actions(category_id: str) -> list[list[InlineKeyboardButton]]:
    return [
        [InlineKeyboardButton(text="➕ បន្ថែម Package", callback_data=f"admin:product-add:{category_id}")],
        [
            InlineKeyboardButton(text="✏️ កែ Catalog", callback_data=f"admin:category-edit:{category_id}"),
            InlineKeyboardButton(text="🗑 បិទ Catalog", callback_data=f"admin:category-disable:{category_id}"),
        ],
        back_button("admin:catalogs"),
    ]


def admin_product_actions(product_id: str, category_id: str) -> list[list[InlineKeyboardButton]]:
    return [
        [
            InlineKeyboardButton(text="✏️ កែ Package", callback_data=f"admin:product-edit:{product_id}"),
            InlineKeyboardButton(text="🗑 បិទ Package", callback_data=f"admin:product-disable:{product_id}"),
        ],
        [
            InlineKeyboardButton(text="➕ បន្ថែមស្តុក", callback_data=f"admin:stock-add:{product_id}"),
            InlineKeyboardButton(text="➖ ដកស្តុក", callback_data=f"admin:stock-remove:{product_id}"),
        ],
        [InlineKeyboardButton(text="📥 បញ្ចូលស្តុក (.txt)", callback_data=f"au:{product_id}")],
        back_button(f"ac:{category_id}"),
    ]


def payment_keyboard(
    order_id: str,
    open_url: str,
) -> InlineKeyboardMarkup:
    return keyboard(
        [
            [InlineKeyboardButton(text="🏦 បើកក្នុង ABA Mobile", url=open_url)],
            [InlineKeyboardButton(text="✅ ខ្ញុំបានទូទាត់ · ពិនិត្យ", callback_data=f"check_payment_{order_id}")],
        ]
    )


async def safe_user_language(store: Store, telegram_id: int) -> str:
    try:
        return await store.user_language(telegram_id) or "km"
    except Exception:
        logger.exception("Could not load language preference for Telegram user %s", telegram_id)
        return "km"


async def safe_upsert_user(store: Store, telegram_id: int, username: str | None, first_name: str, language: str) -> None:
    try:
        await store.upsert_user(telegram_id, username, first_name, language)
    except Exception:
        logger.exception("Could not save profile for Telegram user %s", telegram_id)


async def notify_stock_added(bot: Bot, store: Store, chat_ids: str, product_id: str, added: int) -> None:
    if added < 1:
        return
    try:
        product = await store.product(product_id)
        if not product:
            logger.warning("Skipping stock notification for unavailable product %s", product_id)
            return
        users = await store.stock_notification_users()
    except Exception:
        logger.exception("Could not prepare stock notification for product %s", product_id)
        return

    destinations: dict[int | str, str | None] = {
        int(user["telegram_id"]): user.get("language", "km") for user in users
    }
    for value in chat_ids.split(","):
        chat = value.strip()
        if not chat:
            continue
        try:
            chat_id: int | str = int(chat)
        except ValueError:
            if not chat.startswith("@"):
                logger.warning("Ignoring invalid stock notification chat %r", chat)
                continue
            chat_id = chat
        destinations.setdefault(chat_id, None)

    keyboard_markup = keyboard(
        [[InlineKeyboardButton(text="🛍 មើល Package / View product", callback_data=f"p:{product_id}")]]
    )
    sent = 0
    failed = 0
    for index, (chat_id, language) in enumerate(destinations.items(), start=1):
        if language == "en":
            text = f"📦 New stock is available!\n🛍 {product['name']}\n✅ New quantity: {added}"
        elif language == "km":
            text = f"📦 មានស្តុកថ្មីហើយ!\n🛍 {product['name']}\n✅ ចំនួនថ្មី៖ {added}"
        else:
            text = (
                f"📦 មានស្តុកថ្មី / New stock is available\n"
                f"🛍 {product['name']}\n✅ ចំនួនថ្មី / New quantity: {added}"
            )
        try:
            await bot.send_message(chat_id, text, reply_markup=keyboard_markup)
            sent += 1
        except Exception:
            failed += 1
            logger.debug("Could not send stock notification to %s", chat_id, exc_info=True)
        if index % 20 == 0:
            await asyncio.sleep(1)
    logger.info(
        "Stock notification for product %s: sent to %s chats, failed for %s",
        product_id,
        sent,
        failed,
    )


async def send_welcome(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    if not user:
        return
    language = await safe_user_language(store, user.id)
    await safe_upsert_user(store, user.id, user.username, user.first_name, language)
    try:
        categories = await store.categories()
    except Exception:
        logger.exception("Could not load categories for user %s", user.id)
        categories = []
    previous_message_id = welcome_message_ids.get(user.id)
    if previous_message_id:
        try:
            await message.bot.delete_message(chat_id=user.id, message_id=previous_message_id)
        except TelegramBadRequest:
            logger.debug("Could not delete previous welcome message %s", previous_message_id)
    welcome_message = await message.answer(
        welcome_text(user, language, categories),
        parse_mode="HTML",
        reply_markup=menu(settings, user.id, language),
    )
    welcome_message_ids[user.id] = welcome_message.message_id


async def deliver_order(bot: Bot, store: Store, settings: Settings, order_id: str, chat_id: int) -> None:
    await delete_payment_message(bot, store, order_id)
    credentials = await store.fulfill_order(order_id)
    if not credentials:
        return
    details = "\n".join(f"<code>{html.escape(decrypt_stock(value, settings.stock_encryption_key))}</code>" for value in credentials)
    language = await safe_user_language(store, chat_id)
    await bot.send_message(
        chat_id,
        copy(language, f"✅ បានបញ្ជាក់ការទូទាត់។ ទិន្នន័យរបស់អ្នក៖\n\n{details}", f"✅ Payment confirmed. Your delivery:\n\n{details}"),
        parse_mode="HTML",
    )
    await store.mark_delivered(order_id)


async def delete_payment_message(bot: Bot, store: Store, order_id: str) -> None:
    payment_message = await store.payment_message(order_id)
    if not payment_message or not payment_message.get("message_id"):
        return
    try:
        await bot.delete_message(
            chat_id=int(payment_message["chat_id"]),
            message_id=int(payment_message["message_id"]),
        )
    except TelegramBadRequest as exc:
        if "message to delete not found" not in str(exc).lower():
            raise
    await store.clear_payment_message(order_id)


async def track_payment_message(bot: Bot, store: Store, order_id: str, message_id: int) -> None:
    payment_status = await store.set_payment_message(order_id, message_id)
    if payment_status != "pending":
        await delete_payment_message(bot, store, order_id)


def register_handlers(
    dispatcher: Dispatcher,
    bot: Bot,
    store: Store,
    payments: KHPayClient,
    settings: Settings,
) -> None:
    @router.message(CommandStart())
    async def start(message: Message) -> None:
        await send_welcome(message, store, settings)

    @router.callback_query(F.data == "home")
    async def home(callback: CallbackQuery) -> None:
        await callback.answer()
        language = await safe_user_language(store, callback.from_user.id)
        categories = await store.categories()
        welcome_message = await edit_text_message(
            callback.message,
            welcome_text(callback.from_user, language, categories),
            parse_mode="HTML",
            reply_markup=menu(settings, callback.from_user.id, language),
        )
        welcome_message_ids[callback.from_user.id] = welcome_message.message_id

    @router.callback_query(F.data == "language")
    async def language_menu(callback: CallbackQuery) -> None:
        await callback.answer()
        language = await safe_user_language(store, callback.from_user.id)
        rows = [
            [InlineKeyboardButton(text="🇰🇭 ភាសាខ្មែរ", callback_data="lang:km")],
            [InlineKeyboardButton(text="🇺🇸 English", callback_data="lang:en")],
            back_button("home", language),
        ]
        await callback.message.edit_text(
            copy(language, "🌐 សូមជ្រើសរើសភាសា៖", "🌐 Choose your language:"),
            reply_markup=keyboard(rows),
        )

    @router.callback_query(F.data.startswith("lang:"))
    async def set_language(callback: CallbackQuery) -> None:
        language = callback.data[5:]
        if language not in {"km", "en"}:
            await callback.answer("Unsupported language", show_alert=True)
            return
        language_before_update = await safe_user_language(store, callback.from_user.id)
        await safe_upsert_user(
            store,
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.first_name,
            language_before_update,
        )
        try:
            await store.set_user_language(callback.from_user.id, language)
        except Exception:
            logger.exception("Could not save language preference for Telegram user %s", callback.from_user.id)
        await callback.answer()
        categories = await store.categories()
        await callback.message.edit_text(
            welcome_text(callback.from_user, language, categories),
            parse_mode="HTML",
            reply_markup=menu(settings, callback.from_user.id, language),
        )

    @router.callback_query(F.data.in_({"how_to_buy", "guide"}))
    async def buying_guide(callback: CallbackQuery) -> None:
        await callback.answer()
        language = await safe_user_language(store, callback.from_user.id)
        back_to_menu = keyboard(
            [[InlineKeyboardButton(text=copy(language, "⬅️ ត្រឡប់ទៅម៉ឺនុយ", "⬅️ Back to menu"), callback_data="home")]]
        )
        try:
            settings_data = await store.bot_settings(("how_to_buy_video_url", "how_to_buy_caption"))
        except Exception:
            logger.exception("Could not load tutorial settings")
            await edit_text_message(
                callback.message,
                copy(language, "មិនអាចទាញយកវីដេអូណែនាំបានទេ។", "Could not load the tutorial video."),
                reply_markup=back_to_menu,
            )
            return
        video = settings_data.get("how_to_buy_video_url")
        if not video:
            await edit_text_message(
                callback.message,
                copy(language, "មិនទាន់មានវីដេអូណែនាំទេ។", "The tutorial video is not configured yet."),
                reply_markup=back_to_menu,
            )
            return
        caption = settings_data.get("how_to_buy_caption", "").strip()[:1024]
        await callback.message.answer_video(
            video=video,
            caption=caption or None,
            reply_markup=back_to_menu,
        )
        await delete_replaced_message(callback.message)

    @router.callback_query(F.data == "shop")
    async def shop(callback: CallbackQuery) -> None:
        await callback.answer()
        language = await safe_user_language(store, callback.from_user.id)
        categories = await store.categories()
        if not categories:
            await callback.message.edit_text(
                copy(
                    language,
                    "បច្ចុប្បន្នមិនមានប្រភេទទំនិញទេ។ សូមពិនិត្យម្ដងទៀតពេលក្រោយ។",
                    "There are no product categories yet. Please check back later.",
                ),
                reply_markup=keyboard([back_button(language=language)]),
            )
            return
        rows = [
            [
                InlineKeyboardButton(
                    text=f"🛍 {item['name']}",
                    callback_data=f"c:{item['id']}",
                )
            ]
            for item in categories
        ]
        rows.append(back_button(language=language))
        text = copy(
            language,
            "🛍 <b>សូមជ្រើសរើសប្រភេទផលិតផល</b>\n"
            "───────────────────\n"
            "សូមជ្រើសរើស Catalog ណាមួយខាងក្រោមដើម្បីមើល Package ទំនិញ៖",
            "🛍 <b>Choose a product category</b>\n"
            "───────────────────\n"
            "Choose a catalog below to browse its packages:",
        )
        await edit_text_message(callback.message, text, parse_mode="HTML", reply_markup=keyboard(rows))

    @router.callback_query(F.data.startswith("c:"))
    async def category(callback: CallbackQuery) -> None:
        await callback.answer()
        language = await safe_user_language(store, callback.from_user.id)
        category_id = callback.data[2:]
        category_data = await store.category(category_id)
        if not category_data:
            await edit_text_message(
                callback.message,
                copy(language, "ប្រភេទផលិតផលនេះមិនមានទៀតទេ។", "This category is no longer available."),
                reply_markup=keyboard([back_button("shop", language)]),
            )
            return
        products = await store.products(category_id)
        if not products:
            await edit_text_message(
                callback.message,
                f"🛍 <b>{html.escape(category_data['name'])}</b>\n"
                "───────────────────\n"
                + copy(language, "ប្រភេទនេះមិនទាន់មាន Package ទេ។", "There are no packages in this category yet."),
                parse_mode="HTML",
                reply_markup=keyboard([back_button("shop", language)]),
            )
            return
        stock_counts = await asyncio.gather(*(store.available_stock(item["id"]) for item in products))
        rows = []
        for item, stock in zip(products, stock_counts):
            stock_label = str(stock) if stock else copy(language, "អស់ស្តុក", "Out")
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"📦 {item['name']} • {money(item['price'])} ({stock_label})",
                        callback_data=f"p:{item['id']}",
                    )
                ]
            )
        rows.append(back_button("shop", language))
        description = (category_data.get("description") or "").strip()
        intro = html.escape(description) if description else ""
        text = copy(
            language,
            f"🛍 <b>{html.escape(category_data['name'])}</b>\n"
            "───────────────────\n"
            f"{intro + chr(10) if intro else ''}សូមជ្រើសរើស Package ខាងក្រោម៖",
            f"🛍 <b>{html.escape(category_data['name'])}</b>\n"
            "───────────────────\n"
            f"{intro + chr(10) if intro else ''}Choose a package below:",
        )
        await edit_text_message(callback.message, text, parse_mode="HTML", reply_markup=keyboard(rows))

    @router.callback_query(F.data.startswith("p:"))
    async def product(callback: CallbackQuery) -> None:
        await callback.answer()
        language = await safe_user_language(store, callback.from_user.id)
        product_data = await store.product(callback.data[2:])
        if not product_data:
            await callback.message.edit_text(
                copy(language, "ផលិតផលនេះមិនមានទៀតទេ។", "This product is no longer available."),
                reply_markup=keyboard([back_button("shop", language)]),
            )
            return
        await show_product(callback.message, product_data, 1, language)

    async def show_product(message: Message, product_data: dict[str, Any], quantity: int, language: str) -> None:
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
                    InlineKeyboardButton(
                        text=f"{copy(language, 'ចំនួន', 'Qty')}: {quantity}",
                        callback_data="noop",
                    ),
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
            rows.append([InlineKeyboardButton(text=copy(language, "អស់ស្តុក", "Out of stock"), callback_data="noop")])
        rows.append(back_button(f"c:{product_data['category_id']}", language))
        category_title = f"🛍 {html.escape(category_data['name'])}\n" if category_data else ""
        description = description_preview(product_data.get("description") or "", language)
        text = (
            f"{category_title}"
            f"🛒 <b>{copy(language, 'បញ្ជាក់ការបញ្ជាទិញ', 'Order details')}</b>\n"
            "───────────────────\n"
            f"• {copy(language, 'ផលិតផល', 'Product')}: {html.escape(product_data['name'])}\n"
            f"• {copy(language, 'តម្លៃឯកតា', 'Unit price')}: {money(product_data['price'])}\n"
            f"• {copy(language, 'ស្តុកមាន', 'Available stock')}: {stock}\n\n"
            f"<b>{copy(language, 'ព័ត៌មានលម្អិត', 'Product details')}</b>\n"
            f"{description}\n"
            "───────────────────"
        )
        markup = keyboard(rows)
        image_url = product_data.get("image_url")
        if image_url:
            if message.photo:
                await message.edit_media(
                    media=InputMediaPhoto(media=image_url, caption=text, parse_mode="HTML"),
                    reply_markup=markup,
                )
            else:
                await message.answer_photo(
                    photo=image_url,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
                try:
                    await message.delete()
                except TelegramBadRequest:
                    logger.debug("Could not delete previous product message %s", message.message_id)
        elif message.photo:
            await message.edit_caption(caption=text, parse_mode="HTML", reply_markup=markup)
        else:
            await message.edit_text(text, parse_mode="HTML", reply_markup=markup)

    @router.callback_query(F.data.startswith("qty:"))
    async def change_quantity(callback: CallbackQuery) -> None:
        await callback.answer()
        language = await safe_user_language(store, callback.from_user.id)
        _, product_id, quantity_text = callback.data.split(":")
        product_data = await store.product(product_id)
        if not product_data:
            await callback.message.edit_text(
                copy(language, "ផលិតផលនេះមិនមានទៀតទេ។", "This product is no longer available."),
                reply_markup=keyboard([back_button("shop", language)]),
            )
            return
        await show_product(callback.message, product_data, int(quantity_text), language)

    @router.callback_query(F.data == "noop")
    async def no_action(callback: CallbackQuery) -> None:
        await callback.answer()

    @router.callback_query(F.data.startswith("b:"))
    async def buy(callback: CallbackQuery) -> None:
        language = await safe_user_language(store, callback.from_user.id)
        await callback.answer(copy(language, "កំពុងបង្កើតការទូទាត់...", "Creating payment..."))
        _, product_id, quantity_text = callback.data.split(":")
        order = None
        try:
            product_data = await store.product(product_id)
            if not product_data:
                raise RuntimeError("Product is no longer available")
            order = await store.reserve_order(callback.from_user.id, product_id, int(quantity_text))
            payment = await payments.create_payment(
                str(order["total"]),
                str(order["id"]),
                callback.from_user.id,
            )
            aba_deeplink = aba_mobile_deeplink(payment["qr_string"])
            open_url = aba_mobile_redirect_url(settings.app_base_url or "", str(order["id"]))
            await store.set_payment(order["id"], payment["transaction_id"], aba_deeplink)
        except Exception:
            logger.exception("Could not create checkout for Telegram user %s", callback.from_user.id)
            if order:
                await store.release_order(str(order["id"]))
            await edit_text_message(
                callback.message,
                copy(language, "មិនអាចបង្កើតការទូទាត់បានទេ។ សូមព្យាយាមម្ដងទៀត។", "Could not create payment. Please try again."),
                reply_markup=menu(settings, callback.from_user.id, language),
            )
            return
        caption = payment_caption(
            str(product_data["name"]),
            int(quantity_text),
            order["total"],
            str(payment["transaction_id"]),
        )
        payment_message = await bot.send_photo(
            callback.from_user.id,
            payment_qr(payment),
            caption=caption,
            parse_mode="HTML",
            reply_markup=payment_keyboard(str(order["id"]), open_url),
        )
        await delete_replaced_message(callback.message)
        await track_payment_message(bot, store, order["id"], payment_message.message_id)

    @router.callback_query(F.data.startswith("cancel:"))
    async def cancel_order(callback: CallbackQuery) -> None:
        await callback.answer()
        order_id = callback.data[7:]
        result = await (
            store.client.table("orders")
            .select("status,transaction_id")
            .eq("id", order_id)
            .eq("chat_id", callback.from_user.id)
            .maybe_single()
            .execute()
        )
        data = result.data
        language = await safe_user_language(store, callback.from_user.id)
        if not data:
            await callback.message.answer(copy(language, "រកមិនឃើញការបញ្ជាទិញទេ។", "Order not found."))
            return
        if data["status"] != "pending":
            await callback.message.answer(
                copy(language, "ការបញ្ជាទិញនេះមិនអាចលុបចោលបានទេ។", "This order can no longer be cancelled.")
            )
            return
        if data.get("transaction_id"):
            try:
                payment_status = (await payments.check_payment(data["transaction_id"])).get("status")
            except Exception:
                logger.exception("Could not verify payment before cancellation for order %s", order_id)
                await callback.message.answer(
                    copy(language, "មិនអាចផ្ទៀងផ្ទាត់ការទូទាត់បានទេ។ សូមសាកល្បងម្ដងទៀត។", "Could not verify payment. Please try again.")
                )
                return
            if payment_status == "paid":
                await deliver_order(bot, store, settings, order_id, callback.from_user.id)
                return
        await delete_payment_message(bot, store, order_id)
        await store.release_order(order_id)
        await callback.message.answer(
            copy(language, "បានលុបចោលការបញ្ជាទិញ។", "Order cancelled."),
            reply_markup=keyboard([back_button("home", language)]),
        )

    @router.callback_query(F.data.startswith("check_payment_"))
    async def check_order(callback: CallbackQuery) -> None:
        language = await safe_user_language(store, callback.from_user.id)
        await callback.answer(copy(language, "កំពុងពិនិត្យការទូទាត់…", "Checking payment…"))
        order_id = callback.data.removeprefix("check_payment_")
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
                await callback.message.answer(copy(language, "រកមិនឃើញការបញ្ជាទិញទេ។", "Order not found."))
                return
            if data["status"] == "paid":
                await deliver_order(bot, store, settings, order_id, callback.from_user.id)
                return
            if data["status"] != "pending":
                await callback.message.answer(
                    copy(language, "ការបញ្ជាទិញនេះមិនសកម្មទៀតទេ។", "This order is no longer active.")
                )
                return
            payment = await payments.check_payment(data["transaction_id"])
            status = payment.get("status")
            if status == "paid":
                await deliver_order(bot, store, settings, order_id, callback.from_user.id)
            elif status in {"expired", "failed"}:
                await delete_payment_message(bot, store, order_id)
                await store.release_order(order_id, status)
                await callback.message.answer(
                    copy(language, "ការទូទាត់នេះផុតកំណត់ ឬបរាជ័យ។ សូមបញ្ជាទិញម្ដងទៀត។", "Payment expired or failed. Please order again."),
                    reply_markup=menu(settings, callback.from_user.id, language),
                )
            else:
                await callback.message.answer(
                    copy(language, "មិនទាន់ទទួលបានការទូទាត់ទេ។ សូមបញ្ចប់ការទូទាត់តាម KHPAY។", "Payment has not arrived yet. Please complete payment with KHPAY.")
                )
        except Exception:
            logger.exception("Payment check failed for order %s", order_id)
            await callback.message.answer(
                copy(language, "មិនអាចពិនិត្យការទូទាត់បានទេ។ សូមព្យាយាមម្ដងទៀតបន្តិចក្រោយ។", "Could not check payment. Please try again shortly.")
            )

    @router.callback_query(F.data == "history")
    async def history(callback: CallbackQuery) -> None:
        await callback.answer()
        language = await safe_user_language(store, callback.from_user.id)
        orders = await store.order_history(callback.from_user.id)
        if not orders:
            text = copy(language, "អ្នកមិនទាន់មានការបញ្ជាទិញទេ។", "You have no orders yet.")
        else:
            status_labels = {
                "pending": copy(language, "កំពុងរង់ចាំ", "Pending"),
                "paid": copy(language, "បានទូទាត់", "Paid"),
                "expired": copy(language, "ផុតកំណត់", "Expired"),
                "failed": copy(language, "បរាជ័យ", "Failed"),
                "cancelled": copy(language, "បានលុបចោល", "Cancelled"),
            }
            text = copy(language, "ការបញ្ជាទិញថ្មីៗ៖\n", "Recent orders:\n") + "\n".join(
                f"• {item['id'][:8]} · {money(item['total'])} · {status_labels.get(item['status'], item['status'])}"
                for item in orders
            )
        await callback.message.edit_text(text, reply_markup=keyboard([back_button(language=language)]))

    @router.callback_query(F.data == "support")
    async def support(callback: CallbackQuery) -> None:
        await callback.answer()
        language = await safe_user_language(store, callback.from_user.id)
        if settings.support_username:
            rows = [
                [
                    InlineKeyboardButton(
                        text=copy(language, "បើកការជជែកជាមួយជំនួយ", "Chat with support"),
                        url=f"https://t.me/{settings.support_username.lstrip('@')}",
                    )
                ],
                back_button(language=language),
            ]
            await callback.message.edit_text(
                copy(language, "សូមទាក់ទងក្រុមជំនួយ៖", "Contact support:"),
                reply_markup=keyboard(rows),
            )
        else:
            await callback.message.edit_text(
                copy(language, "សូមទាក់ទងអ្នកគ្រប់គ្រងហាង។", "Please contact the store administrator."),
                reply_markup=keyboard([back_button(language=language)]),
            )

    @router.callback_query(F.data == "admin")
    async def admin(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            await callback.message.edit_text("អ្នកមិនមានសិទ្ធិប្រើប្រាស់ទេ។", reply_markup=keyboard([back_button()]))
            return
        result = await store.client.table("products").select("id,name").eq("active", True).order("sort_order").execute()
        products = result.data or []
        stock_counts = await asyncio.gather(*(store.available_stock(item["id"]) for item in products))
        lines = [
            f"• {html.escape(item['name'])}: {stock} នៅសល់"
            for item, stock in zip(products, stock_counts)
        ]
        total_stock = sum(stock_counts)
        rows = [
            [InlineKeyboardButton(text="🗂 គ្រប់គ្រង Catalog និង Package", callback_data="admin:catalogs")],
            [InlineKeyboardButton(text="📥 បញ្ចូលស្តុក (.txt)", callback_data="admin:upload")],
            [InlineKeyboardButton(text="📊 ស្ថិតិការលក់", callback_data="admin:sales")],
            back_button(),
        ]
        await callback.message.edit_text(
            "⚙️ <b>ផ្ទាំងគ្រប់គ្រងហាង</b>\n"
            f"📦 <b>ស្តុកដែលអាចលក់បាន៖ {total_stock}</b>\n"
            + ("\n".join(lines) or "មិនមាន Package សកម្មទេ។"),
            parse_mode="HTML",
            reply_markup=keyboard(rows),
        )

    @router.callback_query(F.data == "admin:catalogs")
    async def admin_catalogs(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            return
        result = await store.client.table("categories").select("id,name").eq("active", True).order("sort_order").execute()
        categories = result.data or []
        rows = [
            [InlineKeyboardButton(text=f"🛍 {item['name']}", callback_data=f"ac:{item['id']}")]
            for item in categories
        ]
        rows.extend(
            [
                [InlineKeyboardButton(text="➕ បន្ថែម Catalog", callback_data="admin:category-add")],
                back_button("admin"),
            ]
        )
        await callback.message.edit_text(
            f"🗂 <b>គ្រប់គ្រង Catalog ({len(categories)})</b>\n"
            + (
                "ជ្រើសរើស Catalog ដើម្បីមើល Package និងសកម្មភាព៖"
                if categories
                else "មិនទាន់មាន Catalog ទេ។ ចុចបន្ថែម Catalog ដើម្បីចាប់ផ្តើម។"
            ),
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
        products = result.data or []
        stock_counts = await asyncio.gather(*(store.available_stock(item["id"]) for item in products))
        rows = [
            [
                InlineKeyboardButton(
                    text=f"📦 {item['name'][:40]} · {stock} នៅសល់",
                    callback_data=f"ap:{item['id']}",
                )
            ]
            for item, stock in zip(products, stock_counts)
        ]
        rows.extend(admin_category_actions(category_id))
        product_summary = (
            f"📦 Package សកម្ម៖ {len(products)}"
            if products
            else "មិនទាន់មាន Package ទេ។ ចុចបន្ថែម Package ដើម្បីចាប់ផ្តើម។"
        )
        await callback.message.edit_text(
            f"🗂 <b>{html.escape(category_data['name'])}</b>\n"
            f"{html.escape(category_data.get('description') or '')}\n\n{product_summary}",
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
        rows = admin_product_actions(product_data["id"], product_data["category_id"])
        await callback.message.edit_text(
            f"📦 <b>{html.escape(product_data['name'])}</b>\n"
            f"ID: <code>{html.escape(product_data['id'])}</code>\n"
            f"តម្លៃ៖ {money(product_data['price'])}\n"
            f"ស្តុកនៅសល់៖ {stock}\n\n"
            f"{html.escape(product_data.get('description') or '')}",
            parse_mode="HTML",
            reply_markup=keyboard(rows),
        )

    @router.message(F.photo, F.caption.startswith("setphoto"))
    async def set_product_photo(message: Message) -> None:
        if not message.from_user or message.from_user.id not in settings.admin_ids:
            return
        parts = (message.caption or "").strip().split(maxsplit=1)
        if not parts or parts[0] != "setphoto" or len(parts) != 2 or not parts[1].strip():
            await message.answer("ទម្រង់មិនត្រឹមត្រូវ។ សូមប្រើ setphoto <product_id> ជាមួយរូបភាព។")
            return
        product_id = parts[1].strip()
        try:
            image_url = await upload_product_image(bot, settings, message.photo[-1].file_id)
            updated = await store.update_product_image(product_id, image_url)
        except Exception:
            logger.exception("Could not update product image %s", product_id)
            await message.answer("មិនអាចធ្វើបច្ចុប្បន្នភាពរូបភាព Package បានទេ។")
            return
        if not updated:
            await message.answer(f"រកមិនឃើញ Package ID {html.escape(product_id)} ទេ។")
            return
        await message.answer(
            f"✅ បាន Upload រូបភាពទៅ Cloudinary និងបច្ចុប្បន្នភាព Package ID <code>{html.escape(product_id)}</code> ជោគជ័យ!",
            parse_mode="HTML",
        )

    @router.message(F.photo, F.caption.contains("|"))
    async def create_product_with_photo(message: Message) -> None:
        if not message.from_user or message.from_user.id not in settings.admin_ids:
            return
        pending = pending_admin_input.get(message.from_user.id)
        if not pending or pending[0] != "product_add" or not pending[1]:
            await message.answer("សូមជ្រើសរើស Catalog និង Package ថ្មីក្នុងម៉ឺនុយគ្រប់គ្រងជាមុនសិន។")
            return
        try:
            name, price, description = parse_product_caption(message.caption or "")
            image_url = await upload_product_image(bot, settings, message.photo[-1].file_id)
            product_id = await store.create_product(pending[1], name, price, description, image_url)
        except (InvalidOperation, ValueError) as exc:
            await message.answer(html.escape(str(exc)))
            return
        except Exception:
            logger.exception("Could not create package with photo for admin %s", message.from_user.id)
            await message.answer("មិនអាចបង្កើត Package បានទេ។ សូមពិនិត្យ Cloudinary និង Supabase រួចព្យាយាមម្ដងទៀត។")
            return
        pending_admin_input.pop(message.from_user.id, None)
        await message.answer(
            f'✅ បានបង្កើត Package "{html.escape(name)}" និង Upload រូបភាពទៅ Cloudinary រួចរាល់! '
            f"(ID: <code>{html.escape(product_id)}</code>)",
            parse_mode="HTML",
        )

    @router.callback_query(F.data.startswith("admin:product-add:"))
    async def add_product_prompt(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            return
        category_id = callback.data.removeprefix("admin:product-add:")
        pending_admin_input[callback.from_user.id] = ("product_add", category_id)
        await callback.message.edit_text(
            "ផ្ញើរូបភាពជាមួយ Caption <code>ឈ្មោះ | តម្លៃ | ព័ត៌មានលម្អិត</code> ដើម្បីបង្កើត Package ថ្មី។",
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
        pending = pending_admin_input.pop(callback.from_user.id, None)
        await callback.answer("បានបោះបង់")
        target = f"ap:{pending[1]}" if pending and pending[0] in {"stock_add", "stock_remove"} else "admin:catalogs"
        await callback.message.edit_text("បានបោះបង់។", reply_markup=keyboard([back_button(target)]))

    @router.callback_query(F.data.startswith("admin:stock-add:"))
    async def add_stock_prompt(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            return
        product_id = callback.data.removeprefix("admin:stock-add:")
        pending_admin_input[callback.from_user.id] = ("stock_add", product_id)
        await callback.message.answer(
            "ផ្ញើ Code ឬ username:password មួយក្នុងមួយបន្ទាត់ (អាចបញ្ចូល 1 ឬច្រើន)៖",
            reply_markup=keyboard([back_button("admin:cancel-input")]),
        )

    @router.callback_query(F.data.startswith("admin:stock-remove:"))
    async def remove_stock_prompt(callback: CallbackQuery) -> None:
        await callback.answer()
        if callback.from_user.id not in settings.admin_ids:
            return
        product_id = callback.data.removeprefix("admin:stock-remove:")
        pending_admin_input[callback.from_user.id] = ("stock_remove", product_id)
        await callback.message.answer(
            "ផ្ញើ Code ឬ username:password ដែលចង់ដក មួយក្នុងមួយបន្ទាត់។ ត្រូវផ្គូផ្គងនឹងទិន្នន័យដើម ហើយដកបានតែស្តុកដែលមិនទាន់កក់ ឬលក់៖",
            reply_markup=keyboard([back_button("admin:cancel-input")]),
        )

    @router.message(F.text)
    async def receive_admin_input(message: Message) -> None:
        if not message.from_user:
            return
        text = (message.text or "").strip()
        if text.startswith("/"):
            return
        if message.from_user.id in settings.admin_ids:
            try:
                stock_add = parse_stock_add(text)
                if stock_add:
                    product_id, credentials = stock_add
                    added = await store.import_stock(product_id, credentials, settings.stock_encryption_key)
                    await notify_stock_added(bot, store, settings.stock_notification_chat_ids, product_id, added)
                    await message.answer(f"បានបញ្ចូលស្តុកថ្មីចំនួន {added}។")
                    return
            except ValueError as exc:
                await message.answer(html.escape(str(exc)))
                return
            except Exception:
                logger.exception("Direct stock import failed for admin %s", message.from_user.id)
                await message.answer("មិនអាចបញ្ចូលស្តុកបានទេ។ សូមពិនិត្យ Product ID រួចព្យាយាមម្ដងទៀត។")
                return
        pending = (
            pending_admin_input.get(message.from_user.id)
            if message.from_user.id in settings.admin_ids
            else None
        )
        if not pending:
            return
        action, target_id = pending
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
            elif action == "product_add":
                raise ValueError("សូមផ្ញើរូបភាពជាមួយ Caption ដើម្បីបង្កើត Package ថ្មី។")
            elif action == "product_edit":
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
                await store.client.table("products").update(values).eq("id", target_id).execute()
            elif action == "stock_add":
                credentials = [line.strip() for line in text.splitlines() if line.strip()]
                if not credentials:
                    raise ValueError("សូមបញ្ចូល Code ឬ username:password យ៉ាងហោចណាស់មួយ។")
                added = await store.import_stock(target_id, credentials, settings.stock_encryption_key)
                await notify_stock_added(bot, store, settings.stock_notification_chat_ids, target_id, added)
            elif action == "stock_remove":
                credentials = [line.strip() for line in text.splitlines() if line.strip()]
                if not credentials:
                    raise ValueError("សូមបញ្ចូល Code ឬ username:password យ៉ាងហោចណាស់មួយ។")
                removed = await store.remove_stock(target_id, credentials, settings.stock_encryption_key)
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
        if action in {"stock_add", "stock_remove"}:
            if action == "stock_add":
                result_message = f"បានបញ្ចូលស្តុកថ្មីចំនួន {added}។"
            else:
                result_message = f"បានដកស្តុកដែលមិនទាន់លក់ចំនួន {removed}។"
            await message.answer(
                result_message,
                reply_markup=keyboard([back_button(f"ap:{target_id}")]),
            )
            return
        if action == "category_edit":
            target = f"ac:{target_id}"
        elif action == "product_edit":
            target = f"ap:{target_id}"
        elif action == "product_add":
            target = f"ac:{target_id}"
        else:
            target = "admin:catalogs"
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
        await notify_stock_added(bot, store, settings.stock_notification_chat_ids, product_id, added)
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
                        await delete_payment_message(bot, store, order["id"])
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
