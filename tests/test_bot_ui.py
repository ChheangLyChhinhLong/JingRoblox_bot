import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.bot import (
    admin_category_actions,
    admin_product_actions,
    deliver_order,
    description_preview,
    edit_text_message,
    menu,
    notify_stock_added,
    payment_caption,
    payment_keyboard,
    parse_product_caption,
    parse_stock_add,
    quantity_limit,
    safe_user_language,
    send_welcome,
    track_payment_message,
    upload_product_image,
    welcome_text,
)
from app.security import encrypt_stock, stock_fingerprint
from app.store import Store


def test_welcome_text_escapes_profile_data_and_handles_missing_username():
    user = SimpleNamespace(id=12345, first_name="<Jing>", username=None)

    text = welcome_text(user)

    assert "&lt;Jing&gt;" in text
    assert "<code>12345</code>" in text
    assert "@" not in text
    assert "មិនមាន" in text


def test_english_welcome_shows_account_details():
    user = SimpleNamespace(id=12345, first_name="Jing", username="jing")

    text = welcome_text(user, "en")

    assert "Welcome, Jing" in text
    assert "<code>12345</code>" in text
    assert "@jing" in text


def test_start_welcome_sends_menu_and_saves_profile():
    async def run_test():
        user = SimpleNamespace(id=12345, first_name="Jing", username="jing")
        message = SimpleNamespace(from_user=user, answer=AsyncMock())
        store = SimpleNamespace(
            user_language=AsyncMock(return_value="km"),
            upsert_user=AsyncMock(),
            categories=AsyncMock(return_value=[{"name": "Catalog", "description": ""}]),
        )
        settings = SimpleNamespace(admin_ids=set())

        await send_welcome(message, store, settings)

        store.upsert_user.assert_awaited_once_with(12345, "jing", "Jing", "km")
        message.answer.assert_awaited_once()
        sent_text = message.answer.call_args.args[0]
        sent_markup = message.answer.call_args.kwargs["reply_markup"]
        assert "សូមស្វាគមន៍ Jing" in sent_text
        assert sent_markup.inline_keyboard[0][0].callback_data == "shop"

    asyncio.run(run_test())


def test_welcome_lists_database_categories():
    user = SimpleNamespace(id=12345, first_name="Jing", username="jing")

    text = welcome_text(
        user,
        categories=[
            {"name": "Gift Cards", "description": "Instant delivery"},
            {"name": "VPN & Tools", "description": "Secure access"},
        ],
    )

    assert "Gift Cards</b> (Instant delivery)" in text
    assert "VPN &amp; Tools</b> (Secure access)" in text
    assert "├─ 🛍" in text
    assert "└─ 🛍" in text


def test_quantity_limit_matches_available_stock_and_order_cap():
    assert quantity_limit(0) == 0
    assert quantity_limit(1) == 1
    assert quantity_limit(2) == 2
    assert quantity_limit(8) == 3


def test_product_description_is_limited_to_three_lines():
    preview = description_preview("First\nSecond\nThird\nFourth", "en")

    assert preview.splitlines() == ["First", "Second", "Third", "• ..."]


def test_parse_package_photo_caption():
    assert parse_product_caption("សាកល្បង | 0.01 | ស្ដុកសាកល្បង") == (
        "សាកល្បង",
        "0.01",
        "ស្ដុកសាកល្បង",
    )


def test_parse_stock_add_accepts_comma_and_newline_separated_codes():
    assert parse_stock_add("addstock product-123 | code1, code2\ncode3") == (
        "product-123",
        ["code1", "code2", "code3"],
    )


def test_parse_stock_add_ignores_other_text_and_rejects_missing_credentials():
    assert parse_stock_add("hello there") is None
    assert parse_stock_add("/addstock product-123 | code1") is None
    try:
        parse_stock_add("addstock product-123 |  ")
    except ValueError as exc:
        assert "Code" in str(exc)
    else:
        raise AssertionError("Expected empty stock data to be rejected")


def test_menu_uses_dynamic_tutorial_callback_and_groups_language_support():
    markup = menu(SimpleNamespace(admin_ids=set()), 12345, "en")

    assert markup.inline_keyboard[2][0].callback_data == "how_to_buy"
    assert [button.callback_data for button in markup.inline_keyboard[3]] == ["language", "support"]


def test_edit_text_message_replaces_photo_with_text_message():
    async def run_test():
        message = SimpleNamespace(
            photo=[object()],
            message_id=456,
            delete=AsyncMock(),
            answer=AsyncMock(),
            edit_text=AsyncMock(),
        )

        await edit_text_message(message, "Choose a package", parse_mode="HTML")

        message.delete.assert_awaited_once_with()
        message.answer.assert_awaited_once_with("Choose a package", parse_mode="HTML", reply_markup=None)
        message.edit_text.assert_not_awaited()

    asyncio.run(run_test())


def test_admin_category_actions_group_catalog_controls_after_package_creation():
    rows = admin_category_actions("category-123")

    assert [[button.callback_data for button in row] for row in rows] == [
        ["admin:product-add:category-123"],
        ["admin:category-edit:category-123", "admin:category-disable:category-123"],
        ["admin:catalogs"],
    ]


def test_admin_package_actions_group_editing_and_stock_controls():
    rows = admin_product_actions("product-123", "category-123")

    assert [[button.callback_data for button in row] for row in rows] == [
        ["admin:product-edit:product-123", "admin:product-disable:product-123"],
        ["admin:stock-add:product-123", "admin:stock-remove:product-123"],
        ["au:product-123"],
        ["ac:category-123"],
    ]


def test_khqr_payment_keyboard_has_only_aba_and_check_buttons():
    open_url = "https://shop.example.com/aba/order-123"
    markup = payment_keyboard("order-123", open_url)

    assert len(markup.inline_keyboard) == 2
    assert markup.inline_keyboard[0][0].text == "🏦 បើកក្នុង ABA Mobile"
    assert markup.inline_keyboard[0][0].url == open_url
    assert markup.inline_keyboard[1][0].text == "✅ ខ្ញុំបានទូទាត់ · ពិនិត្យ"
    assert markup.inline_keyboard[1][0].callback_data == "check_payment_order-123"


def test_payment_caption_matches_requested_html_layout_and_escapes_data():
    caption = payment_caption("Gold <Package>", 2, "10.5", "txn-123")

    assert caption == (
        "💳 <b>Pay $10.50</b>\n\n"
        "🛍 <b>Product:</b> Gold &lt;Package&gt; x2\n"
        "💰 <b>Total:</b> $10.50\n"
        "🟢 <b>Remaining to pay:</b> $10.50\n"
        "🏷 <b>Ref:</b> <code>txn-123</code>\n"
        "⏱ <b>Scan KHQR to complete payment.</b>\n"
        "⏰ <b>You have 15 minutes to pay. The QR refreshes itself.</b>"
    )


def test_terminal_payment_status_deletes_qr_after_message_is_saved():
    async def run_test():
        for status in ("paid", "expired", "failed", "cancelled"):
            bot = SimpleNamespace(delete_message=AsyncMock())
            store = SimpleNamespace(
                set_payment_message=AsyncMock(return_value=status),
                payment_message=AsyncMock(return_value={"chat_id": 123, "message_id": 456}),
                clear_payment_message=AsyncMock(),
            )

            await track_payment_message(bot, store, "order-123", 456)

            bot.delete_message.assert_awaited_once_with(chat_id=123, message_id=456)
            store.clear_payment_message.assert_awaited_once_with("order-123")

    asyncio.run(run_test())


def test_product_image_update_targets_product_and_stores_cloudinary_url():
    async def run_test():
        product_id = "product-123"
        image_url = "https://res.cloudinary.com/example/image/upload/product.png"
        query = Mock()
        query.update.return_value = query
        query.eq.return_value = query
        query.select.return_value = query
        query.maybe_single.return_value = query
        query.execute = AsyncMock(return_value=SimpleNamespace(data={"id": product_id}))
        client = SimpleNamespace(table=Mock(return_value=query))

        updated = await Store(client).update_product_image(product_id, image_url)

        assert updated
        client.table.assert_called_once_with("products")
        query.update.assert_called_once_with({"image_url": image_url})
        query.eq.assert_called_once_with("id", product_id)

    asyncio.run(run_test())


def test_product_creation_inserts_category_and_cloudinary_image_url():
    async def run_test():
        query = Mock()
        query.insert.return_value = query
        query.select.return_value = query
        query.execute = AsyncMock(return_value=SimpleNamespace(data=[{"id": "product-123"}]))
        client = SimpleNamespace(table=Mock(return_value=query))

        product_id = await Store(client).create_product(
            "category-123",
            "Test package",
            "0.01",
            "Description",
            "https://res.cloudinary.com/example/image/upload/test.png",
        )

        assert product_id == "product-123"
        query.insert.assert_called_once_with(
            {
                "category_id": "category-123",
                "name": "Test package",
                "price": "0.01",
                "description": "Description",
                "image_url": "https://res.cloudinary.com/example/image/upload/test.png",
            }
        )

    asyncio.run(run_test())


def test_stock_removal_matches_only_available_stock_for_the_selected_product():
    async def run_test():
        product_id = "product-123"
        credential = "user:password"
        key = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
        query = Mock()
        query.delete.return_value = query
        query.eq.return_value = query
        query.in_.return_value = query
        query.select.return_value = query
        query.execute = AsyncMock(return_value=SimpleNamespace(data=[{"id": "stock-1"}]))
        client = SimpleNamespace(table=Mock(return_value=query))

        removed = await Store(client).remove_stock(product_id, [credential], key)

        assert removed == 1
        client.table.assert_called_once_with("stock_items")
        query.eq.assert_any_call("product_id", product_id)
        query.eq.assert_any_call("status", "available")
        query.in_.assert_called_once_with(
            "credential_fingerprint",
            [stock_fingerprint(credential, key)],
        )

    asyncio.run(run_test())


def test_product_photo_downloads_and_uploads_to_cloudinary(monkeypatch):
    async def run_test():
        import app.bot as bot_module

        async def download_photo(file_id, destination):
            destination.write(b"photo-bytes")

        download = AsyncMock(side_effect=download_photo)
        telegram_bot = SimpleNamespace(download=download)
        settings = SimpleNamespace(
            cloudinary_cloud_name="cloud",
            cloudinary_api_key="key",
            cloudinary_api_secret="secret",
        )
        uploaded = Mock(return_value={"secure_url": "https://res.cloudinary.com/cloud/image/upload/item.png"})
        monkeypatch.setattr(bot_module.cloudinary.uploader, "upload", uploaded)

        image_url = await upload_product_image(telegram_bot, settings, "telegram-file-id")

        assert image_url == "https://res.cloudinary.com/cloud/image/upload/item.png"
        download.assert_awaited_once()
        assert uploaded.call_args.args[0].getvalue() == b"photo-bytes"
        assert uploaded.call_args.kwargs["resource_type"] == "image"
        assert uploaded.call_args.kwargs["cloud_name"] == "cloud"

    asyncio.run(run_test())


def test_delivery_deletes_payment_qr_before_fulfilling_and_sending_credentials():
    async def run_test():
        events = []
        key = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="

        async def delete_message(**kwargs):
            events.append("delete")

        async def clear_payment_message(order_id):
            events.append("clear")

        async def fulfill_order(order_id):
            events.append("fulfill")
            return [encrypt_stock("user:password", key)]

        async def send_message(*args, **kwargs):
            events.append("send")

        async def mark_delivered(order_id):
            events.append("mark")

        bot = SimpleNamespace(
            delete_message=AsyncMock(side_effect=delete_message),
            send_message=AsyncMock(side_effect=send_message),
        )
        store = SimpleNamespace(
            payment_message=AsyncMock(return_value={"chat_id": 123, "message_id": 456}),
            clear_payment_message=AsyncMock(side_effect=clear_payment_message),
            fulfill_order=AsyncMock(side_effect=fulfill_order),
            user_language=AsyncMock(return_value="en"),
            mark_delivered=AsyncMock(side_effect=mark_delivered),
        )
        settings = SimpleNamespace(stock_encryption_key=key)

        await deliver_order(bot, store, settings, "order-123", 123)

        assert events == ["delete", "clear", "fulfill", "send", "mark"]
        bot.delete_message.assert_awaited_once_with(chat_id=123, message_id=456)

    asyncio.run(run_test())


def test_user_language_falls_back_to_khmer_when_preferences_are_unavailable():
    store = SimpleNamespace(user_language=AsyncMock(side_effect=RuntimeError("users table missing")))

    language = asyncio.run(safe_user_language(store, 12345))

    assert language == "km"


def test_stock_notification_reaches_users_and_configured_chats_once():
    async def run_test():
        bot = SimpleNamespace(send_message=AsyncMock())
        store = SimpleNamespace(
            product=AsyncMock(return_value={"id": "product-123", "name": "Robux"}),
            stock_notification_users=AsyncMock(
                return_value=[
                    {"telegram_id": 12345, "language": "en"},
                    {"telegram_id": 23456, "language": "km"},
                ]
            ),
        )
        await notify_stock_added(bot, store, "-100987,@shopnews,-100987", "product-123", 4)

        assert [call.args[0] for call in bot.send_message.await_args_list] == [
            12345,
            23456,
            -100987,
            "@shopnews",
        ]
        assert "New quantity: 4" in bot.send_message.await_args_list[0].args[1]
        assert "ចំនួនថ្មី៖ 4" in bot.send_message.await_args_list[1].args[1]
        assert "New quantity: 4" in bot.send_message.await_args_list[2].args[1]
        assert bot.send_message.await_args_list[0].kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "p:product-123"

    asyncio.run(run_test())


def test_stock_notification_skips_duplicate_stock():
    async def run_test():
        bot = SimpleNamespace(send_message=AsyncMock())
        store = SimpleNamespace(
            product=AsyncMock(),
            stock_notification_users=AsyncMock(),
        )
        await notify_stock_added(bot, store, "@shopnews", "product-123", 0)

        store.product.assert_not_awaited()
        store.stock_notification_users.assert_not_awaited()
        bot.send_message.assert_not_awaited()

    asyncio.run(run_test())


def test_stock_notification_users_are_loaded_in_pages():
    async def run_test():
        first_page = [{"telegram_id": user_id, "language": "km"} for user_id in range(1000)]
        second_page = [{"telegram_id": 1000, "language": "en"}]
        query = Mock()
        query.select.return_value = query
        query.order.return_value = query
        query.range.return_value = query
        query.execute = AsyncMock(
            side_effect=[
                SimpleNamespace(data=first_page),
                SimpleNamespace(data=second_page),
            ]
        )
        client = SimpleNamespace(table=Mock(return_value=query))

        users = await Store(client).stock_notification_users()

        assert len(users) == 1001
        assert [call.args for call in query.range.call_args_list] == [(0, 999), (1000, 1999)]

    asyncio.run(run_test())