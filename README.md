# Telegram Digital Shop: Tutorial ពេញលេញ

Project នេះជាហាងលក់ digital products តាម Telegram Bot។ អ្នកទិញជ្រើស Catalog និង Package, កក់ស្តុក, ទូទាត់តាម KHPAY KHQR ហើយ bot ផ្ញើ credential បន្ទាប់ពី KHPAY បញ្ជាក់ថាបានបង់ប្រាក់រួច។ Backend ប្រើ Supabase, ដំណើរការលើ Render និងអាចត្រួតពិនិត្យស្ថានភាពតាម `/health`។

## មាតិកា

- [តម្រូវការមុនចាប់ផ្តើម](#តម្រូវការមុនចាប់ផ្តើម)
- [រៀបចំ Telegram Bot](#1-រៀបចំ-telegram-bot)
- [រៀបចំ Supabase](#2-រៀបចំ-supabase)
- [កំណត់ Environment Variables](#3-កំណត់-environment-variables)
- [ដំណើរការលើម៉ាស៊ីនផ្ទាល់ខ្លួន](#4-ដំណើរការលើម៉ាស៊ីនផ្ទាល់ខ្លួន)
- [បង្កើត Catalog, Package និង Stock](#5-បង្កើត-catalog-package-និង-stock)
- [កំណត់វីដេអូណែនាំ និងរូបភាព](#6-កំណត់វីដេអូណែនាំ-និងរូបភាព)
- [ដាក់ឲ្យដំណើរការលើ Render](#7-ដាក់ឲ្យដំណើរការលើ-render)
- [ភ្ជាប់ KHPAY Webhook](#8-ភ្ជាប់-khpay-webhook)
- [ត្រួតពិនិត្យដោយ UptimeRobot](#9-ត្រួតពិនិត្យដោយ-uptimerobot)
- [របៀបប្រើក្នុង Telegram](#របៀបប្រើក្នុង-telegram)
- [សុវត្ថិភាព និងថែទាំ](#សុវត្ថិភាព-និងថែទាំ)
- [ដោះស្រាយបញ្ហា](#ដោះស្រាយបញ្ហា)

## តម្រូវការមុនចាប់ផ្តើម

- Python និង PowerShell សម្រាប់ការដំឡើង/សាកល្បងក្នុង Windows។
- Telegram account និង bot token ពី [@BotFather](https://t.me/BotFather)។
- Supabase project, KHPAY API key និង Cloudinary account (Cloudinary ត្រូវការតែពេលប្រើរូបភាពផលិតផល)។
- GitHub repository ដែល Render អាចចូលប្រើបាន ប្រសិនបើ deploy តាម Render។

## 1. រៀបចំ Telegram Bot

1. បើក [@BotFather](https://t.me/BotFather) ហើយផ្ញើ `/newbot`។
2. ជ្រើសឈ្មោះ និង username សម្រាប់ bot រួចរក្សាទុក token ដែល BotFather ផ្តល់ឲ្យ។
3. រកលេខ Telegram user ID របស់អ្នក ដើម្បីដាក់ក្នុង `TELEGRAM_ADMIN_IDS`។ ដាក់ជា ID លេខសុទ្ធ មិនមែន username; អាចដាក់ admin ច្រើនដោយបំបែកជាមួយសញ្ញាក្បៀស។
4. កុំផ្ញើ bot token ទៅអ្នកដទៃ និងកុំដាក់វាក្នុង source control។

## 2. រៀបចំ Supabase

1. បង្កើត project ថ្មីនៅ [Supabase](https://supabase.com/) ហើយរង់ចាំ database រួចរាល់។
2. បើក **SQL Editor → New query**។ បើក [schema.sql](schema.sql), ចម្លង SQL ទាំងមូលទៅក្នុង editor ហើយចុច **Run**។ Script នេះបង្កើត tables, indexes និង database functions ដែល bot ត្រូវការ។
3. បើមាន database ចាស់ អាច run `schema.sql` ម្តងទៀត ដើម្បីអនុវត្តការបន្ថែម schema ដែល idempotent។
4. បើក **Project Settings → API** រួចចម្លង Project URL និង `service_role` key ទៅ environment variables។ ប្រើ `service_role` key តែក្នុង backend/Render ប៉ុណ្ណោះ។
5. ទុក Row Level Security (RLS) ឲ្យបើក។ កុំបង្កើត public policies សម្រាប់ stock ឬ orders។

> `service_role` key អាចមើល/កែទិន្នន័យទាំងមូលបាន។ កុំដាក់វាក្នុង Telegram, browser, public repository ឬ screenshot។

## 3. កំណត់ Environment Variables

នៅក្នុង project root ចម្លង `.env.example` ទៅ `.env`។ ក្នុង PowerShell:

```powershell
Copy-Item .env.example .env
notepad .env
```

បំពេញតម្លៃខាងក្រោម។ កុំដាក់ quote លើតម្លៃ លុះត្រាតែតម្លៃនោះត្រូវការវាពិតៗ។

| Variable | ត្រូវការ | អត្ថន័យ |
| --- | --- | --- |
| `BOT_TOKEN` | ចាំបាច់ | Token ពី BotFather។ |
| `TELEGRAM_ADMIN_IDS` | ណែនាំ | Telegram user IDs របស់ admin បំបែកដោយសញ្ញាក្បៀស។ ឧទាហរណ៍ `123456789,987654321`។ |
| `SUPABASE_URL` | ចាំបាច់ | Project URL ពី Supabase។ |
| `SUPABASE_SERVICE_ROLE_KEY` | ចាំបាច់ | `service_role` API key; រក្សាសម្ងាត់។ |
| `STOCK_ENCRYPTION_KEY` | ចាំបាច់ | Fernet key សម្រាប់ encrypt stock credentials។ បង្កើតម្តង ហើយរក្សាទុកឲ្យបានល្អ។ |
| `KHPAY_API_KEY` | ចាំបាច់ | KHPAY API key ដែលនៅមានសុពលភាព។ |
| `KHPAY_BASE_URL` | មាន default | ជាទូទៅ `https://khpay.site/api/v1`។ |
| `KHPAY_WEBHOOK_URL` | សម្រាប់ production | URL ពេញលេញទៅ `/webhook/khpay` របស់ service។ |
| `KHPAY_WEBHOOK_SECRET` | សម្រាប់ webhook | Secret ដែល KHPAY បង្កើតសម្រាប់ webhook។ |
| `PUBLIC_BASE_URL` | សម្រាប់ ABA link | URL HTTPS សាធារណៈរបស់ Render ដោយមិនបញ្ចូល path។ |
| `CLOUDINARY_CLOUD_NAME` | ស្រេចចិត្ត | Cloud name; ត្រូវបំពេញជាមួយ API key/secret ប្រសិនបើប្រើរូបភាព។ |
| `CLOUDINARY_API_KEY` | ស្រេចចិត្ត | Cloudinary API key។ |
| `CLOUDINARY_API_SECRET` | ស្រេចចិត្ត | Cloudinary API secret; រក្សាសម្ងាត់។ |
| `STOCK_NOTIFICATION_CHAT_IDS` | ស្រេចចិត្ត | Group/channel IDs ឬ `@channelname` បំបែកដោយក្បៀស។ |
| `SUPPORT_USERNAME` | ស្រេចចិត្ត | Telegram username របស់ផ្នែក support ដោយមិនចាំបាច់មាន `@`។ |
| `POLL_INTERVAL_SECONDS` | មាន default | ចន្លោះពេលពិនិត្យ payment background; default `20` វិនាទី។ |
| `PORT` | មាន default | Port របស់ web service; default `10000`។ Render អាចកំណត់ port ផ្ទាល់។ |

បង្កើត encryption key ម្តងដោយប្រើ Python ដែលនឹងដំឡើងនៅជំហានបន្ទាប់:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

ចម្លងលទ្ធផលទៅ `STOCK_ENCRYPTION_KEY`។ កុំបង្កើត key ថ្មីក្រោយមាន stock encrypted រួច ព្រោះ stock ចាស់មិនអាច decrypt ដោយ key ថ្មីបានទេ។ Backup key ដាច់ដោយឡែកពី database។

> កុំ commit `.env`។ ពិនិត្យឲ្យប្រាកដថា `.env` មិនត្រូវបានបញ្ចូលក្នុង Git មុន push។

## 4. ដំណើរការលើម៉ាស៊ីនផ្ទាល់ខ្លួន

បើក PowerShell នៅ project root (`D:\JingRoblox_bot`) ហើយបង្កើត virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

បើ PowerShell រារាំងការបើក script សម្រាប់ session នេះ អាចរត់:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

ចាប់ផ្តើម bot និង web server:

```powershell
python -m app.main
```

ទុក process នេះឲ្យដំណើរការ ហើយបើក browser ទៅ `http://127.0.0.1:10000/health`។ លទ្ធផលធម្មតាគឺ `{"status":"ok"}`។ បន្ទាប់មកបើក bot ក្នុង Telegram ហើយចុច **Start** ឬផ្ញើ `/start`។

Webhook និង ABA deep link ត្រូវការអាសយដ្ឋាន HTTPS ដែល KHPAY/Telegram អាចចូលដល់បាន។ ដូច្នេះការសាកល្បង webhook ក្នុង local machine ត្រូវការប្រើ HTTPS tunnel; បើមិនបានកំណត់ webhook ទេ bot នៅតែអាចពិនិត្យ payment តាម background polling និងប៊ូតុងពិនិត្យ payment។

## 5. បង្កើត Catalog, Package និង Stock

### តាម Admin panel ក្នុង Telegram

1. បន្ថែម Telegram ID របស់អ្នកក្នុង `TELEGRAM_ADMIN_IDS` ហើយចាប់ផ្តើម bot ឡើងវិញ។
2. បើក bot ដោយ admin account ហើយចុច **Store admin → Catalogs and packages → Add Catalog**។
3. បញ្ចូល Catalog តាមទម្រង់:

```text
ឈ្មោះ Catalog | ព័ត៌មានលម្អិត (អាចទុកទទេ)
```

4. បើក Catalog ដែលទើបបង្កើត ហើយចុច **Add Package**។ ផ្ញើរូបភាពជាមួយ caption តាមទម្រង់:

```text
ឈ្មោះ Package | តម្លៃ USD | ព័ត៌មានលម្អិត
```

ឧទាហរណ៍ `Premium Account | 5.00 | Delivery after payment`។ តម្លៃត្រូវធំជាងសូន្យ។ ការបង្កើត package ជាមួយរូបភាពត្រូវការកំណត់ Cloudinary variables ទាំងបី។

5. ចូល package ហើយប្រើ **Add stock** ដើម្បីបញ្ចូល code ឬ `username:password`, មួយក្នុងមួយបន្ទាត់។ Bot encrypt ទិន្នន័យមុនរក្សាទុក។
6. ឬប្រើទម្រង់សារនេះពី admin account ដោយផ្ទាល់:

```text
addstock PRODUCT_UUID | code1, code2
```

អាចប្រើបន្ទាត់ថ្មីជំនួស comma បាន។ កុំផ្ញើ stock ទៅ chat សាធារណៈ។

### បញ្ចូល stock ជា `.txt`

ក្នុង Admin panel ជ្រើស **Import stock (.txt)**, ជ្រើស package ហើយផ្ញើឯកសារ `.txt`។ ឯកសារមិនអាចធំជាង 1 MB; ដាក់ stock មួយក្នុងមួយបន្ទាត់។ Admin upload អាចប្រើ redeem code ឬ `username:password`។

អាចប្រើ command-line importer ផងដែរ។ វិធីនេះទទួលតែ `username:password` មួយក្នុងមួយបន្ទាត់:

```text
user001:password001
user002:password002
```

រក Product UUID នៅក្នុង admin panel រួចរត់ពី project root:

```powershell
python -m scripts.import_stock PRODUCT_UUID .\stock.txt
```

Script អាន `.env` ពី project root។ វាត្រូវការ `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` និង `STOCK_ENCRYPTION_KEY`។ ទិន្នន័យស្ទួនត្រូវបានរំលង។ បន្ទាប់ពី import សូមលុប/ផ្លាស់ទីឯកសារ stock ឲ្យមានសុវត្ថិភាព ព្រោះក្នុងនោះមាន credentials ជាអក្សរធម្មតា។

### កែប្រែ និងបិទ Catalog/Package

- **Edit Catalog**: `ឈ្មោះ | ព័ត៌មានលម្អិត`
- **Edit Package**: `ឈ្មោះ | តម្លៃ | ព័ត៌មានលម្អិត`
- **Remove stock**: បញ្ចូល credential ដើមមួយក្នុងមួយបន្ទាត់។ លុបបានតែ stock ដែលមានស្ថានភាព `available`; stock កំពុង reserve ឬលក់រួចមិនត្រូវបានលុបទេ។
- **Deactivate**: បិទ Catalog នឹងបិទ packages របស់វាទាំងអស់; បិទ Package បិទតែ package នោះ។ វាមិនមែនជា delete ទេ។
- **Sales**: មើលចំនួន paid orders និង revenue។

## 6. កំណត់វីដេអូណែនាំ និងរូបភាព

### វីដេអូ “How to buy”

បញ្ចូល `how_to_buy_video_url` និង caption ក្នុង `public.bot_settings` តាម Supabase SQL Editor។ `value` របស់ video អាចជា Telegram `file_id` ឬ URL វីដេអូដែលអាចចូលប្រើជាសាធារណៈបាន។ ប្រើ `how_to_buy_caption_km` និង `how_to_buy_caption_en` ដើម្បីបង្ហាញ caption តាមភាសាអ្នកប្រើ។ បើមិនបានកំណត់ caption តាមភាសា bot នឹងប្រើ `how_to_buy_caption` ចាស់ជាជម្រើសបម្រុង។ Telegram កំណត់ caption អតិបរមា 1024 តួអក្សរ។

```sql
insert into public.bot_settings (key, value)
values
    ('how_to_buy_video_url', 'PASTE_TELEGRAM_FILE_ID_OR_PUBLIC_VIDEO_URL'),
    ('how_to_buy_caption_km', 'ការណែនាំអំពីរបៀបទិញ'),
    ('how_to_buy_caption_en', 'How to buy tutorial')
on conflict (key) do update set value = excluded.value;
```

Bot ទាញ settings ថ្មីរាល់ពេលអ្នកប្រើបើក tutorial ដូច្នេះមិនចាំបាច់ restart bot បន្ទាប់ពីកែទេ។

### រូបភាព Package

បំពេញ `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY` និង `CLOUDINARY_API_SECRET`។ ដើម្បីដាក់/ប្តូររូបភាព package ដែលមានស្រាប់ ផ្ញើរូបភាពឲ្យ bot ជាមួយ caption:

```text
setphoto PRODUCT_UUID
```

រូបភាពត្រូវបាន upload ទៅ Cloudinary ហើយ secure URL ត្រូវរក្សាទុកក្នុង `products.image_url`។

## 7. ដាក់ឲ្យដំណើរការលើ Render

1. Push project ទៅ GitHub ហើយភ្ជាប់ repository នៅ [Render](https://render.com/) ដោយបង្កើត **New → Web Service**។
2. ប្រសិនបើ Render សួរ config file សូមប្រើ `render.yaml`។ វាកំណត់ build command, start command, health check និង instance តែមួយ។
3. នៅ **Environment** បញ្ចូល variables តាម `.env.example`។ `render.yaml` មិនកំណត់ `CLOUDINARY_*` ឬ `PUBLIC_BASE_URL` ទេ ដូច្នេះបន្ថែមវាដោយដៃបើប្រើរូបភាព/ABA Mobile។ បន្ថែម `PORT` តែបើ deployment ត្រូវការកំណត់វាដោយដៃ។
4. ត្រូវមានយ៉ាងហោចណាស់ `BOT_TOKEN`, `TELEGRAM_ADMIN_IDS`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `KHPAY_API_KEY` និង `STOCK_ENCRYPTION_KEY`។
5. ចុច **Deploy** ហើយពិនិត្យ Logs រហូត service ដំណើរការ។ URL សាធារណៈមានទម្រង់ `https://YOUR-SERVICE.onrender.com`។
6. កំណត់ environment values:

```text
KHPAY_WEBHOOK_URL=https://YOUR-SERVICE.onrender.com/webhook/khpay
PUBLIC_BASE_URL=https://YOUR-SERVICE.onrender.com
```

7. Save changes ហើយ redeploy។ សាកល្បង `https://YOUR-SERVICE.onrender.com/health`; ត្រូវទទួល `{"status":"ok"}`។

កុំបង្កើត Render instances ច្រើនជាងមួយ ខណៈ bot ប្រើ Telegram long polling ព្រោះ instances ច្រើនអាចប៉ះទង្គិចគ្នា។

## 8. ភ្ជាប់ KHPAY Webhook

Checkout ប្រើ KHPAY `/qr/generate` ជា USD។ រៀបចំ KHPAY API key, account/product និង payout settings តាមការកំណត់ក្នុង KHPAY account របស់អ្នក។ Webhook ជូនដំណឹងអំពី paid/expired/failed ប៉ុន្តែ backend នៅតែសួរ KHPAY API ដើម្បីផ្ទៀងផ្ទាត់ status និង amount មុនពេលបញ្ជូន stock។

### បង្កើត webhook ថ្មីតាម PowerShell

បើក PowerShell session ថ្មី ហើយកែ `$webhookUrl` ឲ្យត្រូវនឹង URL Render របស់អ្នក។ Script ខាងក្រោមលុប webhook ចាស់ៗដែលមាន URL ដូចគ្នា បង្កើត webhook ថ្មីសម្រាប់ paid/expired/failed events ហើយចម្លង secret ទៅ clipboard ដោយមិន print secret ចេញ។ វាត្រូវការ KHPAY API key ដែលបាន rotate រួច:

```powershell
$secureKey = Read-Host "Rotated KHPAY API key" -AsSecureString
$apiKey = [System.Net.NetworkCredential]::new("", $secureKey).Password
$headers = @{ Authorization = "Bearer $apiKey" }
$webhookUrl = "https://YOUR-SERVICE.onrender.com/webhook/khpay"

$existing = Invoke-RestMethod `
    -Method Get `
    -Uri "https://khpay.site/api/v1/webhooks" `
    -Headers $headers

$matching = @($existing.data | Where-Object { $_.url -eq $webhookUrl })
foreach ($hook in $matching) {
    Invoke-RestMethod `
        -Method Delete `
        -Uri "https://khpay.site/api/v1/webhooks/$($hook.id)" `
        -Headers $headers | Out-Null
}

$body = @{
    url = $webhookUrl
    events = @("payment.paid", "payment.expired", "payment.failed")
} | ConvertTo-Json

$created = Invoke-RestMethod `
    -Method Post `
    -Uri "https://khpay.site/api/v1/webhooks" `
    -Headers $headers `
    -ContentType "application/json" `
    -Body $body

Set-Clipboard -Value $created.data.secret
Write-Host "Webhook created. Secret copied to clipboard; it was not printed."

$secureKey = $null
$apiKey = $null
$headers = $null
$body = $null
$existing = $null
$matching = $null
$created = $null
```

ចូល KHPAY Dashboard → Webhooks ដើម្បីបញ្ជាក់ថា URL និង events ត្រឹមត្រូវ។ បន្ទាប់មក paste secret ពី clipboard ទៅ Render Environment ជា `KHPAY_WEBHOOK_SECRET` ហើយ redeploy។ កុំដាក់ webhook secret ក្នុង README, GitHub ឬ chat។ បិទ PowerShell session បន្ទាប់ពីរួចរាល់ និងកុំទុក secret នៅ clipboard យូរ។

Webhook endpoint ទទួល `POST /webhook/khpay`, ពិនិត្យ HMAC signature លើ raw request body, សួរ KHPAY ដើម្បីផ្ទៀងផ្ទាត់ status ហើយផ្ទៀងផ្ទាត់ទឹកប្រាក់មុន delivery។ កុំប្រើ browser redirect ជាភស្តុតាងទូទាត់។

## 9. ត្រួតពិនិត្យដោយ UptimeRobot

1. បង្កើត **HTTP(s) monitor** ក្នុង [UptimeRobot](https://uptimerobot.com/)។
2. ដាក់ URL `https://YOUR-SERVICE.onrender.com/health` និង interval 5 នាទី។
3. សាកល្បងឲ្យ monitor បង្ហាញ Online បន្ទាប់ពី Render deploy រួច។

## របៀបប្រើក្នុង Telegram

1. អ្នកទិញចុច **Shop**, ជ្រើស Catalog និង Package ហើយកំណត់ចំនួនទិញ។ ចំនួនមួយ order មានអតិបរមា 3 ហើយមិនអាចលើសស្តុកនៅសល់។
2. ពេលបង្កើត order, Supabase កក់ stock ជាអាតូមិក ដើម្បីកុំឲ្យអតិថិជនពីរនាក់បាន credential ដូចគ្នា។
3. អ្នកទិញបង់តាម KHQR ឬបើក ABA Mobile។ អាចចុចប៊ូតុងពិនិត្យ payment ដោយខ្លួនឯងបាន។
4. បន្ទាប់ពី KHPAY បញ្ជាក់ `paid` bot ផ្ញើ credential ក្នុង Telegram ហើយលុបសារដែលមាន QR។ ករណី expired/failed stock ដែលបាន reserve នឹងត្រឡប់ទៅ available។
5. អ្នកប្រើអាចមើល order history, ប្តូរភាសា Khmer/English, បើកវីដេអូ How to buy និងទាក់ទង support។

Admin panel អាចបន្ថែម/កែ Catalog និង Package, បិទធាតុ, បញ្ចូល/ដក stock, upload `.txt` និងមើល sales summary។ អ្នកប្រើដែលមិនមាន ID ក្នុង `TELEGRAM_ADMIN_IDS` មិនអាចគ្រប់គ្រងហាងបានទេ។

## សុវត្ថិភាព និងថែទាំ

- រក្សា bot token, Supabase service role key, KHPAY API key/webhook secret, Cloudinary API secret និង stock encryption key ជាសម្ងាត់។ ប្រសិនបើសង្ស័យថាបែកធ្លាយ សូម rotate/revoke key នោះភ្លាមៗ ហើយ update secret នៅ Render។
- Backup `STOCK_ENCRYPTION_KEY` នៅកន្លែងសុវត្ថិភាពដាច់ពី database។ បើបាត់ key នេះ credentials ដែលបាន encrypt រួចមិនអាចយកមកប្រើបានទេ។
- កុំបិទ Supabase RLS និងកុំបង្កើត public access policies សម្រាប់ orders/stock។ Backend ប្រើ service-role key ដោយផ្ទាល់។
- កំណត់ `STOCK_NOTIFICATION_CHAT_IDS` ជា comma-separated IDs/usernames ឧទាហរណ៍ `-1001234567890,@myshopnews`។ បន្ថែម bot ទៅ group/channel និងអនុញ្ញាតឲ្យ post។ Bot ក៏ជូនដំណឹងទៅ users ដែលបានប្រើ bot រួច; អ្នកដែល block bot ឬ chat ដែល bot មិនអាច post បាន នឹងត្រូវរំលង។
- Stock credentials ក្នុង database ត្រូវបាន encrypt។ ឯកសារ `.txt` មុន import និងសារ stock ក្នុង Telegram នៅតែជា plaintext ដូច្នេះកុំទុក/បញ្ជូនវាក្នុងកន្លែងមិនមានសុវត្ថិភាព។
- កុំ run bot local និង Render instance ច្រើនក្នុងពេលតែមួយដោយប្រើ bot token ដូចគ្នា ពេល long polling កំពុងដំណើរការ។
- ការបង្កើត payment មាន idempotency key ដោយប្រើ order ID។ ការបញ្ជូន order កើតឡើងតែបន្ទាប់ពី KHPAY API បញ្ជាក់ការទូទាត់ប៉ុណ្ណោះ។

## ដោះស្រាយបញ្ហា

| រោគសញ្ញា | អ្វីដែលត្រូវពិនិត្យ |
| --- | --- |
| Bot មិនឆ្លើយតប | ពិនិត្យ `BOT_TOKEN`, Render Logs និងថាមាន polling process តែមួយប៉ុណ្ណោះ។ |
| Bot បង្ហាញថាមិនមាន Catalog | ពិនិត្យថាមាន `categories` ដែល `active = true` ក្នុង Supabase។ |
| Admin panel មិនបង្ហាញ | ពិនិត្យ Telegram numeric ID ក្នុង `TELEGRAM_ADMIN_IDS` ហើយ restart/redeploy។ |
| Supabase request បរាជ័យ | ពិនិត្យ `SUPABASE_URL`, service-role key និងថា `schema.sql` បាន run ជោគជ័យ។ កុំបិទ RLS ដើម្បីជៀសបញ្ហា។ |
| Import stock មិនជោគជ័យ | ពិនិត្យ Product UUID, file UTF-8, format មួយ credential ក្នុងមួយបន្ទាត់ និង encryption key។ CLI importer ត្រូវការ `username:password`។ |
| រូបភាពមិន upload | បំពេញ Cloudinary variables ទាំងបី ហើយពិនិត្យ `CLOUDINARY_CLOUD_NAME`, API key/secret នៅ local/Render។ |
| KHPAY checkout បរាជ័យ | ពិនិត្យ API key, `KHPAY_BASE_URL`, KHPAY account/payout setup និង Render Logs។ |
| Webhook បាន `401` | ពិនិត្យថា `KHPAY_WEBHOOK_SECRET` ត្រូវនឹង secret របស់ webhook ដែលកំពុងសកម្ម ហើយ redeploy បន្ទាប់ពី update។ |
| ABA button មិនដំណើរការ | `PUBLIC_BASE_URL` ត្រូវជា public HTTPS URL របស់ Render ដោយគ្មាន `/webhook/khpay`; ពិនិត្យថា order នៅ pending។ |
| Health check មិនឆ្លើយ | សាកល្បង `/health`, ពិនិត្យ Render Logs និង environment variables ចាំបាច់។ |

## សាកល្បងមុនបើកលក់

បង្កើត Catalog និង Package សាកល្បងដែលមានតម្លៃទាប, បញ្ចូល stock test មួយ, ទិញពី Telegram account ផ្សេង, បញ្ជាក់ថា payment status ត្រឹមត្រូវ និង credential ត្រូវបានផ្ញើតែម្តង។ បន្ទាប់មកសាកល្បង expired/failed payment, order history, admin stock notification និង webhook logs មុនដាក់លក់ពិត។