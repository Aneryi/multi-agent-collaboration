"""应用服务层 — StoryService

本文件是 MASE 的业务逻辑中枢，负责串联持久化、LLM 调用和 LangGraph 编排。

职责：
    1. 对外提供面向用户的操作（创建会话、角色、场景、运行叙事等）
    2. 管理 JSONRepository（持久化）和 NarrativeLLM（AI调用）的生命周期
    3. 构建 LangGraph 可执行图并调用 invoke()
    4. 将图的输出结果回写到持久化层

依赖关系：
    StoryService
    ├── JSONRepository  — 数据持久化
    ├── NarrativeLLM    — AI 模型调用
    └── CompiledGraph   — LangGraph 叙事编排（由 build_story_graph 构建）

典型用法：
    # 方式1：使用默认配置（数据目录 + 环境变量选择 LLM）
    service = StoryService.with_data_dir(".mase_data")

    # 方式2：手动注入依赖
    repo = JSONRepository(data_dir="/path/to/data")
    llm = DeepSeekNarrativeLLM(api_key="sk-...")
    service = StoryService(repository=repo, llm=llm)
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from mase.graph import build_story_graph
from mase.llm import NarrativeLLM, create_narrative_llm
from mase.models import Character, Scene, SceneStatus, StoryBundle, StoryState
from mase.storage import JSONRepository


class StoryService:
    """故事应用服务 — 叙事引擎的业务外观层。

    封装了创建会话、管理角色/场景、运行叙事、导出等全部业务操作。
    """

    def __init__(
        self,
        repository: JSONRepository | None = None,
        llm: NarrativeLLM | None = None,
    ) -> None:
        """初始化服务。

        Args:
            repository: JSON 持久化仓储，默认使用 .mase_data 目录
            llm: 叙事 LLM 适配器，默认由 create_narrative_llm() 根据环境变量选择
        """
        self.repository = repository or JSONRepository()
        self.llm = llm or create_narrative_llm()
        # 基于选定的 LLM 构建 LangGraph 可执行图（编译一次，反复调用）
        self.graph = build_story_graph(self.llm)

    @classmethod
    def with_data_dir(
        cls,
        data_dir: str | Path,
        llm: NarrativeLLM | None = None,
    ) -> "StoryService":
        """便捷工厂：指定数据目录创建服务。

        Args:
            data_dir: JSON 文件存储目录
            llm: 可选的 LLM 适配器（不传则由环境变量决定）

        Returns:
            配置好的 StoryService 实例
        """
        return cls(repository=JSONRepository(data_dir=data_dir), llm=llm)

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------

    def create_session(self, title: str) -> StoryBundle:
        """创建一个新的故事会话。

        Args:
            title: 故事标题

        Returns:
            新创建的 StoryBundle（仅含 session，角色和场景需后续添加）
        """
        return self.repository.create_bundle(title=title)

    def get_session(self, session_id: UUID) -> StoryBundle:
        """读取会话的完整数据。

        Args:
            session_id: 会话 UUID

        Returns:
            包含会话、所有场景、所有角色和意图日志的 StoryBundle

        Raises:
            KeyError: 会话不存在
        """
        return self.repository.load_bundle(session_id)

    # ------------------------------------------------------------------
    # 角色管理
    # ------------------------------------------------------------------

    def add_character(
        self,
        session_id: UUID,
        *,
        name: str,
        persona: str,
        appearance: str = "",
        goal: str = "",
    ) -> Character:
        """向会话添加一个角色。

        Args:
            session_id: 目标会话 UUID
            name: 角色名
            persona: 性格、经历、说话风格描述
            appearance: 外貌描述（可选）
            goal: 当前目标（可选）

        Returns:
            创建的角色对象（含自动生成的 character_id）
        """
        bundle = self.repository.load_bundle(session_id)
        character = Character(
            session_id=session_id,
            name=name,
            persona=persona,
            appearance=appearance,
            goal=goal,
        )
        self.repository.upsert_character(bundle, character)
        return character

    # ------------------------------------------------------------------
    # 场景管理
    # ------------------------------------------------------------------

    def add_scene(self, session_id: UUID, *, title: str, description: str) -> Scene:
        """向会话添加一个场景。

        order_index 自动递增（当前场景数 + 1）。

        Args:
            session_id: 目标会话 UUID
            title: 场景标题
            description: 场景描述（地点、时间、天气、氛围等）

        Returns:
            创建的场景对象
        """
        bundle = self.repository.load_bundle(session_id)
        scene = Scene(
            session_id=session_id,
            title=title,
            description=description,
            order_index=len(bundle.scenes) + 1,
        )
        self.repository.upsert_scene(bundle, scene)
        return scene

    # ------------------------------------------------------------------
    # 事件注入
    # ------------------------------------------------------------------

    def inject_event(self, session_id: UUID, event: str) -> StoryBundle:
        """向会话注入用户事件。

        事件将在下一轮叙事中被 DM 和角色感知到。

        Args:
            session_id: 目标会话 UUID
            event: 事件描述文本

        Returns:
            更新后的 StoryBundle
        """
        bundle = self.repository.load_bundle(session_id)
        bundle.pending_user_events.append(event)
        self.repository.save_bundle(bundle)
        return bundle

    # ------------------------------------------------------------------
    # 叙事运行
    # ------------------------------------------------------------------

    def run_scene(
        self,
        session_id: UUID,
        scene_id: UUID,
        *,
        max_rounds: int = 1,
        seed: int | None = None,
    ) -> StoryState:
        """运行指定场景的叙事循环。

        内部流程：
        1. 加载会话数据，定位目标场景
        2. 构建 StoryState（LangGraph 图的输入）
        3. 调用 graph.invoke() 运行叙事循环
        4. 将图输出回写到持久化层

        Args:
            session_id: 会话 UUID
            scene_id: 要运行的场景 UUID
            max_rounds: 本次运行的最大轮数（从当前轮次累加）
            seed: 随机种子（用于复现相同叙事）

        Returns:
            运行结束后的 StoryState（包含最新场景状态和生成的意图/裁决）

        Raises:
            ValueError: 会话没有角色，或 max_rounds < 1
            KeyError: 场景不存在
        """
        # 加载并验证
        bundle = self.repository.load_bundle(session_id)
        scene = self._find_scene(bundle, scene_id)

        if not bundle.characters:
            raise ValueError("At least one character is required before running a scene.")
        if max_rounds < 1:
            raise ValueError("max_rounds must be greater than 0.")

        # 构建运行时状态（从当前轮次累加 max_rounds）
        story = StoryState(
            session=bundle.session,
            scene=scene,
            characters=bundle.characters,
            pending_user_events=bundle.pending_user_events,
            max_rounds=scene.round_index + max_rounds,
            seed=seed,
        )

        # 调用 LangGraph 状态图
        result = self.graph.invoke({"story": story})
        updated: StoryState = result["story"]

        # 回写持久化：将会话、角色、场景、意图日志同步到 StoryBundle
        bundle.session = updated.session
        bundle.characters = updated.characters
        bundle.pending_user_events = updated.pending_user_events
        bundle.scenes = [
            updated.scene if item.scene_id == scene_id else item
            for item in bundle.scenes
        ]
        bundle.intent_logs.extend(updated.generated_intents)
        self.repository.save_bundle(bundle)

        return updated

    # ------------------------------------------------------------------
    # 场景停止与导出
    # ------------------------------------------------------------------

    def stop_scene(self, session_id: UUID, scene_id: UUID) -> Scene:
        """停止场景运行，将其标记为 ENDED 并生成摘要。

        Args:
            session_id: 会话 UUID
            scene_id: 要停止的场景 UUID

        Returns:
            更新后的场景对象（status=ENDED, summary 已填充）
        """
        bundle = self.repository.load_bundle(session_id)
        scene = self._find_scene(bundle, scene_id)

        # 标记结束并生成摘要（调用 LLM 的 summarize_scene）
        scene.status = SceneStatus.ENDED
        scene.summary = self.llm.summarize_scene(
            scene=scene, characters=bundle.characters
        )
        self.repository.upsert_scene(bundle, scene)
        return scene

    def export_markdown(self, session_id: UUID) -> str:
        """将完整故事导出为 Markdown 格式文本。

        格式：
            # 故事标题
            ## 场景标题
            场景描述
            ### 第 N 轮
            叙事正文
            > 场景摘要：...

        Args:
            session_id: 会话 UUID

        Returns:
            Markdown 格式的完整故事文本
        """
        bundle = self.repository.load_bundle(session_id)
        lines = [f"# {bundle.session.title}", ""]

        # 按 order_index 排序输出每个场景
        for scene in sorted(bundle.scenes, key=lambda item: item.order_index):
            lines.extend([f"## {scene.title}", "", scene.description, ""])

            # 每轮叙事
            for entry in scene.narrative_log:
                lines.extend([f"### 第 {entry.round_index} 轮", "", entry.text, ""])

            # 场景摘要
            if scene.summary:
                lines.extend(["> 场景摘要：" + scene.summary, ""])

        return "\n".join(lines).strip() + "\n"

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _find_scene(bundle: StoryBundle, scene_id: UUID) -> Scene:
        """在 StoryBundle 中查找指定场景。

        Raises:
            KeyError: 场景不存在
        """
        for scene in bundle.scenes:
            if scene.scene_id == scene_id:
                return scene
        raise KeyError(f"Scene not found: {scene_id}")
