"""Small value-normalization helpers shared across seascape families."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

import pandas as pd


def clean_optional_text(value: object) -> str | None:
    """Return stripped text or ``None`` for null/blank values."""

    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def iter_frame_records(frame: pd.DataFrame) -> Iterator[tuple[Any, pd.Series]]:
    """Yield index/row records through the faster tuple iterator.

    The Series facade preserves source column names for heterogeneous GIS
    normalization code while avoiding pandas' high-overhead ``iterrows`` path.
    """

    columns = list(frame.columns)
    for values in frame.itertuples(index=True, name=None):
        yield values[0], pd.Series(dict(zip(columns, values[1:], strict=True)))


def pipe_delimited_union(values: Iterable[object]) -> str | None:
    """Join unique non-null pipe-delimited tokens in deterministic order."""

    tokens: set[str] = set()
    for value in values:
        if value is None or pd.isna(value):
            continue
        tokens.update(token for token in str(value).split("|") if token)
    return "|".join(sorted(tokens)) or None


__all__ = ["clean_optional_text", "iter_frame_records", "pipe_delimited_union"]
