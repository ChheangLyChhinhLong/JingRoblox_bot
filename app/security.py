import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken


def encrypt_stock(value: str, key: str) -> str:
    return Fernet(key.encode("ascii")).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_stock(value: str, key: str) -> str:
    try:
        return Fernet(key.encode("ascii")).decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise ValueError("Cannot decrypt stock; verify STOCK_ENCRYPTION_KEY") from exc


def stock_fingerprint(value: str, key: str) -> str:
    secret = base64.urlsafe_b64decode(key.encode("ascii"))
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()
