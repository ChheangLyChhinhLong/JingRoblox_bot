# Telegram digital-product shop

Button-driven Telegram storefront for digital accounts (`username:password`). It uses KHPAY hosted checkout, Supabase for catalog/orders/stock, Render for the running service, and `/health` for UptimeRobot.

## Setup

1. Create a Supabase project. Run [`schema.sql`](schema.sql) in its SQL editor.
2. Create a Telegram bot with BotFather and copy its token.
3. Copy `.env.example` to `.env` and fill in the Telegram, Supabase, and KHPAY settings. Never commit `.env` or expose the Supabase service-role key.
4. Generate the stock encryption key with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and save it as `STOCK_ENCRYPTION_KEY`. Keep this key backed up: stock credentials cannot be decrypted without it.
5. Install dependencies with `pip install -r requirements.txt` and start locally with `python -m app.main`.
6. In Supabase, insert categories and products. Copy a product UUID and import stock using `python -m scripts.import_stock PRODUCT_UUID stock.txt`. Each line in the file must be `username:password`. Set the same environment variables locally before running the importer.
7. In Render, create a Web Service from this repository. The included [`render.yaml`](render.yaml) sets the start command and `/health` check; add all `.env.example` secrets in the Render Environment tab.
8. After Render deploys, set `KHPAY_WEBHOOK_URL` to `https://YOUR-RENDER-SERVICE.onrender.com/webhook/khpay` in Render and redeploy. Add the same URL in KHPAY Dashboard → Settings → Webhooks, enable paid/failed/expired events, then copy the generated webhook secret into Render as `KHPAY_WEBHOOK_SECRET` and redeploy. The endpoint verifies the raw-body HMAC and confirms payment status and amount through KHPAY before delivery.
9. In UptimeRobot, create an HTTP(s) monitor for `https://YOUR-RENDER-SERVICE.onrender.com/health`, with a 5-minute interval.

## Store behavior

- Customers navigate categories, products, quantity, payment, order history, and support using inline buttons. Product listings show current available stock, and quantity selection is limited to available stock and three items per order.
- New orders atomically reserve stock in Supabase. If checkout creation fails or KHPAY reports an expired/failed payment, the reservation is released.
- The bot checks KHPAY on demand and in the background. It delivers credentials only after the authenticated KHPAY status endpoint reports `paid`; it never trusts a browser redirect.
- Admins can manage catalogs and packages from the bot's button-based admin panel: add or edit a category/package, deactivate entries, import stock from a `.txt` attachment, and view sales totals. Category input uses `name | description`; package input uses `name | price | description`. Stock files accept one redeem code or `username:password` per line. These workflows do not use admin slash commands; the standard Telegram `/start` entry point remains available.
- Catalogs and packages can also be managed directly in Supabase. The command-line importer remains available.
- This starter uses KHPAY's ABA `/qr/generate` endpoint and USD. The KHPAY account must have an active payout link.

## Operations and security

- Keep `TELEGRAM_ADMIN_IDS` as comma-separated numeric Telegram user IDs.
- Keep Supabase RLS enabled and use only the service-role key on this private server. Do not add client policies exposing stock or orders.
- The bot stores encrypted credentials in `stock_items`; protect and back up `STOCK_ENCRYPTION_KEY` independently of Supabase.
- Run a single Render instance while using long polling. A second instance would conflict on Telegram polling.
- KHPAY API calls use bearer auth and an idempotency key when creating checkouts.
