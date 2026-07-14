from app.services.crypto import decrypt, encrypt


def test_encrypt_decrypt_roundtrip():
    value = "s3cret-imap-password"
    encrypted = encrypt(value)
    assert encrypted != value
    assert decrypt(encrypted) == value


def test_encrypt_produces_different_ciphertext_each_time():
    # Fernet includes a random IV/timestamp, so repeated encryption of
    # the same plaintext should not be byte-identical.
    a = encrypt("same-value")
    b = encrypt("same-value")
    assert a != b
    assert decrypt(a) == decrypt(b) == "same-value"
