from common.storage import FrameWriter, read_frames


def test_write_read_roundtrip(tmp_path):
    p = tmp_path / "cap.bin"
    with FrameWriter(p) as w:
        w.write(1000, b"hello")
        w.write(2000, b"world!!")
    frames = list(read_frames(p))
    assert frames == [(1000, b"hello"), (2000, b"world!!")]


def test_truncated_tail_is_ignored(tmp_path):
    p = tmp_path / "cap.bin"
    with FrameWriter(p) as w:
        w.write(1, b"ok")
    with open(p, "ab") as f:
        f.write(b"\x05\x00")  # partial header, must not crash the reader
    assert list(read_frames(p)) == [(1, b"ok")]
