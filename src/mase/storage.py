"""持久化层 — JSON 文件仓储

本文件实现 MVP 阶段的数据持久化：以 UUID 为文件名，JSON 格式存储完整会话数据。

设计决策：
- 每个 StoryBundle 序列化为一个 JSON 文件，存放在 data_dir 下
- 文件名 = {session_id}.json，天然保证会话隔离
- 读写均为全量替换（非增量），简单可靠，适合 MVP 阶段
- 后续阶段可替换为 PostgreSQL + Redis（参见阶段6规划）

线程安全说明：
- JSONRepository 本身不保证线程安全
- 多会话并发操作不同文件是安全的（不同 session_id = 不同文件）
- 同一会话的并发写入需外部加锁（MVP 阶段暂不考虑）

数据目录结构示例：
    .mase_data/
    ├── a1b2c3d4-....json    # 会话1
    ├── e5f6g7h8-....json    # 会话2
    └── ...
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from mase.models import Character, CharacterIntent, Scene, StoryBundle, StorySession, now_utc


class JSONRepository:
    """JSON 文件仓储 — 以 JSON 文件存储和读取故事数据。

    用法：
        repo = JSONRepository(data_dir=".mase_data")
        bundle = repo.create_bundle(title="我的故事")
        repo.save_bundle(bundle)
        reloaded = repo.load_bundle(bundle.session.session_id)
    """

    def __init__(self, data_dir: str | Path = ".mase_data") -> None:
        """初始化仓储，自动创建数据目录（如不存在）。

        Args:
            data_dir: 数据存储目录路径，默认为项目根目录下的 .mase_data
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 基础 CRUD
    # ------------------------------------------------------------------

    def _path(self, session_id: UUID) -> Path:
        """根据 session_id 生成对应的 JSON 文件路径。"""
        return self.data_dir / f"{session_id}.json"

    def save_bundle(self, bundle: StoryBundle) -> None:
        """将 StoryBundle 序列化为 JSON 并写入文件。

        会先更新 bundle.session.updated_at 时间戳，然后全量覆盖写入。
        """
        path = self._path(bundle.session.session_id)
        bundle.session.updated_at = now_utc()
        payload = bundle.model_dump(mode="json")
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_bundle(self, session_id: UUID) -> StoryBundle:
        """从 JSON 文件加载 StoryBundle。

        Raises:
            KeyError: 指定 session_id 的文件不存在
        """
        path = self._path(session_id)
        if not path.exists():
            raise KeyError(f"Session not found: {session_id}")
        return StoryBundle.model_validate_json(path.read_text(encoding="utf-8"))

    def create_bundle(self, title: str) -> StoryBundle:
        """创建一个新的 StoryBundle（仅含 StorySession），持久化并返回。

        Args:
            title: 故事标题
        """
        bundle = StoryBundle(session=StorySession(title=title))
        self.save_bundle(bundle)
        return bundle

    def list_sessions(self) -> list[StorySession]:
        """列出所有已保存的会话（仅返回 StorySession 元信息）。"""
        sessions: list[StorySession] = []
        for path in sorted(self.data_dir.glob("*.json")):
            bundle = StoryBundle.model_validate_json(path.read_text(encoding="utf-8"))
            sessions.append(bundle.session)
        return sessions

    # ------------------------------------------------------------------
    # 实体更新辅助方法
    # ------------------------------------------------------------------

    def upsert_scene(self, bundle: StoryBundle, scene: Scene) -> StoryBundle:
        """插入或更新场景。按 order_index 排序，并设为当前场景。

        Args:
            bundle: 所属 StoryBundle
            scene: 要保存的场景

        Returns:
            更新后的 StoryBundle（同时已写入磁盘）
        """
        # 移除同 ID 旧记录（更新场景）
        bundle.scenes = [item for item in bundle.scenes if item.scene_id != scene.scene_id]
        bundle.scenes.append(scene)
        bundle.scenes.sort(key=lambda item: item.order_index)
        bundle.session.current_scene_id = scene.scene_id
        self.save_bundle(bundle)
        return bundle

    def upsert_character(self, bundle: StoryBundle, character: Character) -> StoryBundle:
        """插入或更新角色。

        Args:
            bundle: 所属 StoryBundle
            character: 要保存的角色

        Returns:
            更新后的 StoryBundle（同时已写入磁盘）
        """
        bundle.characters = [
            item for item in bundle.characters
            if item.character_id != character.character_id
        ]
        bundle.characters.append(character)
        self.save_bundle(bundle)
        return bundle

    def append_intents(self, bundle: StoryBundle, intents: list[CharacterIntent]) -> StoryBundle:
        """追加意图日志到 StoryBundle 并保存。

        Args:
            bundle: 所属 StoryBundle
            intents: 要追加的意图列表

        Returns:
            更新后的 StoryBundle
        """
        bundle.intent_logs.extend(intents)
        self.save_bundle(bundle)
        return bundle
