"""应用配置：从 backend/.env 加载，并按 CHAT_LLM_MODE 在云端千问、本地 vLLM 和兼容 DeepSeek 之间解析对话模型参数。"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from pathlib import Path

# .env 文件绝对路径：backend/.env
_ENV_FILE = str(Path(__file__).resolve().parent.parent.parent / ".env")


class Settings(BaseSettings):
    # 强制用绝对路径加载 .env，避免相对路径依赖 CWD 导致 uvicorn worker 读取不到配置
    """全局配置对象。用绝对路径加载 .env，避免 uvicorn worker 因工作目录不同而读不到文件；未出现在模型里的环境变量会被忽略。数据库和 Redis 的完整 URL 若未填写，会在初始化时用主机、端口和账号拼出来。"""
    model_config = SettingsConfigDict(env_file=_ENV_FILE, case_sensitive=True, extra="ignore")
    # 应用配置
    APP_NAME: str = "Smart-Repair-System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    BACKEND_PORT: int = 18080

    # 数据库配置
    DB_USER: str = "admin"
    DB_PASSWORD: str = "admin123"
    DB_NAME: str = "maintenance_db"
    DB_HOST: str = "localhost"
    DB_PORT: int = 15432
    DATABASE_URL: str = ""

    # Redis 配置
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    REDIS_DB: int = 0
    REDIS_URL: str = ""

    # 向量维度（BAAI/bge-m3 dense，写入 PostgreSQL pgvector，余弦度量）
    VECTOR_DIM: int = 1024
    # 兼容旧配置名：历史代码与文档曾用 MILVUS_VECTOR_SIZE，与 VECTOR_DIM 同值
    MILVUS_VECTOR_SIZE: int = 1024
    # 向量检索时 HNSW 的 ef_search（越大召回越稳，延迟略增）
    PGVECTOR_EF_SEARCH: int = 64
    # 关键词路 ts_rank 权重：D, C, B, A（标题与故障码为 A，正文为 B，标签为 C）
    TS_RANK_WEIGHTS: str = "{0.1, 0.2, 0.4, 1.0}"

    # 对话模型切换：cloud 走阿里云百炼（通义千问）OpenAI 兼容接口；
    # local 走本机 vLLM 的 Qwen2.5-7B-Instruct。调用点统一走 chat_llm_mode / make_chat_llm。
    CHAT_LLM_MODE: str = "cloud"  # cloud | local；兼容值 deepseek 仍可读旧的 DEEPSEEK_* 配置

    CHAT_CLOUD_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    CHAT_CLOUD_MODEL: str = "qwen-plus"
    CHAT_CLOUD_API_KEY: str = ""
    DASHSCOPE_API_KEY: str = ""  # 官方常用名；CHAT_CLOUD_API_KEY 为空时回退用它

    # 本地 vLLM 不要占用 embedding 服务的 8010，也不要和 7B 抢同一张 24GB 卡
    CHAT_LOCAL_BASE_URL: str = "http://127.0.0.1:8001/v1"
    CHAT_LOCAL_MODEL: str = "Qwen/Qwen2.5-7B-Instruct"
    CHAT_LOCAL_API_KEY: str = "dummy"
    CHAT_LOCAL_TIMEOUT_FLOOR: int = 30  # local 模式下，低于此时长的调用会被抬到此值

    # 兼容旧环境变量；仅当 CHAT_LLM_MODE=deepseek 时生效
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    # 钉钉开放平台配置
    DINGTALK_APP_KEY: str = ""
    DINGTALK_APP_SECRET: str = ""
    DINGTALK_AGENT_ID: str = ""
    DINGTALK_CORP_ID: str = ""
    DINGTALK_ROBOT_CODE: str = ""  # 企业内部机器人 RobotCode（单聊消息回复用）
    DINGTALK_API_TOKEN: str = ""  # 直接使用 API Token（跳过 AppKey/AppSecret 换 token）
    DINGTALK_REDIRECT_URI: str = "http://localhost:8000/api/v1/dingtalk/callback"
    DINGTALK_MOCK_MODE: bool = True  # Mock 模式：钉钉 API 不可用时使用模拟数据

    # 阿里云短信服务配置
    SMS_ACCESS_KEY_ID: str = ""
    SMS_ACCESS_KEY_SECRET: str = ""
    SMS_SIGN_NAME: str = ""          # 短信签名（需在阿里云短信控制台申请）
    SMS_TEMPLATE_CODE: str = ""      # 验证码短信模板 CODE（需在阿里云短信控制台申请）
    SMS_NOTICE_TEMPLATE_CODE: str = ""  # 车主状态通知模板，变量 work_order_no、status
    SMS_ENABLED: bool = False        # 是否启用真实短信发送

    # 服务器公开访问地址（用于生成可扫码的真实 URL）
    SERVER_PUBLIC_URL: str = "http://127.0.0.1:8000"

    # JWT 配置。生产（DEBUG=false）拒绝占位密钥，见 assert_production_secrets。
    SECRET_KEY: str = "your-secret-key-change-this-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # 调度接口令牌。不设默认口令；未配置时调度 HTTP 入口拒绝调用。
    SCHEDULER_TOKEN: str = ""
    # 设备外部同步。密钥必填才接受 report/sync；HMAC 密钥可选，配置后还要校验签名。
    DEVICE_SYNC_API_KEY: str = ""
    DEVICE_SYNC_HMAC_SECRET: str = ""
    # 钉钉通讯录同步等内部入口。空则只能用管理员 JWT，不接受匿名。
    DINGTALK_INTERNAL_TOKEN: str = ""
    # 非调试时的浏览器来源，逗号分隔。调试模式仍允许任意来源。
    CORS_ORIGINS: str = ""

    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/app.log"

    # Embedding / Rerank 推理服务配置（OpenAI 兼容，供主链路 HTTP 调用 + RAGFlow 等外部系统调用）
    EMBEDDING_SERVER_URL: str = "http://localhost:8010"   # 推理服务地址（主链路编码/重排走这里）
    EMBEDDING_SERVER_HOST: str = "0.0.0.0"
    EMBEDDING_SERVER_PORT: int = 8010
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-m3"             # 召回模型（1024 维）
    EMBEDDING_MAX_LENGTH: int = 512
    EMBEDDING_LOG_FILE: str = "logs/embedding_server.log"
    RERANKER_MODEL_NAME: str = "BAAI/bge-reranker-v2-m3"  # 精排模型（0~1 分；质量阀门阈值仍按原 Qwen 标定，尚未重标）
    RERANKER_ENABLED: bool = True                          # 模型重排总开关（纯 CPU 延迟敏感时可关）
    RERANKER_CANDIDATES: int = 30                          # 送入重排模型的候选条数

    # 检索链路参数
    RECALL_TOP_K: int = 30        # 各路召回 top-k（向量/BM25），RRF 融合后候选池
    FINAL_TOP_N: int = 10         # 重排后最终送 LLM 的条数
    RETRIEVAL_COARSE_THRESHOLD: float = 0.45   # 粗筛：RRF 融合后向量相似度下限（bge-m3 实测分布标定：无关~0.35、英文日志≥0.495）
    SEMANTIC_RESCUE_THRESHOLD: float = 0.6     # 语义兜底：词法严格过滤为空时，保留向量语义分≥此值的候选（保住英文日志→中文手册的跨语言语义命中）
    RETRIEVAL_VECTOR_THRESHOLD: float = 0.3    # 单路向量检索阈值（quick/knowledge 搜索）
    DEDUP_CANDIDATE_THRESHOLD: float = 0.45    # 去重：向量候选召回阈值
    DEDUP_LLM_THRESHOLD: float = 0.55          # 去重：触发 LLM 判定阈值
    AGENT_QUALITY_HIGH_SCORE: float = 0.6      # 检索 Agent 质量判定："高分"单条线
    AGENT_QUALITY_TARGET_SCORE: float = 0.7    # 检索 Agent 质量判定：最高分达标线
    MAX_VECTOR_CONTENT_LEN: int = 500          # 向量编码文本 content 截断长度（各写入路径统一）
    MAX_MANUAL_VECTOR_TEXT_LEN: int = 1200     # 手册条目向量编码文本截断长度（error_code+title+message_text+description+前3情形信号）

    # 追踪后端选择：ragflow | langfuse | local
    TRACING_BACKEND: str = "ragflow"

    # RAGFlow 追踪配置
    RAGFLOW_HOST: str = "http://localhost:9380"
    RAGFLOW_API_KEY: str = ""
    RAGFLOW_TRACES_DATASET: str = "ticket_traces"
    RAGFLOW_ENABLED: bool = True

    # LangFuse 追踪配置（保留兼容）
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"
    LANGFUSE_ENABLED: bool = False

    # MCP 服务配置
    MCP_API_KEY: str = ""  # MCP 认证密钥（配置后要求 Authorization: Bearer <key>，未配置则仅允许本机 IP）
    MCP_PUBLIC_ENABLED: bool = False  # 第三方只读入口 /mcp/public，生产默认关，需要时显式打开
    MCP_ENABLE_WRITE_TOOLS: bool = False  # 默认不把写工具挂到 HTTP MCP

    def __init__(self, **kwargs):
        """加载环境变量后，补全 DATABASE_URL、REDIS_URL；若公网地址仍是默认的本机 8000，则尝试自动探测实际对外地址。"""
        super().__init__(**kwargs)
        if not self.DATABASE_URL:
            self.DATABASE_URL = f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        if not self.REDIS_URL:
            redis_auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
            self.REDIS_URL = f"redis://{redis_auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        if self.SERVER_PUBLIC_URL == "http://127.0.0.1:8000":
            self.SERVER_PUBLIC_URL = self._detect_public_url()

    def _detect_public_url(self) -> str:
        """自动检测本机局域网 IP，用于生成可扫码的 URL"""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return f"http://{ip}:{self.BACKEND_PORT}"
        except Exception:
            return f"http://127.0.0.1:{self.BACKEND_PORT}"

    @staticmethod
    def _normalize_chat_llm_mode(raw: str) -> str:
        """把 CHAT_LLM_MODE 规范成 cloud / local / deepseek。空值按 cloud；其它值抛出 ValueError。"""
        mode = (raw or "cloud").strip().lower()
        if not mode:
            return "cloud"
        if mode not in {"cloud", "local", "deepseek"}:
            raise ValueError(
                f"CHAT_LLM_MODE 只支持 cloud / local（兼容 deepseek），当前为: {raw!r}"
            )
        return mode

    @property
    def chat_llm_mode(self) -> str:
        """返回规范化后的对话模型模式，供工厂和启动日志使用。"""
        return self._normalize_chat_llm_mode(self.CHAT_LLM_MODE)

    @property
    def chat_llm_base_url(self) -> str:
        """按当前模式返回对话接口根地址：本地走 vLLM，deepseek 走旧兼容配置，默认走云端千问兼容地址。"""
        mode = self.chat_llm_mode
        if mode == "local":
            return (self.CHAT_LOCAL_BASE_URL or "").strip()
        if mode == "deepseek":
            return (self.DEEPSEEK_BASE_URL or "").strip()
        return (self.CHAT_CLOUD_BASE_URL or "").strip()

    @property
    def chat_llm_model(self) -> str:
        """按当前模式返回对话模型名：本地默认 Qwen2.5-7B-Instruct，云端默认 qwen-plus，deepseek 走旧配置。"""
        mode = self.chat_llm_mode
        if mode == "local":
            return (self.CHAT_LOCAL_MODEL or "").strip()
        if mode == "deepseek":
            return (self.DEEPSEEK_MODEL or "").strip()
        return (self.CHAT_CLOUD_MODEL or "").strip()

    @property
    def chat_llm_api_key(self) -> str:
        """按当前模式返回密钥。本地模式若未配则用 dummy（vLLM 通常不校验）；云端优先 CHAT_CLOUD_API_KEY，其次 DASHSCOPE_API_KEY。"""
        mode = self.chat_llm_mode
        if mode == "local":
            return (self.CHAT_LOCAL_API_KEY or "dummy").strip()
        if mode == "deepseek":
            return (self.DEEPSEEK_API_KEY or "").strip()
        return (self.CHAT_CLOUD_API_KEY or self.DASHSCOPE_API_KEY or "").strip()

    @property
    def chat_llm_configured(self) -> bool:
        """判断当前模式是否已具备调用条件：本地看地址和模型名，云端或 deepseek 看是否已配置密钥。"""
        if self.chat_llm_mode == "local":
            return bool(self.chat_llm_base_url and self.chat_llm_model)
        return bool(self.chat_llm_api_key)


settings = Settings()

_DEFAULT_SECRET = "your-secret-key-change-this-in-production"
_KNOWN_SCHEDULER_TOKENS = {"", "sched_token_2026"}


def assert_production_secrets() -> None:
    """DEBUG 关闭时拒绝占位 JWT 密钥和未配置/已公开的调度令牌。本地调试不拦截。"""
    if settings.DEBUG:
        return
    secret = (settings.SECRET_KEY or "").strip()
    if secret == _DEFAULT_SECRET or len(secret) < 24:
        raise RuntimeError("生产环境拒绝默认或过短的 SECRET_KEY，请设置随机密钥后再启动")
    token = (settings.SCHEDULER_TOKEN or "").strip()
    if token in _KNOWN_SCHEDULER_TOKENS:
        raise RuntimeError("生产环境必须设置 SCHEDULER_TOKEN，且不能使用已公开的默认值")