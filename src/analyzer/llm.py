from pydantic import BaseModel, Field
from typing import List, Union, Optional, Dict, Tuple
from openai import OpenAI
from utils import CONFIG
from utils.formatter import format_time_display
from json_repair import repair_json
from pathlib import Path
from push.sender import generate_html_report
from crawler.process import read_all_today_titles
import os
import re
import json


# === 大模型分析 ===
# LLM 分析结果的数据模型
class NewsTitle(BaseModel):
    rank: Union[int, List[int]]  # 支持单个排名或排名列表
    source: str


class NewsGroup(BaseModel):
    rank: int = Field(description="按照当前分组的新闻数量和热榜位置给出排名")
    keywords: List[str] = Field(description="当前分组的新闻关键词，格式为字符串数组")
    news_title: List[NewsTitle] = Field(description="当前分组的所有新闻标题")


class LLMAnalyzer:
    client: OpenAI
    system_prompt: str

    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=CONFIG["LLM_KEY"],
            base_url=CONFIG["LLM_URL"],
        )
        self.system_prompt = self._load_llm_system_prompt()

    def _load_llm_system_prompt(self) -> str:
        """加载大模型系统提示词"""
        prompt_file = os.environ.get(
            "LLM_SYSTEM_PROMPT_PATH", "config/llm_system_prompt.md"
        )

        prompt_path = Path(prompt_file)
        if not prompt_path.exists():
            raise FileNotFoundError(f"大模型系统提示词文件 {prompt_file} 不存在")

        with open(prompt_path, "r", encoding="utf-8") as f:
            content = f.read().strip()

        print(f"大模型系统提示词加载成功: {prompt_file}")
        return content

    def _extract_and_validate_json(
        self, llm_response: str
    ) -> Optional[List[NewsGroup]]:
        """从 LLM 响应中提取 JSON 并进行类型验证"""
        try:
            # 使用正则表达式提取 JSON 内容
            json_pattern = r"```json\s*\n(.*?)\n\s*```"
            matches = re.findall(json_pattern, llm_response, re.DOTALL)

            if not matches:
                # 如果没有找到代码块，尝试直接解析整个响应
                json_content = llm_response.strip()
            else:
                json_content = matches[0].strip()

            # 解析 JSON
            try:
                data = json.loads(json_content)
            except json.JSONDecodeError as e:
                print(f"JSON 解析失败: {e}")
                print(f"原始内容: {json_content}")

                # 尝试使用 json-repair 修复
                if repair_json is not None:
                    print("尝试使用 json-repair 修复 JSON...")
                    try:
                        repaired_json = repair_json(json_content)
                        print(f"修复后的 JSON: {repaired_json}")
                        data = json.loads(repaired_json)
                        print("JSON 修复成功")
                    except Exception as repair_error:
                        print(f"JSON 修复失败: {repair_error}")
                        return None
                else:
                    print("json-repair 库不可用，无法修复 JSON")
                    return None

            # 使用 Pydantic 进行类型验证
            try:
                news_groups = [NewsGroup(**group) for group in data]
                print(f"LLM JSON 验证成功，共 {len(news_groups)} 个新闻分组")
                return news_groups
            except Exception as e:
                print(f"Pydantic 类型验证失败: {e}")
                print(f"解析的数据: {data}")
                return None

        except Exception as e:
            print(f"提取 JSON 时发生错误: {e}")
            return None

    def _prepare_news_title(self, news_title: List[Dict[str, str | List[str]]]) -> str:
        """将新闻数据转换为大模型可读的 Markdown 格式文本"""
        if not news_title:
            return ""

        content = "> 以下是新闻来源及相应的热榜内容和热榜排名\n\n"

        for source_data in news_title:
            platform_name = source_data.get("platform", "未知来源")
            articles = source_data.get("articles", [])

            if not articles:
                continue

            content += f"## {platform_name}\n\n"

            for idx, article in enumerate(articles, 1):
                content += f"{idx}. {article}\n"

            content += "\n"

        return content.rstrip()

    def _convert_llm_groups_to_stats(
        self, validated_groups: List[NewsGroup], deduplicated_data_source: Dict, title_info: Dict
    ) -> List[Dict]:
        """将LLM分析结果转换为stats数据格式"""
        stats = []
        total_titles = sum(len(group.news_title) for group in validated_groups)

        for group in validated_groups:
            # 构建关键词字符串
            keywords_str = " ".join(group.keywords)

            # 构建titles数据
            titles = []
            for news_title in group.news_title:
                # 获取rank值（如果是列表取第一个）
                rank_value = (
                    news_title.rank[0]
                    if isinstance(news_title.rank, list)
                    else news_title.rank
                )

                # 从title_info中查找对应的新闻详细信息（使用去重后的数据）
                news_detail = self._find_news_detail_from_title_info(
                    rank_value, news_title.source, deduplicated_data_source, title_info
                )

                first_time = news_detail.get("first_time", "")
                last_time = news_detail.get("last_time", "")

                # 根据rank查找原始标题
                original_title = self._find_original_title_by_rank(
                    rank_value, news_title.source, deduplicated_data_source
                )

                title_data = {
                    "title": original_title,
                    "source_name": news_title.source,
                    "first_time": first_time,
                    "last_time": last_time,
                    "time_display": format_time_display(
                        news_detail.get("first_time", ""),
                        news_detail.get("last_time", ""),
                    ),
                    "count": news_detail.get("count", 1),
                    "ranks": news_title.rank
                    if isinstance(news_title.rank, list)
                    else [news_title.rank],
                    "rank_threshold": CONFIG["RANK_THRESHOLD"],
                    "url": news_detail.get("url", ""),
                    "mobile_url": news_detail.get("mobile_url", ""),
                    "is_new": news_detail.get("is_new", False),
                }
                titles.append(title_data)

            # 计算百分比
            percentage = (
                round(len(group.news_title) / total_titles * 100, 2)
                if total_titles > 0
                else 0
            )

            stats.append(
                {
                    "word": keywords_str,
                    "count": len(group.news_title),
                    "percentage": percentage,
                    "titles": titles,
                }
            )

        return stats

    def _find_news_detail_from_title_info(self, rank: int, source: str, deduplicated_data_source: Dict, title_info: Dict) -> Dict:
        """从title_info中根据rank和source查找新闻的详细信息（使用去重后的数据）"""
        # 根据source查找对应的platform_id
        platform_id = None
        for platform in CONFIG["PLATFORMS"]:
            if platform.get("name") == source or platform["id"] == source:
                platform_id = platform["id"]
                break

        if not platform_id or platform_id not in deduplicated_data_source:
            return {}

        # 在去重后的数据中根据rank查找对应的新闻
        for stored_title, title_data in deduplicated_data_source[platform_id].items():
            ranks = title_data.get("ranks", [])
            if rank in ranks:
                # 从title_info中获取完整的统计信息
                if (platform_id in title_info and
                    stored_title in title_info[platform_id]):
                    info = title_info[platform_id][stored_title]
                    return {
                        "first_time": info.get("first_time", ""),
                        "last_time": info.get("last_time", ""),
                        "count": info.get("count", len(ranks)),
                        "url": info.get("url", title_data.get("url", "")),
                        "mobile_url": info.get("mobileUrl", title_data.get("mobileUrl", "")),
                        "is_new": False,
                    }
                else:
                    return {
                        "first_time": "",
                        "last_time": "",
                        "count": len(ranks),
                        "url": title_data.get("url", ""),
                        "mobile_url": title_data.get("mobileUrl", ""),
                        "is_new": False,
                    }

        return {}

    def _find_news_detail(self, rank: int, source: str, data_source: Dict) -> Dict:
        """从data_source中根据rank查找新闻的详细信息"""
        # 根据source查找对应的platform_id
        platform_id = None
        for platform in CONFIG["PLATFORMS"]:
            if platform.get("name") == source or platform["id"] == source:
                platform_id = platform["id"]
                break

        if not platform_id or platform_id not in data_source:
            return {}

        # 在该平台的数据中根据rank查找对应的新闻
        for stored_title, title_data in data_source[platform_id].items():
            ranks = title_data.get("ranks", [])
            if rank in ranks:
                return {
                    "first_time": "",
                    "last_time": "",
                    "count": title_data.get("count", len(ranks)),
                    "url": title_data.get("url", ""),
                    "mobile_url": title_data.get("mobileUrl", ""),
                    "is_new": False,
                }

        return {}

    def _find_original_title_by_rank(
        self, rank: int, source: str, data_source: Dict
    ) -> str:
        """从data_source中根据rank查找原始新闻标题"""
        # 根据source查找对应的platform_id
        platform_id = None
        for platform in CONFIG["PLATFORMS"]:
            if platform.get("name") == source or platform["id"] == source:
                platform_id = platform["id"]
                break

        if not platform_id or platform_id not in data_source:
            return ""

        # 在该平台的数据中根据rank查找对应的原始标题
        for stored_title, title_data in data_source[platform_id].items():
            ranks = title_data.get("ranks", [])
            if rank in ranks:
                return stored_title

        return ""

    def _generate_llm_html_report(
        self, stats: List[Dict], validated_groups: List[NewsGroup], data_source: Dict
    ) -> str:
        """生成基于LLM分析结果的HTML报告"""
        total_titles = sum(len(group.news_title) for group in validated_groups)

        # 构建report_data
        report_data = {
            "stats": stats,
            "new_titles": [],  # LLM分析模式下暂不处理新增新闻
            "failed_ids": [],
            "total_new_count": 0,
        }

        # 生成HTML文件
        html_file = generate_html_report(
            stats=stats,
            total_titles=total_titles,
            failed_ids=[],
            new_titles=None,
            id_to_name=self._build_id_to_name_mapping(data_source),
            mode="llm_analysis",
            is_daily_summary=False,
            update_info=None,
        )

        return html_file

    def _build_id_to_name_mapping(self, data_source: Dict) -> Dict:
        """构建platform_id到name的映射"""
        id_to_name = {}
        for platform in CONFIG["PLATFORMS"]:
            platform_id = platform["id"]
            platform_name = platform.get("name", platform_id)
            id_to_name[platform_id] = platform_name
        return id_to_name

    def _deduplicate_data_source(self, data_source: Dict) -> Tuple[Dict, Dict]:
        """对 data_source 进行去重处理，参考 process_source_data 逻辑"""
        deduplicated_results = {}
        title_info = {}

        for source_id, titles_data in data_source.items():
            deduplicated_results[source_id] = {}
            title_info[source_id] = {}

            for title, data in titles_data.items():
                ranks = data.get("ranks", [])
                url = data.get("url", "")
                mobile_url = data.get("mobileUrl", "")

                # 如果标题不存在，直接添加
                if title not in deduplicated_results[source_id]:
                    deduplicated_results[source_id][title] = {
                        "ranks": ranks,
                        "url": url,
                        "mobileUrl": mobile_url,
                    }
                    title_info[source_id][title] = {
                        "first_time": "",
                        "last_time": "",
                        "count": len(ranks) if ranks else 1,
                        "ranks": ranks,
                        "url": url,
                        "mobileUrl": mobile_url,
                    }
                else:
                    # 如果标题已存在，合并信息
                    existing_data = deduplicated_results[source_id][title]
                    existing_ranks = existing_data.get("ranks", [])
                    existing_url = existing_data.get("url", "")
                    existing_mobile_url = existing_data.get("mobileUrl", "")

                    # 合并排名
                    merged_ranks = existing_ranks.copy()
                    for rank in ranks:
                        if rank not in merged_ranks:
                            merged_ranks.append(rank)

                    # 更新去重结果
                    deduplicated_results[source_id][title] = {
                        "ranks": merged_ranks,
                        "url": existing_url or url,
                        "mobileUrl": existing_mobile_url or mobile_url,
                    }

                    # 更新统计信息
                    title_info[source_id][title]["ranks"] = merged_ranks
                    title_info[source_id][title]["count"] += len(ranks) if ranks else 1
                    if not title_info[source_id][title].get("url"):
                        title_info[source_id][title]["url"] = url
                    if not title_info[source_id][title].get("mobileUrl"):
                        title_info[source_id][title]["mobileUrl"] = mobile_url

        return deduplicated_results, title_info

    def news_analyze(self, data_source: Dict):
        # 获取当前监控平台ID列表
        current_platform_ids = [platform["id"] for platform in CONFIG["PLATFORMS"]]

        # 读取完整的历史数据（类似 daily 模式）
        all_results, id_to_name, title_info = read_all_today_titles(current_platform_ids)

        if not all_results:
            print("没有找到当天的历史数据，使用当前批次数据")
            # 如果没有历史数据，回退到原有逻辑
            deduplicated_data_source, title_info = self._deduplicate_data_source(data_source)
            original_count = sum(len(titles) for titles in data_source.values())
            deduplicated_count = sum(len(titles) for titles in deduplicated_data_source.values())
        else:
            print(f"读取到历史数据，平台：{list(all_results.keys())}")
            # 使用历史数据作为基础
            deduplicated_data_source = all_results
            original_count = sum(len(titles) for titles in data_source.values())
            deduplicated_count = sum(len(titles) for titles in deduplicated_data_source.values())

        print(f"LLM处理：当前批次 {original_count} 条，历史数据 {deduplicated_count} 条")

        # 准备LLM分析的新闻标题（使用去重后的数据）
        news_titles: List[Dict[str, str | List[str]]] = []
        for platform, articles in deduplicated_data_source.items():
            platform_name = next(
                (
                    p.get("name", p["id"])
                    for p in CONFIG["PLATFORMS"]
                    if p["id"] == platform
                ),
                platform,
            )
            news_titles.append(
                {
                    "platform": platform_name,
                    "articles": list(articles.keys()),
                }
            )

        print(f"LLM 分析中，模型：{CONFIG['LLM_MODEL']}")
        response = self.client.chat.completions.create(
            model=CONFIG["LLM_MODEL"],
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self._prepare_news_title(news_titles)},
            ],
            stream=False,
        )

        llm_summary = response.choices[0].message.content
        print("LLM 分析完成")

        if llm_summary is None:
            print("LLM 返回的结果为空")
            return None
        # 提取并验证 JSON 格式
        validated_groups = self._extract_and_validate_json(llm_summary)
        if validated_groups is None:
            print("LLM 分析结果格式验证失败，跳过此步骤")
            return None
        else:
            print(f"LLM 分析结果验证成功，共 {len(validated_groups)} 个新闻分组")

        # 将LLM分析结果转换为stats数据（使用完整的历史数据）
        stats = self._convert_llm_groups_to_stats(validated_groups, deduplicated_data_source, title_info)

        # 生成HTML文件
        html_file = self._generate_llm_html_report(stats, validated_groups, deduplicated_data_source)

        return stats, html_file
