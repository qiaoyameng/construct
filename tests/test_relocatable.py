# -*- coding: utf-8 -*-

from tests.declarativeunittest import *
from construct import *
from construct.lib import *


def test_section_offsetof_basic():
    d = Relocatable(Struct(
        "off_data" / OffsetOf("data", Int32ub),
        "data" / Section("data", Bytes(3)),
    ))
    common(d, b"\x00\x00\x00\x04abc", Container(off_data=4, data=b"abc"), SizeofError)

    # multiple fields may reference the same section
    d = Relocatable(Struct(
        "off1" / OffsetOf("data", Int16ub),
        "off2" / OffsetOf("data", Int16ub),
        "data" / Section("data", Bytes(1)),
    ))
    common(d, b"\x00\x04\x00\x04Z", Container(off1=4, off2=4, data=b"Z"), SizeofError)


def test_forward_and_backward_reference():
    # forward reference: offset field precedes the section
    d = Relocatable(Struct(
        "off" / OffsetOf("blob", Int16ub),
        "filler" / Bytes(5),
        "blob" / Section("blob", Bytes(2)),
    ))
    common(d, b"\x00\x07abcdeXY", Container(off=7, filler=b"abcde", blob=b"XY"), SizeofError)

    # backward reference: section precedes the offset field
    d = Relocatable(Struct(
        "blob" / Section("blob", Bytes(2)),
        "off" / OffsetOf("blob", Int16ub),
    ))
    common(d, b"XY\x00\x00", Container(blob=b"XY", off=0), SizeofError)


def test_relative_offset():
    d = Relocatable(Struct(
        "tag" / Byte,
        "rel" / OffsetOf("data", Int16ub, relative=True),
        "data" / Section("data", Bytes(2)),
    ))
    # field at position 1, section at position 3, relative offset is 2
    common(d, b"\xff\x00\x02XY", Container(tag=255, rel=2, data=b"XY"), SizeofError)


def test_nested_sections():
    d = Relocatable(Struct(
        "off_outer" / OffsetOf("outer", Int16ub),
        "off_inner" / OffsetOf("inner", Int16ub),
        "outer" / Section("outer", Struct(
            "off_inner2" / OffsetOf("inner", Int16ub),
            "inner" / Section("inner", Bytes(2)),
        )),
    ))
    data = b"\x00\x04\x00\x06\x00\x06XY"
    obj = Container(off_outer=4, off_inner=6, outer=Container(off_inner2=6, inner=b"XY"))
    common(d, data, obj, SizeofError)


def test_alignment_and_padbyte():
    d = Relocatable(Struct(
        "off" / OffsetOf("data", Byte),
        "data" / Section("data", Bytes(2), align=8),
    ))
    common(d, b"\x08\x00\x00\x00\x00\x00\x00\x00XY", Container(off=8, data=b"XY"), SizeofError)

    d = Relocatable(Struct(
        "off" / OffsetOf("data", Byte),
        "data" / Section("data", Bytes(1), align=4, padbyte=b"\xff"),
    ))
    assert d.build(dict(data=b"Z")) == b"\x04\xff\xff\xffZ"

    # alignment and absolute offsets use stream positions, also when nested
    d = Struct(
        "prefix" / Bytes(2),
        "r" / Relocatable(Struct(
            "off" / OffsetOf("data", Byte),
            "data" / Section("data", Bytes(1), align=4),
        )),
    )
    assert d.build(dict(prefix=b"HI", r=dict(data=b"Z"))) == b"HI\x04\x00Z"
    assert d.parse(b"HI\x04\x00Z") == Container(prefix=b"HI", r=Container(off=4, data=b"Z"))


def test_varint_offset_length_change():
    # offset value crosses the VarInt 1-byte/2-byte boundary (127/128),
    # so the layout must be recomputed until it converges
    d = Relocatable(Struct(
        "off" / OffsetOf("blob", VarInt),
        "pad" / Bytes(200),
        "blob" / Section("blob", Bytes(1)),
    ))
    data = d.build(dict(pad=b"\x00" * 200, blob=b"Z"))
    assert len(data) == 203
    assert data[:2] == b"\xca\x01"  # VarInt encoding of 202
    assert data[-1:] == b"Z"
    assert d.parse(data) == Container(off=202, pad=b"\x00" * 200, blob=b"Z")

    # small layout, offset stays a 1-byte VarInt
    d = Relocatable(Struct(
        "off" / OffsetOf("blob", VarInt),
        "pad" / Bytes(10),
        "blob" / Section("blob", Bytes(1)),
    ))
    data = d.build(dict(pad=b"\x00" * 10, blob=b"Z"))
    assert data == b"\x0b" + b"\x00" * 10 + b"Z"
    assert d.parse(data).off == 11


def test_offset_overflow_raises():
    # section lands beyond what a Byte-sized field can hold
    d = Relocatable(Struct(
        "off" / OffsetOf("blob", Byte),
        "pad" / Bytes(300),
        "blob" / Section("blob", Bytes(1)),
    ))
    assert raises(d.build, dict(pad=b"\x00" * 300, blob=b"Z")) == FormatFieldError

    # relative offset to a section located before the field is negative
    d = Relocatable(Struct(
        "blob" / Section("blob", Bytes(1)),
        "rel" / OffsetOf("blob", Int16ub, relative=True),
    ))
    assert raises(d.build, dict(blob=b"Z")) == FormatFieldError


def test_unknown_section_raises():
    d = Relocatable(Struct(
        "off" / OffsetOf("missing", Int16ub),
        "data" / Section("data", Bytes(1)),
    ))
    assert raises(d.build, dict(data=b"Z")) == LayoutError


def test_duplicate_section_raises():
    d = Relocatable(Struct(
        "a" / Section("dup", Bytes(1)),
        "b" / Section("dup", Bytes(1)),
    ))
    assert raises(d.build, dict(a=b"x", b=b"y")) == LayoutError
    assert raises(d.parse, b"xy") == LayoutError


def test_offsetof_outside_relocatable():
    # parsing works like a plain field, building requires a Relocatable
    d = Struct("off" / OffsetOf("data", Int16ub))
    assert d.parse(b"\x00\x05") == Container(off=5)
    assert raises(d.build, dict(off=5)) == LayoutError


def test_nonconverging_layout_raises():
    class EvenOddInt(Construct):
        # pathological field: 1 byte for even values, 2 bytes for odd values
        def _parse(self, stream, context, path):
            raise NotImplementedError
        def _build(self, obj, stream, context, path):
            data = bytes([obj & 0xff]) * (1 if obj % 2 == 0 else 2)
            stream_write(stream, data, len(data), path)
            return obj

    d = Relocatable(Struct(
        "off" / OffsetOf("s", EvenOddInt()),
        "s" / Section("s", Bytes(1)),
    ), maxiterations=10)
    # offset value oscillates between 1 and 2 and never stabilizes
    assert raises(d.build, dict(s=b"Z")) == LayoutError


def test_layout_shrink_truncates_stream():
    class ZeroWideInt(Construct):
        # 2 bytes for value 0, 1 byte otherwise
        def _parse(self, stream, context, path):
            raise NotImplementedError
        def _build(self, obj, stream, context, path):
            data = b"\x00\x00" if obj == 0 else bytes([obj & 0xff])
            stream_write(stream, data, len(data), path)
            return obj

    d = Relocatable(Struct(
        "off" / OffsetOf("s", ZeroWideInt()),
        "s" / Section("s", Bytes(1)),
    ))
    # iteration 1 writes a 2-byte placeholder, final layout is 1 byte shorter;
    # a stale trailing byte must not survive in the output
    data = d.build(dict(s=b"Z"))
    assert data == b"\x01Z"


def test_parse_validates_offsets():
    d = Relocatable(Struct(
        "off" / OffsetOf("data", Int16ub),
        "data" / Section("data", Bytes(2)),
    ))
    assert d.parse(b"\x00\x02XY") == Container(off=2, data=b"XY")
    # corrupted offset does not match the actual section position
    assert raises(d.parse, b"\x00\x05XY") == LayoutError

    # nested sections are validated too
    d = Relocatable(Struct(
        "off" / OffsetOf("inner", Int16ub),
        "outer" / Section("outer", Struct(
            "inner" / Section("inner", Bytes(2)),
        )),
    ))
    assert d.parse(b"\x00\x02XY") == Container(off=2, outer=Container(inner=b"XY"))
    assert raises(d.parse, b"\x00\x04XY") == LayoutError


def test_parse_validates_reference_range():
    # reference to a section that is not part of the layout must stay in bounds
    d = Relocatable(Struct(
        "off" / OffsetOf("external", Int16ub),
        "data" / Bytes(2),
    ))
    assert d.parse(b"\x00\x04XY") == Container(off=4, data=b"XY")
    assert raises(d.parse, b"\xff\xffXY") == LayoutError

    d = Relocatable(Struct(
        "rel" / OffsetOf("external", Int16sb, relative=True),
        "data" / Bytes(2),
    ))
    assert raises(d.parse, b"\xff\xfeXY") == LayoutError  # target before stream start


def test_nonseekable_stream_raises():
    class PipeStream(object):
        def __init__(self):
            self.buf = b""
        def write(self, data):
            self.buf += data
            return len(data)

    d = Relocatable(Struct(
        "off" / OffsetOf("data", Int16ub),
        "data" / Section("data", Bytes(1)),
    ))
    assert raises(d.build_stream, dict(data=b"Z"), PipeStream()) == StreamError


def test_build_into_file(tmp_path):
    d = Relocatable(Struct(
        "off" / OffsetOf("blob", VarInt),
        "pad" / Bytes(200),
        "blob" / Section("blob", Bytes(1)),
    ))
    filename = str(tmp_path / "sample.bin")
    d.build_file(dict(pad=b"\x00" * 200, blob=b"Z"), filename)
    with open(filename, "rb") as f:
        data = f.read()
    assert len(data) == 203
    assert d.parse(data) == Container(off=202, pad=b"\x00" * 200, blob=b"Z")


def test_roundtrip_recomputes_offsets():
    d = Relocatable(Struct(
        "off" / OffsetOf("data", Int32ub),
        "data" / Section("data", Bytes(2)),
    ))
    obj = d.parse(b"\x00\x00\x00\x04XY")
    obj.off = 999  # stale value in the dict is ignored, offsets are recomputed
    assert d.build(obj) == b"\x00\x00\x00\x04XY"


def test_sizeof():
    d = OffsetOf("data", Int32ub)
    assert d.sizeof() == 4
    d = OffsetOf("data", VarInt)
    assert raises(d.sizeof) == SizeofError
    d = Section("data", Bytes(4))
    assert d.sizeof() == 4
    d = Section("data", Bytes(4), align=8)
    assert raises(d.sizeof) == SizeofError
    d = Relocatable(Struct("data" / Section("data", Bytes(4))))
    assert raises(d.sizeof) == SizeofError
