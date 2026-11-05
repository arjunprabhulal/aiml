"""Signed JSON Web Tokens (HS256) with the checks a receiver must make. Standard library only.

A token is three base64url parts joined by dots: a header, a claims set and an
HMAC-SHA256 signature over the first two (RFC 7515 compact serialization, RFC 7519
claims). verify() accepts a token only when every check passes, in this order:

  form       three parts that decode to JSON objects
  algorithm  the header names HS256, the only algorithm this receiver allows (RFC 8725 3.1)
  type       the header's typ is the one this receiver expects, so a session token
             cannot pass as a tool token (RFC 8725 3.11)
  signature  HMAC-SHA256 with the issuer's key, compared in constant time
  audience   aud names this receiver (RFC 7519 4.1.3, RFC 8725 3.9)
  expiry     the current time is before exp (RFC 7519 4.1.4)
  replay     a token with a jti is accepted once per receiver (RFC 7519 4.1.7)

The keys below are teaching values printed in the source; a real issuer keeps its
key in a secret store and rotates it.
"""
import base64
import hashlib
import hmac
import json

ISSUER = "support-gateway"
KEYS = {ISSUER: b"teaching-key-not-a-secret-0123456789abcdef"}


class TokenError(ValueError):
    """The token was refused. The message names the first check that failed."""


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(claims, typ, issuer=ISSUER):
    header = {"alg": "HS256", "typ": typ}
    head = _b64(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    body = _b64(json.dumps({"iss": issuer, **claims}, separators=(",", ":"), sort_keys=True).encode())
    mac = hmac.new(KEYS[issuer], f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{_b64(mac)}"


def verify(token, audience, typ, now, seen_jti=None):
    """Return the claims of a valid token, or raise TokenError naming the failed check."""
    parts = token.split(".") if isinstance(token, str) else []
    try:
        header, claims = (json.loads(_unb64(part)) for part in parts[:2])
        signature = _unb64(parts[2])
        if len(parts) != 3 or not isinstance(header, dict) or not isinstance(claims, dict):
            raise ValueError
    except (ValueError, IndexError):
        raise TokenError("form: not a signed token") from None
    if header.get("alg") != "HS256":
        raise TokenError(f"algorithm: {header.get('alg')!r} is not allowed")
    if header.get("typ") != typ:
        raise TokenError(f"type: expected {typ}, got {header.get('typ')!r}")
    key = KEYS.get(claims.get("iss"))
    expected = key and hmac.new(key, f"{parts[0]}.{parts[1]}".encode(), hashlib.sha256).digest()
    if not expected or not hmac.compare_digest(expected, signature):
        raise TokenError("signature: does not match")
    if claims.get("aud") != audience:
        raise TokenError(f"audience: issued for {claims.get('aud')!r}, not {audience!r}")
    if not isinstance(claims.get("exp"), int) or now >= claims["exp"]:
        raise TokenError("expiry: the token has expired")
    if seen_jti is not None:
        if claims.get("jti") in seen_jti or not claims.get("jti"):
            raise TokenError("replay: this token was already used")
        seen_jti.add(claims["jti"])
    return claims
