import asyncio
from unittest.mock import AsyncMock

import httpx

from app.payments import KHPayClient, aba_mobile_deeplink


def test_qr_payment_uses_qr_endpoint():
    async def run_test():
        client = KHPayClient("api-key", "https://khpay.site/api/v1")
        request = httpx.Request("POST", "https://khpay.site/api/v1/qr/generate")
        response = httpx.Response(
            200,
            json={
                "success": True,
                "data": {"transaction_id": "txn-456", "qr_string": "KHQR+payload/123", "md5": "md5-456"},
            },
            request=request,
        )
        post = AsyncMock(return_value=response)
        client._client.post = post
        try:
            payment = await client.create_payment("10.00", "order-456", 789)
            assert post.await_args.args[0] == "/qr/generate"
            assert post.await_args.kwargs["json"]["currency"] == "USD"
            assert payment["qr_string"] == "KHQR+payload/123"
            assert payment["md5"] == "md5-456"
        finally:
            await client.close()

    asyncio.run(run_test())


def test_aba_mobile_deeplink_encodes_raw_qr_string():
    assert aba_mobile_deeplink("KHQR+payload/123=") == (
        "abamobilebank://ababank.com?type=payway&qrcode=KHQR%2Bpayload%2F123%3D"
    )