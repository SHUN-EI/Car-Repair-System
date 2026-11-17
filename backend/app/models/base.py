"""所有业务表的抽象基类：统一主键和创建/更新时间，并给出默认表名规则。"""

from datetime import datetime
from sqlalchemy import Column, Integer, DateTime
from sqlalchemy.ext.declarative import declared_attr
from app.core.database import Base


class BaseModel(Base):
    """SQLAlchemy 抽象基类。子表自动拥有自增 id、created_at、updated_at（更新时自动刷新）。本身不对应数据库表。"""
    __abstract__ = True

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    @declared_attr
    def __tablename__(cls):
        """默认表名为类名小写再加 s。子类若要使用其它表名，直接覆盖 __tablename__ 字符串即可。"""
        return cls.__name__.lower() + "s"