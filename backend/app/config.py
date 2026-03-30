"""
配置管理
统一从项目根目录的 .env 文件加载配置
"""

import os
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
# 路径: MiroFish/.env (相对于 backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # 如果根目录没有 .env，尝试加载环境变量（用于生产环境）
    load_dotenv(override=True)


class Config:
    """Flask配置类"""

    # Flask配置
    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'

    # JSON配置 - 禁用ASCII转义，让中文直接显示（而不是 \uXXXX 格式）
    JSON_AS_ASCII = False

    # LLM配置（统一使用OpenAI格式）
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')
    LOCAL_LLM_REQUEST_TIMEOUT_SECONDS = float(os.environ.get('LOCAL_LLM_REQUEST_TIMEOUT_SECONDS', '900'))
    LOCAL_LLM_MAX_RETRIES = int(os.environ.get('LOCAL_LLM_MAX_RETRIES', '1'))
    LOCAL_LLM_MAX_TOKENS = int(os.environ.get('LOCAL_LLM_MAX_TOKENS', '192'))
    LOCAL_LLM_TEMPERATURE = float(os.environ.get('LOCAL_LLM_TEMPERATURE', '0.2'))

    # 图谱后端配置
    GRAPH_BACKEND = os.environ.get('GRAPH_BACKEND', 'auto').lower().strip()

    # Zep配置（可选，GRAPH_BACKEND=zep 或 auto+key 时启用）
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')

    # 本地图谱存储路径
    LOCAL_GRAPH_STORE_PATH = os.path.join(os.path.dirname(__file__), '../uploads/graphs')
    LOCAL_GRAPH_EXTRACTION_MODE = os.environ.get('LOCAL_GRAPH_EXTRACTION_MODE', 'fast').lower().strip()
    LOCAL_SIMULATION_PROFILE = os.environ.get('LOCAL_SIMULATION_PROFILE', 'lean').lower().strip()
    LOCAL_SIM_MAX_AGENTS = int(os.environ.get('LOCAL_SIM_MAX_AGENTS', '48'))
    LOCAL_SIM_INITIAL_POST_LIMIT = int(os.environ.get('LOCAL_SIM_INITIAL_POST_LIMIT', '2'))
    LOCAL_SIM_AGENTS_PER_HOUR_MIN = int(os.environ.get('LOCAL_SIM_AGENTS_PER_HOUR_MIN', '3'))
    LOCAL_SIM_AGENTS_PER_HOUR_MAX = int(os.environ.get('LOCAL_SIM_AGENTS_PER_HOUR_MAX', '8'))

    # 文件上传配置
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}

    # 文本处理配置
    DEFAULT_CHUNK_SIZE = 500  # 默认切块大小
    DEFAULT_CHUNK_OVERLAP = 50  # 默认重叠大小

    # OASIS模拟配置
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')

    # OASIS平台可用动作配置
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]

    # Report Agent配置
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))

    @classmethod
    def resolved_graph_backend(cls) -> str:
        backend = (cls.GRAPH_BACKEND or 'auto').lower().strip()
        if backend in ['', 'auto']:
            return 'zep' if cls.ZEP_API_KEY else 'local'
        return backend

    @classmethod
    def is_local_llm(cls) -> bool:
        base_url = (cls.LLM_BASE_URL or '').strip().lower()
        if not base_url:
            return False
        return any(
            marker in base_url
            for marker in (
                '127.0.0.1',
                'localhost',
                '0.0.0.0',
                'ollama',
            )
        )

    @classmethod
    def validate(cls):
        """验证必要配置"""
        errors = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY 未配置")
        if cls.resolved_graph_backend() == 'zep' and not cls.ZEP_API_KEY:
            errors.append("ZEP_API_KEY 未配置")
        return errors
