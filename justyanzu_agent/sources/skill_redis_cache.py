"""
将任意 skills/<name>/skill.md 缓存到 Redis（按 mtime 失效）。

Redis key 形如：{redis_key_prefix}:{skill_dir_name}，例如 agenticseek:skill:daily_casual_summary。
未启用 Redis、连接失败或缺少 redis 包时退回读盘。
"""
from __future__ import annotations

import os
import configparser
from pathlib import Path
from typing import Optional

SECTION = "SKILL_CACHE"


def parse_casual_skill_dirs(cfg: configparser.ConfigParser) -> list[str]:
    """读取 [CASUAL_AGENT] skills（逗号分隔目录名）。"""
    if not cfg.has_section("CASUAL_AGENT"):
        return []
    raw = cfg.get("CASUAL_AGENT", "skills", fallback="")
    return [x.strip() for x in raw.split(",") if x.strip()]


def _read_config(repo_root: Path) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    for p in (repo_root / "config.ini", Path("config.ini")):
        if p.is_file():
            cfg.read(p, encoding="utf-8")
            break
    return cfg


def _skill_cache_enabled(cfg: configparser.ConfigParser) -> bool:
    if not cfg.has_section(SECTION):
        return False
    return cfg.getboolean(SECTION, "enabled", fallback=False)


def _redis_key_prefix(cfg: configparser.ConfigParser) -> str:
    return cfg.get(SECTION, "redis_key_prefix", fallback="agenticseek:skill")


def redis_key_for_skill(cfg: configparser.ConfigParser, skill_dir_name: str) -> str:
    """单 skill 在 Redis 中的 Hash key（内容由 hget mtime/content）。"""
    return f"{_redis_key_prefix(cfg)}:{skill_dir_name.strip()}"


def _redis_client(cfg: configparser.ConfigParser):
    try:
        import redis  # type: ignore
    except ImportError:
        return None

    host = os.getenv("REDIS_HOST") or cfg.get(SECTION, "redis_host", fallback="127.0.0.1")
    port_env = os.getenv("REDIS_PORT")
    port = int(port_env) if port_env else cfg.getint(SECTION, "redis_port", fallback=6379)
    db = cfg.getint(SECTION, "redis_db", fallback=0)
    password = cfg.get(SECTION, "redis_password", fallback="").strip()
    timeout = cfg.getfloat(SECTION, "redis_socket_timeout", fallback=2.0)

    kw: dict = dict(
        host=host,
        port=port,
        db=db,
        decode_responses=True,
        socket_connect_timeout=timeout,
        socket_timeout=timeout,
    )
    if password:
        kw["password"] = password
    try:
        r = redis.Redis(**kw)
        r.ping()
        return r
    except Exception:
        return None


def load_skill_file_cached(
    repo_root: Path,
    skill_dir_name: str,
    cfg: Optional[configparser.ConfigParser] = None,
) -> str:
    """
    读取 repo_root/skills/<skill_dir_name>/skill.md；启用 SKILL_CACHE 且 Redis 可用时走缓存。
    """
    name = skill_dir_name.strip()
    path = repo_root / "skills" / name / "skill.md"
    cfg = cfg if cfg is not None else _read_config(repo_root)

    mtime = path.stat().st_mtime

    if _skill_cache_enabled(cfg):
        key = redis_key_for_skill(cfg, name)
        r = _redis_client(cfg)
        if r is not None:
            try:
                cached_mtime = r.hget(key, "mtime")
                content = r.hget(key, "content")
                if (
                    cached_mtime is not None
                    and content is not None
                    and float(cached_mtime) == mtime
                ):
                    return content
            except Exception:
                pass

    text = path.read_text(encoding="utf-8")

    if _skill_cache_enabled(cfg):
        key = redis_key_for_skill(cfg, name)
        r = _redis_client(cfg)
        if r is not None:
            try:
                r.hset(key, mapping={"mtime": str(mtime), "content": text})
                ttl = cfg.getint(SECTION, "ttl_seconds", fallback=0)
                if ttl > 0:
                    r.expire(key, ttl)
            except Exception:
                pass

    return text


def load_daily_casual_skill_markdown(
    repo_root: Path,
    cfg: Optional[configparser.ConfigParser] = None,
) -> str:
    """供每日总结专用：等同 load_skill_file_cached(..., 'daily_casual_summary', ...)."""
    return load_skill_file_cached(repo_root, "daily_casual_summary", cfg)


def _casual_skill_preamble(loaded_skill_ids: list[str]) -> str:
    """告知模型：下列 Skill 为可用能力，匹配用户意图时按章节执行。"""
    lines = [
        "## 你已具备的技能（按需执行）",
        "",
        "以下技能已在下文以 `# Skill: …` 章节加载。**当用户需求与某一技能场景一致时，你必须按该章节的步骤、格式与约束来组织回答**，而不是忽略这些说明。",
        "在仅有对话、未接入真实 HTTP/机器人时：**不要虚构已成功调用飞书等外部接口**；应产出**可直接复制使用或可交给开发者接入**的正文、模板或请求体说明。",
        "",
        "**当前已加载的技能标识**（按章节名一一对应）：",
    ]
    for sid in loaded_skill_ids:
        lines.append(f"- **{sid}** → 见下方章节 `# Skill: {sid}`")
    lines.extend([
        "",
        "若用户话题与上述技能均无关，按常规模块回答即可，不必套用技能。",
    ])
    return "\n".join(lines)


def merge_casual_skills_into_prompt(
    repo_root: Path,
    base_prompt: str,
    skill_dir_names: list[str],
    cfg: Optional[configparser.ConfigParser] = None,
) -> str:
    """
    在 casual 主 prompt 后先插入「可用技能」说明，再按顺序拼接各 skills/<name>/skill.md。
    """
    cfg = cfg if cfg is not None else _read_config(repo_root)
    names = [n.strip() for n in skill_dir_names if n.strip()]
    if not names:
        return base_prompt

    loaded: list[tuple[str, str]] = []
    for name in names:
        path = repo_root / "skills" / name / "skill.md"
        if not path.is_file():
            continue
        body = load_skill_file_cached(repo_root, name, cfg)
        loaded.append((name, body.strip()))

    if not loaded:
        return base_prompt

    preamble = _casual_skill_preamble([n for n, _ in loaded])
    blocks: list[str] = [base_prompt.rstrip(), preamble]
    for name, body in loaded:
        blocks.append(f"# Skill: {name}\n\n{body}")
    return "\n\n---\n\n".join(blocks)
