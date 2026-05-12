import json
from typing import List, Tuple, Type, Dict
from pydantic import ValidationError
from sources.planner_plan_schema import PlanDocument, plan_document_to_agent_dicts
from sources.utility import pretty_print, animate_thinking
from sources.agents.agent import Agent
from sources.agents.code_agent import CoderAgent
from sources.agents.file_agent import FileAgent
from sources.agents.browser_agent import BrowserAgent
from sources.agents.casual_agent import CasualAgent
from sources.agents.memory_agent import MemoryAgent
from sources.text_to_speech import Speech
from sources.tools.tools import Tools
from sources.logger import Logger
from sources.memory import Memory

class PlannerAgent(Agent):
    def __init__(self, name, prompt_path, provider, verbose=False, browser=None):
        """
        The planner agent is a special agent that divides and conquers the task.
        """
        super().__init__(name, prompt_path, provider, verbose, None)
        self.tools = {
            "json": Tools()
        }
        self.tools['json'].tag = "json"
        self.browser = browser
        self.agents = {
            "coder": CoderAgent(name, "prompts/base/coder_agent.txt", provider, verbose=False),
            "file": FileAgent(name, "prompts/base/file_agent.txt", provider, verbose=False),
            "web": BrowserAgent(name, "prompts/base/browser_agent.txt", provider, verbose=False, browser=browser),
            "casual": CasualAgent(name, "prompts/base/casual_agent.txt", provider, verbose=False),
            "memory": MemoryAgent(name, "prompts/base/memory_agent.txt", provider, verbose=False),
        }
        self.role = "planification"
        self.type = "planner_agent"
        self.memory = Memory(self.load_prompt(prompt_path),
                                recover_last_session=False, # session recovery in handled by the interaction class
                                memory_compression=False,
                                model_provider=provider.get_model_name())
        self.logger = Logger("planner_agent.log")
    
    def get_task_names(self, text: str) -> List[str]:
        """
        Extracts task names from the given text.
        This method processes a multi-line string, where each line may represent a task name.
        containing '##' or starting with a digit. The valid task names are collected and returned.
        Args:
            text (str): A string containing potential task titles (eg: Task 1: I will...).
        Returns:
            List[str]: A list of extracted task names that meet the specified criteria.
        """
        tasks_names = []
        lines = text.strip().split('\n')
        for line in lines:
            if line is None:
                continue
            line = line.strip()
            if len(line) == 0:
                continue
            if '##' in line or line[0].isdigit():
                tasks_names.append(line)
                continue
        self.logger.info(f"Found {len(tasks_names)} tasks names.")
        return tasks_names

    def _extract_plan_raw_dict(self, text: str) -> dict | None:
        """
        从模型回复中取出根 JSON 对象（优先纯 JSON / raw_decode；兼容历史 ```json 代码块）。
        """
        s = (text or "").strip()
        if not s:
            return None
        if s.startswith("```"):
            first_nl = s.find("\n")
            if first_nl != -1:
                s = s[first_nl + 1 :]
            s = s.rstrip()
            if s.endswith("```"):
                s = s[:-3].strip()
        for slice_start in (0, s.find("{")):
            if slice_start < 0:
                continue
            chunk = s[slice_start:] if slice_start else s
            try:
                obj, _ = json.JSONDecoder().raw_decode(chunk.lstrip())
                if isinstance(obj, dict) and "plan" in obj:
                    return obj
            except json.JSONDecodeError:
                continue
        blocks, _ = self.tools["json"].load_exec_block(text)
        if blocks:
            try:
                line_json = json.loads(blocks[0])
                if isinstance(line_json, dict) and "plan" in line_json:
                    return line_json
            except json.JSONDecodeError as e:
                self.logger.warning(f"Failed to parse JSON block: {e}")
        return None

    def parse_agent_tasks(self, text: str) -> List[Tuple[str, str]]:
        """
        Parses agent tasks from the given LLM text.
        抽取 JSON 后使用 Pydantic（PlanDocument）校验 plan 结构。
        """
        tasks_names = self.get_task_names(text)
        raw = self._extract_plan_raw_dict(text)
        if raw is None:
            self.logger.warning("No plan JSON object found in planner response.")
            return []
        try:
            doc = PlanDocument.model_validate(raw)
        except ValidationError as e:
            self.logger.warning(f"Plan Pydantic validation failed: {e}")
            err = e.errors()
            hint = err[0].get("msg", str(e)) if err else str(e)
            loc = err[0].get("loc", ()) if err else ()
            pretty_print(f"计划 JSON 未通过校验（{loc}: {hint}）。详见 planner_agent.log。", color="warning")
            return []
        agent_dicts = plan_document_to_agent_dicts(doc)
        tasks = []
        for agent in agent_dicts:
            self.logger.info(f"Created agent {agent['agent']} with task: {agent['task']}")
            if agent.get("need"):
                self.logger.info(f"Agent {agent['agent']} was given info:\n {agent['need']}")
            tasks.append(agent)
        if len(tasks_names) != len(tasks):
            names = [t["task"] for t in tasks]
            return list(map(list, zip(names, tasks)))
        return list(map(list, zip(tasks_names, tasks)))
    
    def make_prompt(self, task: str, agent_infos_dict: dict) -> str:
        """
        Generates a prompt for the agent based on the task and previous agents work information.
        Args:
            task (str): The task to be performed.
            agent_infos_dict (dict): A dictionary containing information from other agents.
        Returns:
            str: The formatted prompt for the agent.
        """
        infos = ""
        if agent_infos_dict is None or len(agent_infos_dict) == 0:
            infos = "（当前步骤不依赖先前步骤的输出。）"
        else:
            for agent_id, info in agent_infos_dict.items():
                infos += f"\t- 来自步骤 id={agent_id} 的代理输出：\n{info}\n\n"
        prompt = f"""以下是前置步骤代理产出的信息，供你参考：
{infos}
你需要在本步骤完成的任务：
{task}
"""
        self.logger.info(f"Prompt for agent:\n{prompt}")
        return prompt
    
    def show_plan(self, agents_tasks: List[dict], answer: str) -> None:
        """
        Displays the plan made by the agent.
        Args:
            agents_tasks (dict): The tasks assigned to each agent.
            answer (str): The answer from the LLM.
        """
        if agents_tasks == []:
            pretty_print(answer, color="warning")
            pretty_print("Failed to make a plan. This can happen with (too) small LLM. Clarify your request and insist on it making a plan within ```json.", color="failure")
            return
        pretty_print("\n▂▘ P L A N ▝▂", color="status")
        for task_name, task in agents_tasks:
            pretty_print(f"{task['agent']} -> {task['task']}", color="info")
        pretty_print("▔▗ E N D ▖▔", color="status")

    def _degraded_casual_tasks(self, user_goal: str) -> list:
        """
        当计划 JSON 多次解析失败时，退化为单步 casual，由 casual_agent 直接处理用户原始目标。
        """
        task_dict = {
            "agent": "casual",
            "id": "1",
            "task": user_goal,
            "need": []
        }
        title = "以对话方式完成用户需求（计划 JSON 多次解析失败，已降级）"
        self.logger.warning("make_plan: degraded to single casual step after repeated parse failures.")
        return [[title, task_dict]]

    async def make_plan(
        self,
        prompt: str,
        max_parse_failures: int | None = None,
        degrade_to_casual_on_failure: bool = False,
    ) -> list:
        """
        Asks the LLM to make a plan.
        Args:
            prompt (str): The prompt to be sent to the LLM.
            max_parse_failures: If set, stop after this many consecutive parse failures (each failed round
                increments after one LLM response). None = unlimited retries (e.g. update_plan).
            degrade_to_casual_on_failure: If True and max_parse_failures is reached, return a one-step
                casual plan for the original user goal instead of retrying forever.
        Returns:
            list: Parsed agent tasks (same shape as parse_agent_tasks), or [] on NO_UPDATE.
        """
        original_user_goal = prompt
        ok = False
        answer = None
        parse_failure_count = 0
        while not ok:
            animate_thinking("Thinking...", color="status")
            self.memory.push('user', prompt)
            answer, reasoning = await self.llm_request()
            if "NO_UPDATE" in answer:
                return []
            agents_tasks = self.parse_agent_tasks(answer)
            if agents_tasks == []:
                self.show_plan(agents_tasks, answer)
                parse_failure_count += 1
                if (
                    max_parse_failures is not None
                    and degrade_to_casual_on_failure
                    and parse_failure_count >= max_parse_failures
                ):
                    pretty_print(
                        "已连续多次无法解析计划 JSON，改为由 casual 代理以对话方式处理您的请求。",
                        color="warning",
                    )
                    return self._degraded_casual_tasks(original_user_goal)
                prompt = f"Failed to parse the tasks. Please write down your task followed by a json plan within ```json. Do not ask for clarification.\n"
                pretty_print("Failed to make plan. Retrying...", color="warning")
                continue
            self.show_plan(agents_tasks, answer)
            ok = True
        self.logger.info(f"Plan made:\n{answer}")
        return self.parse_agent_tasks(answer)
    
    async def update_plan(self, goal: str, agents_tasks: List[dict], agents_work_result: dict, id: str, success: bool) -> dict:
        """
        Updates the plan with the results of the agents work.
        Args:
            goal (str): The goal to be achieved.
            agents_tasks (list): The tasks assigned to each agent.
            agents_work_result (dict): The results of the agents work.
        Returns:
            dict: The updated plan.
        """
        self.status_message = "正在更新计划…"
        last_agent_work = agents_work_result[id]
        tool_success_str = "成功" if success else "失败"
        pretty_print(f"步骤 id={id} 的执行结果：{tool_success_str}。", color="success" if success else "failure")
        try:
            id_int = int(id)
        except Exception as e:
            return agents_tasks
        if id_int == len(agents_tasks):
            next_task = "当前已是原计划中的最后一步；若本步失败，可在新计划中增加一步用于重试或补救。"
        else:
            next_task = f"原计划中紧接着的下一步（摘要）为：{agents_tasks[int(id)][0]}。"
        #if success:
        #    return agents_tasks # we only update the plan if last task failed, for now
        update_prompt = f"""
你的总体目标是：{goal}
你先前已制定计划，各代理正在按序执行。
刚完成的是步骤 id={id}，其产出如下：
{last_agent_work}
系统解释器判定：步骤 {id} 的执行结果为「{tool_success_str}」。
{next_task}
请判断：步骤 {id} 的产出是否达到预期？是否需要在后续步骤中补救或重试？
- 若结果良好、后续可按原计划继续：请**仅**回复一行大写英文：NO_UPDATE（不要输出 ```json，也不要其它说明）。
- 若执行失败或必须调整后续任务：请**只输出一个 JSON 对象**（可含 reasoning + plan，格式与初次制定计划相同），不要 `## Task`、不要 JSON 外的说明。
- 新计划中：id 小于等于 {id} 的步骤须与当前计划**完全一致**（代理、任务描述、need 均不变）；只允许修改 id 大于 {id} 的步骤，或在末尾**最多增加一步**用于重试/补救。
- 计划总步数应与原 plan 相同，或仅比原来多一步。
"""
        pretty_print("正在更新计划…", color="status")
        plan = await self.make_plan(update_prompt)
        if plan == []:
            pretty_print("无需更新计划（NO_UPDATE 或解析失败时均会回到当前计划）。", color="info")
            return agents_tasks
        self.logger.info(f"Plan updated:\n{plan}")
        return plan
    
    async def start_agent_process(self, task: dict, required_infos: dict | None) -> str:
        """
        Starts the agent process for a given task.
        Args:
            task (dict): The task to be performed.
            required_infos (dict | None): The required information for the task.
        Returns:
            str: The result of the agent process.
        """
        self.status_message = f"Starting task {task['task']}..."
        agent_prompt = self.make_prompt(task['task'], required_infos)
        pretty_print(f"Agent {task['agent']} started working...", color="status")
        self.logger.info(f"Agent {task['agent']} started working on {task['task']}.")
        answer, reasoning = await self.agents[task['agent'].lower()].process(agent_prompt, None)
        self.last_answer = answer
        self.last_reasoning = reasoning
        self.blocks_result = self.agents[task['agent'].lower()].blocks_result
        agent_answer = self.agents[task['agent'].lower()].raw_answer_blocks(answer)
        success = self.agents[task['agent'].lower()].get_success
        self.agents[task['agent'].lower()].show_answer()
        pretty_print(f"Agent {task['agent']} completed task.", color="status")
        self.logger.info(f"Agent {task['agent']} finished working on {task['task']}. Success: {success}")
        agent_answer += "\nAgent succeeded with task." if success else "\nAgent failed with task (Error detected)."
        return agent_answer, success
    
    def get_work_result_agent(self, task_needs, agents_work_result):
        res = {k: agents_work_result[k] for k in task_needs if k in agents_work_result}
        self.logger.info(f"Next agent needs: {task_needs}.\n Match previous agent result: {res}")
        return res

    async def process(self, goal: str, speech_module: Speech) -> Tuple[str, str]:
        """
        Process the goal by dividing it into tasks and assigning them to agents.
        Args:
            goal (str): The goal to be achieved (user prompt).
            speech_module (Speech): The speech module for text-to-speech.
        Returns:
            Tuple[str, str]: The result of the agent process and empty reasoning string.
        """
        agents_tasks = []
        required_infos = None
        agents_work_result = dict()

        self.status_message = "Making a plan..."
        agents_tasks = await self.make_plan(
            goal, max_parse_failures=3, degrade_to_casual_on_failure=True
        )

        if agents_tasks == []:
            return "Failed to parse the tasks.", ""
        i = 0
        steps = len(agents_tasks)
        while i < steps and not self.stop:
            task_name, task = agents_tasks[i][0], agents_tasks[i][1]
            self.status_message = "Starting agents..."
            pretty_print(f"I will {task_name}.", color="info")
            self.last_answer = f"I will {task_name.lower()}."
            pretty_print(f"Assigned agent {task['agent']} to {task_name}", color="info")
            if speech_module: speech_module.speak(f"I will {task_name}. I assigned the {task['agent']} agent to the task.")

            if agents_work_result is not None:
                required_infos = self.get_work_result_agent(
                    task.get("need", []), agents_work_result
                )
            try:
                answer, success = await self.start_agent_process(task, required_infos)
            except Exception as e:
                raise e
            if self.stop:
                pretty_print(f"Requested stop.", color="failure")
            agents_work_result[task['id']] = answer
            agents_tasks = await self.update_plan(goal, agents_tasks, agents_work_result, task['id'], success)
            steps = len(agents_tasks)
            i += 1

        return answer, ""
