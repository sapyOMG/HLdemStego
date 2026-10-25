"""
Suite de pruebas para HLdemStego (arquitectura con clave criptografica).
Solo usa unittest (stdlib). Sin dependencias externas.

    python -m unittest discover tests/ -v
"""

import os, sys, struct, zlib, base64, tempfile, shutil, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from hldemstego.constants    import (CHUNK_SIZE, FRAME_STRINGCMD, FRAME_LASTRECORD,
                                    FRAME_CLIENTDATA, HEADER_SIZE, DEMO_MAGIC)
from hldemstego.cryptocore   import (derive_key, encrypt, decrypt, permute_secure,
                                    inverse_permute_secure, safe_filename,
                                    validate_payload_limits, _HMACCSPRNG,
                                    MAX_CHUNKS, MAX_PLAINTEXT)
from hldemstego.input_handler import prepare_payload, reconstruct_payload, validate_capacity
from hldemstego.entropy       import collect_cd_frames, build_key, shuffle_chunks, unshuffle_chunks
from hldemstego.stego         import make_injection_frames, parse_dc_commands
from hldemstego.dem_io        import (Frame, make_stringcmd_frame, serialize_frame,
                                     DemoHeader, DirEntry, parse_header, parse_directory,
                                     serialize_header, serialize_directory,
                                     scan_dc_commands, scan_clientdata_frames,
                                     surgical_save_dem)


# --- Helpers ---

def _cd_frame(ts, z, wb=0):
    body = struct.pack("<6fIf", 0.0, 0.0, z, 0.0, 0.0, 0.0, wb, 90.0)
    f = Frame(ts, FRAME_CLIENTDATA, body)
    f.origin=(0.0,0.0,z); f.viewangles=(0.0,0.0,0.0); f.weaponbits=wb; f.fov=90.0
    return f

def _end_frame(ts=30.0):
    return Frame(ts, FRAME_LASTRECORD, b"")

def _basic_frames(dur=60.0, n=5):
    frames=[]; pz=0.0; step=dur/(n+1)
    for i in range(n):
        ts=step*(i+1)
        frames.append(_cd_frame(ts-0.01, pz))
        frames.append(_cd_frame(ts, pz+5.0))
        pz+=5.0
    frames.append(_end_frame(dur))
    return frames

def _minimal_dem(dur=60.0, n=5):
    frames  = _basic_frames(dur, n)
    seg     = b"".join(serialize_frame(f) for f in frames)
    hdr     = bytearray(544)  # always 544, not HEADER_SIZE variable
    hdr[:8] = DEMO_MAGIC
    struct.pack_into("<ii", hdr, 8, 5, 48)
    hdr[16:24]  = b"dc_test\x00"    # 8 bytes exact
    hdr[276:284] = b"cstrike\x00"   # 8 bytes exact
    dir_off = 544 + len(seg)
    struct.pack_into("<Ii", hdr, 536, 0, dir_off)
    entry = DirEntry(1,"Playback",0,0,dur,len(frames),HEADER_SIZE,len(seg))
    return bytes(hdr) + seg + serialize_directory([entry])

def _load(raw):
    hdr  = parse_header(raw)
    dire = parse_directory(raw, hdr.dir_offset)
    return hdr, dire


# ================================================================
#  Test 1 - cryptocore
# ================================================================
class TestCryptocoreBasics(unittest.TestCase):

    def test_hmac_csprng_deterministic(self):
        key = b"testkey" * 4
        r1 = _HMACCSPRNG(key)
        r2 = _HMACCSPRNG(key)
        vals1 = [r1.randbelow(1000) for _ in range(20)]
        vals2 = [r2.randbelow(1000) for _ in range(20)]
        self.assertEqual(vals1, vals2)

    def test_hmac_csprng_different_keys(self):
        r1 = _HMACCSPRNG(b"key1" * 8)
        r2 = _HMACCSPRNG(b"key2" * 8)
        v1 = [r1.randbelow(10000) for _ in range(10)]
        v2 = [r2.randbelow(10000) for _ in range(10)]
        self.assertNotEqual(v1, v2)

    def test_encrypt_decrypt_roundtrip(self):
        key  = os.urandom(32)
        data = b"secreto!" * 100
        payload, mac = encrypt(data, key)
        result = decrypt(payload, key, mac)
        self.assertEqual(result, data)

    def test_wrong_key_raises(self):
        key1 = os.urandom(32)
        key2 = os.urandom(32)
        data = b"data" * 50
        payload, mac = encrypt(data, key1)
        with self.assertRaises(ValueError):
            decrypt(payload, key2, mac)

    def test_tampered_payload_raises(self):
        key = os.urandom(32)
        data = b"integrity check"
        payload, mac = encrypt(data, key)
        tampered = bytearray(payload)
        tampered[20] ^= 0xFF
        with self.assertRaises(ValueError):
            decrypt(bytes(tampered), key, mac)

    def test_permute_secure_deterministic(self):
        key = b"shufflekey" * 3
        p1 = permute_secure(20, key)
        p2 = permute_secure(20, key)
        self.assertEqual(p1, p2)

    def test_permute_inverse_correct(self):
        key = os.urandom(32)
        for n in (1, 5, 20, 100):
            perm = permute_secure(n, key)
            inv  = inverse_permute_secure(n, key)
            for k in range(n):
                self.assertEqual(inv[perm[k]], k)

    def test_safe_filename_traversal(self):
        self.assertEqual(safe_filename("../../etc/passwd"), "passwd")
        self.assertEqual(safe_filename("/abs/path/file.txt"), "file.txt")
        self.assertEqual(safe_filename("normal.txt"), "normal.txt")
        self.assertNotEqual(safe_filename(""), "")  # fallback
        self.assertNotIn("..", safe_filename("../../evil"))

    def test_validate_limits_ok(self):
        validate_payload_limits(10, "A" * 100)  # should not raise

    def test_validate_limits_chunks_exceeded(self):
        with self.assertRaises(ValueError):
            validate_payload_limits(MAX_CHUNKS + 1, "")

    def test_validate_limits_b64_exceeded(self):
        from hldemstego.cryptocore import MAX_PAYLOAD_B64
        with self.assertRaises(ValueError):
            validate_payload_limits(1, "A" * (MAX_PAYLOAD_B64 + 1))


# ================================================================
#  Test 2 - derive_key
# ================================================================
class TestDeriveKey(unittest.TestCase):

    def _frames(self, n=10):
        return _basic_frames(60.0, n)

    def test_key_deterministic_same_frames(self):
        frames = collect_cd_frames(self._frames())
        k1 = derive_key(frames)
        k2 = derive_key(frames)
        self.assertEqual(k1, k2)

    def test_key_32_bytes(self):
        frames = collect_cd_frames(self._frames())
        self.assertEqual(len(derive_key(frames)), 32)

    def test_key_changes_with_frames(self):
        f1 = collect_cd_frames(_basic_frames(60.0, 5))
        f2 = collect_cd_frames(_basic_frames(60.0, 8))
        self.assertNotEqual(derive_key(f1), derive_key(f2))

    def test_password_changes_key(self):
        frames = collect_cd_frames(self._frames())
        k1 = derive_key(frames, password=None)
        k2 = derive_key(frames, password="hola")
        k3 = derive_key(frames, password="chau")
        self.assertNotEqual(k1, k2)
        self.assertNotEqual(k2, k3)

    def test_no_frames_no_password_raises(self):
        with self.assertRaises(ValueError):
            derive_key([])

    def test_no_frames_with_password_ok(self):
        key = derive_key([], password="somepassword")
        self.assertEqual(len(key), 32)


# ================================================================
#  Test 3 - entropy / shuffle
# ================================================================
class TestEntropyShuffle(unittest.TestCase):

    def test_shuffle_unshuffle(self):
        key    = os.urandom(32)
        chunks = [f"chunk_{i}" for i in range(20)]
        sh, _  = shuffle_chunks(chunks, key)
        self.assertNotEqual(sh, chunks)
        self.assertEqual(unshuffle_chunks(sh, key), chunks)

    def test_collect_cd_frames(self):
        frames = _basic_frames(60.0, 5)
        cd = collect_cd_frames(frames)
        self.assertGreater(len(cd), 0)
        for f in cd:
            self.assertEqual(f.ftype, FRAME_CLIENTDATA)
            self.assertIsNotNone(f.origin)


# ================================================================
#  Test 4 - input_handler
# ================================================================
class TestInputHandler(unittest.TestCase):

    def _tmp(self, data):
        fd, p = tempfile.mkstemp()
        os.write(fd, data); os.close(fd)
        self.addCleanup(os.unlink, p)
        return p

    def test_roundtrip_no_key(self):
        secret = b"SECRETO " * 100
        src = self._tmp(secret)
        outdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outdir)
        chunks, fn, _, _, mac = prepare_payload(src, key=None)
        out = reconstruct_payload(chunks, outdir, fn, key=None)
        self.assertEqual(open(out,"rb").read(), secret)

    def test_roundtrip_with_key(self):
        secret = b"CIFRADO " * 100
        key = os.urandom(32)
        src = self._tmp(secret)
        outdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outdir)
        chunks, fn, _, _, mac = prepare_payload(src, key=key)
        out = reconstruct_payload(chunks, outdir, fn, key=key, mac=mac)
        self.assertEqual(open(out,"rb").read(), secret)

    def test_wrong_key_fails(self):
        secret = b"DATOS SECRETOS"
        key1 = os.urandom(32)
        key2 = os.urandom(32)
        src = self._tmp(secret)
        outdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outdir)
        chunks, fn, _, _, mac = prepare_payload(src, key=key1)
        with self.assertRaises(Exception):
            reconstruct_payload(chunks, outdir, fn, key=key2, mac=mac)

    def test_path_traversal_sanitized(self):
        from hldemstego.cryptocore import safe_filename
        self.assertNotIn("..", safe_filename("../../secret"))
        self.assertNotIn("/", safe_filename("/etc/passwd"))

    def test_chunk_size_respected(self):
        src = self._tmp(b"x" * 5000)
        chunks, *_ = prepare_payload(src)
        for c in chunks:
            self.assertLessEqual(len(c), CHUNK_SIZE)


# ================================================================
#  Test 5 - stego (make / parse con MAC)
# ================================================================
class TestStego(unittest.TestCase):

    def test_roundtrip_with_mac(self):
        mac    = os.urandom(32)
        chunks = [f"B64DATA_{i:03d}" for i in range(5)]
        frames = make_injection_frames(chunks, "test.txt", 1.0, 30.0, mac=mac)
        cmds   = [f.cmd for f in frames if f.cmd]
        fn, total, extracted, recovered_mac = parse_dc_commands(cmds)
        self.assertEqual(fn, "test.txt")
        self.assertEqual(extracted, chunks)
        self.assertEqual(recovered_mac, mac)

    def test_no_head_raises(self):
        with self.assertRaises(ValueError):
            parse_dc_commands(["HL:END:AAAA"])

    def test_timestamps_monotonic(self):
        chunks = ["A"] * 10
        frames = make_injection_frames(chunks, "f", 1.0, 50.0)
        ts = [f.timestamp for f in frames]
        for a,b in zip(ts, ts[1:]):
            self.assertLessEqual(a, b)


# ================================================================
#  Test 6 - pipeline end-to-end en memoria
# ================================================================
class TestPipelineE2E(unittest.TestCase):

    def _run(self, secret, n_events=8, password=None):
        tmpdir = tempfile.mkdtemp()
        try:
            src   = os.path.join(tmpdir, "secreto.bin")
            base  = os.path.join(tmpdir, "base.dem")
            stego = os.path.join(tmpdir, "stego.dem")
            outd  = os.path.join(tmpdir, "out")
            os.makedirs(outd)
            with open(src,"wb") as f: f.write(secret)
            with open(base,"wb") as f: f.write(_minimal_dem(120.0, n_events))
            from hldemstego.pipeline import encode, decode
            encode(src, base, stego, password=password, force=True)
            self.assertGreater(os.path.getsize(stego), os.path.getsize(base))
            out = decode(stego, outd, password=password)
            self.assertEqual(open(out,"rb").read(), secret)
        finally:
            shutil.rmtree(tmpdir)

    def test_small_text(self):
        self._run(b"Hola mundo!" * 10)

    def test_binary(self):
        self._run(bytes(range(256)) * 5)

    def test_with_password(self):
        self._run(b"cifrado con password" * 20, password="mipassword123")

    def test_wrong_password_fails(self):
        tmpdir = tempfile.mkdtemp()
        try:
            src   = os.path.join(tmpdir, "s.bin")
            base  = os.path.join(tmpdir, "b.dem")
            stego = os.path.join(tmpdir, "st.dem")
            outd  = os.path.join(tmpdir, "o")
            os.makedirs(outd)
            with open(src,"wb") as f: f.write(b"secreto" * 50)
            with open(base,"wb") as f: f.write(_minimal_dem(120.0, 8))
            from hldemstego.pipeline import encode, decode
            encode(src, base, stego, password="correcta", force=True)
            with self.assertRaises(Exception):
                decode(stego, outd, password="incorrecta")
        finally:
            shutil.rmtree(tmpdir)

    def test_large(self):
        self._run(os.urandom(8192), n_events=12)


if __name__ == "__main__":
    unittest.main(verbosity=2)
