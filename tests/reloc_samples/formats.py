# -*- coding: utf-8 -*-
# Binary sample formats exercising Section and OffsetField.
# The .bin files next to this module are generated from these definitions,
# see generate.py (run "python -m tests.reloc_samples.generate" from repo root).

from construct import *


# Nested sections with alignment: an outer section containing an inner section,
# with a header holding absolute and relative offsets to both.
nested_format = Struct(
    Const(b"NEST"),
    "outer_off" / OffsetField("outer", Int32ub),
    "inner_off" / OffsetField("inner", Int32ub),
    "inner_rel" / OffsetField("inner", Int16ub, relative=True),
    Section("outer", Struct(
        Const(b"OUT"),
        Section("inner", Struct(
            Const(b"IN"),
            "value" / Int32ub,
        ), alignment=4),
    ), alignment=16),
)
nested_obj = dict(outer=dict(inner=dict(value=0x01020304)))


# Forward references: the header is a table of contents with absolute and
# relative offsets to sections that appear later, two fields referencing
# the same section.
forward_format = Struct(
    Const(b"FWD!"),
    "toc_a" / OffsetField("alpha", Int32ub),
    "toc_b" / OffsetField("beta", Int32ub),
    "toc_a2" / OffsetField("alpha", Int32ub),
    "beta_rel" / OffsetField("beta", Int32sb, relative=True),
    Section("alpha", Struct(
        Const(b"A"),
        "data" / Bytes(5),
    ), alignment=8),
    Section("beta", Struct(
        Const(b"B"),
        "data" / Bytes(3),
    ), alignment=8),
)
forward_obj = dict(alpha=dict(data=b"HELLO"), beta=dict(data=b"XYZ"))


# Offset length change: the VarInt offset fields grow from 1 to 2 bytes once
# the target section offset crosses 127, so the layout only converges after
# several build passes.
varint_format = Struct(
    Const(b"VI"),
    "target_off" / OffsetField("target", VarInt),
    "target_off2" / OffsetField("target", VarInt),
    "filler" / Bytes(130),
    Section("target", Struct(
        Const(b"T"),
        "payload" / Bytes(4),
    )),
)
varint_obj = dict(filler=bytes(130), target=dict(payload=b"DATA"))


SAMPLES = [
    ("nested_sections.bin", nested_format, nested_obj),
    ("forward_refs.bin", forward_format, forward_obj),
    ("varint_growth.bin", varint_format, varint_obj),
]
