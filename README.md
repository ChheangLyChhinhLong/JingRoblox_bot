# Telegram digital-product shop

Button-driven Telegram storefront for digital accounts (`username:password`). It uses KHPAY hosted checkout, Supabase for catalog/orders/stock, Render for the running service, and `/health` for UptimeRobot.

## Setup

1. Create a Supabase project. Run [`schema.sql`](schema.sql) in its SQL editor. Existing deployments should rerun it to apply additive tables and columns, including tutorial settings and payment-message tracking; the schema uses idempotent statements.
2. Create a Telegram bot with BotFather and copy its token.
3. Copy `.env.example` to `.env` and fill in the Telegram, Supabase, Cloudinary, and KHPAY settings. Never commit `.env` or expose the Supabase service-role key.
4. Generate the stock encryption key with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and save it as `STOCK_ENCRYPTION_KEY`. Keep this key backed up: stock credentials cannot be decrypted without it.
5. Install dependencies with `pip install -r requirements.txt` and start locally with `python -m app.main`.
6. In Supabase, insert categories and products. Copy a product UUID and import stock using `python -m scripts.import_stock PRODUCT_UUID stock.txt`. Each line in the file must be `username:password`. Set the same environment variables locally before running the importer.
	Configure the tutorial by upserting `how_to_buy_video_url` (a Telegram file ID or publicly accessible video URL) and `how_to_buy_caption` into `public.bot_settings`; the bot reads both settings from Supabase each time a user opens the tutorial.
7. In Render, create a Web Service from this repository. The included [`render.yaml`](render.yaml) sets the start command and `/health` check; add all `.env.example` secrets in the Render Environment tab.
8. After Render deploys, set `KHPAY_WEBHOOK_URL` to `https://YOUR-RENDER-SERVICE.onrender.com/webhook/khpay` and `PUBLIC_BASE_URL` to `https://YOUR-RENDER-SERVICE.onrender.com` in Render, then redeploy. Add the webhook URL in KHPAY Dashboard → Settings → Webhooks, enable paid/failed/expired events, then copy the generated webhook secret into Render as `KHPAY_WEBHOOK_SECRET` and redeploy. The endpoint verifies the raw-body HMAC and confirms payment status and amount through KHPAY before delivery. `PUBLIC_BASE_URL` is also used for the Telegram-compatible ABA Mobile redirect.
9. In UptimeRobot, create an HTTP(s) monitor for `https://YOUR-RENDER-SERVICE.onrender.com/health`, with a 5-minute interval.

## Store behavior

- Customers navigate categories, products, quantity, payment, order history, and support using inline buttons. Product listings show current available stock, and quantity selection is limited to available stock and three items per order.
- New orders atomically reserve stock in Supabase. If checkout creation fails or KHPAY reports an expired/failed payment, the reservation is released.
- The bot checks KHPAY on demand and in the background. It delivers credentials only after the authenticated KHPAY status endpoint reports `paid`; it never trusts a browser redirect.
- Customer language (`km` or `en`) and Telegram profile details are stored in the `users` table. The home screen lists active categories from Supabase.
- Tutorial video URL and caption are fetched from the `bot_settings` table on each tutorial request.
- Checkout uses KHPAY KHQR directly, with no payment-method selection. The payment screen shows a QR image, an ABA Mobile deep link, and a payment-status button; a confirmed payment automatically removes the QR message before delivering credentials.
- Admins can manage catalogs and packages from the bot's button-based admin panel: add or edit a category/package, deactivate entries, add stock, remove matching unsold stock, import stock from a `.txt` attachment, and view sales totals. After editing, the return button opens the updated category or package. Category input uses `name | description`; package input uses `name | price | description`. Stock files accept one redeem code or `username:password` per line. To set a product image, send a Telegram photo with caption `setphoto PRODUCT_ID`; the bot uploads the image to Cloudinary and stores its secure HTTPS URL in `products.image_url`. Product image URLs are fetched from Supabase and used for the customer detail photo. Removing stock only deletes matching items with `available` status; reserved or sold stock is kept.
- To create a package with its first image, choose a category and its **Add Package** option, then send a photo with caption `NAME | PRICE | DESCRIPTION`; the package is inserted with its Cloudinary HTTPS image URL. To add stock later without an image, send `addstock PRODUCT_ID | code1, code2` or use the package's admin stock buttons. Stock is encrypted before it is stored.
- Catalogs and packages can also be managed directly in Supabase. The command-line importer remains available.
- Checkout uses KHPAY `/qr/generate` in USD. Configure the matching KHPAY product and active payout link in the KHPAY account.

## Operations and security

- Keep `TELEGRAM_ADMIN_IDS` as comma-separated numeric Telegram user IDs.
- Set `STOCK_NOTIFICATION_CHAT_IDS` to comma-separated group/channel chat IDs or public channel usernames (for example, `-1001234567890,@myshopnews`) to receive new-stock announcements. The bot also notifies users already recorded in the `users` table; blocked users and chats where the bot cannot post are skipped. Add the bot to each group/channel and grant permission to send messages. The CLI stock importer sends notifications when `BOT_TOKEN` is configured.
- Keep Supabase RLS enabled and use only the service-role key on this private server. Do not add client policies exposing stock or orders.
- The bot stores encrypted credentials in `stock_items`; protect and back up `STOCK_ENCRYPTION_KEY` independently of Supabase.
- Run a single Render instance while using long polling. A second instance would conflict on Telegram polling.
- KHPAY API calls use bearer auth and an idempotency key when creating checkouts.
