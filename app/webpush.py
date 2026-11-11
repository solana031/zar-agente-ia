"""Minimal standards-based Web Push (RFC 8291 aes128gcm + RFC 8292 VAPID).

Free push delivery to the owner's browsers/PWA through the browser vendors' push
services; no third-party SDK. Keys come from VAPID_PRIVATE_KEY / VAPID_PUBLIC_KEY
(base64url raw P-256 values). Payloads are encrypted end-to-end for each device.
"""
import base64
import json
import os
import struct
import time
from urllib.parse import urlsplit

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SUBJECT = 'mailto:zaragente031@gmail.com'


def b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def unb64u(text):
    text = str(text or '')
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def configured():
    return bool(os.environ.get('VAPID_PRIVATE_KEY') and os.environ.get('VAPID_PUBLIC_KEY'))


def public_key():
    return os.environ.get('VAPID_PUBLIC_KEY', '')


def generate_keys():
    private = ec.generate_private_key(ec.SECP256R1())
    d = private.private_numbers().private_value.to_bytes(32, 'big')
    pub = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64u(d), b64u(pub)


def _private_key():
    d = int.from_bytes(unb64u(os.environ['VAPID_PRIVATE_KEY']), 'big')
    return ec.derive_private_key(d, ec.SECP256R1())


def vapid_header(endpoint):
    parts = urlsplit(endpoint)
    header = b64u(json.dumps({'typ': 'JWT', 'alg': 'ES256'}, separators=(',', ':')).encode())
    claims = b64u(json.dumps({'aud': parts.scheme + '://' + parts.netloc, 'exp': int(time.time()) + 12 * 3600,
                              'sub': SUBJECT}, separators=(',', ':')).encode())
    signing_input = (header + '.' + claims).encode()
    der = _private_key().sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    token = header + '.' + claims + '.' + b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))
    return 'vapid t=%s, k=%s' % (token, public_key())


def _hkdf(salt, ikm, info, length):
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(payload, p256dh, auth, salt=None, server_key=None):
    ua_public = unb64u(p256dh)
    auth_secret = unb64u(auth)
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = server_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = server_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    prk = _hkdf(auth_secret, shared, b'WebPush: info\x00' + ua_public + as_public, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, prk, b'Content-Encoding: aes128gcm\x00', 16)
    nonce = _hkdf(salt, prk, b'Content-Encoding: nonce\x00', 12)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b'\x02', None)
    return salt + struct.pack('!IB', 4096, len(as_public)) + as_public + ciphertext


class PushGone(Exception):
    pass


def send(subscription, data, ttl=600, urgency='high'):
    if not configured():
        raise ValueError('PUSH_NOT_CONFIGURED')
    endpoint = subscription['endpoint']
    if urlsplit(endpoint).scheme != 'https':
        raise ValueError('PUSH_ENDPOINT_INVALID')
    body = encrypt(json.dumps(data, ensure_ascii=False).encode()[:3000], subscription['keys']['p256dh'], subscription['keys']['auth'])
    response = requests.post(endpoint, data=body, timeout=(5, 15), allow_redirects=False, headers={
        'Content-Encoding': 'aes128gcm', 'Content-Type': 'application/octet-stream', 'TTL': str(ttl),
        'Urgency': urgency, 'Authorization': vapid_header(endpoint)})
    if response.status_code in (404, 410):
        raise PushGone()
    if not response.ok:
        raise ValueError('PUSH_HTTP_%s' % response.status_code)
    return True
