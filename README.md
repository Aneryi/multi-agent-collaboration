# AgentVerse：基于 LangGraph 的多 Agent 协作决策平台

> **面试定位**：展示 Multi-Agent、Memory System、Agent Evaluation、Observability 能力的 AI 应用开发项目。

## 文档导航

| 文档 | 说明 |
|---|---|
| [SPEC.md](SPEC.md) | 系统设计 Spec —— 架构图、模块设计、面试展示点 |
| [PROJECT_PHASES.md](PROJECT_PHASES.md) | 6 阶段开发计划 + 面试叙事脚本 |
| [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) | 目录结构与各文件作用说明 |
| [需求文档.md](需求文档.md) | 原始 MVP 需求基线（已被 SPEC.md 取代，保留参考） |

## 一句话总结

N 个 Character Agent 各自拥有独立的 Persona、三层记忆和目标 → Planner 编排 → DM 裁决 → Reflection 反思 → Observer 监控 → Evaluation 评分。基于 LangGraph 编排，通过 Protocol 抽象实现本地测试 / 云端模型无缝切换。

## 当前能力（阶段 0 已交付）

- ✅ Multi-Agent 协作叙事：2+ 角色独立生成意图，DM 统一裁决
- ✅ LangGraph 状态图：Intent → DM → State → Memory → 循环
- ✅ 双 LLM 适配器：Rule-based (本地测试) + DeepSeek (真实模型)
- ✅ FastAPI 7 个端点 + CLI demo
- ✅ JSON 持久化 + seed 可复现测试

## 快速开始

```bash
# 安装
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]

# 运行 demo（无需 API Key）
python -m mase.cli demo

# 使用 DeepSeek 真实模型
$env:DEEPSEEK_API_KEY = "sk-your-key-here"
python -m mase.cli --llm deepseek demo

# 启动 API
uvicorn mase.api.app:app --reload

# 运行测试
pytest
```

## 核心架构

```text
Character Agents × N  →  Planner Agent  →  DM Agent
                                              ↓
Evaluation Agent  ←  Observer Agent  ←  Reflection Agent
```

详见 [SPEC.md §2 系统架构](SPEC.md#2-系统架构)。

## 技术栈

`Python 3.11` `LangGraph` `Pydantic v2` `FastAPI` `DeepSeek` `OpenAI SDK` `pytest`

## 面试关键词

`Multi-Agent` `LangGraph` `Memory System` `Reflection` `Observer Pattern` `Agent Evaluation` `Protocol Abstraction` `Observability` `Token Budget`
