import base64
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from fan_tracker.aqara_app import (PUBLIC_KEY_PEM, AqaraAppClient, rsa_pkcs1v15_encrypt,
                                   rsa_public_key)


class RsaTest(unittest.TestCase):
    def test_parses_embedded_key(self):
        n, e = rsa_public_key(PUBLIC_KEY_PEM)
        self.assertEqual(n.bit_length(), 1024)
        self.assertEqual(e, 65537)

    @unittest.skipUnless(shutil.which("openssl"), "needs openssl")
    def test_openssl_decrypts_our_ciphertext(self):
        with tempfile.TemporaryDirectory() as d:
            key, pub = Path(d, "k.pem"), Path(d, "p.pem")
            subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt",
                            "rsa_keygen_bits:1024", "-out", key], check=True, capture_output=True)
            subprocess.run(["openssl", "pkey", "-in", key, "-pubout", "-out", pub],
                           check=True, capture_output=True)
            n, e = rsa_public_key(pub.read_text())
            msg = hashlib.md5(b"hunter2").hexdigest().encode()
            ct = Path(d, "ct.bin")
            ct.write_bytes(rsa_pkcs1v15_encrypt(n, e, msg))
            out = subprocess.run(["openssl", "pkeyutl", "-decrypt", "-inkey", key, "-in", ct,
                                  "-pkeyopt", "rsa_padding_mode:pkcs1"],
                                 check=True, capture_output=True).stdout
            self.assertEqual(out, msg)


class SignTest(unittest.TestCase):
    def test_sign_with_and_without_token(self):
        c = AqaraAppClient("a@b.c", "pw")
        c.appid, c.appkey = "APP", "KEY"
        body = '{"x": 1}'
        self.assertEqual(c.sign("N", "T", body, None),
                         hashlib.md5(b'Appid=APP&Nonce=N&Time=T&{"x": 1}&KEY').hexdigest())
        self.assertEqual(c.sign("N", "T", body, "TOK"),
                         hashlib.md5(b'Appid=APP&Nonce=N&Time=T&Token=TOK&{"x": 1}&KEY').hexdigest())


if __name__ == "__main__":
    unittest.main()
