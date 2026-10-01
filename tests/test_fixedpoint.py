# -*- coding: utf-8 -*-

from decimal import Decimal
from fractions import Fraction

import pytest

from construct import (
    BitStruct,
    BitsInteger,
    BytesInteger,
    FixedPoint,
    FixedPointError,
    FIXED_POINT_OVERFLOW_CLAMP,
    FIXED_POINT_OVERFLOW_RAISE,
    FIXED_POINT_OVERFLOW_WRAP,
    Int8sb,
    Int16sb,
    Padding,
    ROUND_05UP,
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Struct,
    this,
)


def test_fixed_point_negative_scale():
    format = FixedPoint(
        Int16sb,
        scale=Fraction(-1, 8),
        offset=0,
        rounding=ROUND_HALF_EVEN,
        overflow=FIXED_POINT_OVERFLOW_RAISE,
    )

    assert format.parse(b"\x80\x00") == Decimal("4096")
    assert format.build(Decimal("-4095.875")) == b"\x7f\xff"


def fixed_point(**overrides):
    parameters = dict(
        scale=Decimal("0.1"),
        offset="0.25",
        rounding=ROUND_HALF_EVEN,
        overflow=FIXED_POINT_OVERFLOW_RAISE,
    )
    parameters.update(overrides)
    return FixedPoint(Int16sb, **parameters)


def test_fixed_point_exact_decimal_boundary_samples():
    format = fixed_point()

    assert format.parse(b"\x80\x00") == Decimal("-3276.55")
    assert format.parse(b"\x80\x01") == Decimal("-3276.45")
    assert format.build(Decimal("-3276.50")) == b"\x80\x00"
    assert fixed_point(rounding=ROUND_HALF_UP).build(Decimal("-3276.50")) == b"\x80\x00"
    assert format.sizeof() == 2


@pytest.mark.parametrize("compiled", [False, True])
def test_fixed_point_compiled_matches_normal(compiled):
    format = fixed_point()
    if compiled:
        format = format.compile()

    assert format.parse(b"\x80\x01") == Decimal("-3276.45")
    assert format.build(Decimal("-3276.50")) == b"\x80\x00"


def test_fixed_point_negative_half_rounding_modes():
    # Decimal("-3276.50") maps to raw=-32767.5.
    samples = {
        ROUND_UP: b"\x80\x00",
        ROUND_DOWN: b"\x80\x01",
        ROUND_CEILING: b"\x80\x01",
        ROUND_FLOOR: b"\x80\x00",
        ROUND_HALF_UP: b"\x80\x00",
        ROUND_HALF_DOWN: b"\x80\x01",
        ROUND_HALF_EVEN: b"\x80\x00",
        ROUND_05UP: b"\x80\x01",
    }
    for rounding, data in samples.items():
        assert fixed_point(rounding=rounding).build(Decimal("-3276.50")) == data


def test_fixed_point_nonbinary_scale_and_explicit_width():
    format = BitStruct(
        "value" / FixedPoint(
            BitsInteger(12, signed=True),
            width=12,
            scale=this._params.scale,
            offset=this._params.offset,
            rounding=ROUND_HALF_EVEN,
            overflow=FIXED_POINT_OVERFLOW_RAISE,
        ),
        Padding(4),
    )

    parsed = format.parse(b"\x80\x00", scale="0.3", offset="0.25")
    assert parsed.value == Decimal("-614.15")
    assert format.build(dict(value=Decimal("-613.85")), scale="0.3", offset="0.25") == b"\x80\x10"
    assert format.build(dict(value=Decimal("-614.00")), scale="0.3", offset="0.25") == b"\x80\x00"
    assert format.sizeof(scale="0.3", offset="0.25") == 2


def test_fixed_point_contextual_byte_width():
    format = Struct(
        "value" / FixedPoint(
            BytesInteger(this._params.width, signed=True),
            width=this._params.width * 8,
            scale=this._params.scale,
            offset=0,
            rounding=ROUND_HALF_EVEN,
            overflow=FIXED_POINT_OVERFLOW_RAISE,
        ),
    )

    assert format.parse(b"\xff", width=1, scale="0.1").value == Decimal("-0.1")
    assert format.build(dict(value=Decimal("-0.1")), width=1, scale="0.1") == b"\xff"


def test_fixed_point_contextual_width_without_subcon():
    format = FixedPoint(
        width=this._params.width,
        scale=this._params.scale,
        offset=0,
        rounding=ROUND_HALF_EVEN,
        overflow=FIXED_POINT_OVERFLOW_RAISE,
    )

    assert format.parse(b"\xff", width=8, scale="0.1") == Decimal("-0.1")
    assert format.build(Decimal("-0.1"), width=8, scale="0.1") == b"\xff"
    assert format.sizeof(width=8) == 1
    assert format.compile().parse(b"\xff", width=8, scale="0.1") == Decimal("-0.1")


def test_fixed_point_sizeof_does_not_convert_scale_or_offset():
    format = fixed_point(scale=this.missing, offset=this.missing)

    assert format.sizeof() == 2


def test_fixed_point_unrepresentable_precision_is_rejected():
    format = fixed_point(scale="1/3")

    with pytest.raises(FixedPointError, match="finite decimal"):
        format.parse(b"\x00\x01")

    format = fixed_point(scale=Fraction(1, 3))
    with pytest.raises(FixedPointError, match="finite decimal"):
        format.parse(b"\x00\x01")


def test_fixed_point_rejects_nonfinite_and_float_values():
    format = fixed_point()

    with pytest.raises(FixedPointError):
        format.build(Decimal("NaN"))
    with pytest.raises(FixedPointError):
        format.build(Decimal("Infinity"))
    with pytest.raises(FixedPointError):
        format.build(-3276.5)
    with pytest.raises(FixedPointError):
        format.build(True)


def test_fixed_point_overflow_policies():
    value = Decimal("-3276.70")

    with pytest.raises(FixedPointError, match="overflows"):
        fixed_point().build(value)

    assert fixed_point(overflow=FIXED_POINT_OVERFLOW_CLAMP).build(value) == b"\x80\x00"

    wrapped = fixed_point(overflow=FIXED_POINT_OVERFLOW_WRAP).build(value)
    assert wrapped == b"\x7f\xfe"
    assert fixed_point(overflow=FIXED_POINT_OVERFLOW_WRAP).parse(wrapped) == Decimal("3276.85")


def test_fixed_point_requires_signed_integer_and_explicit_policy():
    with pytest.raises(FixedPointError):
        FixedPoint(BytesInteger(1), scale=1, rounding=ROUND_HALF_EVEN,
                   overflow=FIXED_POINT_OVERFLOW_RAISE)

    with pytest.raises(FixedPointError):
        FixedPoint(Int8sb, scale=1, rounding="truncate",
                   overflow=FIXED_POINT_OVERFLOW_RAISE)

    with pytest.raises(FixedPointError):
        FixedPoint(Int8sb, scale=1, rounding=ROUND_HALF_EVEN, overflow="ignore")


def test_fixed_point_zero_scale_is_rejected():
    format = fixed_point(scale=0)

    with pytest.raises(FixedPointError, match="scale must not be zero"):
        format.parse(b"\x00\x00")
    with pytest.raises(FixedPointError, match="scale must not be zero"):
        format.build(Decimal("0"))
