"""RAG 检索层：编码、向量读写、混合检索与精排。

外部调用统一走 app.rag.rag_service，不要直接使用 app.core.embeddings / vector_store / reranker。
"""
