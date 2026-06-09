"""
UCloud GEO Web - Pydantic 数据模型
"""
from pydantic import BaseModel
from typing import Optional, List, Dict, Any


# ============ 评测 ============

class EvaluationCreate(BaseModel):
    name: str = "GEO评估"
    model_keys: List[str] = ["deepseek", "ernie", "doubao", "kimi", "qwen"]
    question_ids: Optional[List[str]] = None  # None=全部
    categories: Optional[List[str]] = None    # 按品类筛选
    temperature: float = 0.7
    delay: float = 1.0
    mode: str = "api"  # "api" 或 "webchat"
    enable_search: bool = False  # 是否启用联网搜索


class EvaluationResponse(BaseModel):
    id: str
    name: str
    status: str
    model_keys: str
    total_questions: int
    completed_questions: int
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class ResultImport(BaseModel):
    """导入单条评测结果"""
    question_id: str
    model_key: str
    model_name: str
    ucloud_mentioned: bool = False
    ucloud_mention_count: int = 0
    ucloud_rank: Optional[int] = None
    has_citation: bool = False
    citation_count: int = 0
    ucloud_recommended: bool = False
    recommendation_strength: str = "none"
    sentiment_score: float = 0.5
    sentiment_label: str = "neutral"
    position_weight: float = 0.0
    response_length: int = 0
    raw_content: str = ""
    competitor_mentions: str = "{}"
    error_message: Optional[str] = None
    citations: str = "[]"
    all_cited_urls: str = "[]"


class ResultsBatchImport(BaseModel):
    """批量导入评测结果"""
    name: str = "GEO评估"
    model_key: str
    mode: str = "webchat"
    results: List[ResultImport]


# ============ 问题 ============

class QuestionCreate(BaseModel):
    id: str
    category: str
    question_type: str
    question: str
    tags: List[str] = []
    difficulty: str = "medium"


class QuestionUpdate(BaseModel):
    category: Optional[str] = None
    question_type: Optional[str] = None
    question: Optional[str] = None
    tags: Optional[List[str]] = None
    difficulty: Optional[str] = None


class QuestionImport(BaseModel):
    questions: List[QuestionCreate]


# ============ 设置 ============

class ModelConfigUpdate(BaseModel):
    api_key: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None


class KeywordsUpdate(BaseModel):
    primary: List[str]
    products: List[str]
    flagship: List[str]
    aliases: List[str]


class WeightsUpdate(BaseModel):
    coverage_rate: float = 0.45
    mention_rate: float = 0.0
    citation_rate: float = 0.25
    recommendation_rate: float = 0.20
    sentiment_score: float = 0.10


# ============ 本地结果导入 ============

class LocalResultsImport(BaseModel):
    run_name: str = "本地WebChat导入"
    model_keys: List[str] = []


# ============ 通用 ============

class ApiResponse(BaseModel):
    success: bool = True
    data: Any = None
    message: str = ""
