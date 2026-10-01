from typing import Any

from supabase import AsyncClient

from app.security import encrypt_stock, stock_fingerprint


class Store:
    def __init__(self, client: AsyncClient) -> None:
        self.client = client

    async def upsert_user(self, telegram_id: int, username: str | None, first_name: str, language: str) -> None:
        await self.client.table("users").upsert(
            {
                "telegram_id": telegram_id,
                "username": username,
                "first_name": first_name,
                "language": language,
            },
            on_conflict="telegram_id",
        ).execute()

    async def user_language(self, telegram_id: int) -> str | None:
        result = await (
            self.client.table("users")
            .select("language")
            .eq("telegram_id", telegram_id)
            .maybe_single()
            .execute()
        )
        return (result.data or {}).get("language")

    async def set_user_language(self, telegram_id: int, language: str) -> None:
        if language not in {"km", "en"}:
            raise ValueError("Unsupported language")
        await self.client.table("users").update({"language": language}).eq("telegram_id", telegram_id).execute()

    async def bot_settings(self, keys: tuple[str, ...]) -> dict[str, str]:
        result = await (
            self.client.table("bot_settings")
            .select("key,value")
            .in_("key", list(keys))
            .execute()
        )
        return {item["key"]: item["value"] for item in result.data or []}

    async def categories(self) -> list[dict[str, Any]]:
        result = await (
            self.client.table("categories")
            .select("id,name,description")
            .eq("active", True)
            .order("sort_order")
            .execute()
        )
        return result.data

    async def category(self, category_id: str) -> dict[str, Any] | None:
        result = await (
            self.client.table("categories")
            .select("id,name,description")
            .eq("id", category_id)
            .eq("active", True)
            .maybe_single()
            .execute()
        )
        return result.data

    async def products(self, category_id: str) -> list[dict[str, Any]]:
        result = await (
            self.client.table("products")
            .select("id,name,description,price")
            .eq("category_id", category_id)
            .eq("active", True)
            .order("sort_order")
            .execute()
        )
        return result.data

    async def product(self, product_id: str) -> dict[str, Any] | None:
        result = await (
            self.client.table("products")
            .select("id,category_id,name,description,price")
            .eq("id", product_id)
            .eq("active", True)
            .maybe_single()
            .execute()
        )
        return result.data

    async def available_stock(self, product_id: str) -> int:
        result = await self.client.rpc(
            "available_stock_count", {"p_product_id": product_id}
        ).execute()
        return int(result.data or 0)

    async def reserve_order(self, chat_id: int, product_id: str, quantity: int) -> dict[str, Any]:
        result = await self.client.rpc(
            "reserve_order",
            {"p_chat_id": chat_id, "p_product_id": product_id, "p_quantity": quantity},
        ).execute()
        return result.data

    async def set_payment(self, order_id: str, transaction_id: str, payment_url: str) -> None:
        await self.client.rpc(
            "set_order_payment",
            {"p_order_id": order_id, "p_transaction_id": transaction_id, "p_payment_url": payment_url},
        ).execute()

    async def order_by_transaction(self, transaction_id: str) -> dict[str, Any] | None:
        result = await (
            self.client.table("orders")
            .select("id,chat_id,total,status")
            .eq("transaction_id", transaction_id)
            .maybe_single()
            .execute()
        )
        return result.data

    async def release_order(self, order_id: str, status: str = "cancelled") -> None:
        await self.client.rpc("release_order", {"p_order_id": order_id, "p_status": status}).execute()

    async def pending_orders(self) -> list[dict[str, Any]]:
        result = await (
            self.client.table("orders")
            .select("id,chat_id,transaction_id,status")
            .eq("status", "pending")
            .not_.is_("transaction_id", "null")
            .execute()
        )
        return result.data

    async def undelivered_orders(self) -> list[dict[str, Any]]:
        result = await (
            self.client.table("orders")
            .select("id,chat_id")
            .eq("status", "paid")
            .is_("delivered_at", "null")
            .execute()
        )
        return result.data

    async def fulfill_order(self, order_id: str) -> list[str]:
        result = await self.client.rpc("fulfill_order", {"p_order_id": order_id}).execute()
        return result.data or []

    async def mark_delivered(self, order_id: str) -> None:
        await self.client.rpc("mark_order_delivered", {"p_order_id": order_id}).execute()

    async def order_history(self, chat_id: int) -> list[dict[str, Any]]:
        result = await (
            self.client.table("orders")
            .select("id,total,status,created_at")
            .eq("chat_id", chat_id)
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )
        return result.data

    async def import_stock(self, product_id: str, credentials: list[str], key: str) -> int:
        rows = [
            {
                "product_id": product_id,
                "credential_cipher": encrypt_stock(value, key),
                "credential_fingerprint": stock_fingerprint(value, key),
            }
            for value in credentials
        ]
        result = await self.client.table("stock_items").upsert(
            rows,
            on_conflict="product_id,credential_fingerprint",
            ignore_duplicates=True,
        ).execute()
        return len(result.data or [])

    async def sales_summary(self) -> dict[str, Any]:
        result = await self.client.rpc("sales_summary").execute()
        return result.data
