"""byteproof 唯一入口：``byteproof <subcommand> ...``。

子命令只有两个（器官不得自带 CLI，新增能力一律作为 auditor 注册）：

    byteproof list [--json]
    byteproof check <slug> --input <file|-> [--basis <file>] [--json]

退出码见 :mod:`byteproof.core.ledger`：0 无阻断 / 1 有阻断 / 2 输入不合法 / 3 契约违约。

**规则包从哪来**：``--basis`` 给了就用它；没给就找随包分发的
``byteproof/data/<slug>.basis.json``（器官自己的规则包）；两者都没有才是空规则包
（此时器官调 ``basis.ref`` 会抛 ``RuleMissing`` -> 退出码 3）。
这条解析放在 CLI 而不是器官里：器官不读文件是契约，而 SKELETON-SPEC §2 把
``<product> check <slug> --input <file>`` 定成唯一的调用形态 —— 它没有 ``--basis``，
所以"不带参数也该能审"必须由宿主保证。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from byteproof import __version__
from byteproof.auditors import load_builtin
from byteproof.core.basis import Basis, RuleMissing
from byteproof.core.ledger import EXIT_CONTRACT, EXIT_INPUT, EXIT_OK, ContractError, Report
from byteproof.core.registry import PackMissing, all_packs, get

PRODUCT = "byteproof"

#: 随包规则包的目录（相对本模块）。
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def shipped_basis_path(slug: str):
    """器官的随包规则包路径；没有就返回 ``None``（不是错误，只是"该器官没带规则"）。"""
    path = os.path.join(DATA_DIR, "%s.basis.json" % slug)
    return path if os.path.isfile(path) else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="byteproof",
        description="字节层缺陷取证引擎：给定工件与规则包，输出可复算的缺陷账本",
    )
    parser.add_argument("--version", action="version", version="%s %s" % (PRODUCT, __version__))
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list", help="列出已注册的器官")
    list_parser.add_argument("--json", action="store_true", help="机器可读输出")

    check_parser = subparsers.add_parser("check", help="用某个器官做一次审计")
    check_parser.add_argument("slug", help="器官 slug")
    check_parser.add_argument("--input", required=True, help="输入 JSON 路径；- 表示 stdin")
    check_parser.add_argument("--basis", help="规则包 JSON 路径（缺省=空规则包）")
    check_parser.add_argument("--json", action="store_true", help="机器可读输出")
    return parser


def main(argv=None) -> int:
    load_builtin()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_OK
    try:
        if args.command == "list":
            return _cmd_list(args)
        if args.command == "check":
            return _cmd_check(args)
    except (ContractError, PackMissing, RuleMissing) as exc:
        # 契约违约：无依据下 error、规则包版本缺失、规则/器官不存在
        print("%s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return EXIT_CONTRACT
    except (OSError, ValueError) as exc:
        # 输入不合法：文件缺失、JSON 解析失败、必填字段缺
        print("输入不合法：%s" % exc, file=sys.stderr)
        return EXIT_INPUT
    return EXIT_INPUT


def _cmd_list(args) -> int:
    packs = all_packs()
    if args.json:
        print(json.dumps([pack.as_dict() for pack in packs], ensure_ascii=False, indent=2))
        return EXIT_OK
    if not packs:
        print("（未注册任何器官）")
        return EXIT_OK
    for pack in packs:
        print("%-28s %-10s %s" % (pack.slug, pack.version, pack.summary))
    return EXIT_OK


def _cmd_check(args) -> int:
    pack = get(args.slug)
    subject = _load_subject(args.input)
    missing = [name for name in pack.input_fields if name not in subject]
    if missing:
        raise ValueError("输入缺少必填字段：%s" % ", ".join(missing))
    basis = _load_basis(args.basis, pack.slug)

    report = Report(
        product=PRODUCT,
        organ=pack.slug,
        organ_version=pack.version,
        subject=_subject_label(args.input),
        records=tuple(pack.evaluate(subject, basis)),
    )
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        for line in report.as_lines():
            print(line)
    return report.exit_code()


def _load_basis(path, slug: str) -> Basis:
    """``--basis`` 优先，其次器官随包规则包，最后才是空规则包。"""
    if path:
        return Basis.from_json(path)
    shipped = shipped_basis_path(slug)
    if shipped is not None:
        return Basis.from_json(shipped)
    return Basis.empty()


def _load_subject(source: str) -> dict:
    if source == "-":
        data = json.load(sys.stdin)
    else:
        with open(source, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("输入必须是 JSON 对象")
    return data


def _subject_label(source: str) -> str:
    if source == "-":
        return "<stdin>"
    return os.path.basename(source)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())