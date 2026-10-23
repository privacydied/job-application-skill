#!/usr/bin/env python3
"""totp.py - RFC 6238 authenticator-app code from a base32 secret (stdlib only).

Use when an ATS forces "Authenticator app" 2FA: the setup page shows a "Manual Entry Key".
Compute the 6-digit code here, enter it, and store the secret in the gitignored
ats-credentials.csv notes so later logins can compute fresh codes.
CLI: python3 scripts/totp.py <BASE32SECRET>   (prints the current code)
"""
import base64
import hmac
import hashlib
import struct
import sys
import time


def totp(secret: str, now: float = None, digits: int = 6, step: int = 30) -> str:
    key = base64.b32decode(secret.replace(" ", "").upper() + "=" * (-len(secret.replace(" ", "")) % 8))
    counter = int((now or time.time()) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 15
    return str((struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % 10 ** digits).zfill(digits)


if __name__ == "__main__":
    print(totp(sys.argv[1]))
