"""PostgreSQL 连接与会话工厂。同步引擎给现网绝大部分接口使用，异步引擎留给需要 AsyncSession 的路径；连接池会先 ping 再复用。"""

from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
from app.core.config import settings
import asyncio

# 同步引擎
engine = create_engine(
    settings.DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://"),
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.DEBUG
)


@event.listens_for(engine, "connect")
def _register_pgvector(dbapi_connection, _connection_record):
    """为每个同步连接注册 pgvector 适配器，才能读写 vector 列。"""
    try:
        from pgvector.psycopg2 import register_vector
        register_vector(dbapi_connection)
    except Exception:
        # 启动期或测试若连的不是 PostgreSQL，忽略即可；真正检索时仍会再失败并被上层降级。
        pass


# 异步引擎
async_engine = create_async_engine(
    settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"),
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.DEBUG
)

# 会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
AsyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=async_engine, class_=AsyncSession)

Base = declarative_base()


def get_db():
    """FastAPI 依赖：打开一个同步 Session，请求结束时关闭。调用方负责提交或回滚事务。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_db():
    """FastAPI 依赖：打开一个异步 Session，请求结束时关闭。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()