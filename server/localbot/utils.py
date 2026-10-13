"""
Utility functions for localbot SDK (e.g. HMAC-SHA256 signature calculation)
"""
import hmac
import hashlib
import base64

def calculate_signature(secret: str, body: str | bytes) -> str:
    """Calculate HMAC-SHA256 signature as base64 string."""
    if isinstance(body, str):
        body = body.encode('utf-8')
    secret_bytes = secret.encode('utf-8') if isinstance(secret, str) else secret
    hash_value = hmac.new(secret_bytes, body, hashlib.sha256).digest()
    return base64.b64encode(hash_value).decode('utf-8')

def check_signature(secret: str, body: str | bytes, signature: str) -> bool:
    """Verify if the signature matches HMAC-SHA256 of body using secret."""
    if not signature:
        return False
    expected = calculate_signature(secret, body)
    return hmac.compare_digest(expected, signature)
