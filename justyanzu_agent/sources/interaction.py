from __future__ import annotations

import readline
import threading
import time
import datetime as dt
from typing import List, Tuple, Type, Dict

from sources.text_to_speech import Speech
from sources.utility import pretty_print, animate_thinking
from sources.router import AgentRouter
from sources.agents.casual_agent import FEISHU_SKILL_MEMORY_MARK
from sources.speech_to_text import AudioTranscriber, AudioRecorder


def _seconds_until_clock(hour: int, minute: int) -> float:
    now = dt.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return (target - now).total_seconds()


def _daily_scheduled_worker(
    interaction: Interaction, hour: int, minute: int, task_kind: str
) -> None:
    last_run_date: str | None = None
    kind = (task_kind or "casual_summary").strip().lower()
    while getattr(interaction, "is_active", True):
        sec = _seconds_until_clock(hour, minute)
        while sec > 0 and getattr(interaction, "is_active", True):
            time.sleep(min(sec, 60.0))
            sec = _seconds_until_clock(hour, minute)
        if not getattr(interaction, "is_active", True):
            break
        today = dt.date.today().isoformat()
        if last_run_date == today:
            time.sleep(65)
            continue
        casual = None
        for a in interaction.agents:
            if getattr(a, "type", None) == "casual_agent":
                casual = a
                break
        if casual is None and kind != "boss_jobs":
            last_run_date = today
            continue
        try:
            if kind == "boss_jobs":
                from sources.daily_boss_jobs_runner import run_scheduled_boss_jobs

                cfg = getattr(interaction, "_scheduler_config", None)
                out = run_scheduled_boss_jobs(casual, cfg)
                pretty_print(
                    f"\n─── Boss 职位抓取与摘要 ({today}) ───\n已写入: {out}\n",
                    color="success",
                )
            else:
                from sources.daily_summary_runner import run_daily_summary

                summary = run_daily_summary(casual)
                pretty_print(f"\n─── 每日总结 ({today}) ───\n{summary}\n", color="success")
        except Exception as e:
            pretty_print(f"定时任务失败 ({kind}): {e}", color="error")
        finally:
            last_run_date = today


class Interaction:
    """
    Interaction is a class that handles the interaction between the user and the agents.
    """
    def __init__(self, agents,
                 tts_enabled: bool = True,
                 stt_enabled: bool = True,
                 recover_last_session: bool = False,
                 langs: List[str] = ["en", "zh"],
                 daily_casual_summary: bool = False,
                 daily_summary_hour: int = 22,
                 daily_summary_minute: int = 0,
                 daily_scheduled_task_kind: str = "casual_summary",
                 scheduler_config=None,
                ):
        self.is_active = True
        self.current_agent = None
        self.last_query = None
        self.last_answer = None
        self.last_reasoning = None
        self.agents = agents
        self.tts_enabled = tts_enabled
        self.stt_enabled = stt_enabled
        self.recover_last_session = recover_last_session
        self.router = AgentRouter(self.agents, supported_language=langs)
        self.ai_name = self.find_ai_name()
        self.speech = None
        self.transcriber = None
        self.recorder = None
        self.is_generating = False
        self.languages = langs
        if tts_enabled:
            self.initialize_tts()
        if stt_enabled:
            self.initialize_stt()
        if recover_last_session:
            self.load_last_session()
        self._scheduler_config = scheduler_config
        self.emit_status()
        if daily_casual_summary:
            threading.Thread(
                target=_daily_scheduled_worker,
                args=(
                    self,
                    int(daily_summary_hour),
                    int(daily_summary_minute),
                    daily_scheduled_task_kind,
                ),
                daemon=True,
            ).start()
    
    def get_spoken_language(self) -> str:
        """Get the primary TTS language."""
        lang = self.languages[0]
        return lang

    def initialize_tts(self):
        """Initialize TTS."""
        if not self.speech:
            animate_thinking("Initializing text-to-speech...", color="status")
            self.speech = Speech(enable=self.tts_enabled, language=self.get_spoken_language(), voice_idx=1)

    def initialize_stt(self):
        """Initialize STT."""
        if not self.transcriber or not self.recorder:
            animate_thinking("Initializing speech recognition...", color="status")
            self.transcriber = AudioTranscriber(self.ai_name, verbose=False)
            self.recorder = AudioRecorder()
    
    def emit_status(self):
        """Print the current status of agenticSeek."""
        if self.stt_enabled:
            pretty_print(f"Text-to-speech trigger is {self.ai_name}", color="status")
        if self.tts_enabled:
            self.speech.speak("Hello, we are online and ready. What can I do for you ?")
        pretty_print("AgenticSeek is ready.", color="status")
    
    def find_ai_name(self) -> str:
        """Find the name of the default AI. It is required for STT as a trigger word."""
        ai_name = "jarvis"
        for agent in self.agents:
            if agent.type == "casual_agent":
                ai_name = agent.agent_name
                break
        return ai_name
    
    def get_last_blocks_result(self) -> List[Dict]:
        """Get the last blocks result."""
        if self.current_agent is None:
            return []
        blks = []
        for agent in self.agents:
            blks.extend(agent.get_blocks_result())
        return blks
    
    def load_last_session(self):
        """Recover the last session."""
        for agent in self.agents:
            if agent.type in ("planner_agent", "memory_agent"):
                continue
            agent.memory.load_memory(agent.type)
            # 恢复文件里的 system 可能是旧版（未含 skill）；若 Agent 在构造时保存了当前完整 system，则写回首条
            fresh = getattr(agent, "_system_prompt_text", None)
            if fresh is not None:
                mem = agent.memory.get()
                if mem and mem[0].get("role") == "system":
                    loaded = mem[0]["content"]
                    if agent.type == "casual_agent" and FEISHU_SKILL_MEMORY_MARK in loaded:
                        agent._system_prompt_text = loaded
                    else:
                        mem[0]["content"] = fresh
    
    def save_session(self):
        """Save the current session."""
        for agent in self.agents:
            if agent.type in ("planner_agent", "memory_agent"):
                continue
            agent.memory.save_memory(agent.type)

    def is_active(self) -> bool:
        return self.is_active
    
    def read_stdin(self) -> str:
        """Read the input from the user."""
        buffer = ""

        PROMPT = "\033[1;35m➤➤➤ \033[0m"
        while not buffer:
            try:
                buffer = input(PROMPT)
            except EOFError:
                return None
            if buffer == "exit" or buffer == "goodbye":
                return None
        return buffer
    
    def transcription_job(self) -> str:
        """Transcribe the audio from the microphone."""
        self.recorder = AudioRecorder(verbose=True)
        self.transcriber = AudioTranscriber(self.ai_name, verbose=True)
        self.transcriber.start()
        self.recorder.start()
        self.recorder.join()
        self.transcriber.join()
        query = self.transcriber.get_transcript()
        if query == "exit" or query == "goodbye":
            return None
        return query

    def get_user(self) -> str:
        """Get the user input from the microphone or the keyboard."""
        if self.stt_enabled:
            query = "TTS transcription of user: " + self.transcription_job()
        else:
            query = self.read_stdin()
        if query is None:
            self.is_active = False
            self.last_query = None
            return None
        self.last_query = query
        return query
    
    def set_query(self, query: str) -> None:
        """Set the query"""
        self.is_active = True
        self.last_query = query
    
    async def think(self) -> bool:
        """Request AI agents to process the user input."""
        push_last_agent_memory = False
        if self.last_query is None or len(self.last_query) == 0:
            return False
        agent = self.router.select_agent(self.last_query)
        if agent is None:
            return False
        if self.current_agent != agent and self.last_answer is not None:
            push_last_agent_memory = True
        tmp = self.last_answer
        self.current_agent = agent
        self.is_generating = True
        self.last_answer, self.last_reasoning = await agent.process(self.last_query, self.speech)
        self.is_generating = False
        if push_last_agent_memory:
            self.current_agent.memory.push('user', self.last_query)
            self.current_agent.memory.push('assistant', self.last_answer)
        if self.last_answer == tmp:
            self.last_answer = None
        return True
    
    def get_updated_process_answer(self) -> str:
        """Get the answer from the last agent."""
        if self.current_agent is None:
            return None
        return self.current_agent.get_last_answer()
    
    def get_updated_block_answer(self) -> str:
        """Get the answer from the last agent."""
        if self.current_agent is None:
            return None
        return self.current_agent.get_last_block_answer()
    
    def speak_answer(self) -> None:
        """Speak the answer to the user in a non-blocking thread."""
        if self.last_query is None:
            return
        if self.tts_enabled and self.last_answer and self.speech:
            def speak_in_thread(speech_instance, text):
                speech_instance.speak(text)
            thread = threading.Thread(target=speak_in_thread, args=(self.speech, self.last_answer))
            thread.start()
    
    def show_answer(self) -> None:
        """Show the answer to the user."""
        if self.last_query is None:
            return
        if self.current_agent is not None:
            self.current_agent.show_answer()

