"""Multi-Agent Storytelling Engine (MASE)

一个基于 LangGraph 的多智能体协作叙事引擎。多个 AI 角色在 Dungeon Master (DM)
的裁决下，按照"角色意图 → DM 裁决 → 状态更新 → 记忆沉淀"的流程自动推进故事。

核心能力：
- 创建故事会话、角色和场景
- LangGraph 编排多轮叙事
- JSON 文件持久化
- 支持本地规则型 + DeepSeek 双 LLM 适配器
- FastAPI HTTP 接口
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
