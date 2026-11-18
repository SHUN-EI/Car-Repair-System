"""OBD 标准故障码接口：列表、详情和 JSON 批量导入。

与手册错误码、工单内部对照表分开。导入会按 code 做 upsert，
并在推理服务可用时回写 embedding。
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from loguru import logger

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.obd_code import ObdCode
from app.models.user import User, UserRole

router = APIRouter()


class ObdCodeIn(BaseModel):
    """一条待写入的 OBD 标准码。"""
    code: str = Field(..., min_length=1, max_length=20)
    system: Optional[str] = Field(None, max_length=1)
    title: str = Field(..., min_length=1, max_length=300)
    description_zh: str
    description_en: Optional[str] = None
    typical_causes: Optional[str] = None
    typical_steps: Optional[str] = None
    standard: Optional[str] = "SAE J2012"
    status: Optional[str] = "PUBLISHED"


class ObdImportJsonRequest(BaseModel):
    """JSON 批量导入请求体。"""
    items: List[ObdCodeIn]


def _to_dict(row: ObdCode) -> dict:
    """把 OBD 行转成接口输出。"""
    return {
        "id": row.id,
        "code": row.code,
        "system": row.system,
        "title": row.title,
        "description_zh": row.description_zh,
        "description_en": row.description_en,
        "typical_causes": row.typical_causes,
        "typical_steps": row.typical_steps,
        "standard": row.standard,
        "source_id": row.source_id,
        "status": row.status,
        "point_id": row.point_id,
    }


def _require_admin(current_user: User) -> None:
    """仅管理员可以导入或改码库。"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="需要管理员权限")


def _norm_code(code: str) -> str:
    """规范成大写标准码。"""
    from app.core.manual_text import normalize_error_code
    return normalize_error_code(code) or (code or "").strip().upper()


def _embed(row: ObdCode) -> None:
    """尽量写入向量；推理服务不可用时只记日志，不让接口失败。"""
    try:
        from app.rag.lexical import obd_point_id
        from app.rag.rag_service import upsert_row_embedding
        text = chr(10).join(p for p in [
            row.code, row.title, row.description_zh or "",
            row.typical_causes or "", row.typical_steps or "",
        ] if p)
        upsert_row_embedding("obd_codes", row.id, text, obd_point_id(row.id))
        row.point_id = obd_point_id(row.id)
    except Exception as exc:
        logger.warning(f"[OBD] 写入 embedding 失败 code={row.code}: {exc}")


@router.get("/", summary="获取 OBD 标准故障码列表")
def list_obd_codes(
    keyword: Optional[str] = Query(None, description="按码或标题过滤"),
    code: Optional[str] = Query(None, description="精确码"),
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出已入库的 OBD 标准码，登录店员即可查阅。"""
    query = db.query(ObdCode)
    if code:
        query = query.filter(ObdCode.code == _norm_code(code))
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            (ObdCode.code.ilike(like)) | (ObdCode.title.ilike(like)) | (ObdCode.description_zh.ilike(like))
        )
    total = query.count()
    rows = query.order_by(ObdCode.code.asc()).offset(skip).limit(limit).all()
    return {"total": total, "items": [_to_dict(r) for r in rows]}


@router.get("/{obd_id}", summary="获取 OBD 标准码详情")
def get_obd_code(
    obd_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """按主键取一条 OBD 标准码。"""
    row = db.query(ObdCode).filter(ObdCode.id == obd_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="未找到该 OBD 码")
    return _to_dict(row)


@router.post("/import-json", summary="JSON 批量导入 OBD 标准码（按 code upsert）")
def import_obd_codes_json(
    payload: ObdImportJsonRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """管理员按标准码批量导入或更新，已存在则覆盖字段。"""
    _require_admin(current_user)
    created = 0
    updated = 0
    for item in payload.items:
        code = _norm_code(item.code)
        if not code:
            continue
        row = db.query(ObdCode).filter(ObdCode.code == code).first()
        fields = dict(
            code=code,
            system=(item.system or code[:1]).upper(),
            title=item.title,
            description_zh=item.description_zh,
            description_en=item.description_en,
            typical_causes=item.typical_causes,
            typical_steps=item.typical_steps,
            standard=item.standard or "SAE J2012",
            status=item.status or "PUBLISHED",
        )
        if row:
            for key, value in fields.items():
                setattr(row, key, value)
            updated += 1
        else:
            row = ObdCode(**fields)
            db.add(row)
            created += 1
        db.flush()
        _embed(row)
    db.commit()
    return {"created": created, "updated": updated, "total": created + updated}
