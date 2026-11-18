-- 与 app.rag.lexical.tokenize_repair_text 同一套中文 2/3-gram + 英文/数字记号规则。
-- 来源：Alembic c4d5e6f7a8b9_add_pgvector_and_tsvector.py

CREATE OR REPLACE FUNCTION repair_text_tokens(src text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
AS $fn$
DECLARE
    result text := '';
    span text;
    i int;
    n int;
    non_cn text;
    w text;
BEGIN
    IF src IS NULL OR btrim(src) = '' THEN
        RETURN '';
    END IF;
    FOR span IN
        SELECT m[1] FROM regexp_matches(src, '[一-鿿]+', 'g') AS m
    LOOP
        result := result || ' ' || span;
        FOR i IN 1..char_length(span) LOOP
            FOR n IN 2..3 LOOP
                IF i + n - 1 <= char_length(span) THEN
                    result := result || ' ' || substr(span, i, n);
                END IF;
            END LOOP;
        END LOOP;
    END LOOP;
    non_cn := regexp_replace(src, '[一-鿿]+', ' ', 'g');
    FOREACH w IN ARRAY regexp_split_to_array(btrim(non_cn), '[[:space:]]+')
    LOOP
        IF char_length(w) >= 2 THEN
            result := result || ' ' || w;
        END IF;
    END LOOP;
    RETURN btrim(result);
END;
$fn$;

CREATE OR REPLACE FUNCTION knowledge_search_tsv(
    title text,
    content text,
    fault_code text,
    fault_tags jsonb
)
RETURNS tsvector
LANGUAGE sql
IMMUTABLE
AS $fn$
    SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(title, ''))), 'A')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(fault_code, ''))), 'A')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(content, ''))), 'B')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(fault_tags::text, ''))), 'C')
$fn$;


CREATE OR REPLACE FUNCTION obd_search_tsv(
    code text,
    title text,
    description_zh text,
    typical_causes text,
    typical_steps text
)
RETURNS tsvector
LANGUAGE sql
IMMUTABLE
AS $fn$
    SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(code, ''))), 'A')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(title, ''))), 'A')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(description_zh, ''))), 'B')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(typical_causes, ''))), 'B')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(typical_steps, ''))), 'C')
$fn$;

CREATE OR REPLACE FUNCTION chunk_search_tsv(
    title text,
    content text,
    chapter text
)
RETURNS tsvector
LANGUAGE sql
IMMUTABLE
AS $fn$
    SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(title, ''))), 'A')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(chapter, ''))), 'A')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(content, ''))), 'B')
$fn$;

CREATE OR REPLACE FUNCTION faq_search_tsv(
    title text,
    content text
)
RETURNS tsvector
LANGUAGE sql
IMMUTABLE
AS $fn$
    SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(title, ''))), 'A')
    || SETWEIGHT(to_tsvector('simple', repair_text_tokens(coalesce(content, ''))), 'B')
$fn$;
