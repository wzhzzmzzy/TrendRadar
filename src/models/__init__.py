"""类型定义模块"""

from .config_models import (
    AppConfig,
    CrawlerConfig,
    ReportConfig,
    TimeRangeConfig,
    PushWindowConfig,
    NotificationConfig,
    WeightConfig,
    PlatformConfig,
    LLMConfig,
    WebhookConfig,
    TrendRadarConfig,
)

from .llm_models import (
    NewsTitle,
    NewsGroup,
)

from .analyzer_models import (
    AnalysisData,
    ModeStrategy,
)

__all__ = [
    # 配置相关模型
    "AppConfig",
    "CrawlerConfig",
    "ReportConfig",
    "TimeRangeConfig",
    "PushWindowConfig",
    "NotificationConfig",
    "WeightConfig",
    "PlatformConfig",
    "LLMConfig",
    "WebhookConfig",
    "TrendRadarConfig",
    # LLM 分析相关模型
    "NewsTitle",
    "NewsGroup",
    # 分析器相关模型
    "AnalysisData",
    "ModeStrategy",
]