"""写入汽修问诊样例（案例 / 保养提示 / 手册错误码）。

幂等：知识按标题、手册码按错误码跳过已存在的行。

    cd backend
    python scripts/seed_auto_repair_knowledge.py
    python scripts/seed_auto_repair_knowledge.py --sync

`--sync` 在推理服务可用时调用 scripts/sync_vectors.py，把已发布知识写入 embedding 列。
推理服务没起来时只写知识行，并打印同步命令。不编造召回率。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from app.core.database import SessionLocal
from app.domain.auto_repair_seed import KNOWLEDGE_SEEDS, MANUAL_CODE_SEEDS
from app.models.knowledge import KnowledgeItem, KnowledgeStatus
from app.models.manual_code import ManualCodeEntry


def seed(db) -> dict:
    """把内置的汽修问诊样例写入数据库。知识按标题、手册码按错误码跳过已存在的记录，保证可重复执行。返回新建数量和知识 ID 列表。"""
    knowledge_ids = []
    created_knowledge = 0
    created_manuals = 0
    for row in KNOWLEDGE_SEEDS:
        existing = db.query(KnowledgeItem).filter(KnowledgeItem.title == row["title"]).first()
        if existing:
            knowledge_ids.append(existing.id)
            continue
        item = KnowledgeItem(
            title=row["title"],
            content=row["content"],
            device_type=row.get("device_type") or "",
            fault_code=row.get("fault_code") or "",
            fault_tags=row.get("fault_tags") or [],
            source_type="SEED",
            status=KnowledgeStatus.PUBLISHED,
        )
        db.add(item)
        db.flush()
        knowledge_ids.append(item.id)
        created_knowledge += 1
    for row in MANUAL_CODE_SEEDS:
        existing = db.query(ManualCodeEntry).filter(ManualCodeEntry.error_code == row["error_code"]).first()
        if existing:
            continue
        db.add(ManualCodeEntry(
            manual_name=row["manual_name"],
            device_type=row.get("device_type") or "",
            error_code=row["error_code"],
            title=row["title"],
            description=row["description"],
            message_text=row.get("message_text") or "",
            severity=row.get("severity") or "",
            effect=row.get("effect") or "",
            conditions=row.get("conditions") or [],
            related_codes=row.get("related_codes") or [],
            causes=row.get("causes") or "",
            solutions=row.get("solutions") or "",
            chapter=row.get("chapter") or "",
            page=row.get("page") or "",
        ))
        created_manuals += 1
    db.commit()
    return {
        "created_knowledge": created_knowledge,
        "created_manuals": created_manuals,
        "knowledge_ids": knowledge_ids,
    }


def sync_vectors() -> None:
    """在推理服务可用时，调用向量同步脚本把刚写入的已发布知识写入 embedding 列；服务不可用则只提示稍后手动同步。"""
    from app.core.config import settings
    from app.rag.rag_service import is_server_available

    if not is_server_available():
        logger.warning(f"推理服务不可用: {settings.EMBEDDING_SERVER_URL}")
        logger.warning("样例已写入 PostgreSQL。向量同步请稍后执行: python scripts/sync_vectors.py")
        return
    from scripts.sync_vectors import main as sync_main
    sync_main()


def main():
    """命令行入口：写入样例知识。带 --sync 时会在写入后再同步向量，需要推理服务已启动，且已执行 pgvector 迁移。"""
    parser = argparse.ArgumentParser(description="写入汽修问诊样例")
    parser.add_argument("--sync", action="store_true", help="写入后调用 sync_vectors（需要推理服务）")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        result = seed(db)
    finally:
        db.close()
    logger.info(
        f"汽修样例: 新知识 {result['created_knowledge']} 条, "
        f"新手册码 {result['created_manuals']} 条, 知识 id {result['knowledge_ids']}"
    )
    if args.sync:
        sync_vectors()
    else:
        logger.info("未执行向量同步。需要时: python scripts/seed_auto_repair_knowledge.py --sync")
        logger.info("或: python scripts/sync_vectors.py")


if __name__ == "__main__":
    main()
