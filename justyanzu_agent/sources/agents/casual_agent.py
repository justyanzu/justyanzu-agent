import asyncio
import configparser
from pathlib import Path
from typing import List, Optional

from sources.utility import animate_thinking, pretty_print
from sources.agents.agent import Agent
from sources.memory import Memory
from sources.feishu_outgoing import extract_feishu_block

# 相对项目根；仅在检测到飞书 payload 后再读入并注入系统提示
FEISHU_SKILL_MD = Path("skills") / "message_to_feishu" / "skill.md"
# 注入后出现在 system 里；interaction 恢复会话时也用此判断勿覆盖
FEISHU_SKILL_MEMORY_MARK = "# Skill: message_to_feishu"


class CasualAgent(Agent):
    def __init__(
        self,
        name,
        prompt_path,
        provider,
        verbose=False,
        casual_skill_dirs: Optional[List[str]] = None,
        cfg: Optional[configparser.ConfigParser] = None,
        repo_root: Optional[Path] = None,
    ):
        """
        casual_skill_dirs 仅为兼容 cli/api；飞书 skill 不在此初始化注入。
        """
        super().__init__(name, prompt_path, provider, verbose, None)
        self.tools = {}
        self.role = "talk"
        self.type = "casual_agent"

        root = repo_root if repo_root is not None else Path(__file__).resolve().parents[2]
        base_prompt = self.load_prompt(prompt_path).rstrip()
        self._system_prompt_text = base_prompt

        self.memory = Memory(
            base_prompt,
            recover_last_session=False,
            memory_compression=False,
            model_provider=provider.get_model_name(),
        )
        self._repo_root = root
        self._cfg = cfg

    def _inject_feishu_skill_if_absent(self) -> None:
        """检测到飞书外发后：把 message_to_feishu/skill.md 并入首条 system（幂等）。"""
        mem = self.memory.get()
        if not mem or mem[0].get("role") != "system":
            return
        if FEISHU_SKILL_MEMORY_MARK in mem[0]["content"]:
            return
        skill_path = self._repo_root / FEISHU_SKILL_MD
        if not skill_path.is_file():
            return
        body = skill_path.read_text(encoding="utf-8").strip()
        merged = (
            mem[0]["content"].rstrip()
            + "\n\n---\n\n"
            + FEISHU_SKILL_MEMORY_MARK
            + "\n\n"
            + body
        )
        mem[0]["content"] = merged
        self._system_prompt_text = merged

    async def process(self, prompt, speech_module) -> str:
        self.memory.push('user', prompt)
        animate_thinking("Thinking...", color="status")
        loop = asyncio.get_event_loop()
        thought = await loop.run_in_executor(
            self.executor,
            lambda: self.llm.respond(self.memory.get(), self.verbose),
        )
        reasoning = self.extract_reasoning_text(thought)
        answer = self.remove_reasoning_text(thought)

        _, payload = extract_feishu_block(answer)
        if payload is not None:
            pretty_print(
                "检测到飞书外发标识，已注入 message_to_feishu skill；再次请求模型按 skill 生成回复",
                color="status",
            )
            self._inject_feishu_skill_if_absent()
            # 首条回复未写入 memory，当前仍为 [system(已含 skill), user]；由模型在阅读 skill 后自行决定正文（如「愚人节快乐」）
            animate_thinking("Thinking (after skill inject)...", color="status")
            thought = await loop.run_in_executor(
                self.executor,
                lambda: self.llm.respond(self.memory.get(), self.verbose),
            )
            reasoning = self.extract_reasoning_text(thought)
            answer = self.remove_reasoning_text(thought).strip()
        else:
            answer = answer.strip()

        self.memory.push('assistant', answer)
        self.last_answer = answer
        self.status_message = "Ready"
        return answer, reasoning


if __name__ == "__main__":
    pass
