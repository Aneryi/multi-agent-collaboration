# AgentVerse 项目阶段规划

**项目**：AgentVerse —— 基于 LangGraph 的多 Agent 协作决策平台
**目标**：AI 应用开发面试展示项目
**版本**：2.0

---

## 阶段总览

| 阶段 | 名称 | 状态 | 核心交付 |
|---|---|---|---|
| 0 | 基础设施 | ✅ 完成 | Pydantic 模型、双 LLM 适配器、LangGraph 核心图、FastAPI |
| 1 | Memory 系统升级 | 🔄 当前 | 三层记忆、LLM 压缩、动态上下文组装 |
| 2 | Reflection + Observer | ⏳ 待开始 | 角色成长反思、行为异常监控 |
| 3 | Planner + Evaluation | ⏳ 待开始 | 意图编排、自动评分体系 |
| 4 | 可观测性 | ⏳ 待开始 | LangSmith 集成、链路追踪、Dashboard |
| 5 | 生产化 | ⏳ 待开始 | PostgreSQL/Redis、向量检索、SSE、前端 |

---

## 阶段 0：基础设施 ✅

**目标**：建立可运行的后端骨架，跑通 Multi-Agent 叙事闭环。

### 已交付

- [x] Pydantic v2 数据模型：Character（含记忆/关系）、Scene、CharacterIntent、DMResult、StoryState
- [x] NarrativeLLM Protocol 抽象 + RuleBased 本地适配器 + DeepSeek 真实模型适配器
- [x] LangGraph 状态图：generate_intentions → adjudicate_scene → apply_state_updates → reflect_memories
- [x] JSON 文件持久化（JSONRepository）
- [x] FastAPI 7 个端点 + OpenAPI 文档
- [x] CLI demo（雨夜图书馆，2 角色 × 3 轮）
- [x] 环境变量切换 LLM（MASE_LLM_PROVIDER=rule|deepseek）
- [x] API 调用重试 + 降级 + token/延迟统计
- [x] pytest 集成测试（seed 可复现）

### 当前可演示的面试点

- Multi-Agent 协作（2+ 角色独立生成意图）
- DM 裁决机制（打断优先级 + 冲动值排序）
- Protocol 抽象（依赖倒置，双适配器无缝切换）
- LangGraph 状态图编排
- 完整 API + OpenAPI 文档

---

## 阶段 1：Memory 系统升级 🔄

**目标**：从简单 list truncate 升级为三层记忆架构，LLM 驱动的记忆压缩。

### 功能

- [ ] **三层记忆模型**：短期（10轮窗口）、中期（每5轮压缩）、长期（反思后沉淀）
- [ ] **Memory Manager Agent**：每5轮调用 LLM 将短期记忆压缩为结构化中期摘要
  ```json
  {
    "key_events": [],
    "relationship_changes": [],
    "goal_progress": ""
  }
  ```
- [ ] **动态上下文组装**：每轮从三层记忆中组装 Agent Context
  - 短期记忆：完整注入（最近10轮）
  - 长期记忆：关键词 TopK 检索，仅注入相关条目
- [ ] **记忆命中率统计**：记录记忆被引用的次数

### 完成标准

- 10 轮后短期记忆不超过 10 条
- 长期记忆包含压缩后的关键事实
- Agent Context 不再随轮次线性增长
- Token 消耗可控（对比升级前后的 context 大小）

### 面试展示点

- 三层记忆工程实现（比"截断 list"高级）
- LLM 驱动的记忆压缩（Agent 能力）
- 动态上下文组装（系统设计）
- Token 成本控制（工程意识）

---

## 阶段 2：Reflection + Observer

**目标**：Agent 的自我进化能力 + 系统行为监控。

### Reflection Agent

- [ ] **深度反思**：不仅仅是"总结"，而是推动角色成长
- [ ] **输出结构**：新目标、学到的教训、重要事件、关系反思、性格偏移
- [ ] **触发条件**：每5轮（常规）、场景结束（完整）、重大事件（触发式）
- [ ] **对系统的影响**：更新 goal、追加长期记忆、调整 relationship_map

### Observer Agent

- [ ] **OOC 检测**：persona 与行为的一致性校验
- [ ] **记忆遗忘检测**：关键事件是否被后续叙事遗忘
- [ ] **重复输出检测**：连续 N 轮相同 action/dialogue
- [ ] **世界状态冲突检测**：死亡复活、物品重复等
- [ ] **告警分级**：Info / Warning / Critical + 自动建议

### 完成标准

- 5 轮后 Reflection 能产出有意义的目标更新
- Observer 能检测到至少 3 种异常类型
- 告警不阻塞叙事主流程

### 面试展示点

- Agent 自我进化（Reflection 推动目标变化）
- Agent 系统"免疫系统"（Observer）
- 规则引擎 + LLM 判断双通道
- 可观测性基础

---

## 阶段 3：Planner + Evaluation

**目标**：意图编排专业化 + Agent 质量可量化。

### Planner Agent

- [ ] **意图排序**：打断优先 + 冲动值降序
- [ ] **冲突检测**：标记互斥意图（攻击 vs 逃跑等）
- [ ] **去重**：检测语义重复的意图
- [ ] **输出**：Prioritized Intents + Conflict Report

### Evaluation Agent

- [ ] **5 维自动评分**：
  - 连贯性 (Consistency) — 30%
  - 记忆利用率 (Memory Usage) — 20%
  - 目标推进率 (Goal Progress) — 20%
  - 多样性 (Diversity) — 15%
  - 重复率 (Repetition) — 15%
- [ ] **评分详情**：每个维度的扣分原因
- [ ] **综合评级**：S/A/B/C/D

### 完成标准

- Planner 能检测并报告至少 2 种冲突类型
- Evaluation 能在 10 轮后产出有参考价值的评分
- 评分能区分"好叙事"和"坏叙事"

### 面试展示点

- Agent 间协调机制（Planner）
- 量化评估 Agent 质量（Evaluation）
- 多维度评分体系设计

---

## 阶段 4：可观测性

**目标**：AI 工程化的完整可观测性体系。

### LangSmith / LangFuse 集成

- [ ] 每次 LLM 调用 → Trace（prompt、response、latency、tokens、cost、status）
- [ ] Agent 链路追踪：Character → Planner → DM → Reflection → Observer → Evaluation
- [ ] 错误 Trace：重试次数、降级原因、异常堆栈

### Dashboard 指标

- [ ] 平均响应时间 / P95 延迟
- [ ] Agent 成功率（各 Agent 分别统计）
- [ ] Token 消耗趋势
- [ ] 记忆命中率
- [ ] API 重试率
- [ ] Observer 告警频率

### 完成标准

- LangSmith 中可查看完整 Agent 链路
- Dashboard 至少展示 5 个关键指标
- 支持按 session / scene 筛选

### 面试展示点

- AI 工程化的专业程度
- Tracing 不是"事后诸葛亮"，而是开发中的调试工具
- 量化一切（Metrics-driven）

---

## 阶段 5：生产化

**目标**：从 MVP 到可部署的生产级系统。

### 功能

- [ ] PostgreSQL 持久化（SQLAlchemy / SQLModel）
- [ ] Redis 缓存 + 会话状态
- [ ] 向量数据库记忆检索（embedding → TopK）
- [ ] SSE 流式叙事输出
- [ ] React + Tailwind 前端 Dashboard
- [ ] 角色关系网可视化
- [ ] 内容安全审核
- [ ] 压力测试（100 轮稳定性）
- [ ] Markdown / Epub / PDF 导出

### 完成标准

- 100 轮连续运行不崩溃
- 多会话并发互不污染
- 前端可完成完整创作流程

---

## 面试叙事脚本

### "请介绍一下你的项目"

> 我做了一个叫 AgentVerse 的项目，是一个基于 LangGraph 的 Multi-Agent 协作决策平台。它的核心场景是叙事创作——N 个 AI 角色在同一个故事世界里自主行动，由一个 DM Agent 统一裁决。
>
> 技术上，我用 LangGraph 构建了状态图来编排 Agent 流水线：Character Agent 生成意图 → Planner 做冲突检测 → DM 做叙事裁决 → Reflection Agent 推动角色成长。最有意思的是我设计了三层记忆系统——短期、中期、长期——每 5 轮用 LLM 做一次记忆压缩，避免 Token 爆炸。还有一个 Observer Agent 实时监控 Agent 异常行为，比如 OOC、记忆遗忘、重复输出。
>
> 整套系统通过 Protocol 抽象实现了双适配器——本地 rule-based 用于开发测试，DeepSeek 用于真实运行——通过环境变量一键切换。我还做了完整的 API 和 CLI，集成了 token 统计和延迟监控，后面准备接 LangSmith 做全链路追踪。

### "你在这个项目里最大的技术挑战是什么？"

> 最大的挑战是**在 Token 预算和叙事质量之间做权衡**。100 轮以后，如果每轮把所有历史记忆都注入 context，Token 会爆炸。我设计了三层记忆——短期保留最近 10 轮、中期每 5 轮 LLM 压缩一次、长期只存关键事实——然后每轮只注入短期 + 关键词检索到的 TopK 长期记忆。这样 context 大小基本恒定，叙事质量不会随轮次下降。

### "你怎么保证 Agent 的输出质量？"

> 我设计了双层保障。第一层是 Observer Agent——实时监控 OOC、重复输出、世界状态冲突，发现问题立即告警。第二层是 Evaluation Agent——从连贯性、记忆利用率、目标推进率、多样性 5 个维度自动打分。如果有问题，分数会下降，配合 LangSmith 的 Trace 可以快速定位是哪个 Agent 的哪次调用出了问题。
