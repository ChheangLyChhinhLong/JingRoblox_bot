from cryptography.fernet import Fernet

from app.security import decrypt_stock, encrypt_stock, stock_fingerprint


def test_credentials_round_trip_without_plaintext_storage():
    key = Fernet.generate_key().decode("ascii")
    credential = "customer@example.com:correct-horse"

    ciphertext = encrypt_stock(credential, key)

    assert ciphertext != credential
    assert decrypt_stock(ciphertext, key) == credential
    assert stock_fingerprint(credential, key) == stock_fingerprint(credential, key)
    assert stock_fingerprint(credential, key) != stock_fingerprint("other@example.com:secret", key)
