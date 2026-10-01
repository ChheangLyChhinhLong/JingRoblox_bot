from types import SimpleNamespace

from app.bot import category_icon, quantity_limit, welcome_text


def test_welcome_text_escapes_profile_data_and_handles_missing_username():
    user = SimpleNamespace(id=12345, first_name="<Jing>", username=None)

    text = welcome_text(user)

    assert "&lt;Jing&gt;" in text
    assert "<code>12345</code>" in text
    assert "@" not in text
    assert "មិនមាន" in text


def test_category_icons_match_catalog_names():
    assert category_icon("Roblox Gift Cards") == "💎"
    assert category_icon("Gamepass Gift") == "🎮"
    assert category_icon("Premium Accounts & Tools") == "⚡️"
    assert category_icon("Other") == "🛍"


def test_quantity_limit_matches_available_stock_and_order_cap():
    assert quantity_limit(0) == 0
    assert quantity_limit(1) == 1
    assert quantity_limit(2) == 2
    assert quantity_limit(8) == 3