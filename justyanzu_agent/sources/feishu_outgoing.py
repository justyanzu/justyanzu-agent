"""Casual 回复中的飞书外发协议：解析标识块并调用 lark-cli。"""
from __future__ import annotations

import json
import configparser
from pathlib import Path
from typing import Any, Optional

from sources.feishu_cli_runner import run_im

BEGIN = "<<<AGENT_OUTGOING_FEISHU>>>"
END = "<<<END_AGENT_OUTGOING_FEISHU>>>"


def extract_feishu_block(raw: str) -> tuple[str, Optional[dict[str, Any]]]:
    """
    若存在成对标识，返回 (去掉整块后的可见正文, JSON 对象)；否则 (原文, None)。
    JSON 必须是一个对象，含 text；chat_id 可省略（用 config default_chat_id）。
    """
    if BEGIN not in raw or END not in raw:
        return raw, None
    i = raw.find(BEGIN)
    j = raw.find(END, i + len(BEGIN))
    if j == -1:
        return raw, None
    inner = raw[i + len(BEGIN) : j].strip()
    before = raw[:i].rstrip()
    after = raw[j + len(END) :].lstrip()
    visible = (before + ("\n" + after if after else "")).strip()

    try:
        data = json.loads(inner)
    except json.JSONDecodeError as e:
        return visible, {"_parse_error": str(e), "raw": inner[:800]}

    if not isinstance(data, dict):
        return visible, {"_parse_error": "JSON 必须是对象", "raw": inner[:800]}
    return visible, data


def dispatch_feishu_payload(
    data: dict[str, Any],
    cfg: Optional[configparser.ConfigParser],
    repo_root: Path,
) -> str:
    """执行发送并返回要附在回复后的说明文本（含成功/失败）。"""
    if "_parse_error" in data:
        return (
            "\n\n【飞书发送】标识块 JSON 解析失败："
            f'{data.get("_parse_error")}\n{data.get("raw", "")}'
        )

    text = data.get("text")
    if not text or not isinstance(text, str):
        return "\n\n【飞书发送】失败：JSON 中缺少字符串字段 text"

    cid = data.get("chat_id")
    if isinstance(cid, str):
        cid = cid.strip()
    else:
        cid = None
    if not cid and cfg is not None and cfg.has_section("FEISHU_CLI"):
        cid = cfg.get("FEISHU_CLI", "default_chat_id", fallback="").strip() or None
    if not cid:
        return (
            "\n\n【飞书发送】失败：未在 JSON 中提供 chat_id，"
            "且 config.ini [FEISHU_CLI] default_chat_id 为空"
        )

    as_mode = data.get("as", "user")
    if not isinstance(as_mode, str):
        as_mode = "user"
    dry_run = bool(data.get("dry_run", False))

    code, out, err = run_im(repo_root, cid, text, as_mode=as_mode, dry_run=dry_run)
    ok = code == 0
    tail_parts = [f"code={code}"]
    if out.strip():
        tail_parts.append(out.strip())
    if err.strip():
        tail_parts.append(f"stderr: {err.strip()}")
    detail = "\n".join(tail_parts)
    status = "成功（dry-run）" if dry_run and ok else ("成功" if ok else "失败")
    return f"\n\n【飞书 CLI】{status}\n{detail}"
