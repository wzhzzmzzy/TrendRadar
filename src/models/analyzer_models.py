"""分析器相关的数据模型定义"""

from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class AnalysisData(BaseModel):
    """分析所需的完整数据集合"""

    # 基础配置数据
    current_platform_ids: List[str] = Field(..., description="当前监控的平台ID列表")
    time_info: str = Field(..., description="时间信息标识")
    title_file: Optional[str] = Field(None, description="保存标题的文件路径")

    # 爬取数据
    results: Dict = Field(default_factory=dict, description="当前爬取的结果数据")
    id_to_name: Dict[str, str] = Field(default_factory=dict, description="ID到名称的映射")
    failed_ids: List[str] = Field(default_factory=list, description="失败的ID列表")

    # 历史数据
    all_results: Dict = Field(default_factory=dict, description="所有历史结果数据")
    title_info: Dict = Field(default_factory=dict, description="标题详细信息")
    historical_id_to_name: Dict[str, str] = Field(default_factory=dict, description="历史ID到名称的映射")

    # 新增和配置数据
    new_titles: Dict = Field(default_factory=dict, description="新增标题数据")
    word_groups: List[Dict] = Field(default_factory=list, description="词组配置")
    filter_words: List[str] = Field(default_factory=list, description="过滤词列表")

    # 当前数据的标题信息
    current_title_info: Dict = Field(default_factory=dict, description="当前数据的标题信息")

    model_config = {
        "arbitrary_types_allowed": True,
        "extra": "forbid"
    }


class ModeStrategy(BaseModel):
    """模式策略配置"""

    mode_name: str = Field(..., description="模式名称")
    description: str = Field(..., description="模式描述")
    realtime_report_type: str = Field(..., description="实时报告类型")
    summary_report_type: str = Field(..., description="汇总报告类型")
    should_send_realtime: bool = Field(..., description="是否发送实时通知")
    should_generate_summary: bool = Field(..., description="是否生成汇总报告")
    summary_mode: str = Field(..., description="汇总模式")