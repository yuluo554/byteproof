"""Tool-face errors（1:1 移植自旧仓 ``judgement/errors.py``）。

caller mistake 是**结果**而不是 traceback：旧 MCP 工具面把 :class:`JudgementError`
渲染为 ``isError: true`` 的结构化结果（rc 0）；账本化后按 SKELETON-SPEC §5 折算为
「输入不合法」→ 宿主 CLI rc 2（口径差登记在 ``docs/http-semantics.md`` §7）。
五个 code 是冻结枚举；``detail`` 是固定模板，不是自由文本。
"""

from __future__ import annotations

ERROR_CODES = (
    "INVALID_INPUT",
    "INVALID_TIME_FORMAT",
    "INVALID_HEADER_NAME",
    "INVALID_HEADER_VALUE",
    "UNSUPPORTED_METHOD",
)


class JudgementError(ValueError):
    """A caller mistake, rendered as ``{"error": {"code", "field", "detail"}}``。

    继承 ``ValueError``：宿主 CLI 把 ``ValueError`` 映射为「输入不合法」rc 2，
    与旧仓「caller mistake 是结果而不是崩溃」的语义等价折算。
    """

    def __init__(self, code, field, detail):
        if code not in ERROR_CODES:
            raise ValueError("unknown error code: " + code)
        ValueError.__init__(self, code + ": " + detail)
        self.code = code
        self.field = field
        self.detail = detail

    def payload(self):
        return {"error": {"code": self.code, "field": self.field, "detail": self.detail}}


def invalid_input(field, detail):
    return JudgementError("INVALID_INPUT", field, detail)


def invalid_header_name(field, name):
    return JudgementError("INVALID_HEADER_NAME", field, "not an RFC 9110 token: " + repr(name))


def invalid_header_value(field, detail):
    return JudgementError("INVALID_HEADER_VALUE", field, detail)


def invalid_time_format(field, value):
    return JudgementError(
        "INVALID_TIME_FORMAT",
        field,
        "expected YYYY-MM-DDTHH:MM:SSZ or an HTTP-date, got " + repr(value),
    )


def unsupported_method(field, method):
    return JudgementError("UNSUPPORTED_METHOD", field, "method not in the accepted set: " + repr(method))
