"""Python implementation of TikTok 47.1.4's ttEncrypt envelope.

Recovered from libEncryptor: JNI 0x7af0 -> helper 0x293c, SHA-512 at
0x6b10 and AES-CBC at 0x27c0. No TikTok binary or emulator is loaded.
Input is exact bytes: this layer does not add JSON serialization or gzip.
"""
import hashlib
import hmac
import secrets

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

PREFIX = bytes.fromhex('746305100000')
SEED_BYTES = 32
MAX_INPUT_BYTES = 256 * 1024
# Second SHA-512 input = SHA512(seed) || this 64-byte native constant.
DERIVATION_SUFFIX = bytes.fromhex(
    '4dd4c2e6b83162090e52b3c7a6733ba41cb2462b829ab58a196b39db57177524f'
    '49baf7f08e8d68d26a72e37c1a95a2f1f05a51892aef2949732b62a38aadd58')


def _key_iv(seed):
    material = hashlib.sha512(hashlib.sha512(seed).digest() + DERIVATION_SUFFIX).digest()
    return material[:16], material[16:32]


def tt_encrypt(raw, *, seed=None):
    """Encode PREFIX || seed32 || AES128-CBC(SHA512(raw) || raw || padding).

    Production uses secure independent seed bytes. Explicit seed is for
    reproducible comparisons with the original Android implementation.
    """
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_INPUT_BYTES:
        raise ValueError(f'ttEncrypt requires 1..{MAX_INPUT_BYTES} exact input bytes')
    if seed is None:
        seed = secrets.token_bytes(SEED_BYTES)
    if not isinstance(seed, bytes) or len(seed) != SEED_BYTES:
        raise ValueError('ttEncrypt seed must be exactly 32 bytes')
    key, iv = _key_iv(seed)
    plaintext = hashlib.sha512(raw).digest() + raw
    ciphertext = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(plaintext, AES.block_size))
    return PREFIX + seed + ciphertext


def tt_decrypt(envelope):
    """Decode and verify an envelope for offline diagnostics/tests."""
    start = len(PREFIX) + SEED_BYTES
    if (not isinstance(envelope, bytes) or not envelope.startswith(PREFIX)
            or not start + 80 <= len(envelope) <= start + MAX_INPUT_BYTES + 80
            or (len(envelope) - start) % AES.block_size):
        raise ValueError('Invalid ttEncrypt envelope')
    key, iv = _key_iv(envelope[len(PREFIX):start])
    try:
        plaintext = unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(envelope[start:]), AES.block_size)
    except ValueError as exc:
        raise ValueError('Invalid ttEncrypt padding') from exc
    digest, raw = plaintext[:64], plaintext[64:]
    if not 1 <= len(raw) <= MAX_INPUT_BYTES or not hmac.compare_digest(digest, hashlib.sha512(raw).digest()):
        raise ValueError('Invalid ttEncrypt payload digest')
    return raw
