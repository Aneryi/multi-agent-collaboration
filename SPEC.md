# AgentVerse：基于 LangGraph 的多 Agent 协作决策平台

**项目定位**：AI 应用开发面试展示项目
**版本**：2.0
**状态**：Spec —— 系统设计文档

---

## 1. 项目定位与面试视角

### 1.1 这不是产品需求文档

本 Spec 按**"面试官想看什么"**组织，而非按"产品 Feature List"堆砌。AgentVerse 的设计目标是在一次技术面试中清晰展示以下能力维度：

| 能力维度 | 面试考察点 | 项目对应模块 |
|---|---|---|
| **Agent 能力** | Multi-Agent 协作、角色扮演、意图生成、DM 裁决 | Character Agent × N → Planner → DM 决策链 |
| **系统设计能力** | 分层架构、状态图编排、Protocol 解耦、依赖注入 | LangGraph 状态图 + Pydantic 模型 + JSON/PostgreSQL 双存储 |
| **工程能力** | 可测试性、错误处理、重试/降级、环境变量配置 | Rule-based 本地回退 + DeepSeek 真实调用 + pytest |
| **可观测性** | Tracing、Metrics、Dashboard、Agent 行为审计 | Observer Agent + LangSmith 集成 + token/延迟统计 |
| **Memory 设计** | 短/中/长三层记忆 + 检索 + 压缩 | Memory Manager + Reflection Agent 定期沉淀 |
| **评估体系** | 自动化质量评分、OOC 检测、一致性校验 | Evaluation Agent + Observer 行为监控 |

### 1.2 一句话总结

> **AgentVerse** 是一个基于 LangGraph 的 Multi-Agent 协作决策平台。N 个 Character Agent 各自拥有独立的人格、记忆和目标；Planner Agent 汇总意图后交由 DM Agent 裁决叙事走向；Reflection Agent 定期沉淀长期记忆；Observer Agent 实时监控 Agent 异常行为；Evaluation Agent 自动评分叙事质量。完整链路接入 LangSmith 追踪，前后端分离，从本地规则型一键切换到云端大模型。

---

## 2. 系统架构

### 2.1 总体架构图

```text
                          ┌──────────────────────────┐
                          │    FastAPI / CLI Entry    │
                          └────────────┬─────────────┘
                                       │
                          ┌────────────▼─────────────┐
                          │     StoryService         │
                          │  (Application Facade)    │
                          └────────────┬─────────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              │                        │                        │
    ┌─────────▼──────────┐  ┌─────────▼──────────┐  ┌─────────▼──────────┐
    │  JSONRepository    │  │  NarrativeLLM      │  │  LangGraph Graph   │
    │  (Persistence)     │  │  (Protocol + Impl) │  │  (Orchestration)   │
    └────────────────────┘  └────────────────────┘  └─────────┬──────────┘
                                                              │
    ┌─────────────────────────────────────────────────────────┘
    │
    │   LangGraph State Graph Pipeline:
    │
    │   ┌──────────────────────┐
    │   │  Character Agents × N │  ← 每个 Agent：独立 Persona + Memory + Goal
    │   │  generate_intentions  │
    │   └──────────┬───────────┘
    │              │ intents[]
    │   ┌──────────▼───────────┐
    │   │   Planner Agent      │  ← 排序、去重、冲突检测
    │   │   (plan & prioritize)│
    │   └──────────┬───────────┘
    │              │ prioritized intents
    │   ┌──────────▼───────────┐
    │   │   DM Agent           │  ← 裁决、叙事生成、世界观更新
    │   │   adjudicate_scene   │
    │   └──────────┬───────────┘
    │              │ narrative + world_delta
    │   ┌──────────▼───────────┐
    │   │   State Manager      │  ← 应用状态变更：轮次+1、记忆写入
    │   │   apply_state_updates│
    │   └──────────┬───────────┘
    │              │
    │   ┌──────────▼───────────┐
    │   │   Reflection Agent   │  ← 每5轮/场景结束：沉淀长期记忆
    │   │   reflect_memories   │  ← 角色成长、目标变化、关系更新
    │   └──────────┬───────────┘
    │              │
    │   ┌──────────▼───────────┐
    │   │   Memory Manager     │  ← 短/中/长三层记忆 + TopK 检索
    │   │   compress & retrieve│
    │   └──────────┬───────────┘
    │              │
    │   ┌──────────▼───────────┐
    │   │   Observer Agent     │  ← OOC检测、记忆遗忘、重复输出、世界冲突
    │   │   audit & monitor    │
    │   └──────────┬───────────┘
    │              │ warnings / alerts
    │   ┌──────────▼───────────┐
    │   │   Evaluation Agent   │  ← 连贯性、记忆利用率、目标推进、多样性
    │   │   auto-score         │
    │   └──────────────────────┘
    │
    └───▶  Should Continue? ──Yes──▶ (loop back to Character Agents)
                  │
                 No
                  │
                  ▼
              [Graph END]
```

### 2.2 技术栈

| 层 | 技术选型 | 面试加分点 |
|---|---|---|
| 编排引擎 | LangGraph (StateGraph + Conditional Edges) | 展示对 Agent 编排框架的深入理解 |
| 数据模型 | Pydantic v2 (Protocol + BaseModel) | 类型安全、JSON Schema 自动生成 |
| LLM 适配 | Protocol 抽象 → RuleBased + DeepSeek (OpenAI SDK) | 依赖倒置、可替换、成本可控 |
| API 层 | FastAPI + Uvicorn | 异步支持、OpenAPI 自动文档 |
| 持久化 | JSON (MVP) → PostgreSQL + Redis (Production) | 渐进式架构演进 |
| 可观测性 | LangSmith Tracing + 内置 Metrics | Agent 链路追踪、token 统计 |
| 测试 | pytest + tmp_path + seed 可复现 | 100% 可复现的确定性测试 |

---

## 3. 核心模块设计

### 3.1 Character Agent（角色意图生成）

每个 Character Agent 是一个独立实体，拥有：

```python
class Character:
    character_id: UUID
    name: str
    persona: str              # 性格、经历、说话风格
    appearance: str           # 外貌
    goal: str                 # 当前目标（可被 Reflection 更新）
    long_term_memory: list    # 长期记忆（上限 50 条）
    medium_term_memory: list  # 中期记忆（每5轮压缩一次）
    short_term_memory: list   # 短期记忆（滑动窗口，最近 10 轮）
    relationship_map: dict    # {other_id: score} 关系分值
    is_active: bool
```

**核心流程**：

```text
场景上下文 + 短期记忆 + 相关长期记忆(TopK)
    → Character Agent
    → 结构化意图 JSON
    → { action, dialogue, target, emotion, interrupt, impulse }
```

**面试展示点**：
- 每个 Agent 有独立的人格 Prompt 模板
- 意图输出为结构化 JSON（Pydantic 校验）
- 支持打断优先级（interrupt）+ 冲动值（impulse）双维排序

---

### 3.2 Planner Agent（意图编排）

Planner Agent 接收所有 Character Agent 的意图，负责：

1. **排序**：打断者优先，同级按冲动值降序
2. **去重**：检测重复/冗余意图
3. **冲突检测**：标记互斥意图（如 A 攻击 B，B 逃跑）
4. **优先级输出**：返回排序后的意图列表供 DM 裁决

```text
Raw Intents[] → Planner → Prioritized Intents[]
```

**面试展示点**：
- Agent 间协调机制
- 冲突检测算法
- 可扩展的优先级策略（策略模式）

---

### 3.3 DM Agent（叙事裁决）

DM（Dungeon Master）Agent 是叙事中枢：

```text
场景上下文 + 角色信息 + 排序后意图列表 + 突发事件
    → DM Agent
    → {
        narrative: str,              # 叙事正文（2-4段）
        world_delta: dict,           # 世界状态变化
        relationship_delta: dict,    # 角色关系变化
        memory_hints: list[str],     # 记忆提示
        debug_reason: str            # 裁决思路（调试/可观测）
      }
```

**面试展示点**：
- 第三人称有限视角叙事
- 打断者优先体现
- 环境描写 + 行动描写 + 对话生成
- debug_reason 提供裁决可解释性

---

### 3.4 State Manager（状态管理）

将 DM 裁决结果应用到持久化状态：

```text
DM Result
    → 场景轮次 +1
    → 叙事日志追加
    → 世界状态合并
    → 角色短期记忆写入（滑动窗口）
    → 用户事件消费
```

---

### 3.5 Memory Manager（三层记忆系统）

这是面试中**最核心**的架构亮点。

#### 3.5.1 三层记忆架构

| 层级 | 容量 | 更新频率 | 内容 |
|---|---|---|---|
| **短期记忆** | 最近 10 轮 | 每轮 | 本轮叙事摘要（180字） |
| **中期记忆** | 每次压缩 1 条 | 每 5 轮 | JSON：关键事件 + 关系变化 + 目标进展 |
| **长期记忆** | 上限 50 条 | 每 5 轮 / 场景结束 | JSON：重要事实 + 角色成长 + 世界变化 |

#### 3.5.2 记忆压缩流程

```text
每 5 轮触发：
    短期记忆（最近10轮）
        → Memory Manager（调用 LLM 压缩）
        → 中期记忆摘要
            {
              "key_events": ["事件1", "事件2"],
              "relationship_changes": [{"from": "A", "to": "B", "delta": +5}],
              "goal_progress": "目标推进了X%，遇到了障碍Y"
            }
        → 追加到长期记忆候选
```

#### 3.5.3 动态上下文组装

每轮运行前：

```text
当前场景描述
+ 短期记忆（最近10轮，完整）
+ 长期记忆中与当前场景语义相关的 TopK 条（向量相似度 / 关键词匹配）
+ 关系图谱中前3相关角色
────────────────────
= 组装后的 Agent Context
```

**面试展示点**：
- 三层记忆的工程实现（非简单的 list truncate）
- LLM 驱动的记忆压缩
- 相关性检索（MVP: 关键词；Production: 向量）
- Token 消耗可控——每轮只注入相关上下文

---

### 3.6 Reflection Agent（深度反思）

Reflection Agent 不只是"总结发生了什么"，而是推动角色**成长**：

#### 触发条件

```text
- 每 5 轮（常规反思）
- 场景结束时（完整反思）
- 重大事件发生时（触发式反思）
  - 角色关系剧烈变化（|delta| > 阈值）
  - 目标完成或失败
  - 角色死亡/退场
```

#### 输出结构

```json
{
  "character_id": "uuid",
  "new_goal": "更新后的目标（如有变化）",
  "goal_progress": 0.65,
  "lessons_learned": ["我学会了...", "我发现..."],
  "important_events_remembered": ["事件1", "事件2"],
  "relationship_reflections": [
    {"character": "B", "change": "+10", "reason": "他救了我"}
  ],
  "personality_shift": "更谨慎了"
}
```

#### 对系统的影响

```text
Reflection 输出
    → 更新 Character.goal（可能）
    → 追加 Character.long_term_memory
    → 调整 Character.relationship_map
    → 影响后续 Character Agent 的行为倾向
```

**面试展示点**：
- Agent 的自我进化能力
- 不是简单的摘要，而是结构化反思
- 目标驱动 vs 反应式行为的区别

---

### 3.7 Observer Agent（行为监控）

JD 中的"可观测性"高频考察点。Observer Agent 独立于叙事流程，异步监控所有 Agent 行为。

#### 检测维度

| 检测项 | 规则 | 告警级别 |
|---|---|---|
| **角色 OOC** | persona 定义"勇敢"，连续3轮选择逃避 | Warning |
| **记忆遗忘** | 上一轮的事件本轮角色表现出不知道 | Critical |
| **重复输出** | 连续 3 轮同一 action/同一 dialogue | Warning |
| **世界状态冲突** | 已死亡角色出现、已毁物品再次使用 | Critical |
| **关系突变** | relationship 单轮变化超过阈值 | Info |
| **叙事停滞** | 5 轮内无实质性目标推进 | Warning |

#### 输出结构

```json
{
  "round_index": 12,
  "warnings": [
    {
      "type": "repetition",
      "character": "林澈",
      "detail": "连续3轮执行相同调查动作",
      "severity": "warning"
    },
    {
      "type": "ooc",
      "character": "许鸢",
      "detail": "角色设定为'敏锐'，但本轮忽略了明显线索",
      "severity": "warning"
    }
  ],
  "severity": "warning",
  "suggestions": [
    "建议注入突发事件打破林澈的重复行为",
    "建议在下一轮给许鸢一个察觉线索的机会"
  ]
}
```

**面试展示点**：
- Agent 系统的"免疫系统"
- 规则引擎 + LLM 判断双通道
- 告警分级 + 自动建议
- 不阻塞叙事主流程（异步/旁路）

---

### 3.8 Evaluation Agent（自动评估）

面试必问：如何评估 Agent 质量？

#### 评分维度

| 维度 | 计算方式 | 权重 |
|---|---|---|
| **连贯性 (Consistency)** | 相邻叙事无逻辑矛盾 / 总检查点 | 30% |
| **记忆利用率 (Memory Usage)** | 叙事中引用了历史记忆的次数 / 可用记忆总数 | 20% |
| **目标推进率 (Goal Progress)** | 目标相关的行动数 / 总行动数 | 20% |
| **多样性 (Diversity)** | 1 - (重复action数 / 总action数) | 15% |
| **重复率 (Repetition)** | 重复的 n-gram 占比 | 15% |

#### 输出结构

```json
{
  "scene_id": "uuid",
  "rounds_evaluated": 10,
  "scores": {
    "consistency": 91,
    "memory_usage": 88,
    "goal_progress": 84,
    "diversity": 76,
    "repetition": 85
  },
  "overall_score": 85.6,
  "grade": "B+",
  "breakdown": {
    "consistency_issues": ["第5轮和第7轮林澈的位置矛盾"],
    "low_diversity_reason": "许鸢连续多轮使用相似对话模式"
  }
}
```

**面试展示点**：
- 量化 Agent 质量（不是"感觉"）
- 多维度评估体系
- 可复现的评分标准
- 评估结果反馈到系统优化

---

## 4. 可观测性设计

### 4.1 LangSmith 集成

```text
每次 LLM 调用 → LangSmith Trace：
    {
      "run_id": "uuid",
      "agent_type": "character | dm | reflection | observer",
      "model": "deepseek-chat",
      "prompt": "完整 prompt",
      "response": "完整 response",
      "latency_ms": 1420,
      "tokens": { "input": 850, "output": 320, "total": 1170 },
      "cost": 0.0012,
      "status": "success | retry | fallback"
    }
```

### 4.2 Agent 链路追踪

```text
Run ID: abc-123
  └─ Character Agent: 林澈     [1420ms, success]
  └─ Character Agent: 许鸢     [1300ms, success]
  └─ Planner                  [50ms, success]
  └─ DM Agent                 [2800ms, success]
  └─ Reflection Agent         [1200ms, success]
  └─ Observer Agent           [100ms, success, 1 warning]
  └─ Evaluation Agent         [800ms, success, score: 89]
Total: 7670ms | Tokens: 5200 | Cost: $0.0042
```

### 4.3 内置 Metrics

```text
运行时统计（DeepSeekNarrativeLLM 已实现）：
    - total_tokens: 累计 token 消耗
    - avg_call_time_ms: 平均 API 延迟
    - _call_times[]: 每次调用耗时

待实现：
    - agent_success_rate: 各 Agent 调用成功率
    - memory_hit_rate: 记忆检索命中率
    - retry_rate: API 重试比例
    - ooc_alert_count: Observer 告警总数
```

---

## 5. 数据流与状态管理

### 5.1 LangGraph 状态图

```text
                    ┌─────────────────────────┐
                    │   generate_intentions    │  ← Character Agents × N
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   plan_intentions        │  ← Planner Agent (新增)
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   adjudicate_scene       │  ← DM Agent
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   apply_state_updates    │  ← State Manager
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   reflect_memories       │  ← Reflection Agent
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   compress_memories      │  ← Memory Manager (新增)
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   observe_round          │  ← Observer Agent (新增)
                    └────────────┬────────────┘
                                 │
                              ┌──▼──┐
                              │ END? │──Yes──▶ evaluate_scene (Evaluation)
                              └──┬──┘
                                 │ No
                                 ▼
                          (back to top)
```

### 5.2 GraphState 类型

```python
class GraphState(TypedDict, total=False):
    story: StoryState          # 核心叙事状态
    observer_warnings: list    # 本轮 Observer 告警
    memory_retrieved: list     # 本轮检索到的长期记忆
    planner_decisions: dict    # Planner 的冲突检测结果
```

---

## 6. LLM 适配器策略

### 6.1 Protocol 抽象（依赖倒置）

```python
class NarrativeLLM(Protocol):
    def generate_intent(...) -> CharacterIntent: ...
    def adjudicate(...) -> DMResult: ...
    def summarize_scene(...) -> str: ...
    def reflect(...) -> ReflectionResult: ...      # 新增
    def evaluate(...) -> EvaluationResult: ...     # 新增
```

### 6.2 双适配器策略

| 模式 | 适配器 | 用途 |
|---|---|---|
| 本地开发/测试 | RuleBasedNarrativeLLM | 无 API Key 可运行，seed 可复现，pytest |
| 真实运行 | DeepSeekNarrativeLLM | JSON 模式，重试，token 统计 |
| 未来扩展 | OpenAINarrativeLLM / AnthropicNarrativeLLM | Protocol 接口支持无缝切换 |

### 6.3 模型分层策略（成本控制）

| Agent 类型 | 模型 | 理由 |
|---|---|---|
| Character Agent | 轻量模型（如 deepseek-chat） | 高频调用（每角色每轮），简单任务 |
| DM Agent | 同模型 / 稍高热度的参数 | 低频调用（每轮1次），核心质量 |
| Reflection Agent | 同 DM 模型 | 每5轮1次，质量优先 |
| Observer Agent | 轻量模型 / 规则优先 | LLM 仅用于模糊判断 |
| Evaluation Agent | 可离线 / 批处理 | 非实时 |

---

## 7. API 设计

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/sessions` | 创建故事会话 |
| GET | `/api/sessions/{id}` | 读取会话 + Agent 状态 |
| POST | `/api/sessions/{id}/characters` | 创建角色 Agent |
| POST | `/api/sessions/{id}/scenes` | 创建场景 |
| POST | `/api/sessions/{id}/scenes/{id}/run` | 运行叙事（返回实时状态流） |
| POST | `/api/sessions/{id}/scenes/{id}/stop` | 停止并触发 Reflection + Evaluation |
| POST | `/api/sessions/{id}/events` | 注入用户事件 |
| GET | `/api/sessions/{id}/export` | 导出 Markdown |
| GET | `/api/sessions/{id}/observer` | 查看 Observer 告警历史 |
| GET | `/api/sessions/{id}/evaluation` | 查看 Evaluation 评分 |
| GET | `/api/sessions/{id}/memory` | 查看角色记忆状态（调试） |

---

## 8. 项目阶段规划

### 阶段 0：基础设施 ✅

- [x] Pydantic 数据模型
- [x] JSON 持久化
- [x] RuleBased + DeepSeek 双适配器
- [x] LangGraph 核心图（Intent → DM → State → Memory）
- [x] FastAPI 全部端点
- [x] CLI demo

### 阶段 1：Memory 系统升级

- [ ] 三层记忆模型（短期 / 中期 / 长期）
- [ ] Memory Manager Agent（LLM 压缩）
- [ ] 动态上下文组装（关键词 TopK 检索）
- [ ] 记忆命中率统计

### 阶段 2：Reflection + Observer

- [ ] Reflection Agent（目标变化、角色成长、关系反思）
- [ ] Observer Agent（OOC / 遗忘 / 重复 / 冲突检测）
- [ ] 告警分级 + 自动建议

### 阶段 3：Planner + Evaluation

- [ ] Planner Agent（意图去重、冲突检测、优先级排序）
- [ ] Evaluation Agent（5 维自动评分）
- [ ] 评分可视化

### 阶段 4：可观测性

- [ ] LangSmith / LangFuse 集成
- [ ] Agent 链路追踪
- [ ] Dashboard（延迟 / 成功率 / Token / 记忆命中率）

### 阶段 5：生产化

- [ ] PostgreSQL + Redis 持久化
- [ ] 向量记忆检索（embedding）
- [ ] SSE 流式叙事输出
- [ ] React 前端 Dashboard

---

## 9. 简历呈现

### 项目名称

**AgentVerse：基于 LangGraph 的多 Agent 协作决策平台**

### 关键词

`Multi-Agent` `LangGraph` `Memory System` `Reflection` `Observer Pattern` `Agent Evaluation` `LangSmith` `Pydantic` `FastAPI` `DeepSeek`

### 简历描述（模板）

> 设计并实现了一个基于 LangGraph 的 Multi-Agent 协作决策平台。N 个 Character Agent 各自拥有独立的 Persona、三层记忆系统（短期/中期/长期）和动态目标；Planner Agent 负责意图冲突检测与优先级编排；DM Agent 统一裁决并生成叙事；Reflection Agent 定期推动角色成长与目标演化；Observer Agent 实时监控 OOC、记忆遗忘和重复输出；Evaluation Agent 从连贯性、记忆利用率、目标推进率等 5 个维度自动评分。系统通过 Protocol 抽象实现了从本地规则型到 DeepSeek 云端模型的无缝切换，集成 LangSmith 全链路追踪，支持 seed 可复现的确定性测试。

---

## 10. 术语表

| 术语 | 说明 |
|---|---|
| **AgentVerse** | 项目名称，Multi-Agent 叙事决策平台 |
| **Character Agent** | 角色智能体，拥有独立人格、记忆、目标的 AI Agent |
| **Planner Agent** | 意图编排智能体，排序/去重/冲突检测 |
| **DM Agent** | Dungeon Master，叙事裁决与文本生成智能体 |
| **Reflection Agent** | 深度反思智能体，推动角色成长与记忆沉淀 |
| **Memory Manager** | 记忆管理模块，三层层级记忆 + 压缩 + 检索 |
| **Observer Agent** | 行为监控智能体，OOC/遗忘/重复/冲突检测 |
| **Evaluation Agent** | 自动评估智能体，5 维量化评分 |
| **OOC** | Out of Character，角色行为偏离设定 |
