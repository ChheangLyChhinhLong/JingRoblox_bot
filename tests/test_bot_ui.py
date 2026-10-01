import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.bot import (
    deliver_order,
    description_preview,
    menu,
    payment_keyboard,
    parse_product_caption,
    parse_stock_add,
    quantity_limit,
    safe_user_language,
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


def test_khqr_payment_keyboard_has_only_aba_and_check_buttons():
    markup = payment_keyboard(
        "order-123",
        "abamobilebank://ababank.com?type=payway&qrcode=encoded",
        "km",
    )

    assert len(markup.inline_keyboard) == 2
    assert markup.inline_keyboard[0][0].text == "🔗 បើក ABA Mobile"
    assert markup.inline_keyboard[0][0].url == "https://shop.example.com/aba/order-123"
    assert markup.inline_keyboard[1][0].callback_data == "q:order-123"


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