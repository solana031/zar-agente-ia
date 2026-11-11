from cryptography.hazmat.primitives.asymmetric import ec
from app import webpush


def test_rfc8291_vector():
    server = ec.derive_private_key(int.from_bytes(webpush.unb64u('yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw'), 'big'), ec.SECP256R1())
    body = webpush.encrypt(b'When I grow up, I want to be a watermelon',
                           'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4',
                           'BTBZMqHH6r4Tts7J_aSIgg', salt=webpush.unb64u('DGv6ra1nlYgDCS1FRnbzlw'), server_key=server)
    assert webpush.b64u(body) == ('DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_'
                                  'yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN')


def test_vapid_header_is_verifiable(monkeypatch):
    private, public = webpush.generate_keys()
    monkeypatch.setenv('VAPID_PRIVATE_KEY', private)
    monkeypatch.setenv('VAPID_PUBLIC_KEY', public)
    header = webpush.vapid_header('https://fcm.googleapis.com/fcm/send/abc')
    token = header.split('t=')[1].split(',')[0]
    head, claims, sig = token.split('.')
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    raw = webpush.unb64u(sig)
    key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), webpush.unb64u(public))
    key.verify(encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big')), (head + '.' + claims).encode(), ec.ECDSA(hashes.SHA256()))
    assert '"aud":"https://fcm.googleapis.com"' in webpush.unb64u(claims).decode()
