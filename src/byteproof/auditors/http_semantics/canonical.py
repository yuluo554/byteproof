"""Single serialisation point（1:1 移植自旧仓 ``canonical.py``）。

Frozen parameters（旧仓 plan/02 §6、data/README.md §4.5）：

* ``sort_keys=True``       -- object keys are ordered by ASCII
* ``ensure_ascii=False``   -- 中文保持可读，不出现 ``\\uXXXX``
* ``separators=(",", ":")`` -- 无空白
* ``allow_nan=False``      -- NaN / Infinity 不是合法 JSON
"""

from __future__ import annotations

import json

__all__ = ["dumps", "loads", "NonFiniteNumber"]

_SEPARATORS = (",", ":")


class NonFiniteNumber(ValueError):
    """Raised when a value cannot be represented as strict JSON."""


def _reject_constant(token):
    raise NonFiniteNumber("non-finite number is not allowed: " + token)


def dumps(value):
    """Serialise ``value`` to the canonical JSON text form."""
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=_SEPARATORS,
        allow_nan=False,
    )


def loads(text):
    """Parse JSON text, rejecting NaN / Infinity as strict JSON does."""
    return json.loads(text, parse_constant=_reject_constant)
