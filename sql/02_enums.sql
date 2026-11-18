-- PostgreSQL 枚举类型，对照当前模型 WorkOrderStatus / KnowledgeStatus。
-- 用户角色、请假、排班、报价等状态在模型里是字符串列，不建枚举类型。

DO $$ BEGIN
    CREATE TYPE workorderstatus AS ENUM (
        'DRAFT',
        'SUBMITTED',
        'ASSIGNED',
        'ACCEPTED',
        'ARRIVED',
        'INSPECTING',
        'IN_PROGRESS',
        'COMPLETED',
        'ARCHIVING',
        'REJECTED',
        'STANDARDIZED',
        'CLASSIFIED',
        'APPROVED',
        'ARCHIVED',
        'INTAKE',
        'DIAGNOSING',
        'QUOTING',
        'QC',
        'CLOSED',
        'CANCELLED'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE knowledgestatus AS ENUM (
        'DRAFT',
        'UNDER_REVIEW',
        'PUBLISHED',
        'DEPRECATED',
        'ARCHIVED'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
