"""
从已落盘的会话文件中检索历史对话，回答用户关于「以前说过什么」的问题。
各 SOURCE_AGENTS 仅读取该类型目录下按文件名排序的**最近一条** memory_*.txt。
多代理记忆整合预留接口，当前仅实现单一 SOURCE_AGENTS。
"""

from __future__ import annotations

import json
import os
import re
from typing import Tuple

from sources.utility import pretty_print, animate_thinking
from sources.agents.agent import Agent
from sources.memory import Memory, get_latest_saved_memory_filepath
from sources.logger import Logger

# 与 save_session 写入的目录名一致（planner_agent 通常不落盘，不参与检索）
_KNOWN_SOURCE_TYPES = frozenset(
    {"casual_agent", "code_agent", "file_agent", "browser_agent"}
)


class MemoryAgent(Agent):
    def __init__(self, name, prompt_path, provider, verbose=False):
        super().__init__(name, prompt_path, provider, verbose, None)
        self.tools = {}
        self.role = "memory_recall"
        self.type = "memory_agent"
        self._prompt_path = prompt_path
        self.memory = Memory(
            self.load_prompt(prompt_path),
            recover_last_session=False,
            memory_compression=False,
            model_provider=provider.get_model_name(),
        )
        self.logger = Logger("memory_agent.log")

    def _parse_directive(self, task_text: str) -> tuple[list[str], str | None, str | None]:
        """
        从 Planner 下发的 task 中解析 SOURCE_AGENTS 与 QUERY。
        返回 (sources, query, error)。error 非空则不应继续执行。
        """
        sources: list[str] = []
        query: str | None = None
        for raw_line in task_text.replace("\r\n", "\n").split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            upper = line.upper()
            if upper.startswith("SOURCE_AGENTS:") or line.startswith("来源代理:"):
                sep = ":" if ":" in line else "："
                parts = re.split(r"[:：]", line, maxsplit=1)
                if len(parts) < 2:
                    continue
                for token in re.split(r"[,，\s]+", parts[1].strip()):
                    t = token.strip().lower()
                    if t:
                        sources.append(t)
            elif upper.startswith("QUERY:") or line.startswith("用户问题:") or line.startswith("查询:"):
                parts = re.split(r"[:：]", line, maxsplit=1)
                if len(parts) == 2:
                    query = parts[1].strip()
        if not sources:
            for t in _KNOWN_SOURCE_TYPES:
                if t in task_text.lower():
                    sources = [t]
                    break
        if not query:
            query = task_text.strip()
        if not sources:
            return [], None, "task 中未指定 SOURCE_AGENTS（或未能推断代理类型），请 Planner 写明，例如 SOURCE_AGENTS: casual_agent"
        if not query:
            return sources, None, "未指定 QUERY（用户想对照历史确认的问题）。"
        return sources, query, None

    def _merge_multi_agent_memories_placeholder(self, sources: list[str], query: str) -> str:
        """多代理记忆整合：预留，后续实现。"""
        return (
            "【多代理记忆整合尚未实现】当前已解析到多个来源："
            f"{', '.join(sources)}。"
            f"用户问题：{query}\n"
            "请之后实现跨目录合并与冲突消解；现阶段请让 Planner 仅指定单一 SOURCE_AGENTS。"
        )

    def _load_records_from_file(self, path: str) -> list | None:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            if not isinstance(data, list):
                self.logger.warning(f"Memory file is not a list: {path}")
                return None
            return data
        except Exception as e:
            self.logger.warning(f"Failed to load memory file {path}: {e}")
            return None

    def _prepare_memory_from_records(self, records: list, query: str) -> None:
        """用本代理 system prompt 新建会话，并注入导入的历史消息。"""
        self.memory = Memory(
            self.load_prompt(self._prompt_path),
            recover_last_session=False,
            memory_compression=False,
            model_provider=self.llm.get_model_name(),
        )
        for item in records:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            if role == "system":
                continue
            content = item.get("content", "")
            if role in ("user", "assistant") and content:
                self.memory.memory.append(
                    {"role": role, "content": str(content)}
                )
        instruction = (
            "以上 JSON 为从磁盘导入的该代理历史会话摘要（按时间顺序）。"
            "请仅依据这些内容回答，不要编造未见过的对话；若记录中没有相关信息，请明确说明。\n\n"
            f"用户当前问题：{query}"
        )
        self.memory.push("user", instruction)

    async def process(self, prompt, speech_module) -> Tuple[str, str]:
        # prompt 可能含 make_prompt 包装；任务体里应含 SOURCE_AGENTS / QUERY
        task_body = prompt
        if "你需要在本步骤完成的任务：" in prompt:
            task_body = prompt.split("你需要在本步骤完成的任务：", 1)[-1].strip()

        sources, query, err = self._parse_directive(task_body)
        if err:
            pretty_print(err, color="warning")
            self.last_answer = err
            self.success = False
            return err, ""

        bad = [s for s in sources if s not in _KNOWN_SOURCE_TYPES]
        if bad:
            msg = f"未知的 SOURCE_AGENTS: {bad}，允许值为 {_KNOWN_SOURCE_TYPES}"
            pretty_print(msg, color="warning")
            self.last_answer = msg
            self.success = False
            return msg, ""

        if len(sources) > 1:
            msg = self._merge_multi_agent_memories_placeholder(sources, query or "")
            pretty_print(msg, color="warning")
            self.last_answer = msg
            self.success = False
            return msg, ""

        agent_type = sources[0]
        cwd = getattr(self, "current_directory", None) or os.getcwd()
        conv_root = os.path.join(cwd, "conversations")

        path = get_latest_saved_memory_filepath(agent_type, conv_root)
        if not path or not os.path.isfile(path):
            msg = (
                f"未找到 {agent_type} 的已保存会话（请先开启 save_session 并至少保存过一次）。"
                f" 查找目录：{os.path.join(conv_root, agent_type)}"
            )
            pretty_print(msg, color="warning")
            self.last_answer = msg
            self.success = False
            return msg, ""

        records = self._load_records_from_file(path)
        if not records:
            msg = f"无法读取会话文件或格式无效：{path}"
            pretty_print(msg, color="warning")
            self.last_answer = msg
            self.success = False
            return msg, ""

        self.logger.info(f"MemoryAgent loading {path} ({len(records)} records) for query.")
        pretty_print(f"已载入 {agent_type} 最近一条落盘会话：{path}", color="status")
        self._prepare_memory_from_records(records, query or "")

        animate_thinking("正在对照历史会话思考…", color="status")
        answer, reasoning = await self.llm_request()
        self.last_answer = answer
        self.success = True
        self.status_message = "Ready"
        return answer, reasoning
