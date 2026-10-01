# -*- coding: utf-8 -*-

from tests.declarativeunittest import *
from construct import *
from construct.lib import *

from tests.reloc_samples import formats as sample_formats


class ParityByte(Construct):
    # encodes even values in 1 byte and odd values in 2 bytes,
    # used to simulate a field whose length depends on the written value
    def _parse(self, stream, context, path):
        return stream_read(stream, 1, path)[0]
    def _build(self, obj, stream, context, path):
        n = 1 if obj % 2 == 0 else 2
        stream_write(stream, bytes([obj & 0xff]) * n, n, path)
        return obj
    def _sizeof(self, context, path):
        raise SizeofError("variable length")


class ShrinkingByte(Construct):
    # encodes 0 in 2 bytes and anything else in 1 byte
    def _parse(self, stream, context, path):
        return stream_read(stream, 1, path)[0]
    def _build(self, obj, stream, context, path):
        data = b"\x00\x00" if obj == 0 else bytes([obj])
        stream_write(stream, data, len(data), path)
        return obj
    def _sizeof(self, context, path):
        raise SizeofError("variable length")


def test_section_basic():
    d = Struct(
        "offset" / OffsetField("data", Byte),
        Section("data", Bytes(3)),
    )
    assert d.build(dict(data=b"abc")) == b"\x01abc"
    assert d.parse(b"\x01abc") == Container(offset=1, data=b"abc")
    assert d.build(d.parse(b"\x01abc")) == b"\x01abc"

def test_section_alignment():
    d = Struct(
        "offset" / OffsetField("data", Byte),
        Section("data", Bytes(2), alignment=4),
    )
    assert d.build(dict(data=b"ab")) == b"\x04\x00\x00\x00ab"
    assert d.parse(b"\x04\x00\x00\x00ab") == Container(offset=4, data=b"ab")

    d = Struct(
        "offset" / OffsetField("data", Byte),
        Section("data", Bytes(2), alignment=4, padpattern=b"\xff"),
    )
    assert d.build(dict(data=b"ab")) == b"\x04\xff\xff\xffab"

def test_section_ctor_errors():
    assert raises(Section, None, Byte) == RelocationError
    assert raises(Section, "", Byte) == RelocationError
    assert raises(Section, "x", Byte, padpattern=b"ab") == PaddingError
    assert raises(OffsetField, None, Byte) == RelocationError
    assert raises(OffsetField, "x", None) == TypeError

def test_offsetfield_multiple_references():
    d = Struct(
        "off1" / OffsetField("s", Int16ub),
        "off2" / OffsetField("s", Int16ub),
        "off3" / OffsetField("s", Int16ub, relative=True),
        Section("s", Bytes(2)),
    )
    data = d.build(dict(s=b"xy"))
    assert data == b"\x00\x06\x00\x06\x00\x00xy"
    obj = d.parse(data)
    assert obj == Container(off1=6, off2=6, off3=0, s=b"xy")

def test_offsetfield_relative_backward():
    d = Struct(
        Section("s", Bytes(2)),
        "off" / OffsetField("s", Int8sb, relative=True),
    )
    data = d.build(dict(s=b"xy"))
    assert data == b"xy\xfd"
    obj = d.parse(data)
    assert obj == Container(s=b"xy", off=-3)

def test_offsetfield_overflow():
    d = Struct(
        "offset" / OffsetField("s", Byte),
        "filler" / Bytes(300),
        Section("s", Bytes(1)),
    )
    assert raises(d.build, dict(filler=bytes(300), s=b"x")) == RelocationError

def test_offsetfield_unknown_section():
    d = Struct("offset" / OffsetField("missing", Byte))
    assert raises(d.build, dict()) == RelocationError
    assert raises(d.parse, b"\x00") == RelocationError

def test_offsetfield_parse_validates_range():
    d = Struct(
        "offset" / OffsetField("s", Byte),
        Section("s", Bytes(2)),
    )
    assert d.parse(b"\x01ab") == Container(offset=1, s=b"ab")
    assert raises(d.parse, b"\x05ab") == RelocationError
    assert raises(d.parse, b"\x00ab") == RelocationError

def test_section_duplicate_name():
    d = Struct(
        Section("s", Const(b"A")),
        Section("s", Const(b"B")),
    )
    assert raises(d.build, dict()) == RelocationError
    assert raises(d.parse, b"AB") == RelocationError

def test_offsetfield_circular_dependency():
    d = Struct(
        "offset" / OffsetField("s", ParityByte()),
        Section("s", Const(b"X")),
    )
    assert raises(d.build, dict()) == RelocationError

def test_offsetfield_shrinking_converges():
    d = Struct(
        "offset" / OffsetField("s", ShrinkingByte()),
        Section("s", Const(b"Z")),
    )
    assert d.build(dict()) == b"\x01Z"
    assert d.parse(b"\x01Z") == Container(offset=1, s=b"Z")

def test_offsetfield_nonseekable_stream():
    class Sink(object):
        def write(self, data):
            return len(data)
    d = Struct(
        "offset" / OffsetField("s", Byte),
        Section("s", Bytes(1)),
    )
    assert raises(d.build_stream, dict(s=b"x"), Sink()) == StreamError

def test_offsetfield_tunnel_rejected():
    d = Prefixed(Byte, Struct(
        "offset" / OffsetField("s", Byte),
        Section("s", Bytes(1)),
    ))
    assert raises(d.build, dict(s=b"x")) == RelocationError

def test_section_sizeof():
    assert Section("s", Bytes(3)).sizeof() == 3
    assert raises(Section("s", Bytes(3), alignment=4).sizeof) == SizeofError
    d = Struct("off" / OffsetField("s", Byte), Section("s", Bytes(3)))
    assert d.sizeof() == 4
    d = Struct("off" / OffsetField("s", VarInt), Section("s", Bytes(3)))
    assert raises(d.sizeof) == SizeofError

def test_reloc_build_stream_offset_start():
    d = Struct(
        "offset" / OffsetField("s", Byte),
        Section("s", Bytes(1), alignment=4),
    )
    stream = io.BytesIO(b"PREFIX")
    stream.seek(3)
    d.build_stream(dict(s=b"Q"), stream)
    assert stream.getvalue() == b"PRE\x04QX"

    stream = io.BytesIO(b"PRE\x04Q")
    stream.read(3)
    assert d.parse_stream(stream) == Container(offset=4, s=b"Q")

def test_reloc_build_file(tmp_path):
    filename = str(tmp_path / "out.bin")
    d = sample_formats.varint_format
    d.build_file(sample_formats.varint_obj, filename)
    with open(filename, "rb") as f:
        data = f.read()
    assert data == d.build(sample_formats.varint_obj)
    assert len(data) == 141

def test_reloc_sample_nested_sections():
    fmt, obj = sample_formats.nested_format, sample_formats.nested_obj
    data = fmt.build(obj)
    with open("tests/reloc_samples/nested_sections.bin", "rb") as f:
        assert f.read() == data
    parsed = fmt.parse(data)
    assert parsed.outer_off == 16
    assert parsed.inner_off == 20
    assert parsed.inner_rel == 6
    assert parsed.outer.inner.value == 0x01020304
    assert fmt.build(parsed) == data

def test_reloc_sample_forward_refs():
    fmt, obj = sample_formats.forward_format, sample_formats.forward_obj
    data = fmt.build(obj)
    with open("tests/reloc_samples/forward_refs.bin", "rb") as f:
        assert f.read() == data
    parsed = fmt.parse(data)
    assert parsed.toc_a == 24
    assert parsed.toc_a2 == 24
    assert parsed.toc_b == 32
    assert parsed.beta_rel == 12
    assert parsed.alpha.data == b"HELLO"
    assert parsed.beta.data == b"XYZ"
    assert fmt.build(parsed) == data

def test_reloc_sample_varint_growth():
    fmt, obj = sample_formats.varint_format, sample_formats.varint_obj
    data = fmt.build(obj)
    with open("tests/reloc_samples/varint_growth.bin", "rb") as f:
        assert f.read() == data
    assert len(data) == 141
    assert data[2:6] == b"\x88\x01\x88\x01"
    parsed = fmt.parse(data)
    assert parsed.target_off == 136
    assert parsed.target_off2 == 136
    assert parsed.target.payload == b"DATA"
    assert fmt.build(parsed) == data

def test_reloc_samples_up_to_date():
    import os
    here = os.path.join("tests", "reloc_samples")
    for filename, fmt, obj in sample_formats.SAMPLES:
        with open(os.path.join(here, filename), "rb") as f:
            assert f.read() == fmt.build(obj)
