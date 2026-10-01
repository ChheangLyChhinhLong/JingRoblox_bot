from types import SimpleNamespace

from app.bot import description_preview, quantity_limit, welcome_text


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

    assert preview.splitlines() == ["First", "Second", "• ..."]