#!/usr/bin python3

import sys
import argparse
import configparser
import asyncio
import subprocess


def _ensure_pydantic() -> None:
    """Planner 依赖 Pydantic；若未安装则自动下载（与 requirements.txt 版本区间一致）。"""
    try:
        import pydantic  # noqa: F401
    except ImportError:
        print(
            "未检测到 pydantic，正在通过 pip 安装 pydantic、pydantic_core …",
            file=sys.stderr,
        )
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "pydantic>=2.10.6",
                "pydantic_core>=2.27.2",
            ]
        )


_ensure_pydantic()

from sources.llm_provider import Provider
from sources.interaction import Interaction
from sources.agents import (
    CoderAgent,
    CasualAgent,
    FileAgent,
    PlannerAgent,
    MemoryAgent,
)
from sources.skill_redis_cache import parse_casual_skill_dirs
from sources.utility import pretty_print

import warnings
warnings.filterwarnings("ignore")

config = configparser.ConfigParser()
config.read('config.ini')


def _casual_skill_dirs(cfg: configparser.ConfigParser) -> list:
    if not cfg.has_section("CASUAL_AGENT"):
        return []
    raw = cfg.get("CASUAL_AGENT", "skills", fallback="")
    return [x.strip() for x in raw.split(",") if x.strip()]


def _main_daily_summary_kwargs(cfg: configparser.ConfigParser) -> dict:
    sec = "MAIN"
    return {
        "daily_casual_summary": cfg.getboolean(sec, "daily_casual_summary")
        if cfg.has_option(sec, "daily_casual_summary")
        else False,
        "daily_summary_hour": cfg.getint(sec, "daily_casual_summary_hour")
        if cfg.has_option(sec, "daily_casual_summary_hour")
        else 22,
        "daily_summary_minute": cfg.getint(sec, "daily_casual_summary_minute")
        if cfg.has_option(sec, "daily_casual_summary_minute")
        else 0,
        "daily_scheduled_task_kind": cfg.get(
            sec, "daily_scheduled_task_kind", fallback="casual_summary"
        ),
        "scheduler_config": cfg,
    }


async def main():
    pretty_print("Initializing...", color="status")
    personality_folder = "jarvis" if config.getboolean('MAIN', 'jarvis_personality') else "base"
    languages = config["MAIN"]["languages"].split(' ')

    provider = Provider(provider_name=config["MAIN"]["provider_name"],
                        model=config["MAIN"]["provider_model"],
                        server_address=config["MAIN"]["provider_server_address"],
                        is_local=config.getboolean('MAIN', 'is_local'))

    agents = [
        CasualAgent(
            name=config["MAIN"]["agent_name"],
            prompt_path=f"prompts/{personality_folder}/casual_agent.txt",
            provider=provider,
            verbose=False,
            casual_skill_dirs=parse_casual_skill_dirs(config),
            cfg=config,
        ),
        CoderAgent(name="coder",
                   prompt_path=f"prompts/{personality_folder}/coder_agent.txt",
                   provider=provider, verbose=False),
        FileAgent(name="File Agent",
                  prompt_path=f"prompts/{personality_folder}/file_agent.txt",
                  provider=provider, verbose=False),
        MemoryAgent(
            name="Memory",
            prompt_path=f"prompts/{personality_folder}/memory_agent.txt",
            provider=provider,
            verbose=False,
        ),
        PlannerAgent(name="Planner",
                     prompt_path=f"prompts/{personality_folder}/planner_agent.txt",
                     provider=provider,
                     verbose=False,
                     cfg=config,
                     personality_folder=personality_folder),
    ]

    interaction = Interaction(
        agents,
        tts_enabled=config.getboolean('MAIN', 'speak'),
        stt_enabled=config.getboolean('MAIN', 'listen'),
        recover_last_session=config.getboolean('MAIN', 'recover_last_session'),
        langs=languages,
        **_main_daily_summary_kwargs(config),
    )
    try:
        while interaction.is_active:
            interaction.get_user()
            if await interaction.think():
                interaction.show_answer()
                interaction.speak_answer()
    except Exception as e:
        if config.getboolean('MAIN', 'save_session'):
            interaction.save_session()
        raise e
    finally:
        if config.getboolean('MAIN', 'save_session'):
            interaction.save_session()

if __name__ == "__main__":
    asyncio.run(main())