"""Strict nullable-H3 string serialization, without altering origin geometry."""

import math

import h3


def nullable_origin_h3(value):
    if value is None or isinstance(value, float) and math.isnan(value):
        return None
    if not isinstance(value, str) or not h3.is_valid_cell(value):
        raise ValueError("Origin H3 must be a valid string or NULL")
    return value
