"""调用飞书官方 lark-cli 发送即时消息（供 send_message.py 与 CasualAgent 协议层共用）。"""
from __future__ import annotations

import configparser
import re
import shlex
import subprocess
from pathlib import Path

_CHAT_ID_PATTERN = re.compile(r"^(oc_|ou_|om_)[a-zA-Z0-9_-]+$")


def repo_root_from_hint(hint: Path | None) -> Path:
    return hint if hint is not None else Path(__file__).resolve().parents[1]


def load_lark_cli_argv(repo_root: Path) -> list[str]:
    cfg_path = repo_root / "config.ini"
    cmd = "lark-cli"
    if cfg_path.is_file():
        cfg = configparser.ConfigParser()
        cfg.read(cfg_path, encoding="utf-8")
        if cfg.has_section("FEISHU_CLI"):
            cmd = cfg.get("FEISHU_CLI", "lark_cli_command", fallback=cmd)
    return shlex.split(cmd.strip(), posix=False) or ["lark-cli"]


def validate_chat_id(chat_id: str) -> bool:
    return bool(_CHAT_ID_PATTERN.match(chat_id.strip()))


def run_im(
    repo_root: Path,
    chat_id: str,
    text: str,
    as_mode: str = "user",
    dry_run: bool = False,
    timeout: int = 120,
) -> tuple[int, str, str]:
    """
    执行 lark-cli im +messages-send。
    返回 (returncode, stdout, stderr)。
    """
    cid = chat_id.strip()
    if not validate_chat_id(cid):
        return 2, "", "chat_id 未通过本地格式校验（oc_/ou_/om_ 前缀）"

    if len(text) > 60_000:
        return 2, "", "正文超过 60000 字符"

    as_mode = (as_mode or "user").strip().lower()
    if as_mode not in ("user", "bot"):
        as_mode = "user"

    argv0 = load_lark_cli_argv(repo_root)
    cmd = list(argv0) + ["im", "+messages-send"]
    if as_mode == "bot":
        cmd.extend(["--as", "bot"])
    cmd.extend(["--chat-id", cid, "--text", text])
    if dry_run:
        cmd.append("--dry-run")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return 127, "", "找不到 lark-cli，请安装或配置 [FEISHU_CLI] lark_cli_command"
    except subprocess.TimeoutExpired:
        return 124, "", "lark-cli 执行超时"

    out = (proc.stdout or "") + (proc.stderr or "")
    # 合并到单一 summary；stderr 已在 out
    return proc.returncode, proc.stdout or "", proc.stderr or ""
