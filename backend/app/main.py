import sys
import os
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from loguru import logger
# __file__ = backend/app/main.py → dirname = backend/app → dirname = backend
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# 同时支持从项目根目录运行的情况
_project_root = os.path.dirname(_backend_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.api import work_orders, knowledge, devices, spare_parts, users, categories, search, dashboard, dispatch, duty_schedules, leave_requests, notifications
from app.api.work_order_imports import router as work_order_imports_router
from app.api.vehicles import router as vehicles_router
from app.api.service_domain import (
    customers_router,
    stores_router,
    bays_router,
    appointments_router,
    part_skus_router,
)
from app.api.service_catalog import packages_router, skus_router
from app.api.quotes import router as quotes_router
from app.api.payments import router as payments_router
from app.api.follow_ups import router as follow_ups_router
from app.api.purchase_orders import router as purchase_orders_router
from app.api.manual_codes import router as manual_codes_router
from app.api.dingtalk import router as dingtalk_router, ensure_oa_services_started
from app.api.session import router as session_router
from app.api.fault_codes import router as fault_codes_router
from app.api.cascade_data import router as cascade_data_router
from app.api.upload import router as upload_router
from app.api.auth import router as auth_router
from app.api.dingtalk_mock import router as dingtalk_mock_router
from app.mcp.public import public_http_app
from app.mcp.server import mcp_http_app
from app.mcp.access import decide_mcp_access
from app.core.security import decode_access_token

logger.remove()
logger.add(
    settings.LOG_FILE,
    rotation="10 MB",
    retention="30 days",
    level=settings.LOG_LEVEL,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    enqueue=False,
    backtrace=False,
    diagnose=False,
)
# 标准输出：低延迟，排查钉钉机器人链路必看
import sys as _sys
logger.add(
    _sys.stdout,
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
    enqueue=False,
    backtrace=False,
    diagnose=False,
)

# MCP Server 实例（lifespan 与 mount 复用同一实例）
_mcp_app = mcp_http_app()
_mcp_public_app = public_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} 启动中...")
    from app.core.config import assert_production_secrets
    assert_production_secrets()
    logger.info(f"📊 数据库: {settings.DATABASE_URL.split('@')[1] if '@' in settings.DATABASE_URL else 'N/A'}")
    logger.info(f"🔴 Redis: {settings.REDIS_URL}")
    logger.info(f"🤖 DeepSeek API: {'已配置' if settings.DEEPSEEK_API_KEY else '未配置'}")
    # 预热：探测推理服务（bge-m3 编码 + reranker 重排）是否就绪，不阻塞启动
    try:
        from app.rag.rag_service import is_server_available
        from app.core.config import settings as _s
        if is_server_available():
            logger.info(f"🧠 推理服务就绪: {_s.EMBEDDING_SERVER_URL}（{_s.EMBEDDING_MODEL_NAME} + {_s.RERANKER_MODEL_NAME}）")
        else:
            logger.warning(
                f"⚠️ 推理服务不可用: {_s.EMBEDDING_SERVER_URL}。检索将降级为 BM25-only，"
                "请尽快启动推理服务（start_all.ps1 / start_embedding_server.ps1）"
            )
    except Exception as e:
        logger.warning(f"⚠️ 推理服务探测失败: {e}")
    # MCP Server 生命周期（内部工具 + 第三方只读入口）
    async with _mcp_app.lifespan(app):
        async with _mcp_public_app.lifespan(app):
            yield
    logger.info("👋 应用关闭中...")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Smart-Repair-System - 以工单收录与知识沉淀为核心",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.DEBUG else [
        origin.strip() for origin in (settings.CORS_ORIGINS or "").split(",") if origin.strip()
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(work_orders.router, prefix="/api/v1/work-orders", tags=["工单管理"])
app.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["知识管理"])
app.include_router(manual_codes_router, prefix="/api/v1/manual-codes", tags=["设备手册错误码"])
app.include_router(devices.router, prefix="/api/v1/devices", tags=["设备管理"])
app.include_router(spare_parts.router, prefix="/api/v1/spare-parts", tags=["备件管理"])
app.include_router(users.router, prefix="/api/v1/users", tags=["用户管理"])
app.include_router(categories.router, prefix="/api/v1/categories", tags=["分类管理"])
app.include_router(search.router, prefix="/api/v1/search", tags=["知识检索"])
app.include_router(session_router, prefix="/api/v1/session", tags=["会话管理"])
app.include_router(dingtalk_router, prefix="/api/v1/dingtalk", tags=["钉钉集成"])
app.include_router(fault_codes_router, prefix="/api/v1", tags=["故障码映射"])
app.include_router(cascade_data_router, prefix="/api/v1", tags=["级联分类数据"])
app.include_router(upload_router, prefix="/api/v1", tags=["文件上传"])
app.include_router(auth_router, prefix="/api/v1/auth", tags=["认证登录"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["数据驾驶舱"])
app.include_router(duty_schedules.router, prefix="/api/v1/duty-schedules", tags=["排班管理"])
app.include_router(leave_requests.router, prefix="/api/v1/leave-requests", tags=["请假申请"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["站内通知"])
app.include_router(dispatch.router, tags=["派工管理"])
app.include_router(dingtalk_mock_router, tags=["钉钉扫码模拟"])
app.include_router(work_order_imports_router, prefix="/api/v1/work-order-imports", tags=["历史工单导入"])
app.include_router(vehicles_router, prefix="/api/v1/vehicles", tags=["车辆档案"])
app.include_router(customers_router, prefix="/api/v1/customers", tags=["客户"])
app.include_router(stores_router, prefix="/api/v1/stores", tags=["门店"])
app.include_router(bays_router, prefix="/api/v1/bays", tags=["工位"])
app.include_router(appointments_router, prefix="/api/v1/appointments", tags=["预约"])
app.include_router(part_skus_router, prefix="/api/v1/part-skus", tags=["配件目录"])
app.include_router(packages_router, prefix="/api/v1/service-packages", tags=["保养套餐"])
app.include_router(skus_router, prefix="/api/v1/service-skus", tags=["服务项目"])
app.include_router(quotes_router, prefix="/api/v1/quotes", tags=["报价"])
app.include_router(payments_router, prefix="/api/v1/payments", tags=["支付占位"])
app.include_router(follow_ups_router, prefix="/api/v1/follow-ups", tags=["回访提醒"])
app.include_router(purchase_orders_router, prefix="/api/v1/purchase-orders", tags=["采购单"])

# ============================================================
# MCP Server（Streamable HTTP）：仅本机可访问，可配置 API Key
# ============================================================
_MCP_ALLOWED_HOSTS = {"127.0.0.1", "::1", "localhost"}


@app.middleware("http")
async def mcp_access_guard(request: Request, call_next):
    """内部 /mcp：API Key、登录令牌或本机。公开 /mcp/public：只读，必须带 Key 或登录令牌。"""
    if request.url.path.startswith("/mcp"):
        auth = request.headers.get("Authorization", "")
        payload = None
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            if token and token != (settings.MCP_API_KEY or ""):
                payload = decode_access_token(token)
        decision = decide_mcp_access(
            path=request.url.path,
            authorization=auth,
            api_key=settings.MCP_API_KEY or "",
            token_payload=payload,
            client_host=request.client.host if request.client else "",
            localhost_hosts=_MCP_ALLOWED_HOSTS,
            public_enabled=settings.MCP_PUBLIC_ENABLED,
        )
        if decision:
            status_code, detail = decision
            return JSONResponse(status_code=status_code, content={"detail": detail})
    return await call_next(request)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """给每个响应带上请求号，便于把日志和一次调用对上。"""
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


app.mount("/mcp/public", _mcp_public_app, name="mcp-public")
app.mount("/mcp", _mcp_app, name="mcp")

# ============================================================
# 启动 Stream 客户端 + APScheduler 定时任务（OA审批同步用）
# ============================================================
ensure_oa_services_started(app)

# 上传附件不再公开挂载。读取走 /api/v1/upload/files/{name}，必须登录。
os.makedirs(os.path.join(_backend_dir, "uploads"), exist_ok=True)


# ============================================================
# 前端静态资源托管（SPA）：frontend/dist 构建产物
# 放在所有 API 路由之后挂载，未匹配的路径回落到 index.html（history 路由刷新不 404）
# ============================================================
_frontend_dist = os.path.join(_project_root, "frontend", "dist")


@app.get("/", tags=["系统"], include_in_schema=False)
async def root():
    """根路径：有前端构建产物时返回 SPA 首页，否则返回 API 信息"""
    if os.path.isfile(os.path.join(_frontend_dist, "index.html")):
        from fastapi.responses import FileResponse
        return FileResponse(os.path.join(_frontend_dist, "index.html"))
    return {
        "message": f"欢迎使用 {settings.APP_NAME}",
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "status": "running"
    }


if os.path.isdir(_frontend_dist):
    # assets 等静态资源（js/css/图片）
    app.mount("/assets", StaticFiles(directory=os.path.join(_frontend_dist, "assets")), name="frontend_assets")
else:
    logger.warning(f"⚠️ 前端构建产物不存在: {_frontend_dist}，根路径将返回 API 信息（执行 npm run build 生成）")


@app.get("/health", tags=["系统"])
async def health_check():
    """数据库和 Redis 决定整体状态。Milvus 与推理服务单独探测，超时不拖死本接口。"""
    from sqlalchemy import text
    import socket

    database = "down"
    try:
        from app.core.database import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        database = "connected"
    except Exception as exc:
        logger.warning(f"[Health] 数据库探测失败: {exc}")

    redis_status = "down"
    try:
        import redis
        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=0.4, socket_timeout=0.4)
        client.ping()
        redis_status = "connected"
    except Exception as exc:
        logger.warning(f"[Health] Redis 探测失败: {exc}")

    milvus = "down"
    try:
        sock = socket.create_connection((settings.MILVUS_HOST, int(settings.MILVUS_PORT)), timeout=0.4)
        sock.close()
        milvus = "reachable"
    except Exception:
        milvus = "down"

    embedding = "down"
    try:
        import httpx
        response = httpx.get(f"{settings.EMBEDDING_SERVER_URL.rstrip('/')}/health", timeout=0.4)
        embedding = "ready" if response.status_code == 200 else "down"
    except Exception:
        embedding = "down"

    core_ok = database == "connected" and redis_status == "connected"
    body = {
        "status": "healthy" if core_ok else "degraded",
        "database": database,
        "redis": redis_status,
        "milvus": milvus,
        "embedding": embedding,
        "version": settings.APP_VERSION,
        "mcp": "ok",
    }
    return JSONResponse(status_code=200 if core_ok else 503, content=body)


if os.path.isdir(_frontend_dist):
    @app.get("/{full_path:path}", tags=["系统"], include_in_schema=False)
    async def spa_fallback(full_path: str):
        """SPA 兜底：非 API/docs/mcp 的未匹配路径统一返回 index.html，支持前端 history 路由"""
        from fastapi.responses import FileResponse
        return FileResponse(os.path.join(_frontend_dist, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.BACKEND_PORT,
        reload=settings.DEBUG
    )