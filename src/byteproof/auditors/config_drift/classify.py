"""影响分类（旧仓 ``internal/classify`` 的判定子集）。

- 分类顺序固定：先影响类规则、再纯书写、最后兜底 ``配置·新增·移除`` + ``class_guess``；
- 不确定**禁止**归入 ``纯书写``；
- 汇总计数全部从明细算得；
- Gate：未列 fail-on 时 = 任一行为差异；列了则只看所列类；indeterminate 默认阻断。
"""

from __future__ import annotations

import re

from . import value
from .spec import (
    ALL_CLASSES,
    BEHAVIORAL,
    CONFIG_CHANGE,
    COSMETIC,
    DEPLOY_SHRINK,
    EXPOSURE,
    IMAGE_CHANGE,
    RESOURCE_SHRINK,
)

KIND_CHANGED = "changed"
KIND_ADDED = "added"
KIND_REMOVED = "removed"
KIND_COSMETIC = "cosmetic"
KIND_INDETERMINATE = "indeterminate"
KINDS = (KIND_CHANGED, KIND_ADDED, KIND_REMOVED, KIND_COSMETIC, KIND_INDETERMINATE)

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class ClassifyError(ValueError):
    """条目结构非法（输入不合法，退出码 2）。"""


def last_segment(path):
    index = path.rfind("/")
    return path if index < 0 else path[index + 1:]


def normalize_entry(raw, index):
    if not isinstance(raw, dict):
        raise ClassifyError("entries[%d] 必须是对象" % index)
    path = raw.get("path")
    if not isinstance(path, str):
        raise ClassifyError("entries[%d].path 必须是字符串" % index)
    kind = raw.get("kind")
    if kind not in KINDS:
        raise ClassifyError("entries[%d].kind 必须是 %s" % (index, "/".join(KINDS)))
    left = right = None
    indeterminate = ""
    if kind == KIND_INDETERMINATE:
        indeterminate = raw.get("reason") or value.REASON_UNKNOWN_FAMILY
    else:
        try:
            if raw.get("left") is not None:
                left = value.canonicalize(raw.get("left"))
            if raw.get("right") is not None:
                right = value.canonicalize(raw.get("right"))
        except value.Indeterminate as exc:
            kind = KIND_INDETERMINATE
            indeterminate = exc.reason
    return {
        "path": path,
        "kind": kind,
        "left": left,
        "right": right,
        "reason": indeterminate,
    }


def shrank(left, right):
    if left is None or right is None:
        return False
    if left.family != right.family or left.rat is None or right.rat is None:
        return False
    return right.rat < left.rat


def grew(left, right):
    if left is None or right is None:
        return False
    if left.family == value.FAMILY_DURATION and right.family == value.FAMILY_DURATION:
        return right.ns > left.ns
    if left.family != right.family or left.rat is None or right.rat is None:
        return False
    return right.rat > left.rat


def is_exposure_path(path):
    if "/protocol" in path:
        return False
    if path == "/spec/type":
        return True
    return any(
        marker in path
        for marker in ("/ports", "/serviceType", "/selector", "/ingress", "/rules", "/host", "/http/paths")
    )


def is_config_path(path):
    return any(
        marker in path
        for marker in ("/env", "/data", "/stringData", "/envFrom", "/configMap", "/secret")
    )


def tag_of(canonical):
    if canonical is None:
        return ""
    text = canonical.text
    index = text.rfind(":")
    if index >= 0 and "/" in text:
        text = text[index + 1:]
    return text


def parse_semver(text):
    if not SEMVER_RE.match(text):
        return None
    parts = tuple(int(part) for part in text.split("."))
    return parts


def semver_bump(left, right):
    left_tag = tag_of(left)
    right_tag = tag_of(right)
    left_parts = parse_semver(left_tag)
    right_parts = parse_semver(right_tag)
    if left_parts is None or right_parts is None:
        return "non-semver"
    if left_parts[0] != right_parts[0]:
        return "major"
    if left_parts[1] != right_parts[1]:
        return "minor"
    if left_parts[2] != right_parts[2]:
        return "patch"
    return "patch"


def classify_entry(entry):
    kind = entry["kind"]
    if kind == KIND_INDETERMINATE:
        return COSMETIC, "", False
    if kind == KIND_COSMETIC:
        return COSMETIC, "", False
    path = entry["path"]
    base = last_segment(path)
    left = entry["left"]
    right = entry["right"]

    if base == "image" and kind == KIND_CHANGED:
        return IMAGE_CHANGE, semver_bump(left, right), False

    if ("/resources/limits" in path or "/resources/requests" in path) and kind == KIND_CHANGED:
        return (RESOURCE_SHRINK, "", False) if shrank(left, right) else (CONFIG_CHANGE, "", False)
    if base == "replicas" and kind == KIND_CHANGED:
        return (RESOURCE_SHRINK, "", False) if shrank(left, right) else (CONFIG_CHANGE, "", False)

    if base == "maxUnavailable" and kind == KIND_CHANGED and grew(left, right):
        return DEPLOY_SHRINK, "", False
    if base == "minReadySeconds" and kind == KIND_CHANGED and grew(left, right):
        return DEPLOY_SHRINK, "", False

    if is_exposure_path(path) and kind in (KIND_CHANGED, KIND_ADDED, KIND_REMOVED):
        return EXPOSURE, "", False

    if is_config_path(path):
        return CONFIG_CHANGE, "", False

    if kind == KIND_CHANGED and left is not None and right is not None:
        equal, _reason = value.compare(left, right)
        if equal:
            return COSMETIC, "", False

    return CONFIG_CHANGE, "", True


def apply(entries):
    classified = []
    for entry in entries:
        cls, subclass, guess = classify_entry(entry)
        item = dict(entry)
        item.update({"class": cls, "subclass": subclass, "guess": guess})
        classified.append(item)
    order = {name: index for index, name in enumerate(ALL_CLASSES)}
    classified.sort(key=lambda item: (order[item["class"]], item["path"]))
    return {"entries": classified, "summary": summarize(classified)}


def summarize(entries):
    summary = {
        "total": len(entries),
        "by_class": {name: 0 for name in ALL_CLASSES},
        "behavioral": 0,
        "cosmetic": 0,
        "indeterminate": 0,
    }
    for entry in entries:
        if entry["kind"] == KIND_INDETERMINATE:
            summary["indeterminate"] += 1
            continue
        summary["by_class"][entry["class"]] += 1
        if entry["class"] in BEHAVIORAL:
            summary["behavioral"] += 1
        else:
            summary["cosmetic"] += 1
    return summary


def gate(summary, fail_on, allow_indeterminate):
    """返回 ``(blocked, reason)``。"""
    if summary["indeterminate"] > 0 and not allow_indeterminate:
        return True, "indeterminate"
    if not fail_on:
        return summary["behavioral"] > 0, "behavioral" if summary["behavioral"] else ""
    for name in fail_on:
        if summary["by_class"][name] > 0:
            return True, name
    return False, ""