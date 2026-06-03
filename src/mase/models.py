"""数据模型层 — Pydantic v2 模型定义

本文件定义了 MASE 系统中所有核心数据结构，是整个项目的数据契约。

模型层级关系：
    StorySession（故事会话）
    ├── Scene（场景，一个会话可有多个场景）
    │   └── NarrativeEntry（每轮叙事记录）
    ├── Character（角色）
    │   ├── 长期记忆 / 短期记忆
    │   └── 关系图谱（对其他角色的好感/敌意值）
    └── StoryState（LangGraph 运行时状态快照）

角色意图 → DM 裁决 的数据流：
    CharacterIntent  ──(多个)──▶  DMResult
    （角色生成的意图）              （DM综合裁决结果）

持久化聚合：
    StoryBundle = Session + Scenes + Characters + IntentLogs
    （一个 JSON 文件包含一个会话的完整数据）
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def now_utc() -> datetime:
    """返回当前 UTC 时间，作为 created_at / updated_at 的默认工厂函数。"""
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------

class SceneStatus(StrEnum):
    """场景生命周期状态机。

    流转路径：DRAFT → RUNNING → PAUSED → ENDED
    """
    DRAFT = "draft"      # 草稿：已创建，尚未运行
    RUNNING = "running"  # 运行中：叙事正在进行
    PAUSED = "paused"    # 暂停：叙事被暂停，可恢复
    ENDED = "ended"      # 已结束：场景已完成并生成摘要


# ---------------------------------------------------------------------------
# 核心实体
# ---------------------------------------------------------------------------

class StorySession(BaseModel):
    """故事会话 — 一个完整故事的顶层容器。

    一个会话包含多个场景和多个角色，通过 current_scene_id
    追踪当前正在进行的场景。world_state 保存跨场景的全局状态。
    """
    session_id: UUID = Field(default_factory=uuid4)
    title: str                                     # 故事标题
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    current_scene_id: UUID | None = None           # 当前激活的场景 ID
    world_state: dict[str, Any] = Field(default_factory=dict)  # 全局世界状态


class Character(BaseModel):
    """角色 — 故事中的智能体（Agent）。

    每个角色拥有独立的性格、记忆和关系网络。
    - short_term_memory：最近 20 轮事件（滑动窗口）
    - long_term_memory：关键事件摘要（最多 50 条）
    - relationship_map：{其他角色ID: 好感度分值}，正数友好/负数敌对
    """
    character_id: UUID = Field(default_factory=uuid4)
    session_id: UUID                                # 所属会话
    name: str                                       # 角色名
    persona: str                                    # 性格、经历、说话风格描述
    appearance: str = ""                            # 外貌描述
    goal: str = ""                                  # 当前目标
    long_term_memory: list[str] = Field(default_factory=list)   # 长期记忆摘要
    short_term_memory: list[str] = Field(default_factory=list)  # 短期记忆（最近事件）
    relationship_map: dict[str, int] = Field(default_factory=dict)  # 关系分值
    is_active: bool = True                          # 是否参与当前场景运行


class NarrativeEntry(BaseModel):
    """叙事记录 — 单轮 DM 裁决的输出，存入场景叙事日志。"""
    round_index: int                                # 场景内第几轮
    text: str                                       # 叙事正文
    world_delta: dict[str, Any] = Field(default_factory=dict)    # 本轮的世界状态变化
    debug_reason: str = ""                          # DM 裁决理由（调试用）
    created_at: datetime = Field(default_factory=now_utc)


class Scene(BaseModel):
    """场景 — 故事中的连续时空单元。

    场景有独立的描述和状态。round_index 追踪已运行轮数，
    narrative_log 记录每轮的叙事输出。
    """
    scene_id: UUID = Field(default_factory=uuid4)
    session_id: UUID                                # 所属会话
    title: str                                      # 场景标题
    description: str                                # 场景描述（地点、时间、天气、氛围等）
    order_index: int                                # 场景在故事中的顺序
    status: SceneStatus = SceneStatus.DRAFT         # 生命周期状态
    round_index: int = 0                            # 已运行轮数
    narrative_log: list[NarrativeEntry] = Field(default_factory=list)  # 叙事日志
    summary: str | None = None                      # 场景结束后的摘要


# ---------------------------------------------------------------------------
# 数据流模型（运行时生成，非持久化根实体）
# ---------------------------------------------------------------------------

class CharacterIntent(BaseModel):
    """角色意图 — 角色在单轮中想要执行的行动。

    由 LLM（或规则适配器）为每个激活角色生成，然后汇总交给 DM 裁决。
    impulse（冲动值）和 interrupt（是否打断）共同决定本轮的行动优先级：
    打断者优先，然后按冲动值降序排列。
    """
    intent_id: UUID = Field(default_factory=uuid4)
    scene_id: UUID                                  # 所属场景
    character_id: UUID                              # 发出意图的角色
    character_name: str                             # 角色名（冗余，方便输出）
    round_index: int                                # 场景内第几轮
    action: str                                     # 行动意图描述
    dialogue: str | None = None                     # 对话内容，无对话则为 None
    target_character_id: UUID | None = None         # 行为指向的角色
    emotion: str = "calm"                           # 当前情绪
    interrupt: bool = False                         # 是否打断他人
    impulse: float = Field(default=0.5, ge=0.0, le=1.0)  # 冲动值 [0, 1]


class DMResult(BaseModel):
    """DM 裁决结果 — Dungeon Master 综合所有角色意图后的输出。

    包含叙事正文、世界状态变化、角色关系变化、记忆提示和调试理由。
    relationship_delta 格式：{"角色A": {"角色B": +1, "角色C": -2}}
    """
    narrative: str                                  # 本轮叙事正文
    world_delta: dict[str, Any] = Field(default_factory=dict)       # 世界状态变化
    relationship_delta: dict[str, dict[str, int]] = Field(default_factory=dict)  # 关系变化
    memory_hints: list[str] = Field(default_factory=list)           # 角色应记住的事件
    debug_reason: str = ""                          # DM 裁决思路（调试用）


# ---------------------------------------------------------------------------
# 运行时与持久化聚合
# ---------------------------------------------------------------------------

class StoryState(BaseModel):
    """故事运行时状态 — LangGraph 图中流转的状态对象。

    每次 graph.invoke() 时创建，包含当前会话的快照和本轮生成的临时数据。
    max_rounds 控制本轮运行的总轮数上限。
    """
    session: StorySession                           # 会话引用
    scene: Scene                                    # 当前场景
    characters: list[Character]                      # 所有角色（含非激活）
    pending_user_events: list[str] = Field(default_factory=list)   # 待处理的用户注入事件
    latest_intents: list[CharacterIntent] = Field(default_factory=list)   # 本轮的意图
    generated_intents: list[CharacterIntent] = Field(default_factory=list) # 本次运行的所有意图
    latest_dm_result: DMResult | None = None        # 本轮的 DM 裁决
    max_rounds: int = 1                             # 运行轮数上限
    seed: int | None = None                         # 随机种子（用于复现）


class StoryBundle(BaseModel):
    """故事持久化聚合 — 一个 JSON 文件存储的完整会话数据。

    包含会话元信息、所有场景、所有角色和全部意图日志。
    JSONRepository 以 session_id 为文件名读写此对象。
    """
    session: StorySession
    scenes: list[Scene] = Field(default_factory=list)
    characters: list[Character] = Field(default_factory=list)
    intent_logs: list[CharacterIntent] = Field(default_factory=list)
    pending_user_events: list[str] = Field(default_factory=list)
