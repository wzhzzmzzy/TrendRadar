"""LLM 分析相关的 Pydantic 模型定义"""

from pydantic import BaseModel, Field
from typing import List, Union


class NewsTitle(BaseModel):
    """新闻标题模型"""
    rank: Union[int, List[int]]  # 支持单个排名或排名列表
    source: str


class NewsGroup(BaseModel):
    """新闻分组模型"""
    rank: int = Field(description="按照当前分组的新闻数量和热榜位置给出排名")
    keywords: List[str] = Field(description="当前分组的新闻关键词，格式为字符串数组")
    news_title: List[NewsTitle] = Field(description="当前分组的所有新闻标题")