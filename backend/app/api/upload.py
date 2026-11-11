"""文件上传 API - 登录后写入本地目录，读取走鉴权接口，不再挂公开静态目录。"""
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from loguru import logger

from app.core.security import get_current_user
from app.models.user import User

router = APIRouter(prefix="/upload", tags=["文件上传"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "uploads")
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mov", ".avi", ".webm"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _safe_path(filename: str) -> str:
    base = os.path.basename(filename or "")
    if not base or base != filename or ".." in base:
        raise HTTPException(status_code=404, detail="文件不存在")
    return os.path.join(UPLOAD_DIR, base)


@router.post("/work-order-image", summary="上传工单附件图片/视频")
async def upload_work_order_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传图片或视频。返回的地址必须带登录令牌再读，不能匿名猜测。"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="文件大小不能超过 50MB")

    date_str = datetime.now().strftime("%Y%m%d")
    unique_name = f"{date_str}_{uuid.uuid4().hex[:12]}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)
    with open(file_path, "wb") as handle:
        handle.write(content)

    url = f"/api/v1/upload/files/{unique_name}"
    logger.info(f"[Upload] 文件上传成功: {unique_name} ({len(content)} bytes) user={current_user.id}")
    return {
        "url": url,
        "name": file.filename,
        "size": len(content),
        "type": "video" if ext in {".mp4", ".mov", ".avi", ".webm"} else "image",
    }


@router.get("/files/{filename}", summary="读取已上传附件")
def read_uploaded_file(filename: str, current_user: User = Depends(get_current_user)):
    path = _safe_path(filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path)
