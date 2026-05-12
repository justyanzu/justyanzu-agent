"""
每日 casual 总结：读取 skill.md + 内存今日片段 + collect_today_memory 磁盘片段，单次 LLM 调用（不写入 casual Memory）。
"""
from __future__ import annotations

import importlib.util
import datetime
from pathlib import Path
from typing import TYPE_CHECKING, List, Tuple, Set

if TYPE_CHECKING:
    from sources.agents.casual_agent import CasualAgent

from sources.skill_redis_cache import load_daily_casual_skill_markdown


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_collect_module():
    path = _repo_root() / "skills" / "daily_casual_summary" / "collect_today_memory.py"
    spec = importlib.util.spec_from_file_location("dcs_collect_today_memory", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载收集脚本: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_skill_markdown() -> str:
    return load_daily_casual_skill_markdown(_repo_root())


def _format_live_rows(rows: List[Tuple[str, str, str]]) -> str:
    lines: List[str] = []
    for label, role, content in rows:
        lines.append(f"[{label}] {role}:\n{content}\n")
    return "\n".join(lines).strip()


def format_today_live_memory(casual_agent: "CasualAgent", date_str: str | None = None) -> str:
    """当前 Memory 中今日相关 user/assistant；有 time 则按前缀筛选，无 time 仅当 session 起始日为今日时纳入。"""
    if date_str is None:
        date_str = datetime.date.today().isoformat()

    mem = casual_agent.memory.get()
    session_date = casual_agent.memory.session_time.date().isoformat()
    seen: Set[Tuple[str, str, str]] = set()
    timed: List[Tuple[str, str, str]] = []
    untimed: List[Tuple[str, str, str]] = []

    for msg in mem:
        if msg.get("role") == "system":
            continue
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content")
        if content is None:
            continue
        if not isinstance(content, str):
            content = str(content)
        t = msg.get("time")
        if isinstance(t, str) and t.startswith(date_str):
            key = (t, str(role), content)
            if key not in seen:
                seen.add(key)
                timed.append((t, str(role), content))
        elif (not t or "time" not in msg) and session_date == date_str:
            label = "(无时间戳·本会话)"
            key = (label, str(role), content)
            if key not in seen:
                seen.add(key)
                untimed.append((label, str(role), content))
        else:
            continue

    timed.sort(key=lambda x: x[0])
    rows = timed + untimed
    return _format_live_rows(rows)


def run_daily_summary(casual_agent: "CasualAgent", working_dir: Path | None = None) -> str:
    """
    单次总结调用；不改变 casual_agent.memory。
    working_dir: 解析 conversations/ 相对路径，默认 Path.cwd()。
    """
    mod = _load_collect_module()
    root = Path.cwd() if working_dir is None else working_dir
    date_str = datetime.date.today().isoformat()

    conv_root = (root / casual_agent.memory.conversation_folder).resolve()
    disk_text = mod.collect_today_from_disk(conv_root, "casual_agent", date_str)
    live_text = format_today_live_memory(casual_agent, date_str)

    skill_md = load_skill_markdown()
    user_blob = (
        f"今日日期（本地）：{date_str}\n\n"
        f"=== 一、当前进程内 casual_agent 内存（今日相关）===\n"
        f"{live_text or '（无）'}\n\n"
        f"=== 二、今日已从磁盘 memory_*.txt 合并的片段（按 message['time'] 筛选）===\n"
        f"{disk_text or '（无带 time 的今日条目）'}\n\n"
        f"请根据上述 Skill 说明输出今日总结。"
    )

    messages = [
        {"role": "system", "content": skill_md},
        {"role": "user", "content": user_blob},
    ]
    thought = casual_agent.llm.respond(messages, verbose=False)
    return casual_agent.remove_reasoning_text(thought)
