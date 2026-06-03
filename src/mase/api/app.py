"""FastAPI 应用 — MASE HTTP API 入口

本文件定义 MASE 的 REST API，提供完整的叙事引擎 HTTP 接口。

启动方式：
    uvicorn mase.api.app:app --reload
    访问 http://127.0.0.1:8000/docs 查看 OpenAPI 交互式文档

API 端点一览：

    会话管理：
    POST   /api/sessions                    创建故事会话
    GET    /api/sessions/{session_id}        读取会话详情

    角色管理：
    POST   /api/sessions/{session_id}/characters  创建角色

    场景管理：
    POST   /api/sessions/{session_id}/scenes       创建场景

    叙事运行：
    POST   /api/sessions/{session_id}/scenes/{scene_id}/run   运行指定轮数
    POST   /api/sessions/{session_id}/scenes/{scene_id}/stop  停止并总结场景

    交互与导出：
    POST   /api/sessions/{session_id}/events     注入用户事件
    GET    /api/sessions/{session_id}/export      导出完整故事 Markdown

设计说明：
    - 每次请求通过 get_service() 获取 StoryService 单例（@lru_cache 缓存）
    - 404 错误 → 会话或场景不存在
    - 400 错误 → 参数校验失败（如 max_rounds < 1、无角色运行场景）
    - 所有响应自动序列化为 JSON（export 端点返回纯文本 Markdown）
"""

from __future__ import annotations

import os
from functools import lru_cache
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from mase.llm import create_narrative_llm
from mase.service import StoryService


# ---------------------------------------------------------------------------
# 服务缓存
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _build_service(data_dir: str) -> StoryService:
    """构建（并缓存）StoryService 实例。

    使用 @lru_cache 确保 LangGraph 图只编译一次，
    后续请求复用同一实例，避免重复构建。
    参数 data_dir 作为缓存键，修改数据目录需重启服务。
    """
    return StoryService.with_data_dir(data_dir)


def get_service() -> StoryService:
    """获取 StoryService 实例（懒加载 + 缓存）。

    数据目录由 MASE_DATA_DIR 环境变量控制，默认 .mase_data。
    """
    data_dir = os.getenv("MASE_DATA_DIR", ".mase_data")
    return _build_service(data_dir)


# ---------------------------------------------------------------------------
# FastAPI 应用初始化
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Multi-Agent Storytelling Engine",
    version="0.1.0",
    description="基于 LangGraph 的多智能体协作叙事引擎 HTTP API",
)

# ---------------------------------------------------------------------------
# 请求体模型
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    """创建会话请求体。"""
    title: str


class CreateCharacterRequest(BaseModel):
    """创建角色请求体。"""
    name: str
    persona: str
    appearance: str = ""
    goal: str = ""


class CreateSceneRequest(BaseModel):
    """创建场景请求体。"""
    title: str
    description: str


class RunSceneRequest(BaseModel):
    """运行场景请求体。"""
    max_rounds: int = 1       # 本次运行的最大轮数
    seed: int | None = None   # 随机种子（可选，用于复现）


class InjectEventRequest(BaseModel):
    """注入事件请求体。"""
    event: str


# ---------------------------------------------------------------------------
# API 路由
# ---------------------------------------------------------------------------

# ---- 会话管理 ----

@app.post("/api/sessions")
def create_session(payload: CreateSessionRequest):
    """创建新的故事会话。

    Request Body:
        { "title": "故事标题" }

    Response:
        完整的 StoryBundle（含自动生成的 session_id）
    """
    return get_service().create_session(payload.title)


@app.get("/api/sessions/{session_id}")
def get_session(session_id: UUID):
    """读取会话详情。

    Path Parameters:
        session_id: 会话 UUID

    Response:
        包含 sessions, scenes, characters, intent_logs 的完整数据
    """
    try:
        return get_service().get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---- 角色管理 ----

@app.post("/api/sessions/{session_id}/characters")
def create_character(session_id: UUID, payload: CreateCharacterRequest):
    """向会话添加角色。

    Path Parameters:
        session_id: 目标会话 UUID

    Request Body:
        { "name": "角色名", "persona": "性格描述", "appearance": "外貌", "goal": "目标" }
    """
    try:
        return get_service().add_character(
            session_id,
            name=payload.name,
            persona=payload.persona,
            appearance=payload.appearance,
            goal=payload.goal,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---- 场景管理 ----

@app.post("/api/sessions/{session_id}/scenes")
def create_scene(session_id: UUID, payload: CreateSceneRequest):
    """向会话添加场景。

    order_index 自动递增，新场景自动设为 current_scene。
    """
    try:
        return get_service().add_scene(
            session_id, title=payload.title, description=payload.description
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---- 叙事运行 ----

@app.post("/api/sessions/{session_id}/scenes/{scene_id}/run")
def run_scene(session_id: UUID, scene_id: UUID, payload: RunSceneRequest):
    """运行指定场景的叙事循环。

    从场景当前轮次开始，运行 payload.max_rounds 轮。
    返回运行后的完整 StoryState。

    Request Body:
        { "max_rounds": 3, "seed": 42 }
    """
    try:
        return get_service().run_scene(
            session_id, scene_id,
            max_rounds=payload.max_rounds,
            seed=payload.seed,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/scenes/{scene_id}/stop")
def stop_scene(session_id: UUID, scene_id: UUID):
    """停止场景运行，标记为 ENDED 并生成摘要。

    角色记忆和目标保留，可在新场景中继续使用。
    """
    try:
        return get_service().stop_scene(session_id, scene_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---- 交互与导出 ----

@app.post("/api/sessions/{session_id}/events")
def inject_event(session_id: UUID, payload: InjectEventRequest):
    """向会话注入用户事件（导演干预）。

    事件将在下一轮叙事中被 DM 和角色感知。
    """
    try:
        return get_service().inject_event(session_id, payload.event)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/api/sessions/{session_id}/export",
    response_class=PlainTextResponse,
)
def export_story(session_id: UUID):
    """导出完整故事为 Markdown 格式文本。

    Content-Type: text/plain; charset=utf-8
    """
    try:
        return get_service().export_markdown(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
