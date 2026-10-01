from tests.declarativeunittest import *
from construct.lib.bitstream import *


def test_restreamed():
    # tested by Bitwise Bytewise ByteSwapped BitsSwapped cases
    pass

def test_seekable_restreamed():
    # only fixed-ratio codecs are supported, variable-length ones are rejected
    assert raises(lambda: SeekableRestreamedBytesIO(io.BytesIO(b"\x00"), lambda b: b.replace(b"\x00", b""), 1, ident, 1)) == ValueError
    assert raises(lambda: SeekableRestreamedBytesIO(io.BytesIO(b"\x00"), bytes2bits, 1, lambda b: b.replace(b"\x00", b""), 8)) == ValueError

    data = bytes([0b10100011, 0b01011010, 0xff])
    bits = bytes2bits(data)

    # sequential reading and telling in logical (bit) units
    bstream = SeekableRestreamedBytesIO(io.BytesIO(data), bytes2bits, 1, bits2bytes, 8)
    assert bstream.seekable()
    assert bstream.tellable()
    assert bstream.tell() == 0
    assert bstream.read(4) == bits[0:4]
    assert bstream.tell() == 4
    assert bstream.read(4) == bits[4:8]
    assert bstream.tell() == 8
    assert bstream.read(6) == bits[8:14]
    assert bstream.tell() == 14
    assert bstream.read(2) == bits[14:16]
    bstream.close()

    # unaligned seeks back and forth, cross-byte reads stay correct
    bstream = SeekableRestreamedBytesIO(io.BytesIO(data), bytes2bits, 1, bits2bytes, 8)
    for at in (3, 17, 9, 20, 0, 13, 8, 21):
        assert bstream.seek(at) == at
        assert bstream.tell() == at
        assert bstream.read(3) == bits[at:at+3]
        assert bstream.tell() == at+3
    bstream.close()

    # whence 1 (relative) and 2 (from EOF)
    bstream = SeekableRestreamedBytesIO(io.BytesIO(data), bytes2bits, 1, bits2bytes, 8)
    assert bstream.seek(5) == 5
    assert bstream.seek(6, 1) == 11
    assert bstream.read(2) == bits[11:13]
    assert bstream.seek(-4, 2) == 20
    assert bstream.read(4) == bits[20:24]
    assert raises(bstream.seek, -1) == ValueError
    bstream.close()

    # short reads at the end boundary
    bstream = SeekableRestreamedBytesIO(io.BytesIO(data), bytes2bits, 1, bits2bytes, 8)
    assert bstream.seek(20) == 20
    assert bstream.read(8) == bits[20:24]
    assert bstream.tell() == 24
    assert bstream.read(1) == b""
    assert bstream.read() == b""
    bstream.close()

    # closing restores the correct byte position in the outer stream
    outer = io.BytesIO(data)
    bstream = SeekableRestreamedBytesIO(outer, bytes2bits, 1, bits2bytes, 8)
    assert bstream.read(8) == bits[0:8]
    bstream.close()
    assert outer.tell() == 1
    outer = io.BytesIO(data)
    bstream = SeekableRestreamedBytesIO(outer, bytes2bits, 1, bits2bytes, 8)
    bstream.seek(16)
    assert bstream.read(8) == bits[16:24]
    bstream.close()
    assert outer.tell() == 3

    # unaligned leftover is rejected on close, not zero-padded
    bstream = SeekableRestreamedBytesIO(io.BytesIO(data), bytes2bits, 1, bits2bytes, 8)
    assert bstream.read(4) == bits[0:4]
    assert raises(bstream.close) == ValueError

    # writing with aligned seeks, then reading back
    outer = io.BytesIO()
    bstream = SeekableRestreamedBytesIO(outer, bytes2bits, 1, bits2bytes, 8)
    assert bstream.write(bits[0:8]) == 8
    assert bstream.seek(16) == 16
    assert bstream.write(bits[16:24]) == 8
    assert bstream.seek(8) == 8
    assert bstream.write(bits[8:16]) == 8
    bstream.close()
    assert outer.getvalue() == data

    # unaligned write positions are rejected explicitly
    outer = io.BytesIO()
    bstream = SeekableRestreamedBytesIO(outer, bytes2bits, 1, bits2bytes, 8)
    bstream.write(bits[0:4])
    assert raises(bstream.seek, 8) == IOError
    bstream = SeekableRestreamedBytesIO(io.BytesIO(), bytes2bits, 1, bits2bytes, 8)
    bstream.write(bits[0:8])
    assert raises(bstream.seek, 4) == IOError

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
