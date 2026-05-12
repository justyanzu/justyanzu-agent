"""
定时任务：DrissionPage 监听 Boss joblist API → 保存 JSON + txt，可选 LLM 摘要。
配置见 config.ini [BOSS_SCHEDULED]。
"""
from __future__ import annotations

import configparser
import datetime as dt
import json
from pathlib import Path
from typing import TYPE_CHECKING

from sources.boss_zhipin_scraper import BossJobBrief, scrape_boss_jobs

if TYPE_CHECKING:
    from sources.agents.casual_agent import CasualAgent

SECTION = "BOSS_SCHEDULED"


def _read_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    root = Path(__file__).resolve().parents[1]
    for p in (Path.cwd() / "config.ini", root / "config.ini"):
        if p.is_file():
            cfg.read(p, encoding="utf-8")
            break
    return cfg


def _cfg_list(cfg: configparser.ConfigParser, key: str, default: str) -> list[str]:
    if not cfg.has_section(SECTION):
        return [x.strip() for x in default.split(",") if x.strip()]
    raw = cfg.get(SECTION, key, fallback=default)
    return [x.strip() for x in raw.split(",") if x.strip()]


def _format_jobs_plain(jobs: list[BossJobBrief]) -> str:
    lines: list[str] = []
    for i, j in enumerate(jobs, 1):
        lines.append(
            f"{i}. {j.title} | {j.salary_raw or '（薪资未列出）'} | {j.company or '（公司名未解析）'}"
        )
        if j.area:
            lines.append(f"   地区: {j.area}")
        if j.card_text:
            lines.append(f"   标签/规模: {j.card_text}")
        if j.url:
            lines.append(f"   链接: {j.url}")
        lines.append("")
    return "\n".join(lines).strip()


def run_scheduled_boss_jobs(
    casual_agent: "CasualAgent | None",
    cfg: configparser.ConfigParser | None = None,
    working_dir: Path | None = None,
) -> Path:
    """
    抓取职位（接口 JSON）、写入 raw JSON 与 txt；若有 casual_agent 则调用 LLM 摘要。
    """
    cfg = cfg if cfg is not None else _read_config()
    root = Path.cwd() if working_dir is None else working_dir

    queries = _cfg_list(cfg, "search_queries", "")
    city = cfg.get(SECTION, "city_code", fallback="101020100") if cfg.has_section(SECTION) else "101020100"
    headless = (
        cfg.getboolean(SECTION, "headless", fallback=True) if cfg.has_section(SECTION) else True
    )
    max_pages = (
        int(cfg.get(SECTION, "max_pages_per_query", fallback="8"))
        if cfg.has_section(SECTION)
        else 8
    )
    listen_timeout = (
        float(cfg.get(SECTION, "listen_timeout_sec", fallback="25"))
        if cfg.has_section(SECTION)
        else 25.0
    )
    scroll_pause = (
        float(cfg.get(SECTION, "scroll_pause_sec", fallback="1.8"))
        if cfg.has_section(SECTION)
        else 1.8
    )
    listen_target = (
        cfg.get(SECTION, "listen_target", fallback="joblist.json")
        if cfg.has_section(SECTION)
        else "joblist.json"
    )
    retry_visible = (
        cfg.getboolean(SECTION, "try_visible_browser_on_listen_fail", fallback=True)
        if cfg.has_section(SECTION)
        else True
    )

    out_sub = (
        cfg.get(SECTION, "output_dir", fallback="reports/boss_jobs")
        if cfg.has_section(SECTION)
        else "reports/boss_jobs"
    )
    max_llm = int(cfg.get(SECTION, "max_llm_chars", fallback="12000")) if cfg.has_section(SECTION) else 12000

    jobs, raw_rows = scrape_boss_jobs(
        queries=queries if queries else None,
        city_code=city.strip(),
        headless=headless,
        max_pages_per_query=max_pages,
        listen_timeout=listen_timeout,
        scroll_pause_sec=scroll_pause,
        listen_target=listen_target.strip(),
        try_visible_browser_on_listen_fail=retry_visible,
    )

    today = dt.date.today().isoformat()
    out_dir = (root / out_sub).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = out_dir / f"boss_jobs_{city}_{today}.txt"
    json_path = out_dir / f"boss_jobs_raw_{city}_{today}.json"

    json_path.write_text(
        json.dumps(raw_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    detail = _format_jobs_plain(jobs)
    summary_block = ""

    if casual_agent is not None and jobs:
        blob = (
            f"以下为 Boss 直聘「搜索页 + joblist 接口」抓取的职位摘要（城市码 {city}）。\n"
            f"原始 JSON 已保存至: {json_path.name}\n"
            f"职位条数：{len(jobs)}\n\n"
            f"列表：\n{detail}"
        )[:max_llm]
        messages = [
            {
                "role": "system",
                "content": (
                    "你是招聘情报整理助手。根据用户提供的 Boss 直聘职位条目做中文摘要："
                    "概括行业/岗位方向、技术栈或标签共现、薪资大致区间感受（仅依据原文，勿编造）。"
                    "结尾列出「值得优先打开的 3～5 条」并简述原因。"
                ),
            },
            {"role": "user", "content": blob},
        ]
        thought = casual_agent.llm.respond(messages, verbose=False)
        summary_block = casual_agent.remove_reasoning_text(thought).strip()
    elif not jobs:
        summary_block = (
            "（未抓取到职位：可能需登录/验证码、listen 目标与接口 URL 不一致或风控。"
            "可尝试 headless=False、调整 listen_target=wapi/zpgeek/search/joblist.json 等。）"
        )
    else:
        summary_block = "（未找到 casual_agent，跳过模型摘要；原始数据见 JSON。）"

    body = (
        f"生成时间（本地日期）：{today}\n"
        f"城市代码：{city} | 监听特征：{listen_target}\n"
        f"原始 JSON：{json_path.name}\n"
        f"职位条数：{len(jobs)}\n"
        f"\n========== 摘要 ==========\n\n{summary_block}\n\n"
        f"========== 职位明细 ==========\n\n{detail if detail else '（无）'}\n"
    )
    txt_path.write_text(body, encoding="utf-8")
    return txt_path
