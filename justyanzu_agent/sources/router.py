"""
路由：所有用户输入统一交给 Planner，由其在内部规划并调用子代理。
不再使用 BART / llm_router 投票、复杂度预估等预路由步骤。
"""
from typing import List

from sources.agents.agent import Agent
from sources.logger import Logger
from sources.utility import pretty_print


class AgentRouter:
    def __init__(self, agents: list, supported_language: List[str] = ["en", "fr", "zh"]):
        self.agents = agents
        self.logger = Logger("router.log")
        # 与 Interaction 构造签名兼容；Planner 路径下不再做按语言预分类
        self._supported_language = supported_language

    def find_planner_agent(self) -> Agent | None:
        for agent in self.agents:
            if agent.type == "planner_agent":
                return agent
        pretty_print(
            "Error finding planner agent. Please add a planner agent to the list of agents.",
            color="failure",
        )
        self.logger.error("Planner agent not found.")
        return None

    def select_agent(self, text: str) -> Agent | None:
        assert len(self.agents) > 0, "No agents available."
        if len(self.agents) == 1:
            return self.agents[0]
        planner = self.find_planner_agent()
        if planner is not None:
            pretty_print("路由：Planner（统一规划）", color="info")
            return planner
        return None


if __name__ == "__main__":
    print("AgentRouter: 所有查询交给 planner_agent；请通过 cli.py 使用。")
