import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from sources.kalshi_ws.auth import KalshiSigner


def _make_key(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption())
    p = tmp_path / "k.pem"
    p.write_bytes(pem)
    return p, key.public_key()


def test_signature_verifies(tmp_path):
    path, pub = _make_key(tmp_path)
    signer = KalshiSigner("kid-123", str(path))
    sig_b64 = signer.sign("1700000000000", "GET", "/trade-api/ws/v2")
    msg = ("1700000000000" + "GET" + "/trade-api/ws/v2").encode()
    pub.verify(
        base64.b64decode(sig_b64), msg,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
        hashes.SHA256())


def test_headers_shape(tmp_path):
    path, _ = _make_key(tmp_path)
    signer = KalshiSigner("kid-123", str(path))
    h = signer.headers("GET", "/trade-api/ws/v2", now_ms=1700000000000)
    assert h["KALSHI-ACCESS-KEY"] == "kid-123"
    assert h["KALSHI-ACCESS-TIMESTAMP"] == "1700000000000"
    assert isinstance(h["KALSHI-ACCESS-SIGNATURE"], str) and h["KALSHI-ACCESS-SIGNATURE"]
