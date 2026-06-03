# 项目结构与阶段说明

## 目录总览

```
multi-agent-collaborative-narrative-engine/
├── PROJECT_PHASES.md        # 项目6阶段周期规划
├── PROJECT_STRUCTURE.md     # 本文件：目录结构与各文件作用说明
├── README.md                # 项目README（安装、运行、配置说明）
├── 需求文档.md               # 原始需求文档（MVP基线）
├── pyproject.toml           # Python项目配置（依赖、构建、pytest设置）
│
├── src/                     # 源代码根目录
│   ├── mase/                # 主包（Multi-Agent Storytelling Engine）
│   │   ├── __init__.py      # 包初始化，定义版本号
│   │   ├── models.py        # 【数据模型层】Pydantic模型定义
│   │   ├── storage.py       # 【持久化层】JSONRepository
│   │   ├── llm.py           # 【LLM适配器层】AI模型调用接口
│   │   ├── graph.py         # 【叙事编排层】LangGraph状态图
│   │   ├── service.py       # 【应用服务层】StoryService
│   │   ├── cli.py           # 【命令行入口】CLI demo工具
│   │   └── api/             # 【HTTP API层】FastAPI接口
│   │       ├── __init__.py
│   │       └── app.py       # FastAPI应用，提供REST API路由
│   │
│   └── multi_agent_collaborative_narrative_engine.egg-info/  # 【构建产物】pip editable install 自动生成
│       ├── PKG-INFO          # 包元信息（名称、版本、依赖等）
│       ├── SOURCES.txt       # 源码文件清单
│       ├── dependency_links.txt  # 依赖链接
│       ├── requires.txt      # 安装依赖列表
│       └── top_level.txt     # 顶层包名（mase）
│
├── tests/                   # 测试目录
│   └── test_story_service.py # StoryService 集成测试（2个用例）
│
├── .mase_data/              # JSON持久化数据目录（运行时自动创建）
├── .claude/                 # Claude Code配置
└── .venv/                   # Python虚拟环境
```

## 各文件详细作用

### 需求与规划文档

| 文件 | 作用 |
|---|---|
| `需求文档.md` | MVP需求基线。定义功能需求、非功能需求、数据模型、API设计、验收标准 |
| `PROJECT_PHASES.md` | 6阶段开发周期规划，每阶段的目标、交付物和完成标准 |
| `README.md` | 项目说明、安装步骤、LLM适配器配置、运行方式 |

### 构建产物 (`src/multi_agent_collaborative_narrative_engine.egg-info/`)

这个目录是执行 `pip install -e .`（editable install）时由 pip 自动生成的元数据目录，**不是手写的源代码**。

**为什么之前文档里没有它？** 因为它是构建产物，不是项目源码的一部分。通常会加入 `.gitignore`，不提交到版本控制。这里单独说明：

| 文件 | 作用 |
|---|---|
| `PKG-INFO` | 包的完整元信息（名称、版本号、作者、依赖列表等），从 `pyproject.toml` 自动生成 |
| `SOURCES.txt` | 包内所有源码文件的清单，pip 用它知道哪些文件属于这个包 |
| `dependency_links.txt` | 额外的依赖下载链接（本项目为空，依赖都从 PyPI 安装） |
| `requires.txt` | 解析后的依赖列表，区分了 `runtime` 依赖和 `dev` 可选依赖 |
| `top_level.txt` | 包的顶层模块名（`mase`），Python 用它知道 `import mase` 对应哪个目录 |

**核心作用**：editable install 模式下，pip 不会把代码复制到 `site-packages`，而是通过这个 egg-info 目录告诉 Python："`mase` 包的实际代码在 `src/` 目录下"。这样你修改源码后无需重新安装即可立即生效，适合开发阶段。

**生命周期**：
- 执行 `pip install -e .` 时自动创建
- 执行 `pip uninstall` 时自动删除
- 不应手动编辑，也不应提交到 Git（`.gitignore` 中应包含 `*.egg-info`）

### 核心源码 (`src/mase/`)

#### `models.py` — 数据模型
定义了整个系统的数据结构，使用 Pydantic v2：

- **StorySession**：故事会话（标题、世界状态、当前场景）
- **Scene**：场景（描述、状态机 draft→running→paused→ended、叙事日志、轮次计数）
- **Character**：角色（性格、外貌、目标、长短期记忆、关系图谱）
- **CharacterIntent**：角色在单轮中的行动意图（动作、对话、情绪、是否打断、冲动值）
- **DMResult**：DM裁决输出（叙事文本、世界状态delta、关系delta、记忆提示、调试理由）
- **NarrativeEntry**：单轮叙事记录
- **StoryState**：LangGraph图中的运行时状态
- **StoryBundle**：持久化聚合（会话+场景+角色+意图日志）

#### `storage.py` — JSON持久化
- `JSONRepository`：以UUID为文件名，JSON格式存储，支持会话/角色/场景的CRUD

#### `llm.py` — LLM适配器
- `NarrativeLLM`：Protocol接口，定义 `generate_intent`、`adjudicate`、`summarize_scene` 三个方法
- `RuleBasedNarrativeLLM`：本地规则型适配器，用模板+随机数生成叙事，无需API Key
- `DeepSeekNarrativeLLM`：通过OpenAI SDK调用DeepSeek API，支持JSON结构化输出、重试、token统计
- `create_narrative_llm()`：读取 `MASE_LLM_PROVIDER` 环境变量返回对应适配器

#### `graph.py` — LangGraph叙事编排
- `build_story_graph(llm)`：构建状态图
  - `generate_intentions`：为每个激活角色并行生成意图
  - `adjudicate_scene`：DM综合所有意图生成叙事
  - `apply_state_updates`：更新场景轮次、叙事日志、角色短期记忆
  - `reflect_memories`：每5轮沉淀长期记忆
  - `should_continue`：判断是否达到max_rounds

#### `service.py` — 应用服务
- `StoryService`：串联repository、llm、graph，提供面向用户的操作：
  - 创建/读取会话、添加角色、添加场景
  - 运行场景（调用LangGraph图）
  - 停止场景并生成摘要
  - 注入用户事件
  - 导出Markdown格式故事

#### `cli.py` — 命令行工具
- `python -m mase.cli demo`：运行内置demo（雨夜图书馆场景，2角色×3轮）
- 支持 `--llm rule|deepseek` 切换适配器
- 自动加载 `.env` 文件
- 使用DeepSeek时显示token用量和延迟

#### `api/app.py` — FastAPI接口
- 提供7个REST API端点（对应需求文档第6节）：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/sessions` | 创建故事会话 |
| GET | `/api/sessions/{id}` | 读取会话详情 |
| POST | `/api/sessions/{id}/characters` | 创建角色 |
| POST | `/api/sessions/{id}/scenes` | 创建场景 |
| POST | `/api/sessions/{id}/scenes/{id}/run` | 运行指定轮数 |
| POST | `/api/sessions/{id}/scenes/{id}/stop` | 停止并总结场景 |
| POST | `/api/sessions/{id}/events` | 注入用户事件 |
| GET | `/api/sessions/{id}/export` | 导出完整故事Markdown |

## 项目当前所处阶段

根据 `PROJECT_PHASES.md` 的6阶段规划：

| 阶段 | 状态 | 说明 |
|---|---|---|
| 阶段0：需求澄清与技术基线 | ✅ 完成 | 需求文档、阶段计划、技术栈已确定 |
| 阶段1：后端核心骨架 | ✅ 完成 | Pydantic模型、JSON持久化、StoryService、规则型LLM适配器 |
| 阶段2：LangGraph叙事编排 | ✅ 完成 | 状态图实现，2角色可连续运行多轮，结果可持久化 |
| 阶段3：API与调试能力 | ✅ 完成 | FastAPI路由全部实现，OpenAPI文档可访问，错误返回清晰 |
| **阶段4：真实LLM接入与提示词优化** | **🔄 进行中** | DeepSeek适配器已完成，结构化输出解析+重试+token统计已实现 |
| 阶段5：前端MVP与实时输出 | ⏳ 未开始 | React前端、SSE/WebSocket实时输出待开发 |
| 阶段6：生产化与高级叙事能力 | ⏳ 未开始 | PostgreSQL/Redis、向量检索、内容审核、压测待开发 |

**总结：当前处于阶段4（真实LLM接入），核心接入能力已完成。** 阶段4的完成标准对照：

- ✅ 可通过环境变量切换模型供应商（`MASE_LLM_PROVIDER=deepseek|rule`）
- ✅ LLM输出失败时有降级或错误说明（重试+降级+日志）
- ⬜ 3个角色运行5轮，叙事连贯且状态正确（需用真实API Key实际验证）
