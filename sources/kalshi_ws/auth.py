"""Kalshi RSA-PSS request signer. See docs.kalshi.com/getting_started/api_keys."""
import base64
import time
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


class KalshiSigner:
    def __init__(self, key_id: str, private_key_path: str):
        self.key_id = key_id
        self._key = serialization.load_pem_private_key(
            Path(private_key_path).read_bytes(), password=None)

    def sign(self, timestamp_ms: str, method: str, path: str) -> str:
        msg = (timestamp_ms + method + path).encode()
        sig = self._key.sign(
            msg,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=hashes.SHA256().digest_size),
            hashes.SHA256())
        return base64.b64encode(sig).decode()

    def headers(self, method: str, path: str, now_ms: int | None = None) -> dict[str, str]:
        ts = str(now_ms if now_ms is not None else int(time.time() * 1000))
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": self.sign(ts, method, path),
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
