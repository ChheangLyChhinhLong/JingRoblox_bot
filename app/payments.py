from typing import Any

import httpx


class KHPayClient:
    def __init__(self, api_key: str, base_url: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=20.0,
        )

    async def create_payment(self, amount: str, order_id: str) -> dict[str, Any]:
        response = await self._client.post(
            "/qr/generate",
            headers={"Idempotency-Key": order_id},
            json={"amount": amount, "currency": "USD", "note": f"Telegram order {order_id}"},
        )
        payload = response.json()
        if response.is_error or not payload.get("success"):
            raise RuntimeError(payload.get("error", f"KHPAY returned HTTP {response.status_code}"))
        data = payload.get("data", {})
        if not data.get("transaction_id") or not data.get("payment_url"):
            raise RuntimeError("KHPAY response is missing transaction_id or payment_url")
        return data

    async def check_payment(self, transaction_id: str) -> dict[str, Any]:
        response = await self._client.get(f"/qr/check/{transaction_id}")
        payload = response.json()
        if response.is_error or not payload.get("success"):
            raise RuntimeError(payload.get("error", f"KHPAY returned HTTP {response.status_code}"))
        return payload.get("data", {})

    async def close(self) -> None:
        await self._client.aclose()
