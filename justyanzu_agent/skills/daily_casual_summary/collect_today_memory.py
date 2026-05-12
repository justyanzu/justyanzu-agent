#!/usr/bin/env python3
"""
从 conversations/<agent_type>/memory_*.txt 汇总「指定日期」的对话片段。
仅包含带 message['time'] 且以 YYYY-MM-DD 开头的条目（与 Memory.push 非 openrouter 行为一致）。
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Iterable, List, Tuple


def _messages_from_file(path: Path) -> List[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return data
    return []


def collect_today_records(
    conversations_folder: str | Path = "conversations",
    agent_type: str = "casual_agent",
    date_str: str | None = None,
) -> List[Tuple[str, str, str]]:
    """
    返回 [(time, role, content), ...] 按 time 排序；time 缺省或日期不符的条目丢弃。
    date_str: YYYY-MM-DD，默认今日（本地）。
    """
    import datetime

    if date_str is None:
        date_str = datetime.date.today().isoformat()

    base = Path(conversations_folder).resolve()
    agent_dir = base / agent_type
    if not agent_dir.is_dir():
        return []

    seen: set[tuple[str, str, str]] = set()
    out: List[Tuple[str, str, str]] = []

    for name in sorted(agent_dir.iterdir(), key=lambda p: p.name):
        if not name.is_file() or not name.name.startswith("memory_") or not name.name.endswith(".txt"):
            continue
        for msg in _messages_from_file(name):
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role == "system":
                continue
            if role not in ("user", "assistant"):
                continue
            t = msg.get("time")
            if not t or not isinstance(t, str) or not t.startswith(date_str):
                continue
            content = msg.get("content")
            if content is None:
                continue
            if not isinstance(content, str):
                content = str(content)
            key = (t, str(role), content)
            if key in seen:
                continue
            seen.add(key)
            out.append((t, str(role), content))

    out.sort(key=lambda x: x[0])
    return out


def format_records_text(records: Iterable[Tuple[str, str, str]]) -> str:
    lines: List[str] = []
    for time_s, role, content in records:
        lines.append(f"[{time_s}] {role}:\n{content}\n")
    return "\n".join(lines).strip()


def collect_today_from_disk(
    conversations_folder: str | Path = "conversations",
    agent_type: str = "casual_agent",
    date_str: str | None = None,
) -> str:
    records = collect_today_records(conversations_folder, agent_type, date_str)
    if not records:
        return ""
    return format_records_text(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect today's casual_agent messages from saved memory_*.txt")
    parser.add_argument("--folder", default="conversations", help="Root folder (default: conversations)")
    parser.add_argument("--agent-type", default="casual_agent", dest="agent_type")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: today local)")
    args = parser.parse_args()
    cwd = Path.cwd()
    folder = (cwd / args.folder).resolve() if not os.path.isabs(args.folder) else Path(args.folder).resolve()
    text = collect_today_from_disk(folder, args.agent_type, args.date)
    print(text if text else "(no matching messages with time for this date)")


if __name__ == "__main__":
    main()
