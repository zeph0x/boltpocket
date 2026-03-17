"""
NXP NTAG424 DNA Secure Unique NFC (SUN) verification.
Reference: https://www.nxp.com/docs/en/application-note/AN12196.pdf

Decrypts the 'p' parameter (PICCData) to extract UID and counter,
and verifies the 'c' parameter (CMAC) to ensure authenticity.
"""

from Crypto.Cipher import AES
from Crypto.Hash import CMAC

# SV2 prefix for CMAC calculation (per NXP spec)
SV2 = "3CC300010080"


def cmac(key: bytes, msg: bytes = b"") -> bytes:
    """Calculate AES-CMAC."""
    cobj = CMAC.new(key, ciphermod=AES)
    if msg != b"":
        cobj.update(msg)
    return cobj.digest()


def decrypt_sun(p: bytes, k1: bytes) -> tuple[bytes, bytes]:
    """
    Decrypt the SUN (p parameter) using K1 (meta key).
    Returns (uid, counter) as raw bytes.
    uid: 7 bytes, counter: 3 bytes (little-endian).
    """
    iv = b"\x00" * 16
    cipher = AES.new(k1, AES.MODE_CBC, iv)
    plaintext = cipher.decrypt(p)

    uid = plaintext[1:8]
    counter = plaintext[8:11]

    return uid, counter


def get_sun_mac(uid: bytes, counter: bytes, k2: bytes) -> bytes:
    """
    Calculate expected CMAC (c parameter) using K2 (file key).
    Returns 8 bytes (every other byte of the full CMAC).
    """
    sv2_prefix = bytes.fromhex(SV2)
    sv2 = sv2_prefix + uid + counter

    mac1 = cmac(k2, sv2)
    mac2 = cmac(mac1)

    # Take every other byte starting from index 1
    return mac2[1::2]


def verify_tap(p_hex: str, c_hex: str, k1_hex: str, k2_hex: str, expected_uid_hex: str) -> tuple[bool, int, str, str]:
    """
    Verify a bolt card tap.

    Args:
        p_hex: encrypted PICCData from URL (32 hex chars)
        c_hex: CMAC from URL (16 hex chars)
        k1_hex: meta key (32 hex chars)
        k2_hex: file key (32 hex chars)
        expected_uid_hex: expected card UID (14 hex chars), or '00000000000000' to accept any

    Returns:
        (success, counter_value, error_message, actual_uid_hex)
    """
    try:
        p = bytes.fromhex(p_hex)
        c = bytes.fromhex(c_hex)
        k1 = bytes.fromhex(k1_hex)
        k2 = bytes.fromhex(k2_hex)
    except ValueError:
        return False, 0, "Invalid hex data", ""

    try:
        uid, counter = decrypt_sun(p, k1)
    except Exception:
        return False, 0, "Decryption failed", ""

    actual_uid = uid.hex().upper()

    # Verify UID matches (skip if placeholder)
    if expected_uid_hex.upper() != '00000000000000' and actual_uid != expected_uid_hex.upper():
        return False, 0, "UID mismatch", actual_uid

    # Verify CMAC
    expected_mac = get_sun_mac(uid, counter, k2)
    if c.hex().upper() != expected_mac.hex().upper():
        return False, 0, "CMAC verification failed", actual_uid

    # Extract counter (little-endian, 3 bytes)
    counter_int = int.from_bytes(counter, "little")

    return True, counter_int, "", actual_uid
