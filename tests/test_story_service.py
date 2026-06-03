"""StoryService 集成测试

本文件包含 StoryService 的核心集成测试，验证：
1. 叙事流程：创建会话 → 添加角色 → 添加场景 → 运行 → 持久化 → 重新加载
2. Markdown 导出：导出的文本包含场景标题、轮次标记和叙事内容

测试使用 tmp_path fixture，数据目录由 pytest 自动创建和清理，
不会污染项目数据目录。

运行方式：
    pytest tests/ -v
"""

from __future__ import annotations

from mase.service import StoryService


def test_story_can_run_and_persist(tmp_path):
    """测试完整叙事流程和持久化一致性。

    流程：
    1. 创建会话、2个角色、1个场景
    2. 运行2轮叙事
    3. 验证运行结果：轮次、叙事日志、意图数量
    4. 重新加载会话，验证持久化数据一致

    验证点：
    - scene.round_index == 2（运行了2轮）
    - narrative_log 有2条记录
    - 每轮2个角色各生成1个意图，共4个
    - 重新加载后 round_index 和 intent_logs 一致
    - 角色短期记忆已更新
    """
    service = StoryService.with_data_dir(tmp_path)

    # 创建会话
    bundle = service.create_session("测试故事")

    # 添加角色1：阿岚
    first = service.add_character(
        bundle.session.session_id,
        name="阿岚",
        persona="冷静的旅人",
        goal="穿过雾门",
    )

    # 添加角色2：白石
    second = service.add_character(
        bundle.session.session_id,
        name="白石",
        persona="固执的守门人",
        goal="守住入口",
    )

    # 添加场景
    scene = service.add_scene(
        bundle.session.session_id,
        title="雾门前",
        description="山谷尽头的石门被白雾包围。",
    )

    # 运行2轮
    state = service.run_scene(
        bundle.session.session_id, scene.scene_id, max_rounds=2, seed=11
    )

    # ---- 验证运行结果 ----
    assert state.scene.round_index == 2, "应运行了2轮"
    assert len(state.scene.narrative_log) == 2, "应有2条叙事日志"

    # 每轮每个角色生成1个意图，2轮×2角色=4个
    assert {intent.character_id for intent in state.latest_intents} == {
        first.character_id, second.character_id
    }, "本轮的意图应包含两个角色"
    assert len(state.generated_intents) == 4, "总共应生成4个意图（2轮×2角色）"

    # ---- 验证持久化 ----
    reloaded = service.get_session(bundle.session.session_id)
    assert reloaded.scenes[0].round_index == 2, "重新加载后轮次应一致"
    assert reloaded.characters[0].short_term_memory, "角色应有短期记忆"
    assert len(reloaded.intent_logs) == 4, "重新加载后意图日志数量应一致"


def test_export_markdown_contains_scene_text(tmp_path):
    """测试 Markdown 导出包含必要内容。

    验证点：
    - 故事标题出现在导出文本中
    - 场景标题出现在导出文本中
    - 轮次编号出现在导出文本中
    """
    service = StoryService.with_data_dir(tmp_path)

    # 准备最小数据
    bundle = service.create_session("导出测试")
    service.add_character(
        bundle.session.session_id, name="青禾", persona="温和", goal="寻找答案"
    )
    scene = service.add_scene(
        bundle.session.session_id, title="河岸", description="清晨的河岸。"
    )

    # 运行1轮并停止
    service.run_scene(
        bundle.session.session_id, scene.scene_id, max_rounds=1, seed=3
    )
    service.stop_scene(bundle.session.session_id, scene.scene_id)

    # 导出
    exported = service.export_markdown(bundle.session.session_id)

    # 验证内容
    assert "# 导出测试" in exported, "应包含故事标题"
    assert "## 河岸" in exported, "应包含场景标题"
    assert "第 1 轮" in exported, "应包含轮次标记"
