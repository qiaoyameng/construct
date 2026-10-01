from tests.declarativeunittest import *
from construct.lib.bitstream import *


def test_restreamed():
    # tested by Bitwise Bytewise ByteSwapped BitsSwapped cases
    pass

def test_seekable_restreamed():
    # reading, seeking and telling in decoded (bit) units
    data = b"\xab\xcd"
    bstream = SeekableRestreamedBytesIO(io.BytesIO(data), bytes2bits, 1, bits2bytes, 8)
    assert bstream.seekable()
    assert bstream.tellable()
    assert bstream.tell() == 0
    assert bstream.read(4) == bytes2bits(b"\xab")[:4]
    assert bstream.tell() == 4
    # cross-byte unaligned read
    assert bstream.seek(4) == 4
    assert bstream.read(8) == bytes2bits(b"\xbc")
    assert bstream.tell() == 12
    # whence: relative to current position and to EOF
    assert bstream.seek(-4, 1) == 8
    assert bstream.seek(-4, 2) == 12
    assert bstream.read(4) == bytes2bits(b"\xcd")[4:]
    # end boundary: reading at EOF yields nothing
    assert bstream.seek(16) == 16
    assert bstream.read(1) == b""
    assert bstream.read() == b""
    # short read returns only the remaining bits, no zero padding
    assert bstream.seek(12) == 12
    assert bstream.read(8) == bytes2bits(b"\xcd")[4:]
    # negative positions are rejected
    assert raises(bstream.seek, -1) == ValueError
    assert raises(bstream.seek, -17, 2) == ValueError
    # read until EOF
    assert bstream.seek(0) == 0
    assert bstream.read() == bytes2bits(data)
    # closing at unaligned position is rejected
    assert bstream.seek(4) == 4
    assert raises(bstream.close) == ValueError

    # closing at aligned position restores substream to the consumed byte
    outer = io.BytesIO(b"\x00\xab\xcd")
    outer.seek(1)
    bstream = SeekableRestreamedBytesIO(outer, bytes2bits, 1, bits2bytes, 8)
    assert bstream.read(16) == bytes2bits(b"\xab\xcd")
    bstream.close()
    assert outer.tell() == 3

    # writing with unaligned jumps forth and back
    out = io.BytesIO()
    bstream = SeekableRestreamedBytesIO(out, bytes2bits, 1, bits2bytes, 8)
    assert bstream.write(bytes2bits(b"\xab")[:4]) == 4
    assert bstream.seek(8) == 8
    assert bstream.write(bytes2bits(b"\xcd")) == 8
    assert bstream.seek(4) == 4
    assert bstream.write(bytes2bits(b"\xab")[4:]) == 4
    assert bstream.tell() == 8
    bstream.close()
    assert out.getvalue() == b"\xab\xcd"

    # partial overwrite merges with previously written content
    out = io.BytesIO()
    bstream = SeekableRestreamedBytesIO(out, bytes2bits, 1, bits2bytes, 8)
    bstream.write(bytes2bits(b"\xab"))
    assert bstream.seek(0) == 0
    bstream.write(bytes2bits(b"\xc0")[:4])
    assert bstream.seek(8) == 8
    bstream.write(bytes2bits(b"\xcd"))
    bstream.close()
    assert out.getvalue() == b"\xcb\xcd"

    # partial write merges with content that predates the view
    out = io.BytesIO(b"\x0b")
    bstream = SeekableRestreamedBytesIO(out, bytes2bits, 1, bits2bytes, 8)
    bstream.write(bytes2bits(b"\xa0")[:4])
    assert bstream.seek(8) == 8
    bstream.close()
    assert out.getvalue() == b"\xab"

    # partial write without content to merge with is rejected, not zero-padded
    out = io.BytesIO()
    bstream = SeekableRestreamedBytesIO(out, bytes2bits, 1, bits2bytes, 8)
    bstream.write(bytes2bits(b"\xa0")[:4])
    assert raises(bstream.close) == ValueError

    # nested fixed-ratio views, bytes on top of bits (Bytewise semantics)
    outer = io.BytesIO(b"\xab\xcd")
    bits = SeekableRestreamedBytesIO(outer, bytes2bits, 1, bits2bytes, 8)
    bits.read(4)
    bytesview = SeekableRestreamedBytesIO(bits, bits2bytes, 8, bytes2bits, 1)
    assert bytesview.read(1) == b"\xbc"
    assert bytesview.tell() == 1
    assert bytesview.seek(0) == 0
    assert bytesview.read(1) == b"\xbc"
    bytesview.close()
    assert bits.tell() == 12

    # non-seekable substream is rejected
    nonseekable = RestreamedBytesIO(io.BytesIO(b"\x00"), bytes2bits, 1, bits2bytes, 8)
    assert raises(SeekableRestreamedBytesIO, nonseekable, bytes2bits, 1, bits2bytes, 8) == ValueError

    # variable-length codecs are rejected
    import zlib
    assert raises(SeekableRestreamedBytesIO, io.BytesIO(b""), zlib.decompress, 1, zlib.compress, 1) == ValueError

def test_rebuffered():
    z = b"0"

    print("sequential read")
    bstream = RebufferedBytesIO(io.BytesIO(z*1000))
    assert bstream.read(1000) == z*1000

    print("random reads")
    data = os.urandom(1000)
    bstream = RebufferedBytesIO(io.BytesIO(data))
    for i in range(50):
        o1 = random.randrange(0, 480)
        o2 = random.randrange(520, 1000)
        assert bstream.seek(o1) == o1
        assert bstream.tell() == o1
        assert bstream.read(o2-o1) == data[o1:o2]
        assert bstream.tell() == o2

    print("sequential writes")
    bstream = RebufferedBytesIO(io.BytesIO())
    for i in range(10):
        assert bstream.write(z*100) == 100
    assert bstream.seek(0) == 0
    assert bstream.read(1000) == z*1000

    print("random writes")
    data = os.urandom(1000)
    bstream = RebufferedBytesIO(io.BytesIO())
    assert bstream.write(data) == len(data)
    for i in range(50):
        o1 = random.randrange(0, 480)
        o2 = random.randrange(520, 1000)
        assert bstream.seek(o1) == o1
        assert bstream.tell() == o1
        assert bstream.write(data[o1:o2]) == o2-o1
        assert bstream.tell() == o2
    assert bstream.seek(0) == 0
    assert bstream.read(len(data)) == data

    print("cutting off trail")
    data = os.urandom(1000)
    bstream = RebufferedBytesIO(io.BytesIO(data), tailcutoff=50)
    for i in range(15):
        at = bstream.tell()
        assert bstream.read(50) == data[at:at+50]
        jumpback = random.randrange(1, 19)
        assert bstream.seek(-jumpback, 1)
