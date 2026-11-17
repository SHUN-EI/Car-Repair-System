"""核心基础设施导出：配置、数据库基类和会话依赖。业务逻辑不要从这里反向依赖 API 层。"""

from app.core.config import settings
from app.core.database import Base, engine, get_db, get_async_db

__all__ = ["settings", "Base", "engine", "get_db", "get_async_db"]