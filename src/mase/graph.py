"""LangGraph 叙事编排层 — 核心状态图

本文件定义了故事叙事的核心编排逻辑。基于 LangGraph 构建状态图，
实现"角色意图 → DM 裁决 → 状态更新 → 记忆沉淀"的循环流程。

状态图结构：
    ┌─────────────────────────────────────────────────┐
    │                                                 │
    │  generate_intentions                            │
    │  （为每个激活角色生成意图）                         │
    │        │                                        │
    │        ▼                                        │
    │  adjudicate_scene                               │
    │  （DM 综合所有意图，生成叙事文本）                    │
    │        │                                        │
    │        ▼                                        │
    │  apply_state_updates                            │
    │  （更新场景轮次、叙事日志、角色短期记忆）              │
    │        │                                        │
    │        ▼                                        │
    │  reflect_memories                               │
    │  （每5轮或场景结束时沉淀长期记忆）                    │
    │        │                                        │
    │        ▼                                        │
    │  should_continue ?                              │
    │   │              │                              │
    │   │ continue     │ finish                       │
    │   ▼              ▼                              │
    │  (回到开头)      END                             │
    └─────────────────────────────────────────────────┘

GraphState 数据结构：
    整个图共享一个 GraphState（TypedDict），其中包含一个
    StoryState 对象（见 models.py）。各节点通过修改 story
    字段来传递状态变化。

节点职责：
    generate_intentions — 读取 scene/characters，调用 llm.generate_intent()
    adjudicate_scene    — 读取 intents，调用 llm.adjudicate()
    apply_state_updates — 将 DMResult 写入 scene/characters 的持久化字段
    reflect_memories    — 每5轮从 DMResult.memory_hints 提取长期记忆
    should_continue     — 判断 round_index 是否达到 max_rounds
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from mase.llm import NarrativeLLM
from mase.models import Character, NarrativeEntry, SceneStatus, StoryState


# ---------------------------------------------------------------------------
# GraphState — LangGraph 图中流转的状态容器
# ---------------------------------------------------------------------------

class GraphState(TypedDict, total=False):
    """LangGraph 状态图的全局状态类型。

    字段：
        story: StoryState — 包含会话、场景、角色、意图和裁决结果的完整快照。
               各节点通过修改 story 的字段来传递状态。
    """
    story: StoryState


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _active_characters(characters: list[Character]) -> list[Character]:
    """过滤出当前激活的角色（is_active=True）。"""
    return [character for character in characters if character.is_active]


# ---------------------------------------------------------------------------
# 图构建入口
# ---------------------------------------------------------------------------

def build_story_graph(llm: NarrativeLLM):
    """构建并编译 LangGraph 叙事状态图。

    Args:
        llm: 实现了 NarrativeLLM 协议的适配器（RuleBased 或 DeepSeek）

    Returns:
        编译后的 LangGraph 可执行图（CompiledGraph）
    """
    graph = StateGraph(GraphState)

    # ==================================================================
    # 节点1：生成角色意图
    # ==================================================================
    def generate_intentions(state: GraphState) -> dict[str, Any]:
        """为每个激活角色调用 llm.generate_intent() 生成结构化意图。

        意图按 (非打断优先, 冲动值降序) 排序后存入 story.latest_intents。
        同时追加到 story.generated_intents 累积列表。
        """
        story = state["story"]
        round_index = story.scene.round_index + 1  # 本轮轮次
        active = _active_characters(story.characters)

        # 并行（实际为顺序循环）为每个角色生成意图
        intents = [
            llm.generate_intent(
                character=character,
                scene=story.scene,
                session=story.session,
                active_characters=active,
                round_index=round_index,
                user_events=story.pending_user_events,
                seed=story.seed,
            )
            for character in active
        ]

        # 排序：打断者优先，然后按冲动值降序
        story.latest_intents = sorted(
            intents,
            key=lambda item: (not item.interrupt, -item.impulse),
        )
        story.generated_intents.extend(story.latest_intents)
        return {"story": story}

    # ==================================================================
    # 节点2：DM 裁决
    # ==================================================================
    def adjudicate_scene(state: GraphState) -> dict[str, Any]:
        """DM 综合所有角色意图，裁决行动结果并生成叙事文本。

        调用 llm.adjudicate()，结果存入 story.latest_dm_result。
        """
        story = state["story"]
        story.latest_dm_result = llm.adjudicate(
            scene=story.scene,
            session=story.session,
            characters=story.characters,
            intents=story.latest_intents,
            user_events=story.pending_user_events,
            seed=story.seed,
        )
        return {"story": story}

    # ==================================================================
    # 节点3：应用状态更新
    # ==================================================================
    def apply_state_updates(state: GraphState) -> dict[str, Any]:
        """将 DM 裁决结果写入持久化字段。

        具体操作：
        - 场景状态 → RUNNING
        - 轮次 +1
        - 追加叙事条目到 narrative_log
        - 合并 world_delta 到会话世界状态
        - 清空待处理用户事件
        - 更新每个激活角色的短期记忆（滑动窗口，保留最近20条）
        """
        story = state["story"]
        if story.latest_dm_result is None:
            return {"story": story}

        # 场景状态更新
        story.scene.status = SceneStatus.RUNNING
        story.scene.round_index += 1
        story.scene.narrative_log.append(
            NarrativeEntry(
                round_index=story.scene.round_index,
                text=story.latest_dm_result.narrative,
                world_delta=story.latest_dm_result.world_delta,
                debug_reason=story.latest_dm_result.debug_reason,
            )
        )

        # 全局世界状态合并
        story.session.world_state.update(story.latest_dm_result.world_delta)
        # 消费本轮用户事件
        story.pending_user_events.clear()

        # 更新每个激活角色的短期记忆
        # 记忆格式：截取叙事文本前180字作为摘要
        memory_text = (
            f"第{story.scene.round_index}轮："
            f"{story.latest_dm_result.narrative[:180]}"
        )
        for character in story.characters:
            if not character.is_active:
                continue
            character.short_term_memory.append(memory_text)
            # 短期记忆滑动窗口：最多保留20条
            character.short_term_memory = character.short_term_memory[-20:]

        return {"story": story}

    # ==================================================================
    # 节点4：记忆沉淀
    # ==================================================================
    def reflect_memories(state: GraphState) -> dict[str, Any]:
        """每5轮执行一次长期记忆沉淀。

        从 DMResult.memory_hints 中取前2条作为长期记忆，
        追加到每个激活角色的 long_term_memory（最多保留50条）。

        触发条件：round_index 能被5整除。
        """
        story = state["story"]
        should_reflect = story.scene.round_index % 5 == 0
        if not should_reflect or story.latest_dm_result is None:
            return {"story": story}

        for character in story.characters:
            if not character.is_active:
                continue
            # 取本轮关键事件（最多2条）存入长期记忆
            character.long_term_memory.extend(
                story.latest_dm_result.memory_hints[:2]
            )
            # 长期记忆上限：50条
            character.long_term_memory = character.long_term_memory[-50:]

        return {"story": story}

    # ==================================================================
    # 条件边：判断是否继续运行
    # ==================================================================
    def should_continue(state: GraphState) -> str:
        """判断是否继续下一轮叙事。

        Returns:
            "finish" — 已达到 max_rounds，结束图运行
            "continue" — 未达上限，回到 generate_intentions 继续
        """
        story = state["story"]
        if story.scene.round_index >= story.max_rounds:
            return "finish"
        return "continue"

    # ==================================================================
    # 图拓扑构建
    # ==================================================================
    # 注册4个处理节点
    graph.add_node("generate_intentions", generate_intentions)
    graph.add_node("adjudicate_scene", adjudicate_scene)
    graph.add_node("apply_state_updates", apply_state_updates)
    graph.add_node("reflect_memories", reflect_memories)

    # 设置入口和线性边
    graph.set_entry_point("generate_intentions")
    graph.add_edge("generate_intentions", "adjudicate_scene")
    graph.add_edge("adjudicate_scene", "apply_state_updates")
    graph.add_edge("apply_state_updates", "reflect_memories")

    # 条件路由：继续 → 回到 generate_intentions；结束 → END
    graph.add_conditional_edges(
        "reflect_memories",
        should_continue,
        {"continue": "generate_intentions", "finish": END},
    )

    # 编译为可执行图
    return graph.compile()
