"""配置相关的 Pydantic 模型定义"""

import os
from pathlib import Path
import yaml
from typing import Dict, List, Optional, Union, Any
from pydantic import BaseModel, Field, field_validator, model_validator


class AppConfig(BaseModel):
    """应用配置"""
    VERSION_CHECK_URL: str = Field(..., description="版本检查URL")
    SHOW_VERSION_UPDATE: bool = Field(True, description="是否显示版本更新提示")


class CrawlerConfig(BaseModel):
    """爬虫配置"""
    REQUEST_INTERVAL: int = Field(1000, description="请求间隔(毫秒)", ge=0)
    ENABLE_CRAWLER: bool = Field(True, description="是否启用爬取新闻功能")
    ONLY_CRAWLER: bool = Field(False, description="是否仅执行爬取功能，禁用分析和推送")
    USE_PROXY: bool = Field(False, description="是否启用代理")
    DEFAULT_PROXY: str = Field("", description="默认代理地址")


class ReportConfig(BaseModel):
    """报告配置"""
    REPORT_MODE: str = Field(..., description="报告模式", pattern="^(daily|incremental|current|llm_analysis)$")
    RANK_THRESHOLD: int = Field(5, description="排名高亮阈值", ge=1)
    SORT_BY_POSITION_FIRST: bool = Field(False, description="是否优先按配置位置排序")
    MAX_NEWS_PER_KEYWORD: int = Field(0, description="每个关键词最大显示数量", ge=0)


class TimeRangeConfig(BaseModel):
    """时间范围配置"""
    START: str = Field("08:00", description="开始时间", pattern="^([01]?[0-9]|2[0-3]):[0-5][0-9]$")
    END: str = Field("22:00", description="结束时间", pattern="^([01]?[0-9]|2[0-3]):[0-5][0-9]$")


class PushWindowConfig(BaseModel):
    """推送时间窗口配置"""
    ENABLED: bool = Field(False, description="是否启用推送时间窗口控制")
    TIME_RANGE: TimeRangeConfig = Field(default_factory=TimeRangeConfig, description="时间范围配置")
    ONCE_PER_DAY: bool = Field(True, description="每天在时间窗口内只推送一次")
    RECORD_RETENTION_DAYS: int = Field(7, description="推送记录保留天数", ge=1)


class NotificationConfig(BaseModel):
    """通知配置"""
    ENABLE_NOTIFICATION: bool = Field(True, description="是否启用通知功能")
    MESSAGE_BATCH_SIZE: int = Field(4000, description="消息分批大小（字节）", ge=1)
    DINGTALK_BATCH_SIZE: int = Field(20000, description="钉钉消息分批大小（字节）", ge=1)
    FEISHU_BATCH_SIZE: int = Field(29000, description="飞书消息分批大小（字节）", ge=1)
    BARK_BATCH_SIZE: int = Field(3600, description="Bark消息分批大小（字节）", ge=1)
    BATCH_SEND_INTERVAL: int = Field(3, description="批次发送间隔（秒）", ge=0)
    FEISHU_MESSAGE_SEPARATOR: str = Field("━━━━━━━━━━━━━━━━━━━", description="飞书消息分割线")
    PUSH_WINDOW: PushWindowConfig = Field(default_factory=PushWindowConfig, description="推送时间窗口配置")


class WeightConfig(BaseModel):
    """权重配置"""
    RANK_WEIGHT: float = Field(0.6, description="排名权重", ge=0, le=1)
    FREQUENCY_WEIGHT: float = Field(0.3, description="频次权重", ge=0, le=1)
    HOTNESS_WEIGHT: float = Field(0.1, description="热度权重", ge=0, le=1)

    @model_validator(mode='after')
    def validate_weights_sum(self):
        """验证权重总和为1"""
        total = self.RANK_WEIGHT + self.FREQUENCY_WEIGHT + self.HOTNESS_WEIGHT
        if abs(total - 1.0) > 0.001:  # 允许小的浮点误差
            raise ValueError(f"权重总和必须为1，当前为{total}")
        return self


class PlatformConfig(BaseModel):
    """平台配置"""
    id: str = Field(..., description="平台ID")
    name: str = Field(..., description="平台名称")


class LLMConfig(BaseModel):
    """LLM配置"""
    LLM_KEY: str = Field("", description="LLM API密钥")
    LLM_URL: str = Field("", description="LLM API基础URL")
    LLM_MODEL: str = Field("", description="LLM模型名称")


class WebhookConfig(BaseModel):
    """Webhook配置"""
    FEISHU_WEBHOOK_URL: str = Field("", description="飞书Webhook URL")
    DINGTALK_WEBHOOK_URL: str = Field("", description="钉钉Webhook URL")
    WEWORK_WEBHOOK_URL: str = Field("", description="企业微信Webhook URL")
    WEWORK_MSG_TYPE: str = Field("markdown", description="企业微信消息类型")
    TELEGRAM_BOT_TOKEN: str = Field("", description="Telegram Bot Token")
    TELEGRAM_CHAT_ID: str = Field("", description="Telegram Chat ID")
    EMAIL_FROM: str = Field("", description="发件人邮箱地址")
    EMAIL_PASSWORD: str = Field("", description="发件人邮箱密码或授权码")
    EMAIL_TO: str = Field("", description="收件人邮箱地址")
    EMAIL_SMTP_SERVER: str = Field("", description="SMTP服务器地址")
    EMAIL_SMTP_PORT: str = Field("", description="SMTP端口")
    NTFY_SERVER_URL: str = Field("https://ntfy.sh", description="ntfy服务器地址")
    NTFY_TOPIC: str = Field("", description="ntfy主题名称")
    NTFY_TOKEN: str = Field("", description="ntfy访问令牌")
    BARK_URL: str = Field("", description="Bark推送URL")


class TrendRadarConfig(BaseModel):
    """TrendRadar完整配置模型"""
    # 应用配置
    VERSION_CHECK_URL: str
    SHOW_VERSION_UPDATE: bool

    # 爬虫配置
    REQUEST_INTERVAL: int
    ENABLE_CRAWLER: bool
    ONLY_CRAWLER: bool
    USE_PROXY: bool
    DEFAULT_PROXY: str

    # 报告配置
    REPORT_MODE: str
    RANK_THRESHOLD: int
    SORT_BY_POSITION_FIRST: bool
    MAX_NEWS_PER_KEYWORD: int

    # 通知配置
    ENABLE_NOTIFICATION: bool
    MESSAGE_BATCH_SIZE: int
    DINGTALK_BATCH_SIZE: int
    FEISHU_BATCH_SIZE: int
    BARK_BATCH_SIZE: int
    BATCH_SEND_INTERVAL: int
    FEISHU_MESSAGE_SEPARATOR: str
    PUSH_WINDOW: Dict[str, Union[bool, Dict[str, str], int]]

    # 权重配置
    WEIGHT_CONFIG: Dict[str, float]

    # 平台配置
    PLATFORMS: List[Dict[str, str]]

    # LLM配置
    LLM_KEY: str
    LLM_URL: str
    LLM_MODEL: str

    # Webhook配置
    FEISHU_WEBHOOK_URL: str
    DINGTALK_WEBHOOK_URL: str
    WEWORK_WEBHOOK_URL: str
    WEWORK_MSG_TYPE: str
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str
    EMAIL_FROM: str
    EMAIL_PASSWORD: str
    EMAIL_TO: str
    EMAIL_SMTP_SERVER: str
    EMAIL_SMTP_PORT: str
    NTFY_SERVER_URL: str
    NTFY_TOPIC: str
    NTFY_TOKEN: str
    BARK_URL: str

    @field_validator('REPORT_MODE')
    @classmethod
    def validate_report_mode(cls, v):
        """验证报告模式"""
        valid_modes = {"daily", "incremental", "current", "llm_analysis"}
        if v not in valid_modes:
            raise ValueError(f"REPORT_MODE必须是以下值之一: {valid_modes}")
        return v

    @field_validator('PLATFORMS')
    @classmethod
    def validate_platforms(cls, v):
        """验证平台配置"""
        if not v:
            raise ValueError("PLATFORMS不能为空")
        for platform in v:
            if not isinstance(platform, dict):
                raise ValueError("每个平台配置必须是字典类型")
            if 'id' not in platform or 'name' not in platform:
                raise ValueError("每个平台配置必须包含'id'和'name'字段")
        return v

    model_config = {
        "extra": "forbid",  # 禁止额外字段
        "validate_assignment": True,  # 赋值时验证
        "use_enum_values": True,  # 使用枚举值
    }

    def __getitem__(self, key: str) -> Any:
        """支持字典式访问: CONFIG["FIELD_NAME"]"""
        if hasattr(self, key):
            return getattr(self, key)
        else:
            raise KeyError(f"配置字段 '{key}' 不存在")

    def __setitem__(self, key: str, value: Any) -> None:
        """支持字典式设置: CONFIG["FIELD_NAME"] = value"""
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            raise KeyError(f"配置字段 '{key}' 不存在")

    def __contains__(self, key: str) -> bool:
        """支持 in 操作符: "FIELD_NAME" in CONFIG"""
        return hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        """支持 get 方法: CONFIG.get("FIELD_NAME", default_value)"""
        if hasattr(self, key):
            return getattr(self, key)
        else:
            return default

    def keys(self):
        """支持 keys() 方法: CONFIG.keys()"""
        return self.model_fields.keys()

    def values(self):
        """支持 values() 方法: CONFIG.values()"""
        return [getattr(self, key) for key in self.model_fields.keys()]

    def items(self):
        """支持 items() 方法: CONFIG.items()"""
        return [(key, getattr(self, key)) for key in self.model_fields.keys()]