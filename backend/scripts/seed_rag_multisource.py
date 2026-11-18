"""写入多源 RAG 样例：OBD 码库、制动章节切片、图谱和一条已审客服知识。

幂等：来源按标题、OBD 按 code、手册按名称、切片按标题、实体按 canonical_key、
客服知识按标题跳过已存在的行。

    cd backend
    python scripts/seed_rag_multisource.py
    python scripts/seed_rag_multisource.py --sync

`--sync` 在推理服务可用时为 OBD、手册章节和客服知识回写 embedding。
不编造召回率。
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from app.core.database import SessionLocal
from app.models.consult_faq import ConsultFaq
from app.models.knowledge import KnowledgeItem
from app.models.knowledge_graph import KgEntity, KgRelation
from app.models.obd_code import ObdCode
from app.models.rag_source import RagSource
from app.models.repair_manual import RepairManual, RepairManualChunk


OBD_SEEDS = [
    {
        "code": "P0300",
        "system": "P",
        "title": "多缸随机失火",
        "description_zh": "发动机控制单元检测到多个气缸出现随机或间歇性失火。",
        "description_en": "Random/Multiple Cylinder Misfire Detected",
        "typical_causes": "点火线圈或火花塞老化、喷油不均、真空泄漏、燃油压力不足、线束接触不良。",
        "typical_steps": "读取失火计数，确认是随机还是某缸持续；检查点火线圈与火花塞；检查进气泄漏和燃油压力；排除机械压缩问题后再考虑更换零件。",
    },
    {
        "code": "P0301",
        "system": "P",
        "title": "1 缸失火",
        "description_zh": "发动机控制单元检测到 1 缸失火。",
        "description_en": "Cylinder 1 Misfire Detected",
        "typical_causes": "1 缸火花塞或点火线圈故障、喷油器异常、该缸压缩不足。",
        "typical_steps": "互换 1 缸与邻缸点火线圈做交叉验证；检查火花塞与喷油器；必要时测压缩。",
    },
    {
        "code": "P0420",
        "system": "P",
        "title": "催化器效率低于阈值（Bank 1）",
        "description_zh": "Bank 1 催化转化器效率低于规定阈值。",
        "description_en": "Catalyst System Efficiency Below Threshold (Bank 1)",
        "typical_causes": "催化器老化、上游或下游氧传感器故障、排气泄漏、长期失火导致催化剂损伤。",
        "typical_steps": "先排除失火和排气泄漏；观察上下游氧传感器波形；不要一出码就更换三元催化器。",
    },
    {
        "code": "C0035",
        "system": "C",
        "title": "左前轮速传感器电路",
        "description_zh": "ABS / ESC 监测到左前轮速传感器信号异常。",
        "description_en": "Left Front Wheel Speed Sensor Circuit",
        "typical_causes": "传感器脏污或间隙异常、线束破损、磁环缺损、控制单元输入电路故障。",
        "typical_steps": "检查传感器安装与线束，清洁磁环，用示波器或诊断仪查看轮速信号后再决定更换。",
    },
    {
        "code": "P0171",
        "system": "P",
        "title": "系统过稀（Bank 1）",
        "description_zh": "Bank 1 混合气长期偏稀，燃油修正超出上限。",
        "description_en": "System Too Lean (Bank 1)",
        "typical_causes": "进气真空泄漏、空气流量计读数偏低、燃油压力不足、氧传感器偏差。",
        "typical_steps": "检查进气管路与真空管，读取短长期燃油修正，测燃油压力，不要先更换氧传感器。",
    },
]

BRAKE_CHUNK = {
    "title": "制动踏板发紧的检查步骤",
    "chapter": "第 5 章 制动系统",
    "section": "踏板发紧 / 回位不良",
    "page_from": "5-12",
    "page_to": "5-14",
    "chunk_type": "procedure",
    "content": (
        "故障现象：制动踏板发紧、行程变短或松开后回位缓慢，低速点刹时车辆有发拖感。"
        "检查步骤：1. 确认制动液规格与液位，排除助力器真空管路泄漏。"
        "2. 检查制动卡钳滑动销是否缺油或卡滞，清洁并按规定润滑。"
        "3. 检查制动片是否异常磨损或卡在支架内。"
        "4. 检查制动管路是否变形或单向阀发卡，必要时测量轮缸回位。"
        "注意：原厂手册只给出检查顺序，更换零件前须先确认卡滞部位。本文为门店内部样例摘录，不得对外传播。"
    ),
}

FAQ_SEED = {
    "title": "刹车有点紧常见原因（已审客服知识）",
    "content": (
        "客户说「刹车有点紧」时，先问是踏板发硬、还是松开后仍有拖滞感，以及是否刚换过片或刚做过保养。"
        "店内常见原因依次是：卡钳滑动销缺油、制动片卡在支架、制动液或助力真空异常。"
        "引导到店检查时不要先报更换总成的价格，价格以目录和报价单为准。"
    ),
}


def _source(db, kind: str, title: str, **kwargs) -> RagSource:
    """按标题取或建一条来源登记。"""
    row = db.query(RagSource).filter(RagSource.title == title).first()
    if row:
        return row
    row = RagSource(
        source_kind=kind,
        title=title,
        status="PUBLISHED",
        ingested_at=datetime.utcnow(),
        **kwargs,
    )
    db.add(row)
    db.flush()
    return row


def _entity(db, entity_type: str, name: str, canonical_key: str, aliases=None, properties=None) -> KgEntity:
    """按规范名取或建实体。"""
    row = db.query(KgEntity).filter(KgEntity.canonical_key == canonical_key).first()
    if row:
        return row
    row = KgEntity(
        entity_type=entity_type,
        name=name,
        canonical_key=canonical_key,
        aliases=aliases or [],
        properties=properties or {},
    )
    db.add(row)
    db.flush()
    return row


def _relation(db, subject: KgEntity, predicate: str, obj: KgEntity, source_kind: str, source_ref: str, confidence: float = 1.0) -> None:
    """按三元组加来源幂等写入关系。"""
    exists = db.query(KgRelation).filter(
        KgRelation.subject_id == subject.id,
        KgRelation.predicate == predicate,
        KgRelation.object_id == obj.id,
        KgRelation.source_kind == source_kind,
        KgRelation.source_ref == source_ref,
    ).first()
    if exists:
        return
    db.add(KgRelation(
        subject_id=subject.id,
        predicate=predicate,
        object_id=obj.id,
        source_kind=source_kind,
        source_ref=source_ref,
        confidence=confidence,
        properties={},
    ))


def seed(db) -> dict:
    """写入多源样例，已存在的行跳过。"""
    created = {
        "sources": 0, "obd": 0, "manuals": 0, "chunks": 0,
        "faqs": 0, "entities": 0, "relations": 0,
    }

    obd_source = db.query(RagSource).filter(RagSource.title == "SAE 风格 OBD 样例码库").first()
    if not obd_source:
        created["sources"] += 1
    obd_source = _source(
        db, "OBD", "SAE 风格 OBD 样例码库",
        publisher="样例", version="seed-1",
        copyright_note="仅含公开常见码的教学样例，不是完整 SAE 码库。",
    )

    for row in OBD_SEEDS:
        existing = db.query(ObdCode).filter(ObdCode.code == row["code"]).first()
        if existing:
            continue
        db.add(ObdCode(source_id=obd_source.id, status="PUBLISHED", **row))
        created["obd"] += 1
    db.flush()

    manual_source = db.query(RagSource).filter(RagSource.title == "汽修样例乘用车维修手册（制动章节摘录）").first()
    if not manual_source:
        created["sources"] += 1
    manual_source = _source(
        db, "OEM_MANUAL", "汽修样例乘用车维修手册（制动章节摘录）",
        publisher="样例（非原厂授权全文）", version="seed-1",
        copyright_note="仅供门店内检索演示，不得作为原厂手册全文，也不得用于外部训练。",
    )
    manual = db.query(RepairManual).filter(RepairManual.name == "汽修样例乘用车维修手册").first()
    if not manual:
        manual = RepairManual(
            source_id=manual_source.id,
            name="汽修样例乘用车维修手册",
            manual_type="OEM",
            make="样例品牌",
            model="样例车型",
            year_from=2018,
            year_to=2024,
            language="zh",
            version="seed-1",
            copyright_note=manual_source.copyright_note,
            status="PUBLISHED",
        )
        db.add(manual)
        db.flush()
        created["manuals"] += 1

    chunk = db.query(RepairManualChunk).filter(RepairManualChunk.title == BRAKE_CHUNK["title"]).first()
    if not chunk:
        chunk = RepairManualChunk(manual_id=manual.id, status="PUBLISHED", **BRAKE_CHUNK)
        db.add(chunk)
        db.flush()
        created["chunks"] += 1

    faq = db.query(ConsultFaq).filter(ConsultFaq.title == FAQ_SEED["title"]).first()
    if not faq:
        faq = ConsultFaq(status="PUBLISHED", **FAQ_SEED)
        db.add(faq)
        db.flush()
        created["faqs"] += 1

    before_e = db.query(KgEntity).count()
    before_r = db.query(KgRelation).count()

    symptom_brake = _entity(db, "symptom", "刹车紧", "刹车紧", aliases=["刹车有点紧", "刹车发紧", "制动发紧", "踏板发硬"])
    cause = _entity(db, "cause", "卡钳回位不良", "卡钳回位不良")
    part = _entity(db, "part", "制动卡钳", "制动卡钳", aliases=["卡钳"])
    step = _entity(db, "procedure", "检查卡钳滑动销润滑", "检查卡钳滑动销润滑")
    symptom_idle = _entity(db, "symptom", "怠速抖动", "怠速抖动", aliases=["热车怠速抖动", "怠速不稳"])
    code_p0300 = _entity(db, "fault_code", "P0300", "P0300", aliases=["p0300"])

    _relation(db, symptom_brake, "caused_by", cause, "OEM_MANUAL", f"chunk:{chunk.id}", 0.9)
    _relation(db, symptom_brake, "needs_part", part, "OEM_MANUAL", f"chunk:{chunk.id}", 0.8)
    _relation(db, symptom_brake, "suggests_step", step, "OEM_MANUAL", f"chunk:{chunk.id}", 0.9)
    _relation(db, symptom_brake, "mentioned_in", step, "FAQ", f"faq:{faq.id}", 0.7)
    _relation(db, symptom_idle, "has_code", code_p0300, "OBD", "obd:P0300", 1.0)

    case = db.query(KnowledgeItem).filter(KnowledgeItem.title == "【汽修样例】发动机怠速抖动").first()
    if case:
        _relation(db, code_p0300, "illustrated_by", symptom_idle, "WORK_ORDER", f"knowledge:{case.id}", 0.8)

    db.flush()
    created["entities"] += max(0, db.query(KgEntity).count() - before_e)
    created["relations"] += max(0, db.query(KgRelation).count() - before_r)
    # entity helper already flushed new ones; recount accurately by tracking is hard if rerun
    # On rerun before_e already includes them so created stays 0, which is correct.

    db.commit()
    return {
        "created": created,
        "chunk_id": chunk.id,
        "faq_id": faq.id,
        "obd_codes": [r["code"] for r in OBD_SEEDS],
    }


def sync_embeddings(db) -> dict:
    """为已发布的 OBD、手册章节和客服知识回写 embedding。"""
    from app.core.config import settings
    from app.rag.lexical import chunk_point_id, faq_point_id, obd_point_id
    from app.rag.rag_service import is_server_available, upsert_row_embedding

    if not is_server_available():
        logger.warning(f"推理服务不可用: {settings.EMBEDDING_SERVER_URL}，跳过向量同步")
        return {"synced": 0, "skipped": True}

    synced = 0
    failed = 0
    for row in db.query(ObdCode).filter(ObdCode.status == "PUBLISHED").all():
        text = chr(10).join(p for p in [row.code, row.title, row.description_zh or "", row.typical_causes or ""] if p)
        try:
            upsert_row_embedding("obd_codes", row.id, text, obd_point_id(row.id))
            synced += 1
        except Exception as exc:
            failed += 1
            logger.error(f"OBD 同步失败 {row.code}: {exc}")
    for row in db.query(RepairManualChunk).filter(RepairManualChunk.status == "PUBLISHED").all():
        text = chr(10).join([row.title, row.chapter or "", (row.content or "")[:settings.MAX_VECTOR_CONTENT_LEN]])
        try:
            upsert_row_embedding("repair_manual_chunks", row.id, text, chunk_point_id(row.id))
            synced += 1
        except Exception as exc:
            failed += 1
            logger.error(f"章节同步失败 id={row.id}: {exc}")
    for row in db.query(ConsultFaq).filter(ConsultFaq.status == "PUBLISHED").all():
        text = chr(10).join([row.title, (row.content or "")[:settings.MAX_VECTOR_CONTENT_LEN]])
        try:
            upsert_row_embedding("consult_faqs", row.id, text, faq_point_id(row.id))
            synced += 1
        except Exception as exc:
            failed += 1
            logger.error(f"客服知识同步失败 id={row.id}: {exc}")
    logger.info(f"向量同步完成: 成功 {synced}, 失败 {failed}")
    return {"synced": synced, "failed": failed, "skipped": False}


def main():
    """写入样例，并按参数决定是否同步向量。"""
    parser = argparse.ArgumentParser(description="写入多源 RAG 样例数据")
    parser.add_argument("--sync", action="store_true", help="在推理服务可用时回写 embedding")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        result = seed(db)
        logger.info(f"多源样例写入完成: {result}")
        if args.sync:
            sync_embeddings(db)
        else:
            logger.info("未指定 --sync。若要写入向量，请再执行: python scripts/seed_rag_multisource.py --sync")
    finally:
        db.close()


if __name__ == "__main__":
    main()
