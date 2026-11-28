"""semver 范围语义核心（Python 重写）。

移植底本：``node_modules/semver`` **7.8.5**（MIT，来源仓 10-27-versionaudit 钉死的唯一
实现版本）。只移植器官判定用到的严格模式（loose 模式不迁）：``parse`` / ``compare`` /
``valid_range``（= ``validRange``）/ ``satisfies`` / ``subset`` / ``intersects``。
逐条改写自 ``classes/semver.js`` / ``classes/comparator.js`` / ``classes/range.js`` /
``ranges/subset.js`` / ``internal/re.js`` / ``internal/identifiers.js``；不做语义推断，
只做结构搬运 —— 与库的差分对照由旧仓 14 组差分向量的期望值承担（见 tests）。
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

# ------------------------------------------------------------------ 正则（internal/re.js 严格模式）
_NUMERIC = r"0|[1-9]\d*"
_NONNUMERIC = r"\d*[a-zA-Z-][a-zA-Z0-9-]*"
_PRERELEASE_ID = r"(?:%s|%s)" % (_NONNUMERIC, _NUMERIC)
_PRERELEASE = r"(?:-(%s(?:\.%s)*))" % (_PRERELEASE_ID, _PRERELEASE_ID)
_BUILD = r"(?:\+([a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*))"
_MAINVERSION = r"(%s)\.(%s)\.(%s)" % (_NUMERIC, _NUMERIC, _NUMERIC)
_FULLPLAIN = r"v?%s%s?%s?" % (_MAINVERSION, _PRERELEASE, _BUILD)
_FULL = r"^%s$" % _FULLPLAIN

_GTLT = r"((?:<|>)?=?)"
_XRANGE_ID = r"%s|x|X|\*" % _NUMERIC
_XRANGEPLAIN = (
    r"[v=\s]*(%s)(?:\.(%s)(?:\.(%s)(?:%s)?%s?)?)?"
    % (_XRANGE_ID, _XRANGE_ID, _XRANGE_ID, _PRERELEASE, _BUILD)
)
_XRANGE = r"^%s\s*%s$" % (_GTLT, _XRANGEPLAIN)
_LONETILDE = r"(?:~>?)"
_TILDE = r"^%s%s$" % (_LONETILDE, _XRANGEPLAIN)
_LONECARET = r"(?:\^)"
_CARET = r"^%s%s$" % (_LONECARET, _XRANGEPLAIN)
_COMPARATOR = r"^%s\s*(%s)$|^$" % (_GTLT, _FULLPLAIN)
_COMPARATORTRIM = r"(\s*)%s\s*(%s|%s)" % (_GTLT, _FULLPLAIN, _XRANGEPLAIN)
_TILDETRIM = r"(\s*)%s\s+" % _LONETILDE
_CARETTRIM = r"(\s*)%s\s+" % _LONECARET
_HYPHENRANGE = r"^\s*(%s)\s+-\s+(%s)\s*$" % (_XRANGEPLAIN, _XRANGEPLAIN)
_STAR = r"(<|>)?=?\s*\*"
_GTE0 = r"^\s*>=\s*0\.0\.0\s*$"

RE_FULL = re.compile(_FULL)
RE_XRANGE = re.compile(_XRANGE)
RE_TILDE = re.compile(_TILDE)
RE_CARET = re.compile(_CARET)
RE_COMPARATOR = re.compile(_COMPARATOR)
RE_COMPARATORTRIM = re.compile(_COMPARATORTRIM)
RE_TILDETRIM = re.compile(_TILDETRIM)
RE_CARETTRIM = re.compile(_CARETTRIM)
RE_HYPHENRANGE = re.compile(_HYPHENRANGE)
RE_STAR = re.compile(_STAR)
RE_GTE0 = re.compile(_GTE0)
RE_BUILD = re.compile(_BUILD)
RE_BUILD_GLOBAL = re.compile(_BUILD)
RE_SPACE = re.compile(r"\s+")

MAX_LENGTH = 256


class InvalidRangeError(Exception):
    """不是合法 semver 范围 / 版本（对应库的 TypeError）。"""


def _is_x(ident) -> bool:
    return ident is None or (isinstance(ident, str) and ident.lower() == "x") or ident == "*"


def _compare_identifiers(a, b) -> int:
    """internal/identifiers.js：数字恒小于字母数字（JS 的 numeric.test 对数字先转串）。"""
    a_num = isinstance(a, int)
    b_num = isinstance(b, int)
    if a_num and b_num:
        return 0 if a == b else (-1 if a < b else 1)
    if a_num:
        a = str(a)
    if b_num:
        b = str(b)
    a_num = a.isdigit()
    b_num = b.isdigit()
    if a_num and b_num:
        ia, ib = int(a), int(b)
        return 0 if ia == ib else (-1 if ia < ib else 1)
    if a_num:
        return -1
    if b_num:
        return 1
    if a == b:
        return 0
    return -1 if a < b else 1


class SemVer:
    """classes/semver.js（严格模式）：三元组 + 预发布标识符数组；build 不参与比较。"""

    __slots__ = ("major", "minor", "patch", "prerelease", "raw")

    def __init__(self, version: str) -> None:
        if not isinstance(version, str):
            raise InvalidRangeError("Invalid Version: %r" % (version,))
        if len(version) > MAX_LENGTH:
            raise InvalidRangeError("version is longer than %d characters" % MAX_LENGTH)
        m = RE_FULL.match(version.strip())
        if not m:
            raise InvalidRangeError("Invalid Version: %s" % version)
        self.raw = version
        self.major = int(m.group(1))
        self.minor = int(m.group(2))
        self.patch = int(m.group(3))
        pre = m.group(4)
        if not pre:
            self.prerelease: Tuple = ()
        else:
            ids: List = []
            for ident in pre.split("."):
                if ident.isdigit():
                    num = int(ident)
                    ids.append(num)
                else:
                    ids.append(ident)
            self.prerelease = tuple(ids)

    @property
    def version(self) -> str:
        text = "%d.%d.%d" % (self.major, self.minor, self.patch)
        if self.prerelease:
            text += "-" + ".".join(str(part) for part in self.prerelease)
        return text

    def compare(self, other: "SemVer") -> int:
        if self.version == other.version:
            return 0
        main = self._compare_main(other)
        if main:
            return main
        return self._compare_pre(other)

    def _compare_main(self, other: "SemVer") -> int:
        for left, right in (
            (self.major, other.major),
            (self.minor, other.minor),
            (self.patch, other.patch),
        ):
            if left < right:
                return -1
            if left > right:
                return 1
        return 0

    def _compare_pre(self, other: "SemVer") -> int:
        if self.prerelease and not other.prerelease:
            return -1
        if not self.prerelease and other.prerelease:
            return 1
        if not self.prerelease and not other.prerelease:
            return 0
        index = 0
        while True:
            a = self.prerelease[index] if index < len(self.prerelease) else None
            b = other.prerelease[index] if index < len(other.prerelease) else None
            if a is None and b is None:
                return 0
            if b is None:
                return 1
            if a is None:
                return -1
            if a == b:
                index += 1
                continue
            return _compare_identifiers(a, b)


def parse(version: str) -> Optional[SemVer]:
    """``semver.parse``（严格）：不是完整三组版本就返回 None。"""
    try:
        return SemVer(version)
    except InvalidRangeError:
        return None


def quote(value) -> str:
    """``JSON.stringify`` 的等价物：证据串里的范围字面量都要带引号。"""
    import json

    return json.dumps(value, ensure_ascii=False)


def compare(a: str, b: str) -> int:
    return SemVer(a).compare(SemVer(b))


ANY = "___ANY___"  # Comparator.ANY 的哨兵


class Comparator:
    """classes/comparator.js：一个 ``op`` + ``semver``；空串 = 任意版本。"""

    __slots__ = ("operator", "semver", "value")

    def __init__(self, comp: str) -> None:
        comp = " ".join(comp.strip().split())
        m = RE_COMPARATOR.match(comp)
        if not m:
            raise InvalidRangeError("Invalid comparator: %s" % comp)
        self.operator = m.group(1) if m.group(1) is not None else ""
        if self.operator == "=":
            self.operator = ""
        if not m.group(2):
            self.semver = ANY
            self.value = ""
        else:
            self.semver = SemVer(m.group(2))
            self.value = self.operator + self.semver.version

    def test(self, version) -> bool:
        if self.semver == ANY or version == ANY:
            return True
        if isinstance(version, str):
            try:
                version = SemVer(version)
            except InvalidRangeError:
                return False
        return _cmp_test(version, self.operator, self.semver)

    def intersects(self, comp: "Comparator") -> bool:
        if self.operator == "":
            if self.value == "":
                return True
            return Range(comp.value).test(self.value)
        if comp.operator == "":
            if comp.value == "":
                return True
            return Range(self.value).test(comp.semver)
        if self.value.startswith("<0.0.0") or comp.value.startswith("<0.0.0"):
            return False
        if self.operator.startswith(">") and comp.operator.startswith(">"):
            return True
        if self.operator.startswith("<") and comp.operator.startswith("<"):
            return True
        if (
            self.semver.version == comp.semver.version
            and "=" in self.operator
            and "=" in comp.operator
        ):
            return True
        if (
            _compare_semver_lt(self.semver, comp.semver)
            and self.operator.startswith(">")
            and comp.operator.startswith("<")
        ):
            return True
        if (
            _compare_semver_lt(comp.semver, self.semver)
            and self.operator.startswith("<")
            and comp.operator.startswith(">")
        ):
            return True
        return False


def _cmp_test(version: SemVer, operator: str, other: SemVer) -> bool:
    """functions/cmp.js 的比较分支（严格模式）。"""
    c = version.compare(other)
    if operator == "":
        return c == 0
    if operator == "<":
        return c < 0
    if operator == "<=":
        return c <= 0
    if operator == ">":
        return c > 0
    if operator == ">=":
        return c >= 0
    raise InvalidRangeError("未知比较运算符 %s" % operator)


def _compare_semver_lt(a: SemVer, b: SemVer) -> bool:
    return a.compare(b) < 0


def _replace_caret(comp: str) -> str:
    m = RE_CARET.match(comp)
    if not m:
        return comp
    M, m_, p, pr = m.group(1), m.group(2), m.group(3), m.group(4)
    if _is_x(M):
        return ""
    if _is_x(m_):
        return ">%s=%s.0.0 <%d.0.0-0" % ("", M, int(M) + 1)
    if _is_x(p):
        if M == "0":
            return ">=%s.%s.0 <%s.%d.0-0" % (M, m_, M, int(m_) + 1)
        return ">=%s.%s.0 <%d.0.0-0" % (M, m_, int(M) + 1)
    if pr:
        if M == "0":
            if m_ == "0":
                return ">=%s.%s.%s-%s <%s.%s.%d-0" % (M, m_, p, pr, M, m_, int(p) + 1)
            return ">=%s.%s.%s-%s <%s.%d.0-0" % (M, m_, p, pr, M, int(m_) + 1)
        return ">=%s.%s.%s-%s <%d.0.0-0" % (M, m_, p, pr, int(M) + 1)
    if M == "0":
        if m_ == "0":
            return ">=%s.%s.%s <%s.%s.%d-0" % (M, m_, p, M, m_, int(p) + 1)
        return ">=%s.%s.%s <%s.%d.0-0" % (M, m_, p, M, int(m_) + 1)
    return ">=%s.%s.%s <%d.0.0-0" % (M, m_, p, int(M) + 1)


def _replace_tilde(comp: str) -> str:
    m = RE_TILDE.match(comp)
    if not m:
        return comp
    M, m_, p, pr = m.group(1), m.group(2), m.group(3), m.group(4)
    if _is_x(M):
        return ""
    if _is_x(m_):
        return ">%s=%s.0.0 <%d.0.0-0" % ("", M, int(M) + 1)
    if _is_x(p):
        return ">=%s.%s.0 <%s.%d.0-0" % (M, m_, M, int(m_) + 1)
    if pr:
        return ">=%s.%s.%s-%s <%s.%d.0-0" % (M, m_, p, pr, M, int(m_) + 1)
    return ">=%s.%s.%s <%s.%d.0-0" % (M, m_, p, M, int(m_) + 1)


def _invalid_xrange_order(M, m_, p) -> bool:
    return (_is_x(M) and not _is_x(m_)) or (_is_x(m_) and p and not _is_x(p))


def _replace_xrange(comp: str) -> str:
    m = RE_XRANGE.match(comp)
    if not m:
        return comp
    gtlt, M, m_, p, pr = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    if _invalid_xrange_order(M, m_, p):
        return comp
    x_m = _is_x(M)
    xm = x_m or _is_x(m_)
    xp = xm or _is_x(p)
    any_x = xp
    gtlt = gtlt if gtlt is not None else ""
    if gtlt == "=" and any_x:
        gtlt = ""
    pr = ""
    if x_m:
        if gtlt in (">", "<"):
            return "<0.0.0-0"
        return "*"
    if gtlt and any_x:
        if xm:
            m_ = "0"
        p = "0"
        if gtlt == ">":
            gtlt = ">="
            if xm:
                M = str(int(M) + 1)
                m_ = "0"
                p = "0"
            else:
                m_ = str(int(m_) + 1)
                p = "0"
        elif gtlt == "<=":
            gtlt = "<"
            if xm:
                M = str(int(M) + 1)
            else:
                m_ = str(int(m_) + 1)
        if gtlt == "<":
            pr = "-0"
        return "%s%s.%s.%s%s" % (gtlt, M, m_, p, pr)
    if xm:
        return ">=%s.0.0 <%d.0.0-0" % (M, int(M) + 1)
    if xp:
        return ">=%s.%s.0 <%s.%d.0-0" % (M, m_, M, int(m_) + 1)
    return comp


def _hyphen_replace(match) -> str:
    # HYPHENRANGE 的分组：1=from 全串，2..6=fM/fm/fp/fpr/build，7=to 全串，8..12=tM/tm/tp/tpr/build
    from_part, fM, fm, fp, fpr = match.group(1), match.group(2), match.group(3), match.group(4), match.group(5)
    to_part, tM, tm, tp, tpr = match.group(7), match.group(8), match.group(9), match.group(10), match.group(11)
    if _is_x(fM):
        from_str = ""
    elif _is_x(fm):
        from_str = ">%s=%s.0.0" % ("", fM)
    elif _is_x(fp):
        from_str = ">=%s.%s.0" % (fM, fm)
    elif fpr:
        from_str = ">%s=%s" % ("", from_part)
    else:
        from_str = ">%s=%s" % ("", from_part)
    if _is_x(tM):
        to_str = ""
    elif _is_x(tm):
        to_str = "<%d.0.0-0" % (int(tM) + 1)
    elif _is_x(tp):
        to_str = "<%s.%d.0-0" % (tM, int(tm) + 1)
    elif tpr:
        to_str = "<=%s.%s.%s-%s" % (tM, tm, tp, tpr)
    else:
        to_str = "<=%s" % to_part
    return ("%s %s" % (from_str, to_str)).strip()


def _parse_comparator_token(comp: str) -> str:
    comp = RE_BUILD.sub("", comp, count=1)
    comp = " ".join(_replace_caret(token) for token in comp.strip().split())
    comp = " ".join(_replace_tilde(token) for token in comp.strip().split())
    comp = " ".join(_replace_xrange(token) for token in comp.split())
    comp = RE_STAR.sub("", comp.strip(), count=1)
    return comp


class Range:
    """classes/range.js：``||`` 分支集合，每支是比较器集合。"""

    def __init__(self, range_str: str) -> None:
        if isinstance(range_str, Comparator):
            self.raw = range_str.value
            self.set: List[List[Comparator]] = [[range_str]]
            return
        if not isinstance(range_str, str):
            raise InvalidRangeError("Invalid SemVer Range: %r" % (range_str,))
        self.raw = RE_SPACE.sub(" ", range_str.strip())
        parsed = [self._parse_range(part.strip()) for part in self.raw.split("||")]
        self.set = [comps for comps in parsed if comps]
        if not self.set:
            raise InvalidRangeError("Invalid SemVer Range: %s" % self.raw)
        if len(self.set) > 1:
            first = self.set[0]
            self.set = [comps for comps in self.set if not _is_null_set(comps[0])]
            if not self.set:
                self.set = [first]
            elif len(self.set) > 1:
                for comps in self.set:
                    if len(comps) == 1 and comps[0].value == "":
                        self.set = [comps]
                        break

    @staticmethod
    def _parse_range(range_str: str) -> List[Comparator]:
        range_str = RE_BUILD_GLOBAL.sub("", range_str)
        range_str = RE_HYPHENRANGE.sub(_hyphen_replace, range_str, count=1)
        range_str = RE_COMPARATORTRIM.sub(r"\1\2\3", range_str)
        range_str = RE_TILDETRIM.sub(r"\1~", range_str)
        range_str = RE_CARETTRIM.sub(r"\1^", range_str)
        tokens = " ".join(_parse_comparator_token(token) for token in range_str.split(" "))
        parts = _js_split_ws(tokens)
        parts = [RE_GTE0.sub("", part) for part in parts]
        range_map = {}
        for part in parts:
            comp = Comparator(part)
            if _is_null_set(comp):
                return [comp]
            range_map.setdefault(comp.value, comp)
        if len(range_map) > 1 and "" in range_map:
            del range_map[""]
        return list(range_map.values())

    @property
    def version(self) -> str:
        formatted = ""
        for i, comps in enumerate(self.set):
            if i > 0:
                formatted += "||"
            formatted += " ".join(comp.value.strip() for comp in comps)
        return formatted

    def test(self, version) -> bool:
        if not version:
            return False
        if isinstance(version, str):
            try:
                version = SemVer(version)
            except InvalidRangeError:
                return False
        for comps in self.set:
            if _test_set(comps, version):
                return True
        return False

    def intersects(self, other: "Range") -> bool:
        for this_comps in self.set:
            if not _is_satisfiable(this_comps):
                continue
            for range_comps in other.set:
                if not _is_satisfiable(range_comps):
                    continue
                if all(
                    this_comp.intersects(range_comp)
                    for this_comp in this_comps
                    for range_comp in range_comps
                ):
                    return True
        return False


def _js_split_ws(text: str) -> List[str]:
    """模拟 JS ``text.split(/\\s+/)``：空串返回 ``[""]`` 而不是 ``[]``。"""
    if text == "":
        return [""]
    return re.split(r"\s+", text)


def _is_null_set(comp: Comparator) -> bool:
    return comp.value == "<0.0.0-0"


def _is_satisfiable(comparators: List[Comparator]) -> bool:
    result = True
    remaining = list(comparators)
    test_comp = remaining.pop()
    while result and remaining:
        result = all(test_comp.intersects(other) for other in remaining)
        test_comp = remaining.pop()
    return result


def _test_set(comps: List[Comparator], version: SemVer) -> bool:
    for comp in comps:
        if not comp.test(version):
            return False
    if version.prerelease:
        for comp in comps:
            if comp.semver == ANY:
                continue
            allowed = comp.semver
            if allowed.prerelease:
                if (
                    allowed.major == version.major
                    and allowed.minor == version.minor
                    and allowed.patch == version.patch
                ):
                    return True
        return False
    return True


def valid_range(range_str: str) -> Optional[str]:
    """``semver.validRange``：合法范围的展开串；空串/``*`` 展开 ``*``；非法返回 None。"""
    try:
        return Range(range_str).version or "*"
    except InvalidRangeError:
        return None


def satisfies(version, range_str) -> bool:
    """``semver.satisfies``（默认 options，不含 includePrerelease）：非法范围恒为 False。

    A8/A9：预发布版本只被「同三元组且带预发布」的比较器放行 —— 这条在
    :meth:`Range.test` / :func:`_test_set` 里实现。
    """
    try:
        rng = Range(range_str)
    except InvalidRangeError:
        return False
    if isinstance(version, str):
        try:
            version = SemVer(version)
        except InvalidRangeError:
            return False
    return rng.test(version)


def intersects(a: str, b: str) -> bool:
    """``semver.intersects``（默认 options）。"""
    try:
        return Range(a).intersects(Range(b))
    except InvalidRangeError:
        return False


# ------------------------------------------------------------------ subset（ranges/subset.js）
_MINIMUM_VERSION = [Comparator(">=0.0.0")]


def subset(sub: str, dom: str) -> bool:
    """``semver.subset``（默认 options）。"""
    if sub == dom:
        return True
    try:
        sub_range = Range(sub)
        dom_range = Range(dom)
    except InvalidRangeError:
        raise
    saw_non_null = False
    for simple_sub in sub_range.set:
        for simple_dom in dom_range.set:
            is_sub = _simple_subset(simple_sub, simple_dom)
            saw_non_null = saw_non_null or is_sub is not None
            if is_sub:
                break
        else:
            if saw_non_null:
                return False
            continue
        # continue OUTER：该 simpleSub 已被某个 simpleDom 覆盖
        continue
    return True


def _higher_gt(a, b) -> Comparator:
    if a is None:
        return b
    c = a.semver.compare(b.semver)
    if c > 0:
        return a
    if c < 0:
        return b
    if b.operator == ">" and a.operator == ">=":
        return b
    return a


def _lower_lt(a, b) -> Comparator:
    if a is None:
        return b
    c = a.semver.compare(b.semver)
    if c < 0:
        return a
    if c > 0:
        return b
    if b.operator == "<" and a.operator == "<=":
        return b
    return a


def _simple_subset(sub: List[Comparator], dom: List[Comparator]):
    if sub == dom:
        return True
    if len(sub) == 1 and sub[0].semver == ANY:
        if len(dom) == 1 and dom[0].semver == ANY:
            return True
        sub = _MINIMUM_VERSION
    if len(dom) == 1 and dom[0].semver == ANY:
        dom = _MINIMUM_VERSION
    eq_set = []
    gt = None
    lt = None
    for comp in sub:
        if comp.operator in (">", ">="):
            gt = _higher_gt(gt, comp)
        elif comp.operator in ("<", "<="):
            lt = _lower_lt(lt, comp)
        else:
            eq_set.append(comp.semver)
    if len(eq_set) > 1:
        return None
    gtlt_comp = 0
    if gt is not None and lt is not None:
        gtlt_comp = gt.semver.compare(lt.semver)
        if gtlt_comp > 0:
            return None
        if gtlt_comp == 0 and (gt.operator != ">=" or lt.operator != "<="):
            return None
    for eq in eq_set:
        if gt is not None and not satisfies(eq.version, gt.value):
            return None
        if lt is not None and not satisfies(eq.version, lt.value):
            return None
        for comp in dom:
            if not satisfies(eq.version, comp.value):
                return False
        return True
    higher = None
    lower = None
    has_dom_lt = False
    has_dom_gt = False
    need_dom_lt_pre = (
        lt.semver
        if lt is not None and lt.semver != ANY and lt.semver.prerelease
        else False
    )
    need_dom_gt_pre = (
        gt.semver
        if gt is not None and gt.semver != ANY and gt.semver.prerelease
        else False
    )
    if need_dom_lt_pre and len(need_dom_lt_pre.prerelease) == 1 and lt.operator == "<" and need_dom_lt_pre.prerelease[0] == 0:
        need_dom_lt_pre = False
    for comp in dom:
        has_dom_gt = has_dom_gt or comp.operator in (">", ">=")
        has_dom_lt = has_dom_lt or comp.operator in ("<", "<=")
        if gt is not None:
            if need_dom_gt_pre:
                if (
                    comp.semver != ANY
                    and comp.semver.prerelease
                    and comp.semver.major == need_dom_gt_pre.major
                    and comp.semver.minor == need_dom_gt_pre.minor
                    and comp.semver.patch == need_dom_gt_pre.patch
                ):
                    need_dom_gt_pre = False
            if comp.operator in (">", ">="):
                higher = _higher_gt(gt, comp)
                if higher == comp and higher != gt:
                    return False
            elif gt.operator == ">=" and not comp.test(gt.semver):
                return False
        if lt is not None:
            if need_dom_lt_pre:
                if (
                    comp.semver != ANY
                    and comp.semver.prerelease
                    and comp.semver.major == need_dom_lt_pre.major
                    and comp.semver.minor == need_dom_lt_pre.minor
                    and comp.semver.patch == need_dom_lt_pre.patch
                ):
                    need_dom_lt_pre = False
            if comp.operator in ("<", "<="):
                lower = _lower_lt(lt, comp)
                if lower == comp and lower != lt:
                    return False
            elif lt.operator == "<=" and not comp.test(lt.semver):
                return False
        if not comp.operator and (lt is not None or gt is not None) and gtlt_comp != 0:
            return False
    if gt is not None and has_dom_lt and lt is None and gtlt_comp != 0:
        return False
    if lt is not None and has_dom_gt and gt is None and gtlt_comp != 0:
        return False
    if need_dom_gt_pre or need_dom_lt_pre:
        return False
    return True
