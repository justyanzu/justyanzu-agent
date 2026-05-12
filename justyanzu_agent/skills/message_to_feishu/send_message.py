#!/usr/bin/env python3
"""
通过飞书官方 CLI 向指定会话发即时消息（封装 lark-cli im +messages-send）。

使用前请完成：npm i -g @larksuite/cli、lark-cli config init、lark-cli auth login
文档：https://github.com/larksuite/cli/blob/main/README.zh.md
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sources.feishu_cli_runner import (  # noqa: E402
    run_im,
    validate_chat_id,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send Feishu IM via lark-cli")
    parser.add_argument("--chat-id", required=True, help="会话 chat_id，如 oc_xxx")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--text", help="消息正文（单行建议用引号）")
    g.add_argument("--text-file", dest="text_file", help="从文件读正文（UTF-8）")
    parser.add_argument("--as", choices=("user", "bot"), default="user", dest="as_mode")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    chat_id = args.chat_id.strip()
    if not validate_chat_id(chat_id):
        print(
            "错误：chat_id 格式未通过本地校验（预期 oc_/ou_/om_ 前缀）。",
            file=sys.stderr,
        )
        return 2

    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
    else:
        text = args.text or ""

    code, out, err = run_im(_ROOT, chat_id, text, as_mode=args.as_mode, dry_run=args.dry_run)
    if out:
        print(out, end="" if str(out).endswith("\n") else "\n")
    if err:
        print(err, end="", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
