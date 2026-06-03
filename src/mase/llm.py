"""LLM 适配器层 — AI 模型调用接口

本文件定义了叙事引擎与 AI 模型之间的抽象接口和具体实现。

架构设计：
    NarrativeLLM (Protocol)
    ├── RuleBasedNarrativeLLM   — 本地规则型适配器（默认，无需 API Key）
    └── DeepSeekNarrativeLLM    — DeepSeek API 适配器（通过 OpenAI SDK 调用）

工厂函数 create_narrative_llm() 根据 MASE_LLM_PROVIDER 环境变量
自动选择适配器：
    - "rule"（默认）→ RuleBasedNarrativeLLM
    - "deepseek"    → DeepSeekNarrativeLLM

Protocol 方法说明：
    generate_intent()   — 角色根据自身状态生成行动意图
    adjudicate()        — DM 综合所有意图，裁决并生成叙事文本
    summarize_scene()   — 场景结束时生成摘要

错误处理策略：
    - RuleBasedNarrativeLLM：无外部依赖，不会出错
    - DeepSeekNarrativeLLM：
        - JSON 解析失败 → 重试（最多 max_retries 次）
        - API 网络错误 → 重试（递增等待）
        - 摘要生成失败 → 降级为规则型摘要
        - 多次重试仍失败 → 抛出 RuntimeError
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from typing import Protocol

from mase.models import Character, CharacterIntent, DMResult, Scene, StorySession

logger = logging.getLogger(__name__)


# =============================================================================
# NarrativeLLM Protocol — 所有 LLM 适配器必须实现的接口
# =============================================================================

class NarrativeLLM(Protocol):
    """叙事 LLM 的抽象协议（接口）。

    不强制继承，任何实现了这三个方法的类都可以作为适配器注入。
    使用 Protocol 而非 ABC 的好处：RuleBasedNarrativeLLM 无需显式继承。
    """

    def generate_intent(
        self,
        *,
        character: Character,
        scene: Scene,
        session: StorySession,
        active_characters: list[Character],
        round_index: int,
        user_events: list[str],
        seed: int | None = None,
    ) -> CharacterIntent:
        """为一个角色生成本轮的行动意图。

        Args:
            character: 当前角色
            scene: 当前场景
            session: 当前会话
            active_characters: 所有激活的角色（包含当前角色）
            round_index: 本轮轮次编号
            user_events: 用户注入的事件列表
            seed: 随机种子（用于复现）

        Returns:
            CharacterIntent — 结构化的角色意图
        """
        ...

    def adjudicate(
        self,
        *,
        scene: Scene,
        session: StorySession,
        characters: list[Character],
        intents: list[CharacterIntent],
        user_events: list[str],
        seed: int | None = None,
    ) -> DMResult:
        """DM 综合所有角色意图，裁决行动结果并生成叙事文本。

        Args:
            scene: 当前场景
            session: 当前会话
            characters: 所有角色
            intents: 本轮的意图列表（已按优先级排序）
            user_events: 用户注入的事件列表
            seed: 随机种子

        Returns:
            DMResult — 包含叙事、世界delta、关系delta、记忆提示和调试理由
        """
        ...

    def summarize_scene(self, *, scene: Scene, characters: list[Character]) -> str:
        """场景结束时生成摘要。

        Args:
            scene: 已结束的场景
            characters: 参与角色列表

        Returns:
            str — 场景摘要文本
        """
        ...


# =============================================================================
# LLM 工厂函数
# =============================================================================

def create_narrative_llm() -> NarrativeLLM:
    """根据环境变量创建合适的叙事 LLM 适配器。

    环境变量：
        MASE_LLM_PROVIDER
            "rule"（默认）— 本地规则型，无 API 依赖
            "deepseek"    — DeepSeek API，需 DEEPSEEK_API_KEY

    Returns:
        实现了 NarrativeLLM 协议的适配器实例
    """
    provider = os.getenv("MASE_LLM_PROVIDER", "rule").strip().lower()
    if provider == "deepseek":
        return DeepSeekNarrativeLLM()
    return RuleBasedNarrativeLLM()


# =============================================================================
# RuleBasedNarrativeLLM — 本地规则型适配器
# =============================================================================

class RuleBasedNarrativeLLM:
    """确定性本地适配器，用于开发、测试和无 API Key 环境。

    实现方式：
    - generate_intent：基于角色目标和场景模板生成意图，使用随机种子保证可复现
    - adjudicate：按打断优先 + 冲动值排序，用模板拼接叙事段落
    - summarize_scene：从叙事日志中提取信息生成规则摘要

    特点：
    - 不需要任何外部 API 调用
    - 使用 seed 参数保证相同输入产生相同输出（便于测试）
    - 叙事文本为模板生成，缺乏真实 LLM 的创造性和连贯性
    """

    # 角色可选情绪列表
    emotions = ["克制", "警觉", "犹豫", "坚定", "焦急"]

    def generate_intent(
        self,
        *,
        character: Character,
        scene: Scene,
        session: StorySession,
        active_characters: list[Character],
        round_index: int,
        user_events: list[str],
        seed: int | None = None,
    ) -> CharacterIntent:
        """基于规则生成角色意图。

        逻辑：
        - 从其他激活角色中随机选择一个作为目标
        - 随机选择情绪
        - 每3轮有概率触发打断行为
        - 使用 seed + character_id + round_index 作为随机种子
        """
        # 用种子保证相同条件产生相同随机结果
        rng = random.Random(f"{seed}:{character.character_id}:{round_index}")

        # 选择目标（排除自己）
        others = [c for c in active_characters if c.character_id != character.character_id]
        target = rng.choice(others) if others else None

        # 随机选择情绪
        emotion = rng.choice(self.emotions)

        # 拼装行动描述
        event_hint = f"并留意刚发生的事件：{user_events[-1]}" if user_events else ""
        goal = character.goal or "弄清当前局势"
        action = f"{character.name}尝试推进目标：{goal}{event_hint}"
        dialogue = f"我会按自己的方式处理这件事。"

        # 每3轮有概率触发打断
        interrupt = (
            round_index % 3 == 0
            and target is not None
            and rng.random() > 0.45
        )

        return CharacterIntent(
            scene_id=scene.scene_id,
            character_id=character.character_id,
            character_name=character.name,
            round_index=round_index,
            action=action,
            dialogue=dialogue,
            target_character_id=target.character_id if target else None,
            emotion=emotion,
            interrupt=interrupt,
            impulse=round(rng.uniform(0.25, 0.9), 2),
        )

    def adjudicate(
        self,
        *,
        scene: Scene,
        session: StorySession,
        characters: list[Character],
        intents: list[CharacterIntent],
        user_events: list[str],
        seed: int | None = None,
    ) -> DMResult:
        """基于规则进行 DM 裁决。

        逻辑：
        - 打断者优先于普通行动者
        - 模板化生成叙事段落（包含环境描写、角色行动和对话）
        - 每个意图生成一段叙事
        """
        # 建立 ID → 角色名的映射
        character_by_id = {str(c.character_id): c for c in characters}

        # 分离打断者和普通行动者，打断者优先
        interrupting = [intent for intent in intents if intent.interrupt]
        ordinary = [intent for intent in intents if not intent.interrupt]
        ordered = interrupting + ordinary

        paragraphs: list[str] = []

        # 注入用户事件
        if user_events:
            paragraphs.append(f"突发事件改变了场面：{user_events[-1]}")

        # 环境描写
        paragraphs.append(f"在{scene.description}中，空气像被重新拧紧。")

        # 为每个意图生成叙事段落
        for intent in ordered:
            target = (
                character_by_id.get(str(intent.target_character_id))
                if intent.target_character_id else None
            )

            if intent.interrupt and target:
                # 打断模板
                paragraphs.append(
                    f"{intent.character_name}以{intent.emotion}的姿态打断了{target.name}，"
                    f"{intent.action} 他说：“{intent.dialogue}”"
                )
            else:
                # 普通行动模板
                target_text = f"看向{target.name}，" if target else ""
                paragraphs.append(
                    f"{intent.character_name}{target_text}带着{intent.emotion}的神情行动："
                    f"{intent.action} 他低声说：“{intent.dialogue}”"
                )

        # 构建世界状态变化
        world_delta = {
            "last_scene_id": str(scene.scene_id),
            "last_round": scene.round_index + 1,
            "last_event": ordered[0].action if ordered else "场景保持沉默",
        }

        # 构建记忆提示
        memory_hints = [
            f"第{scene.round_index + 1}轮：{intent.action}"
            for intent in ordered
        ]

        return DMResult(
            narrative="\n".join(paragraphs),
            world_delta=world_delta,
            memory_hints=memory_hints,
            debug_reason="规则型DM按打断优先、冲动值次序和场景环境合成叙事。",
        )

    def summarize_scene(self, *, scene: Scene, characters: list[Character]) -> str:
        """基于规则生成场景摘要。

        从叙事日志最后一条取第一行，结合角色名和轮数拼装摘要。
        """
        if not scene.narrative_log:
            return "场景尚未发生有效叙事。"
        latest = scene.narrative_log[-1].text.splitlines()[0]
        names = "、".join(
            character.name for character in characters if character.is_active
        )
        return (
            f"{scene.title}已运行{scene.round_index}轮，"
            f"参与角色包括{names}。最近事件：{latest}"
        )


# =============================================================================
# DeepSeekNarrativeLLM — DeepSeek API 适配器
# =============================================================================

class DeepSeekNarrativeLLM:
    """通过 OpenAI 兼容接口调用 DeepSeek API 的真实 LLM 适配器。

    配置方式：
        必需：DEEPSEEK_API_KEY 环境变量
        可选：DEEPSEEK_BASE_URL（默认 https://api.deepseek.com）
        可选：DEEPSEEK_MODEL（默认 deepseek-chat）
        可选：DEEPSEEK_CHARACTER_MODEL（默认同 DM 模型，可指定更便宜的模型控制成本）

    特性：
    - JSON 模式输出（response_format={"type": "json_object"}）
    - 自动重试（JSON 解析失败 + 网络错误，最多 max_retries 次）
    - token 用量统计（total_tokens 属性）
    - 调用延迟追踪（avg_call_time_ms 属性）
    - 摘要生成失败降级为规则型摘要
    - Markdown 代码块自动剥离
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        character_model: str | None = None,
        max_retries: int = 2,
    ) -> None:
        """初始化 DeepSeek 适配器。

        Args:
            api_key: DeepSeek API 密钥，默认从 DEEPSEEK_API_KEY 环境变量读取
            base_url: API 端点（可指向代理或兼容服务）
            model: DM 裁决使用的模型名
            character_model: 角色意图使用的模型名（None = 同 DM 模型）
            max_retries: API 调用失败时的最大重试次数

        Raises:
            ValueError: 未设置 DEEPSEEK_API_KEY
        """
        import openai

        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY environment variable is required for the DeepSeek adapter. "
                "Set it in your environment or switch to the rule-based adapter "
                "(MASE_LLM_PROVIDER=rule)."
            )

        # 创建 OpenAI 客户端（指向 DeepSeek 端点）
        self.client = openai.OpenAI(api_key=self.api_key, base_url=base_url)
        self.model = model
        self.character_model = character_model or model
        self.max_retries = max_retries

        # 统计指标
        self._call_times: list[float] = []   # 每次调用的耗时（秒）
        self._total_tokens: int = 0          # 累计 token 消耗

    # ------------------------------------------------------------------
    # 公开统计属性
    # ------------------------------------------------------------------

    @property
    def total_tokens(self) -> int:
        """累计消耗的 token 总数。"""
        return self._total_tokens

    @property
    def avg_call_time_ms(self) -> float:
        """平均 API 调用延迟（毫秒）。"""
        if not self._call_times:
            return 0.0
        return sum(self._call_times) / len(self._call_times) * 1000

    # ------------------------------------------------------------------
    # NarrativeLLM 协议实现
    # ------------------------------------------------------------------

    def generate_intent(
        self,
        *,
        character: Character,
        scene: Scene,
        session: StorySession,
        active_characters: list[Character],
        round_index: int,
        user_events: list[str],
        seed: int | None = None,
    ) -> CharacterIntent:
        """调用 DeepSeek 生成角色意图。

        Prompt 结构：
        - 系统提示：角色扮演指令 + JSON 输出要求
        - 用户提示：场景描述 + 角色信息 + 近期记忆 + 其他角色 + 突发事件
        """
        # 构建其他角色描述
        others = [
            f"- {c.name}（{c.persona[:80]}）目标：{c.goal or '无'}"
            for c in active_characters
            if c.character_id != character.character_id
        ]

        # 近期短期记忆（最近6条）
        recent = character.short_term_memory[-6:] or ["（尚无近期记忆）"]

        # 系统提示：角色扮演 + JSON 格式要求
        system = (
            "你是一个故事中的角色。根据当前场景、你的性格和局势，"
            "生成你在本轮中想要执行的行动意图。"
            "你必须严格按照 JSON 格式返回，不要输出其他内容。"
        )

        # 用户提示：完整的上下文信息
        user_prompt = f"""场景：{scene.title} — {scene.description}
轮次：第 {round_index} 轮

【你的角色】
姓名：{character.name}
性格与经历：{character.persona}
外貌：{character.appearance or '未设定'}
当前目标：{character.goal or '弄清当前局势'}

【近期记忆】
{chr(10).join(recent)}

【场上其他角色】
{chr(10).join(others) if others else '（无其他角色）'}

【突发事件】
{chr(10).join(f'- {e}' for e in user_events) if user_events else '（无）'}

请返回以下 JSON 对象（仅 JSON，无其他文字）：
{{
  "action": "你打算做什么（一句话描述行动意图）",
  "dialogue": "你口中说的话，无对话则为 null",
  "target_character_name": "行为指向的角色名，无明确目标则为 null",
  "emotion": "当前情绪，如：冷静、警觉、焦虑、愤怒、坚定、犹豫、欣喜",
  "interrupt": true或false（是否打断他人当前行动），
  "impulse": 0.0-1.0 之间的冲动值（越高越冲动）
}}"""

        # 调用 API（使用角色模型）
        data = self._call(
            system=system,
            user=user_prompt,
            model=self.character_model,
            seed=seed,
        )

        # 解析为 CharacterIntent
        return CharacterIntent(
            scene_id=scene.scene_id,
            character_id=character.character_id,
            character_name=character.name,
            round_index=round_index,
            action=data.get("action", f"{character.name}观察周围。"),
            dialogue=data.get("dialogue"),
            target_character_id=self._resolve_target_id(
                data.get("target_character_name"), active_characters
            ),
            emotion=data.get("emotion", "calm"),
            interrupt=bool(data.get("interrupt", False)),
            impulse=float(data.get("impulse", 0.5)),
        )

    def adjudicate(
        self,
        *,
        scene: Scene,
        session: StorySession,
        characters: list[Character],
        intents: list[CharacterIntent],
        user_events: list[str],
        seed: int | None = None,
    ) -> DMResult:
        """调用 DeepSeek 进行 DM 裁决。

        Prompt 结构：
        - 系统提示：DM 角色指令 + 叙事要求 + JSON 输出要求
        - 用户提示：场景信息 + 角色列表 + 意图列表 + 突发事件
        """
        # 角色描述
        char_desc = "\n".join(
            f"- {c.name}：{c.persona[:100]}，目标：{c.goal or '无'}"
            for c in characters
        )

        # 意图描述
        intent_desc = "\n".join(
            f"- {i.character_name}：行动={i.action}，对话={i.dialogue or '无'}，"
            f"情绪={i.emotion}，打断={'是' if i.interrupt else '否'}，"
            f"冲动值={i.impulse}"
            for i in intents
        )

        # 系统提示：DM 角色 + 叙事风格要求
        system = (
            "你是一个叙事故事中的地下城主（Dungeon Master，DM）。"
            "你将收到场景描述、角色信息以及本轮所有角色的行动意图。"
            "你需要综合所有意图，裁决结果，并输出一个连贯、有画面感的叙事段落。"
            "采用第三人称有限视角，优先体现打断者的行动。"
            "你必须严格按照 JSON 格式返回，不要输出其他内容。"
        )

        user_prompt = f"""场景：{scene.title} — {scene.description}
已运行 {scene.round_index} 轮，当前为第 {scene.round_index + 1} 轮。

【角色信息】
{char_desc}

【角色意图列表】
{intent_desc}

【突发事件】
{chr(10).join(f'- {e}' for e in user_events) if user_events else '（无）'}

请返回以下 JSON 对象（仅 JSON，无其他文字）：
{{
  "narrative": "本轮的叙事正文（2-4 段，包含环境描写、行动描写与对话）",
  "world_delta": {{"key": "value"}} （世界状态变化，如天气、物品、地点变化，无变化则为空对象）,
  "relationship_delta": {{"角色A": {{"角色B": +1}}}} （角色关系变化，正数增进，负数恶化，无变化则为空对象）,
  "memory_hints": ["事件1", "事件2"] （本轮角色应该记住的关键事件，2-4条）,
  "debug_reason": "作为DM你的裁决思路（2-3句话）"
}}"""

        data = self._call(system=system, user=user_prompt, model=self.model, seed=seed)

        return DMResult(
            narrative=data.get("narrative", "场景陷入短暂的沉默……"),
            world_delta=data.get("world_delta", {}),
            relationship_delta=data.get("relationship_delta", {}),
            memory_hints=data.get("memory_hints", []),
            debug_reason=data.get("debug_reason", ""),
        )

    def summarize_scene(self, *, scene: Scene, characters: list[Character]) -> str:
        """调用 DeepSeek 生成场景摘要。

        与 generate_intent / adjudicate 不同，摘要生成不使用 JSON 模式，
        直接返回纯文本。失败时降级为规则型摘要。
        """
        if not scene.narrative_log:
            return "场景尚未发生有效叙事。"

        # 取最近5轮叙事（每轮截取前300字）作为上下文
        narrative_text = "\n".join(
            entry.text[:300] for entry in scene.narrative_log[-5:]
        )
        names = "、".join(c.name for c in characters if c.is_active)

        system = (
            "你是一个故事编辑。请根据场景叙事日志，"
            "生成一段简洁的场景摘要（100字以内）。只输出摘要文本，不要 JSON。"
        )
        user_prompt = f"""场景标题：{scene.title}
场景描述：{scene.description}
已运行轮数：{scene.round_index}
参与角色：{names}

近期叙事：
{narrative_text}

请生成场景摘要："""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.5,
                max_tokens=300,
            )
            choice = response.choices[0]
            self._record_usage(response)
            return choice.message.content.strip() or ""

        except Exception:
            # 降级：API 失败时回退到规则型摘要
            logger.exception(
                "DeepSeek summarization failed, falling back to rule-based summary"
            )
            names_str = "、".join(c.name for c in characters if c.is_active)
            latest = scene.narrative_log[-1].text.splitlines()[0]
            return (
                f"{scene.title}已运行{scene.round_index}轮，"
                f"参与角色包括{names_str}。最近事件：{latest}"
            )

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_target_id(
        name: str | None,
        active_characters: list[Character],
    ) -> str | None:
        """根据角色名查找对应的 character_id。

        Args:
            name: 目标角色名（来自 LLM 输出）
            active_characters: 当前激活角色列表

        Returns:
            str | None — 匹配到的角色 ID，未找到则为 None
        """
        if not name:
            return None
        for c in active_characters:
            if c.name == name:
                return str(c.character_id)
        return None

    def _call(
        self,
        *,
        system: str,
        user: str,
        model: str,
        seed: int | None = None,
    ) -> dict:
        """调用 DeepSeek Chat API，带重试和 JSON 解析。

        内部流程：
        1. 发送请求（JSON 模式，temperature=0.8, max_tokens=2048）
        2. 剥离可能的 Markdown 代码块（```json ... ```）
        3. 解析为 Python dict
        4. 失败时重试（JSON 解析错误 / 空响应 / 网络错误）

        Args:
            system: 系统提示词
            user: 用户提示词
            model: 模型名称
            seed: 随机种子（用于复现）

        Returns:
            dict — 解析后的 JSON 对象

        Raises:
            RuntimeError: 所有重试均失败
        """
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                # 构建请求参数
                kwargs: dict = dict(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.8,
                    max_tokens=2048,
                    response_format={"type": "json_object"},  # JSON 模式
                )
                if seed is not None:
                    kwargs["seed"] = seed  # DeepSeek 支持 seed 参数

                # 发起请求并计时
                t0 = time.perf_counter()
                response = self.client.chat.completions.create(**kwargs)
                self._record_usage(response, start=t0)

                # 提取响应文本
                raw = response.choices[0].message.content
                if raw is None:
                    raise RuntimeError("DeepSeek returned empty response")

                # 剥离可能的 Markdown 代码块标记
                raw = raw.strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[-1]  # 去掉 ```json
                    if raw.endswith("```"):
                        raw = raw[:-3]              # 去掉结尾 ```
                    raw = raw.strip()

                return json.loads(raw)

            except (json.JSONDecodeError, RuntimeError) as exc:
                # JSON 解析失败或空响应 — 可重试
                last_error = exc
                logger.warning(
                    "DeepSeek call attempt %d/%d failed: %s",
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                )
                if attempt < self.max_retries:
                    time.sleep(0.5 * (attempt + 1))  # 递增等待

            except Exception as exc:
                # 网络或其他错误 — 可重试
                logger.exception(
                    "DeepSeek API call failed (attempt %d)", attempt + 1
                )
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(1.0 * (attempt + 1))  # 网络错误等待更久

        # 所有重试均失败
        raise RuntimeError(
            f"DeepSeek API call failed after {self.max_retries + 1} attempts: {last_error}"
        )

    def _record_usage(self, response, *, start: float | None = None) -> None:
        """记录 API 调用的耗时和 token 消耗。

        Args:
            response: OpenAI API 响应对象
            start: 调用开始的 time.perf_counter() 时间戳
        """
        if start is not None:
            self._call_times.append(time.perf_counter() - start)
        if hasattr(response, "usage") and response.usage:
            self._total_tokens += response.usage.total_tokens
