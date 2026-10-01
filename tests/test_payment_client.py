import asyncio
from unittest.mock import AsyncMock

import httpx

from app.payments import KHPayClient


def test_bakong_payment_sends_order_metadata_and_normalizes_deeplink():
    async def run_test():
        client = KHPayClient("api-key", "https://khpay.site/api/v1")
        request = httpx.Request("POST", "https://khpay.site/api/v1/bakong/generate")
        response = httpx.Response(
            200,
            json={
                "success": True,
                "data": {"transaction_id": "txn-123", "bakong_deeplink": "bakong://pay/txn-123"},
            },
            request=request,
        )
        post = AsyncMock(return_value=response)
        client._client.post = post
        try:
            payment = await client.create_payment("3.85", "order-123", 456, "bakong")
            assert post.await_args.args[0] == "/bakong/generate"
            assert post.await_args.kwargs["json"]["metadata"] == {
                "telegram_id": 456,
                "order_id": "order-123",
            }
            assert payment["payment_url"] == "bakong://pay/txn-123"
        finally:
            await client.close()

    asyncio.run(run_test())


def test_qr_payment_uses_qr_endpoint():
    async def run_test():
        client = KHPayClient("api-key", "https://khpay.site/api/v1")
        request = httpx.Request("POST", "https://khpay.site/api/v1/qr/generate")
        response = httpx.Response(
            200,
            json={"success": True, "data": {"transaction_id": "txn-456", "payment_url": "https://pay.example/txn-456"}},
            request=request,
        )
        post = AsyncMock(return_value=response)
        client._client.post = post
        try:
            await client.create_payment("10.00", "order-456", 789, "qr")
            assert post.await_args.args[0] == "/qr/generate"
            assert post.await_args.kwargs["json"]["currency"] == "USD"
        finally:
            await client.close()

    asyncio.run(run_test())