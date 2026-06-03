"""命令行入口 — MASE CLI 工具

本文件提供项目的命令行交互方式，支持运行内置 demo 和切换 LLM 适配器。

用法：
    # 使用默认 rule-based 适配器运行 demo（无需 API Key）
    python -m mase.cli demo

    # 使用 DeepSeek 适配器运行 demo
    python -m mase.cli --llm deepseek demo

    # 查看帮助
    python -m mase.cli --help

全局选项：
    --llm {rule,deepseek}   选择 LLM 适配器（覆盖 MASE_LLM_PROVIDER 环境变量）

环境变量：
    MASE_LLM_PROVIDER       LLM 适配器选择（rule | deepseek）
    MASE_DATA_DIR           JSON 数据存储目录（默认 .mase_data）
    DEEPSEEK_API_KEY        DeepSeek API 密钥（使用 deepseek 适配器时必需）

.env 文件支持：
    CLI 启动时自动加载当前目录和上级目录的 .env 文件（通过 python-dotenv）。
    可在 .env 中配置上述环境变量，避免每次手动设置。
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from mase.llm import DeepSeekNarrativeLLM, RuleBasedNarrativeLLM, create_narrative_llm
from mase.service import StoryService

logger = logging.getLogger("mase.cli")


# =============================================================================
# Demo 场景
# =============================================================================

def run_demo() -> None:
    """运行内置叙事 demo："雨夜图书馆"。

    场景：深夜旧图书馆，调查员林澈与档案管理员许鸢在封锁的阅览室对峙。
    运行 3 轮叙事，输出最后一轮叙事文本和完整 Markdown 导出。
    使用 DeepSeek 时额外显示 token 用量和延迟统计。
    """
    # 自动加载 .env 文件（项目根目录或当前目录）
    for env_path in (".env", "../.env"):
        if os.path.isfile(env_path):
            load_dotenv(env_path)
            break

    # 根据环境变量或 CLI 参数选择 LLM 适配器
    llm = create_narrative_llm()
    llm_label = _describe_llm(llm)

    # 创建服务
    service = StoryService.with_data_dir(
        os.getenv("MASE_DATA_DIR", ".mase_data"),
        llm=llm,
    )
    print(f"[LLM] {llm_label}")
    print()

    # 创建故事会话
    bundle = service.create_session("雨夜图书馆")

    # 添加角色1：林澈 — 调查员
    service.add_character(
        bundle.session.session_id,
        name="林澈",
        persona="谨慎的调查员，说话简短，习惯先观察再判断。",
        appearance="深色风衣，随身带一本旧笔记。",
        goal="找出图书馆失踪案的线索",
    )

    # 添加角色2：许鸢 — 档案管理员
    service.add_character(
        bundle.session.session_id,
        name="许鸢",
        persona="敏锐的档案管理员，熟悉馆内每一道门。",
        appearance="银框眼镜，手指总沾着纸页灰尘。",
        goal="保护被封存的地下书库",
    )

    # 创建场景
    scene = service.add_scene(
        bundle.session.session_id,
        title="封锁后的阅览室",
        description="深夜的旧图书馆，暴雨敲打高窗，阅览室只剩一盏摇晃的台灯。",
    )

    # 运行3轮叙事
    state = service.run_scene(
        bundle.session.session_id, scene.scene_id, max_rounds=3, seed=7
    )

    # 停止场景并生成摘要
    service.stop_scene(bundle.session.session_id, scene.scene_id)

    # 输出结果
    print("-" * 50)
    print(state.scene.narrative_log[-1].text)
    print("-" * 50)
    print()
    print(service.export_markdown(bundle.session.session_id))

    # DeepSeek 模式下输出统计信息
    if isinstance(llm, DeepSeekNarrativeLLM):
        print(
            f"[Stats] Tokens used: {llm.total_tokens}  |  "
            f"Avg latency: {llm.avg_call_time_ms:.0f} ms"
        )


# =============================================================================
# 工具函数
# =============================================================================

def _describe_llm(llm) -> str:
    """返回 LLM 适配器的可读描述。

    Args:
        llm: LLM 适配器实例

    Returns:
        描述字符串，如 "DeepSeek (deepseek-chat)" 或 "Rule-based (local)"
    """
    if isinstance(llm, DeepSeekNarrativeLLM):
        return f"DeepSeek ({llm.model})"
    if isinstance(llm, RuleBasedNarrativeLLM):
        return "Rule-based (local)"
    return type(llm).__name__


# =============================================================================
# CLI 入口
# =============================================================================

def main() -> None:
    """CLI 主入口 — 解析参数并分发到子命令。"""
    # 配置日志（INFO 级别，仅输出消息）
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # 构建参数解析器
    parser = argparse.ArgumentParser(description="MASE command line tools.")
    parser.add_argument(
        "--llm",
        choices=["rule", "deepseek"],
        default=None,
        help="LLM provider (overrides MASE_LLM_PROVIDER env var).",
    )

    # 子命令
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("demo", help="Run a storytelling demo.")

    args = parser.parse_args()

    # --llm 参数优先于环境变量
    if args.llm:
        os.environ["MASE_LLM_PROVIDER"] = args.llm

    # 分发子命令
    if args.command == "demo":
        run_demo()
        return

    # 无有效子命令时打印帮助
    parser.print_help()


if __name__ == "__main__":
    main()
