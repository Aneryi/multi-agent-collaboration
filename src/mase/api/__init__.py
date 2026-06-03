"""FastAPI 应用子包

提供 MASE 的 HTTP API 层，包含以下端点：

- POST   /api/sessions                    — 创建故事会话
- GET    /api/sessions/{id}               — 读取会话详情
- POST   /api/sessions/{id}/characters    — 创建角色
- POST   /api/sessions/{id}/scenes        — 创建场景
- POST   /api/sessions/{id}/scenes/{id}/run   — 运行场景
- POST   /api/sessions/{id}/scenes/{id}/stop  — 停止场景
- POST   /api/sessions/{id}/events        — 注入用户事件
- GET    /api/sessions/{id}/export        — 导出 Markdown 故事

启动方式：uvicorn mase.api.app:app --reload
"""
