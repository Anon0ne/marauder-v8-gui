"""Client tests for marauder_sdfs against a simulated `sd` firmware command."""

import base64
import os
import shlex
import shutil
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from marauder_sdfs import SDError, SDFiles


class FakeSerial:
    def __init__(self, device):
        self.device = device
        self.rx = b""

    @property
    def in_waiting(self):
        return len(self.rx)

    def read(self, n):
        data, self.rx = self.rx[:n], self.rx[n:]
        return data

    def reset_input_buffer(self):
        self.rx = b""


class FakeMarauder:
    """Answers like the firmware: echo, output lines, result line, prompt."""

    def __init__(self, root, chunk=256):
        self.root = root
        self.chunk = chunk
        self.ser = FakeSerial(self)
        self.put = None
        self.corrupt_get = False

    def _out(self, *lines):
        self.ser.rx += "".join(line + "\n" for line in lines).encode()

    def _local(self, path):
        return os.path.join(self.root, path.lstrip("/"))

    def send(self, command):
        if self.put is not None:
            return self._put_line(command)
        args = shlex.split(command)
        self._out("#" + command)
        sub = args[1]
        flags = [a for a in args[2:] if a.startswith("-")]
        pos = [a for a in args[2:] if not a.startswith("-")]
        try:
            getattr(self, "_" + sub)(pos, flags)
        except FileNotFoundError:
            self._out(f"@SD:ERR {sub} NOT_FOUND")
        if self.put is None:
            self.ser.rx += b"> "

    def _ls(self, pos, flags):
        path = self._local(pos[0] if pos else "/")
        names = sorted(os.listdir(path))
        for name in names:
            full = os.path.join(path, name)
            self._out(f"D\t{name}" if os.path.isdir(full) else f"F\t{name}\t{os.path.getsize(full)}")
        self._out(f"@SD:OK ls {len(names)}")

    def _df(self, pos, flags):
        self._out("Total: 1 MB", "@SD:OK df 1048576 4096")

    def _mkdir(self, pos, flags):
        os.makedirs(self._local(pos[0]), exist_ok=True)
        self._out(f"@SD:OK mkdir {pos[0]}")

    def _rm(self, pos, flags):
        path = self._local(pos[0])
        if os.path.isdir(path):
            if "-r" in flags:
                shutil.rmtree(path)
            elif os.listdir(path):
                return self._out("@SD:ERR rm DIRECTORY_NOT_EMPTY")
            else:
                os.rmdir(path)
        else:
            os.remove(path)
        self._out(f"@SD:OK rm {pos[0]}")

    def _mv(self, pos, flags):
        os.rename(self._local(pos[0]), self._local(pos[1]))
        self._out(f"@SD:OK mv {pos[1]}")

    def _cp(self, pos, flags):
        src = self._local(pos[0])
        if os.path.isdir(src):
            if "-r" not in flags:
                return self._out("@SD:ERR cp IS_DIRECTORY_USE_-r")
            shutil.copytree(src, self._local(pos[1]))
        else:
            shutil.copyfile(src, self._local(pos[1]))
        self._out(f"@SD:OK cp {pos[1]}")

    def _crc(self, pos, flags):
        data = Path(self._local(pos[0])).read_bytes()
        self._out(f"@SD:OK crc {zlib.crc32(data):08x} {len(data)}")

    def _get(self, pos, flags):
        data = Path(self._local(pos[0])).read_bytes()
        self._out(f"@SD:GET {len(data)}")
        for i in range(0, len(data), 384):
            piece = data[i:i + 384]
            if self.corrupt_get:
                piece = bytes([piece[0] ^ 1]) + piece[1:]
            self._out("@SD:D " + base64.b64encode(piece).decode())
        self._out(f"@SD:OK get {zlib.crc32(data):08x}")

    def _put(self, pos, flags):
        self.put = {"path": self._local(pos[0]), "size": int(pos[1]),
                    "crc": int(pos[2], 16), "data": b""}
        self._out(f"@SD:READY {self.chunk}")
        if self.put["size"] == 0:
            self._finish_put()

    def _put_line(self, line):
        if line == "@SD:ABORT":
            self.put = None
            return self._out("@SD:ERR put ABORTED")
        self.put["data"] += base64.b64decode(line[6:])
        self._out(f"@SD:ACK {len(self.put['data'])}")
        if len(self.put["data"]) >= self.put["size"]:
            self._finish_put()

    def _finish_put(self):
        put, self.put = self.put, None
        if zlib.crc32(put["data"]) != put["crc"]:
            self._out("@SD:ERR put CRC_MISMATCH")
        else:
            with open(put["path"], "wb") as f:
                f.write(put["data"])
            self._out(f"@SD:OK put {put['crc']:08x}")
        self.ser.rx += b"> "


class SDFilesTests(unittest.TestCase):
    def setUp(self):
        self.card = tempfile.mkdtemp()
        self.pc = tempfile.mkdtemp()
        self.dev = FakeMarauder(self.card)
        self.fs = SDFiles(self.dev, line_timeout=0.5)

    def tearDown(self):
        shutil.rmtree(self.card)
        shutil.rmtree(self.pc)

    def test_upload_download_round_trip(self):
        payload = os.urandom(5000)
        src = os.path.join(self.pc, "in.bin")
        with open(src, "wb") as f:
            f.write(payload)
        seen = []
        self.assertEqual(self.fs.upload(src, "/in.bin", lambda d, t: seen.append(d)), 5000)
        self.assertEqual(seen[-1], 5000)
        dst = os.path.join(self.pc, "out.bin")
        self.assertEqual(self.fs.download("/in.bin", dst), 5000)
        self.assertEqual(Path(dst).read_bytes(), payload)
        self.assertEqual(self.fs.crc("/in.bin"), (zlib.crc32(payload), 5000))

    def test_empty_file_upload(self):
        src = os.path.join(self.pc, "empty.txt")
        open(src, "wb").close()
        self.assertEqual(self.fs.upload(src, "/empty.txt"), 0)
        self.assertEqual(os.path.getsize(os.path.join(self.card, "empty.txt")), 0)

    def test_corrupt_download_is_rejected_and_not_saved(self):
        with open(os.path.join(self.card, "a.bin"), "wb") as f:
            f.write(os.urandom(1000))
        self.dev.corrupt_get = True
        dst = os.path.join(self.pc, "a.bin")
        with self.assertRaises(SDError):
            self.fs.download("/a.bin", dst)
        self.assertFalse(os.path.exists(dst))
        self.assertFalse(os.path.exists(dst + ".part"))

    def test_listing_and_file_operations(self):
        self.fs.mkdir("/logs")
        with open(os.path.join(self.card, "logs", "scan.pcap"), "wb") as f:
            f.write(b"x" * 42)
        entries = self.fs.ls("/")
        self.assertEqual([(e.name, e.is_dir) for e in entries], [("logs", True)])
        self.assertEqual(self.fs.ls("/logs")[0].size, 42)
        self.fs.cp("/logs/scan.pcap", "/logs/copy.pcap")
        self.fs.mv("/logs/copy.pcap", "/moved.pcap")
        self.assertEqual({e.name for e in self.fs.ls("/")}, {"logs", "moved.pcap"})
        with self.assertRaises(SDError):
            self.fs.rm("/logs")
        self.fs.rm("/logs", recursive=True)
        self.assertEqual([e.name for e in self.fs.ls("/")], ["moved.pcap"])
        self.assertEqual(self.fs.df(), (1048576, 4096))

    def test_rejects_quote_in_path(self):
        with self.assertRaises(SDError):
            self.fs.rm('/bad"name')


if __name__ == "__main__":
    unittest.main()
