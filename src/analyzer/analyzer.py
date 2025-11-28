from pathlib import Path
import webbrowser
import os
from .llm import LLMAnalyzer
from crawler.fetcher import DataFetcher
from crawler.process import read_all_today_titles, load_frequency_words, detect_latest_new_titles, save_titles_to_file
from push.sender import generate_html_report, send_to_notifications
from utils import CONFIG, VERSION, check_version_update, get_beijing_time, ensure_directory_exists
from utils.config import MODE_STRATEGIES_CONFIG
from utils.statistics import count_word_frequency
from typing import Dict, List, Tuple, Optional

# === 主分析器 ===
class NewsAnalyzer:
    """新闻分析器"""

    # 模式策略定义
    MODE_STRATEGIES = MODE_STRATEGIES_CONFIG

    def __init__(self):
        self.request_interval = CONFIG.REQUEST_INTERVAL
        self.report_mode = CONFIG.REPORT_MODE
        self.rank_threshold = CONFIG.RANK_THRESHOLD
        self.is_github_actions = os.environ.get("GITHUB_ACTIONS") == "true"
        self.is_docker_container = self._detect_docker_environment()
        self.update_info = None
        self.proxy_url: str | None = None
        self._setup_proxy()
        self.data_fetcher = DataFetcher(self.proxy_url)
        self.llm_analyzer = LLMAnalyzer() if CONFIG.LLM_KEY else None

        # 缓存 save_titles_to_file 的结果
        self._cached_title_file: Optional[str] = None

        if self.is_github_actions:
            self._check_version_update()

    def _detect_docker_environment(self) -> bool:
        """检测是否运行在 Docker 容器中"""
        try:
            if os.environ.get("DOCKER_CONTAINER") == "true":
                return True

            if os.path.exists("/.dockerenv"):
                return True

            return False
        except Exception:
            return False

    def _should_open_browser(self) -> bool:
        """判断是否应该打开浏览器"""
        return not self.is_github_actions and not self.is_docker_container

    def _setup_proxy(self) -> None:
        """设置代理配置"""
        if not self.is_github_actions and CONFIG.USE_PROXY:
            self.proxy_url = CONFIG.DEFAULT_PROXY
            print("本地环境，使用代理")
        elif not self.is_github_actions and not CONFIG.USE_PROXY:
            print("本地环境，未启用代理")
        else:
            print("GitHub Actions环境，不使用代理")

    def _check_version_update(self) -> None:
        """检查版本更新"""
        try:
            need_update, remote_version = check_version_update(
                VERSION, CONFIG.VERSION_CHECK_URL, self.proxy_url
            )

            if need_update and remote_version:
                self.update_info = {
                    "current_version": VERSION,
                    "remote_version": remote_version,
                }
                print(f"发现新版本: {remote_version} (当前: {VERSION})")
            else:
                print("版本检查完成，当前为最新版本")
        except Exception as e:
            print(f"版本检查出错: {e}")

    def _get_mode_strategy(self) -> Dict:
        """获取当前模式的策略配置"""
        return self.MODE_STRATEGIES.get(self.report_mode, self.MODE_STRATEGIES["daily"])

    def _has_notification_configured(self) -> bool:
        """检查是否配置了任何通知渠道"""
        return any(
            [
                CONFIG["FEISHU_WEBHOOK_URL"],
                CONFIG["DINGTALK_WEBHOOK_URL"],
                CONFIG["WEWORK_WEBHOOK_URL"],
                (CONFIG["TELEGRAM_BOT_TOKEN"] and CONFIG["TELEGRAM_CHAT_ID"]),
                (
                    CONFIG["EMAIL_FROM"]
                    and CONFIG["EMAIL_PASSWORD"]
                    and CONFIG["EMAIL_TO"]
                ),
                (CONFIG["NTFY_SERVER_URL"] and CONFIG["NTFY_TOPIC"]),
                CONFIG["BARK_URL"],
            ]
        )

    def _has_valid_content(
        self, stats: List[Dict], new_titles: Optional[Dict] = None
    ) -> bool:
        """检查是否有有效的新闻内容"""
        if self.report_mode in ["incremental", "current"]:
            # 增量模式和current模式下，只要stats有内容就说明有匹配的新闻
            return any(stat["count"] > 0 for stat in stats)
        else:
            # 当日汇总模式下，检查是否有匹配的频率词新闻或新增新闻
            has_matched_news = any(stat["count"] > 0 for stat in stats)
            has_new_news = bool(
                new_titles and any(len(titles) > 0 for titles in new_titles.values())
            )
            return has_matched_news or has_new_news

    def _load_analysis_data(
        self,
    ) -> Optional[Tuple[Dict, Dict, Dict, Dict, List, List]]:
        """统一的数据加载和预处理，使用当前监控平台列表过滤历史数据"""
        try:
            # 获取当前配置的监控平台ID列表
            current_platform_ids = []
            for platform in CONFIG["PLATFORMS"]:
                current_platform_ids.append(platform["id"])

            print(f"当前监控平台: {current_platform_ids}")

            all_results, id_to_name, title_info = read_all_today_titles(
                current_platform_ids
            )

            if not all_results:
                print("没有找到当天的数据")
                return None

            total_titles = sum(len(titles) for titles in all_results.values())
            print(f"读取到 {total_titles} 个标题（已按当前监控平台过滤）")

            new_titles = detect_latest_new_titles(current_platform_ids)
            word_groups, filter_words = load_frequency_words()

            return (
                all_results,
                id_to_name,
                title_info,
                new_titles,
                word_groups,
                filter_words,
            )
        except Exception as e:
            print(f"数据加载失败: {e}")
            return None

    def _prepare_current_title_info(self, results: Dict, time_info: str) -> Dict:
        """从当前抓取结果构建标题信息"""
        title_info = {}
        for source_id, titles_data in results.items():
            title_info[source_id] = {}
            for title, title_data in titles_data.items():
                ranks = title_data.get("ranks", [])
                url = title_data.get("url", "")
                mobile_url = title_data.get("mobileUrl", "")

                title_info[source_id][title] = {
                    "first_time": time_info,
                    "last_time": time_info,
                    "count": 1,
                    "ranks": ranks,
                    "url": url,
                    "mobileUrl": mobile_url,
                }
        return title_info

    def _run_analysis_pipeline(
        self,
        data_source: Dict,
        mode: str,
        title_info: Dict,
        new_titles: Dict,
        word_groups: List[Dict],
        filter_words: List[str],
        id_to_name: Dict,
        failed_ids: Optional[List] = None,
        is_daily_summary: bool = False,
    ) -> Tuple[List[Dict], str]:
        """统一的分析流水线：数据处理 → 统计计算 → HTML生成"""

        if self.llm_analyzer and mode == "llm_analysis":
            result = self.llm_analyzer.news_analyze(data_source)
            if result is not None:
                return result

        # 统计计算
        stats, total_titles = count_word_frequency(
            data_source,
            word_groups,
            filter_words,
            id_to_name,
            title_info,
            self.rank_threshold,
            new_titles,
            mode=mode,
        )

        # HTML生成
        html_file = generate_html_report(
            stats,
            total_titles,
            failed_ids=failed_ids,
            new_titles=new_titles,
            id_to_name=id_to_name,
            mode=mode,
            is_daily_summary=is_daily_summary,
            update_info=self.update_info if CONFIG["SHOW_VERSION_UPDATE"] else None,
        )

        return stats, html_file

    def _send_notification_if_needed(
        self,
        stats: List[Dict],
        report_type: str,
        mode: str,
        failed_ids: Optional[List] = None,
        new_titles: Optional[Dict] = None,
        id_to_name: Optional[Dict] = None,
        html_file_path: Optional[str] = None,
    ) -> bool:
        """统一的通知发送逻辑，包含所有判断条件"""
        has_notification = self._has_notification_configured()

        if (
            CONFIG["ENABLE_NOTIFICATION"]
            and has_notification
            and self._has_valid_content(stats, new_titles)
        ):
            send_to_notifications(
                stats,
                failed_ids or [],
                report_type,
                new_titles,
                id_to_name,
                self.update_info,
                self.proxy_url,
                mode=mode,
                html_file_path=html_file_path,
            )
            return True
        elif CONFIG["ENABLE_NOTIFICATION"] and not has_notification:
            print("⚠️ 警告：通知功能已启用但未配置任何通知渠道，将跳过通知发送")
        elif not CONFIG["ENABLE_NOTIFICATION"]:
            print(f"跳过{report_type}通知：通知功能已禁用")
        elif (
            CONFIG["ENABLE_NOTIFICATION"]
            and has_notification
            and not self._has_valid_content(stats, new_titles)
        ):
            mode_strategy = self._get_mode_strategy()
            if "实时" in report_type:
                print(
                    f"跳过实时推送通知：{mode_strategy['mode_name']}下未检测到匹配的新闻"
                )
            else:
                print(
                    f"跳过{mode_strategy['summary_report_type']}通知：未匹配到有效的新闻内容"
                )

        return False

    def _generate_summary_report(self, mode_strategy: Dict) -> Optional[str]:
        """生成汇总报告（带通知）"""
        summary_type = (
            "当前榜单汇总" if mode_strategy["summary_mode"] == "current" else "当日汇总"
        )
        print(f"生成{summary_type}报告...")

        # 加载分析数据
        analysis_data = self._load_analysis_data()
        if not analysis_data:
            return None

        all_results, id_to_name, title_info, new_titles, word_groups, filter_words = (
            analysis_data
        )

        # 运行分析流水线
        stats, html_file = self._run_analysis_pipeline(
            all_results,
            mode_strategy["summary_mode"],
            title_info,
            new_titles,
            word_groups,
            filter_words,
            id_to_name,
            is_daily_summary=True,
        )

        print(f"{summary_type}报告已生成: {html_file}")

        # 发送通知
        self._send_notification_if_needed(
            stats,
            mode_strategy["summary_report_type"],
            mode_strategy["summary_mode"],
            failed_ids=[],
            new_titles=new_titles,
            id_to_name=id_to_name,
            html_file_path=html_file,
        )

        return html_file

    def _generate_summary_html(self, mode: str = "daily") -> Optional[str]:
        """生成汇总HTML"""
        summary_type = "当前榜单汇总" if mode == "current" else "当日汇总"
        print(f"生成{summary_type}HTML...")

        # 加载分析数据
        analysis_data = self._load_analysis_data()
        if not analysis_data:
            return None

        all_results, id_to_name, title_info, new_titles, word_groups, filter_words = (
            analysis_data
        )

        # 运行分析流水线
        _, html_file = self._run_analysis_pipeline(
            all_results,
            mode,
            title_info,
            new_titles,
            word_groups,
            filter_words,
            id_to_name,
            is_daily_summary=True,
        )

        print(f"{summary_type}HTML已生成: {html_file}")
        return html_file

    def _initialize_and_check_config(self) -> None:
        """通用初始化和配置检查"""
        now = get_beijing_time()
        print(f"当前北京时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")

        if not CONFIG["ENABLE_CRAWLER"]:
            print("爬虫功能已禁用（ENABLE_CRAWLER=False），将使用历史数据生成分析报告")
        elif CONFIG["ONLY_CRAWLER"]:
            print("仅爬取模式已启用（ONLY_CRAWLER=True），将只执行数据爬取，跳过分析和推送")

        has_notification = self._has_notification_configured()
        if not CONFIG["ENABLE_NOTIFICATION"]:
            print("通知功能已禁用（ENABLE_NOTIFICATION=False），将只进行数据抓取")
        elif not has_notification:
            print("未配置任何通知渠道，将只进行数据抓取，不发送通知")
        else:
            print("通知功能已启用，将发送通知")

        mode_strategy = self._get_mode_strategy()
        print(f"报告模式: {self.report_mode}")
        print(f"运行模式: {mode_strategy['description']}")

    def _crawl_data(self) -> Tuple[Dict, Dict, List]:
        """执行数据爬取"""
        ids = []
        for platform in CONFIG["PLATFORMS"]:
            if "name" in platform:
                ids.append((platform["id"], platform["name"]))
            else:
                ids.append(platform["id"])

        print(
            f"配置的监控平台: {[p.get('name', p['id']) for p in CONFIG['PLATFORMS']]}"
        )
        print(f"开始爬取数据，请求间隔 {self.request_interval} 毫秒")
        ensure_directory_exists("output")

        results, id_to_name, failed_ids = self.data_fetcher.crawl_websites(
            ids, self.request_interval
        )

        # 缓存 save_titles_to_file 的结果
        self._cached_title_file = save_titles_to_file(results, id_to_name, failed_ids)
        print(f"标题已保存到: {self._cached_title_file}")

        return results, id_to_name, failed_ids


    # === 新的方法结构：数据准备 ===
    def _prepare_analysis_data(self, results: Dict, id_to_name: Dict, failed_ids: List) -> Dict:
        """准备分析所需的基础数据"""
        current_platform_ids = [platform["id"] for platform in CONFIG["PLATFORMS"]]
        new_titles = detect_latest_new_titles(current_platform_ids)
        time_info = Path(self._cached_title_file).stem
        word_groups, filter_words = load_frequency_words()

        return {
            "current_platform_ids": current_platform_ids,
            "new_titles": new_titles,
            "time_info": time_info,
            "word_groups": word_groups,
            "filter_words": filter_words,
            "results": results,
            "id_to_name": id_to_name,
            "failed_ids": failed_ids
        }

    def _load_current_and_historical_data(self, analysis_data: Dict) -> Dict:
        """加载当前和历史数据"""
        # 当前数据的标题信息
        current_title_info = self._prepare_current_title_info(
            analysis_data["results"],
            analysis_data["time_info"]
        )

        # 历史数据（用于current模式）
        historical_data = self._load_analysis_data()

        return {
            "current_title_info": current_title_info,
            "historical_data": historical_data
        }

    def _prepare_analysis_data_from_history(self) -> Dict:
        """从历史数据准备分析所需的基础数据（用于ENABLE_CRAWLER=false的情况）"""
        current_platform_ids = [platform["id"] for platform in CONFIG["PLATFORMS"]]
        new_titles = detect_latest_new_titles(current_platform_ids)
        word_groups, filter_words = load_frequency_words()

        # 加载历史数据作为"当前"数据
        historical_data = self._load_analysis_data()
        if not historical_data:
            raise RuntimeError("无法加载历史数据进行分析")

        all_results, id_to_name, title_info, historical_new_titles, _, _ = historical_data

        return {
            "current_platform_ids": current_platform_ids,
            "new_titles": new_titles,
            "time_info": "history",  # 标记为历史数据
            "word_groups": word_groups,
            "filter_words": filter_words,
            "results": all_results,  # 使用历史数据作为results
            "id_to_name": id_to_name,
            "failed_ids": []  # 历史数据没有失败的ID
        }

    # === 新的方法结构：分析方法（按模式拆分） ===
    def _analyze_current_mode(self, analysis_data: Dict, data_bundle: Dict) -> Tuple[List[Dict], str]:
        """current模式分析：使用完整历史数据"""
        historical_data = data_bundle["historical_data"]
        if not historical_data:
            raise RuntimeError("current模式需要历史数据，但无法加载历史数据")

        all_results, historical_id_to_name, historical_title_info, historical_new_titles, _, _ = historical_data

        print(f"current模式：使用过滤后的历史数据，包含平台：{list(all_results.keys())}")

        stats, html_file = self._run_analysis_pipeline(
            all_results,
            self.report_mode,
            historical_title_info,
            historical_new_titles,
            analysis_data["word_groups"],
            analysis_data["filter_words"],
            historical_id_to_name,
            failed_ids=analysis_data["failed_ids"],
        )

        return stats, html_file

    def _analyze_incremental_mode(self, analysis_data: Dict, data_bundle: Dict) -> Tuple[List[Dict], str]:
        """incremental模式分析：使用当前数据"""
        stats, html_file = self._run_analysis_pipeline(
            analysis_data["results"],
            self.report_mode,
            data_bundle["current_title_info"],
            analysis_data["new_titles"],
            analysis_data["word_groups"],
            analysis_data["filter_words"],
            analysis_data["id_to_name"],
            failed_ids=analysis_data["failed_ids"],
        )

        return stats, html_file

    def _analyze_daily_mode(self, analysis_data: Dict, data_bundle: Dict) -> Tuple[List[Dict], str]:
        """daily模式分析：使用当前数据"""
        stats, html_file = self._run_analysis_pipeline(
            analysis_data["results"],
            self.report_mode,
            data_bundle["current_title_info"],
            analysis_data["new_titles"],
            analysis_data["word_groups"],
            analysis_data["filter_words"],
            analysis_data["id_to_name"],
            failed_ids=analysis_data["failed_ids"],
        )

        return stats, html_file

    def _analyze_llm_mode(self, analysis_data: Dict, data_bundle: Dict) -> Tuple[List[Dict], str]:
        """llm_analysis模式分析：使用当前数据"""
        stats, html_file = self._run_analysis_pipeline(
            analysis_data["results"],
            self.report_mode,
            data_bundle["current_title_info"],
            analysis_data["new_titles"],
            analysis_data["word_groups"],
            analysis_data["filter_words"],
            analysis_data["id_to_name"],
            failed_ids=analysis_data["failed_ids"],
        )

        return stats, html_file

    # === 新的方法结构：推送方法 ===
    def _send_realtime_notification(self, stats: List[Dict], analysis_data: Dict, data_bundle: Dict,
                                   html_file: str, mode_strategy: Dict) -> None:
        """发送实时通知"""
        if not mode_strategy["should_send_realtime"]:
            return

        # 根据模式选择合适的数据
        if self.report_mode == "current":
            historical_data = data_bundle["historical_data"]
            if historical_data:
                _, historical_id_to_name, _, historical_new_titles, _, _ = historical_data
                combined_id_to_name = {**historical_id_to_name, **analysis_data["id_to_name"]}

                self._send_notification_if_needed(
                    stats,
                    mode_strategy["realtime_report_type"],
                    self.report_mode,
                    failed_ids=analysis_data["failed_ids"],
                    new_titles=historical_new_titles,
                    id_to_name=combined_id_to_name,
                    html_file_path=html_file,
                )
        else:
            self._send_notification_if_needed(
                stats,
                mode_strategy["realtime_report_type"],
                self.report_mode,
                failed_ids=analysis_data["failed_ids"],
                new_titles=analysis_data["new_titles"],
                id_to_name=analysis_data["id_to_name"],
                html_file_path=html_file,
            )

    def _generate_and_send_summary(self, mode_strategy: Dict, should_send_realtime: bool) -> Optional[str]:
        """生成汇总报告并发送通知"""
        if not mode_strategy["should_generate_summary"]:
            return None

        if should_send_realtime:
            # 如果已经发送了实时通知，汇总只生成HTML不发送通知
            return self._generate_summary_html(mode_strategy["summary_mode"])
        else:
            # daily模式等：直接生成汇总报告并发送通知
            return self._generate_summary_report(mode_strategy)

    def _open_report_in_browser(self, html_file: str, summary_html: Optional[str]) -> None:
        """在浏览器中打开报告"""
        if not self._should_open_browser() or not html_file:
            if self.is_docker_container and html_file:
                if summary_html:
                    print(f"汇总报告已生成（Docker环境）: {summary_html}")
                else:
                    print(f"HTML报告已生成（Docker环境）: {html_file}")
            return

        if summary_html:
            summary_url = "file://" + str(Path(summary_html).resolve())
            print(f"正在打开汇总报告: {summary_url}")
            webbrowser.open(summary_url)
        else:
            file_url = "file://" + str(Path(html_file).resolve())
            print(f"正在打开HTML报告: {file_url}")
            webbrowser.open(file_url)

    def run(self) -> None:
        """执行分析流程"""
        try:
            # 1. 初始化和配置读取
            self._initialize_and_check_config()
            mode_strategy = self._get_mode_strategy()

            # 2. 数据准备：根据是否启用爬虫选择数据源
            if CONFIG["ENABLE_CRAWLER"]:
                # 启用爬虫：爬取数据并输出到 output 目录
                results, id_to_name, failed_ids = self._crawl_data()

                # 检查是否仅执行爬取功能
                if CONFIG["ONLY_CRAWLER"]:
                    return

                # 准备分析所需的数据
                analysis_data = self._prepare_analysis_data(results, id_to_name, failed_ids)
            else:
                # 禁用爬虫：使用历史数据
                analysis_data = self._prepare_analysis_data_from_history()

            # 3. 读取当前和历史数据
            data_bundle = self._load_current_and_historical_data(analysis_data)

            # 4. 根据当前的模式策略，分别执行不同的分析逻辑
            if self.report_mode == "current":
                stats, html_file = self._analyze_current_mode(analysis_data, data_bundle)
            elif self.report_mode == "incremental":
                stats, html_file = self._analyze_incremental_mode(analysis_data, data_bundle)
            elif self.report_mode == "daily":
                stats, html_file = self._analyze_daily_mode(analysis_data, data_bundle)
            elif self.report_mode == "llm_analysis":
                stats, html_file = self._analyze_llm_mode(analysis_data, data_bundle)
            else:
                # 默认使用daily模式
                stats, html_file = self._analyze_daily_mode(analysis_data, data_bundle)

            print(f"HTML报告已生成: {html_file}")

            # 5. 根据推送配置，推送最新的分析报告
            # 发送实时通知
            self._send_realtime_notification(stats, analysis_data, data_bundle, html_file, mode_strategy)

            # 生成汇总报告并发送通知
            summary_html = self._generate_and_send_summary(mode_strategy, mode_strategy["should_send_realtime"])

            # 在浏览器中打开报告
            self._open_report_in_browser(html_file, summary_html)

        except Exception as e:
            print(f"分析流程执行出错: {e}")
            raise
