import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from supabase import acreate_client

from app.security import encrypt_stock, stock_fingerprint


async def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Import username:password lines into encrypted Supabase stock")
    parser.add_argument("product_id", help="UUID of the product in Supabase")
    parser.add_argument("file", type=Path, help="UTF-8 text file, one username:password credential per line")
    args = parser.parse_args()

    key = os.environ["STOCK_ENCRYPTION_KEY"]
    credentials = [line.strip() for line in args.file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not credentials or any(
        ":" not in item or not item.split(":", 1)[0] or not item.split(":", 1)[1]
        for item in credentials
    ):
        raise SystemExit("Stock file must contain at least one username:password line")
    supabase = await acreate_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    rows = [
        {
            "product_id": args.product_id,
            "credential_cipher": encrypt_stock(item, key),
            "credential_fingerprint": stock_fingerprint(item, key),
        }
        for item in credentials
    ]
    result = await supabase.table("stock_items").upsert(
        rows, on_conflict="product_id,credential_fingerprint", ignore_duplicates=True
    ).execute()
    print(f"Imported {len(result.data)} stock item(s).")


if __name__ == "__main__":
    asyncio.run(main())
