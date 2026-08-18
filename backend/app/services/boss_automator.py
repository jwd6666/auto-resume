"""BOSS 直聘自动化：登录引导 + 列表抓取 + 自动打招呼。

设计要点：
- 每个任务一个 user_data_dir（持久化登录态）；账号互不污染。
- 启动后停在登录页让用户手动登录；检测到登录成功（出现头像/userInfo）后切换到搜索页。
- 循环：抓岗位卡片 → 过滤黑名单 → 检查"已沟通"或本地已记录 → 点"立即沟通"→ 在弹窗发送招呼语 → 关闭弹窗 → 等下一轮。
- 反检测：使用持久化 context（非 incognito）+ 真实 user-agent + 关闭 webdriver flag。
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, List, Optional
from urllib.parse import urlencode

# 使用 patchright（playwright 的反检测增强分支）替代原生 playwright
# patchright 修补了 navigator.webdriver、CDP 信号、cdc_ runtime、Closed Shadow Roots 等检测点
from patchright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PWTimeoutError,
    async_playwright,
)

from ..core.config import BOSS_HOME, BOSS_SEARCH_URL, DEFAULT_CLICK_DELAY_SECONDS, PROFILES_DIR
from ..core.logger import TaskLogger
from ..schemas.task import AIConfig, JobFilter, SubTask
from . import storage
from .ai_greeting import generate_greeting

LogPusher = Callable[[dict], Awaitable[None]]
StatusPusher = Callable[[str, dict], Awaitable[None]]

# patchright 官方文档推荐：不要传 user_agent / viewport，使用真实浏览器默认值
# 也不要加 --disable-blink-features=AutomationControlled 等 args，会反向暴露


def _profile_dir(task_id: str) -> Path:
    p = PROFILES_DIR / task_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _login_marker(task_id: str) -> Path:
    """登录成功标记文件：用于前端判断该任务是否已登录过。"""
    return PROFILES_DIR / task_id / ".login_ok"


def has_login_session(task_id: str) -> bool:
    """该任务是否已经成功登录过（cookie 已保存）。"""
    return _login_marker(task_id).exists()


def clear_login_session(task_id: str) -> None:
    """清登录态（删 marker）。"""
    try:
        _login_marker(task_id).unlink(missing_ok=True)
    except Exception:
        pass


def clear_profile(task_id: str) -> None:
    """清整个浏览器 profile（cookie 等也一并清掉）。任务删除时调用。"""
    import shutil
    p = PROFILES_DIR / task_id
    if p.exists():
        try:
            shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass


# BOSS 直聘城市名 → 编码映射（兼容前端可能传中文的旧任务）
_CITY_NAME_CODES = {
    "全国": "100010000",
    # 一线 / 新一线
    "北京": "101010100", "上海": "101020100", "广州": "101280100", "深圳": "101280600",
    "杭州": "101210100", "天津": "101030100", "武汉": "101200100", "成都": "101270100",
    "西安": "101110100", "苏州": "101190400", "南京": "101190100", "重庆": "101040100",
    "长沙": "101250100", "郑州": "101180100", "合肥": "101220100", "济南": "101120100",
    "青岛": "101120200", "沈阳": "101070100", "大连": "101070200", "哈尔滨": "101050100",
    "长春": "101060100", "昆明": "101290100", "贵阳": "101260100", "南宁": "101300100",
    "福州": "101230100", "厦门": "101230200", "石家庄": "101090100", "太原": "101100100",
    "南昌": "101240100", "海口": "101310100", "兰州": "101160100", "银川": "101170100",
    "呼和浩特": "101080100", "乌鲁木齐": "101130100", "拉萨": "101140100", "西宁": "101150100",
    # 广东
    "东莞": "101281600", "佛山": "101280800", "珠海": "101280700", "中山": "101281700",
    "惠州": "101280300", "江门": "101281100", "肇庆": "101280900", "湛江": "101281000",
    "汕头": "101280500", "茂名": "101282000", "揭阳": "101281900", "潮州": "101281500",
    "清远": "101281300", "阳江": "101281800", "韶关": "101280200", "河源": "101281200",
    "梅州": "101280400", "汕尾": "101282100", "云浮": "101281400",
    # 广西
    "桂林": "101300500", "柳州": "101300300", "北海": "101301300", "玉林": "101300900",
    "梧州": "101300600", "钦州": "101301100", "贵港": "101300800", "百色": "101301000",
    "防城港": "101301400", "河池": "101301200", "来宾": "101300400", "贺州": "101300700",
    "崇左": "101300200",
    # 其他 GDP 较高城市
    "宁波": "101210400", "温州": "101210700", "无锡": "101190200", "南通": "101190600",
    "常州": "101191100", "绍兴": "101210500", "嘉兴": "101210300", "烟台": "101120500",
    "潍坊": "101120600", "泉州": "101230500", "洛阳": "101180900", "徐州": "101190300",
    "唐山": "101090500", "芜湖": "101220300", "株洲": "101250300", "保定": "101090200",
}


def _normalize_city(city: Optional[str]) -> str:
    """城市标准化：空 / 中文名 → 编码。已经是编码就原样返回。"""
    if not city: return "100010000"
    s = city.strip()
    if s.isdigit(): return s
    return _CITY_NAME_CODES.get(s, "100010000")


def _build_search_url(f: JobFilter) -> str:
    """根据筛选构造 BOSS 搜索 URL。BOSS city 参数必传，缺失/不识别默认全国。"""
    params: dict = {"query": f.keyword, "city": _normalize_city(f.city)}
    if f.salary: params["salary"] = f.salary
    if f.experience: params["experience"] = f.experience
    if f.degree: params["degree"] = f.degree
    if f.scale: params["scale"] = f.scale
    return f"{BOSS_SEARCH_URL}?{urlencode(params)}"


def _job_key(href: str) -> str:
    """提取岗位唯一 key（jobId+lid 或 url 截断）。"""
    if not href: return ""
    return href.split("?")[0].rstrip("/")


def _matches_blacklist(text: str, blacklist: List[str]) -> bool:
    text = (text or "").lower()
    return any(kw.lower() in text for kw in blacklist if kw.strip())


class BossAutomator:
    """单个 BOSS 任务执行体。一次实例服务一个 task_id。"""

    def __init__(
        self,
        task_id: str,
        name: str,
        sub_tasks: List[SubTask],
        greetings: List[str],
        interval_seconds: int,
        daily_limit: int,
        logger: TaskLogger,
        on_log: LogPusher,
        on_status: StatusPusher,
        click_delay_seconds: int = DEFAULT_CLICK_DELAY_SECONDS,
        ai_config: Optional[AIConfig] = None,
    ) -> None:
        if not sub_tasks:
            raise ValueError("sub_tasks 至少需要 1 条")
        self.task_id = task_id
        self.name = name
        self.sub_tasks = sub_tasks
        # 当前正在执行的子任务索引；_loop_greet 会顺序推进
        self._sub_index = 0
        # 老字段保留，方便日志/状态推送时取首个 filter 当兜底
        self.filter = sub_tasks[0].filter
        self.greetings = greetings
        self.interval = interval_seconds
        self.daily_limit = daily_limit
        self.click_delay_seconds = max(0, click_delay_seconds)
        self.logger = logger
        self.on_log = on_log
        self.on_status = on_status
        self.ai_config = ai_config

        self._pw: Optional[Playwright] = None
        self._ctx: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._stop_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # set = 不暂停

        # BOSS 服务端硬上限标记：弹出「无法进行沟通 / 明天再来」时由 _dismiss_after_send 置 True，
        # _loop_greet 下个循环检测到就立即结束整个任务（不再继续后续子任务）
        self._daily_limit_hit = False

    # ---------------- 外部控制 ----------------
    def request_stop(self) -> None: self._stop_event.set(); self._pause_event.set()
    def request_pause(self) -> None: self._pause_event.clear()
    def request_resume(self) -> None: self._pause_event.set()

    # ---------------- 主流程 ----------------
    async def run(self) -> None:
        """完整流程：登录（若未登录）→ 进搜索页 → 打招呼循环。"""
        try:
            await self._push_status("launching", {"msg": "启动浏览器..."})
            await self._launch()

            if not await self._is_logged_in():
                await self._push_status("awaiting_login", {"msg": "请在浏览器中完成登录"})
                await self._wait_for_login()

            self._mark_login_success()
            await self._push_status("running", {"msg": "登录成功，进入岗位列表"})
            await self._navigate_search()

            await self._loop_greet()
        except asyncio.CancelledError:
            await self._log("WARN", "任务被取消")
            raise
        except Exception as e:
            await self._log("ERROR", f"任务异常：{e}")
            await self._push_status("error", {"msg": str(e)})
        finally:
            await self._cleanup()

    async def run_login_only(self) -> None:
        """仅登录：打开浏览器 → 等用户登录 → 关闭浏览器（profile 保存 cookie）。"""
        try:
            await self._push_status("launching", {"msg": "启动浏览器..."})
            await self._launch()

            if await self._is_logged_in():
                await self._log("INFO", "检测到已登录态，无需重复登录")
            else:
                await self._push_status("awaiting_login", {"msg": "请在浏览器中完成登录"})
                await self._wait_for_login()
                await self._log("SUCCESS", "登录成功，账号信息已保存")

            self._mark_login_success()
            await self._push_status("logged_in", {"msg": "登录完成，可以开始打招呼"})
        except asyncio.CancelledError:
            await self._log("WARN", "登录被取消")
            raise
        except Exception as e:
            await self._log("ERROR", f"登录异常：{e}")
            await self._push_status("error", {"msg": str(e)})
        finally:
            await self._cleanup()

    # ---------------- 浏览器启动 ----------------
    async def _launch(self) -> None:
        """patchright 官方推荐配置：用真实 Chrome、user_data_dir 持久化、no_viewport，
        不要传 args/user_agent/viewport 等可被识别为自动化指纹的字段。"""
        await self._log("INFO", "正在启动 Chrome 浏览器...")
        self._pw = await async_playwright().start()
        self._ctx = await self._pw.chromium.launch_persistent_context(
            user_data_dir=str(_profile_dir(self.task_id)),
            channel="chrome",  # 使用本机已安装的 Chrome 浏览器
            headless=False,
            no_viewport=True,    # 用真实窗口分辨率，不固定 viewport
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
        await self._log("INFO", "浏览器已启动，正在打开 BOSS 直聘首页...")
        try:
            await self._page.goto(BOSS_HOME, wait_until="domcontentloaded", timeout=30_000)
        except Exception as e:
            await self._log("WARN", f"首页加载较慢（{e}），继续等待...")
        try:
            await self._page.bring_to_front()
        except Exception:
            pass
        await self._log("INFO", "BOSS 页面已打开")

    def _mark_login_success(self) -> None:
        """登录成功后落 marker，前端用此判断该账号是否可直接开始。"""
        try:
            _login_marker(self.task_id).touch(exist_ok=True)
        except Exception:
            pass

    async def _is_logged_in(self) -> bool:
        """快速探测：当前页面是否已是登录态。"""
        page = self._page
        if not page: return False
        try:
            el = await page.query_selector(".user-nav .figure, .nav-figure, [ka='header-username']")
            return el is not None
        except Exception:
            return False

    async def _wait_for_login(self, timeout_seconds: int = 600) -> None:
        """轮询是否登录成功。最长等 10 分钟。"""
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        await self._log("INFO", "请扫码或输入账密登录 BOSS 直聘...")
        while asyncio.get_event_loop().time() < deadline:
            if self._stop_event.is_set(): raise asyncio.CancelledError()
            if await self._is_logged_in(): return
            await asyncio.sleep(2)
        raise TimeoutError("登录超时（10 分钟）")

    # ---------------- 列表抓取与打招呼 ----------------
    async def _navigate_search(self) -> None:
        url = _build_search_url(self.filter)
        await self._log("INFO", f"跳转到搜索页：{url}")
        await self._page.goto(url, wait_until="domcontentloaded")
        await self._page.wait_for_timeout(2000)

    async def _loop_greet(self) -> None:
        """主循环：依次执行每个子任务。

        - 每个子任务有独立 limit（今日目标次数）
        - 全局 daily_limit 为兜底总上限：合计触达即整体结束
        - 子任务跑到 limit 或当前搜索条件无可招呼项时跳到下一个
        """
        total_sent = storage.count_greeted_today(self.task_id)
        await self._push_status("running", {"sent_today": total_sent})

        for sub_index, sub in enumerate(self.sub_tasks):
            if self._stop_event.is_set(): return
            if self._daily_limit_hit:
                await self._log("ERROR", "BOSS 服务端已限制今日沟通，停止后续子任务")
                await self._push_status("finished", {"sent_today": total_sent, "reason": "boss_daily_limit"})
                return
            self._sub_index = sub_index
            self.filter = sub.filter  # 让 _navigate_search/_build_search_url 用当前子任务条件

            sub_sent = storage.count_greeted_today(self.task_id, sub_index=sub_index)
            await self._log(
                "INFO",
                f"=== 开始子任务 {sub_index + 1}/{len(self.sub_tasks)}：{sub.filter.keyword} "
                f"(目标 {sub.limit}，今日已 {sub_sent}) ==="
            )
            await self._navigate_search()

            empty_rounds = 0  # 连续空页计数：达到阈值则放弃当前子任务
            all_skipped_rounds = 0  # 连续全部跳过的轮数：达到阈值说明无新岗位

            while not self._stop_event.is_set():
                await self._pause_event.wait()

                # BOSS 服务端硬上限：发完弹窗里出现「明天再来」时由 _dismiss_after_send 置位
                if self._daily_limit_hit:
                    await self._log("ERROR", "BOSS 已达每日沟通上限（150 次封顶），任务终止，明日再试")
                    await self._push_status("finished", {"sent_today": total_sent, "reason": "boss_daily_limit"})
                    return

                if total_sent >= self.daily_limit:
                    await self._log("SUCCESS", f"今日总上限 {self.daily_limit} 已达，任务整体结束")
                    await self._push_status("finished", {"sent_today": total_sent})
                    return
                if sub_sent >= sub.limit:
                    await self._log("SUCCESS", f"子任务 {sub_index + 1} 已达 {sub.limit} 次，进入下一个")
                    break

                cards = await self._collect_cards()
                if not cards:
                    empty_rounds += 1
                    await self._log("WARN", f"本页未发现岗位（{empty_rounds}/3），尝试翻页")
                    if empty_rounds >= 3:
                        await self._log("WARN", f"子任务 {sub_index + 1} 连续 3 轮无岗位，跳过")
                        break
                    if not await self._goto_next_page():
                        await self._navigate_search()
                    continue
                empty_rounds = 0

                sent_this_round = 0
                for card in cards:
                    if self._stop_event.is_set(): return
                    await self._pause_event.wait()
                    if self._daily_limit_hit:
                        break  # 由外层 while 顶部统一记日志 + 推送状态
                    if sub_sent >= sub.limit or total_sent >= self.daily_limit:
                        break
                    ok = await self._try_greet_card(card)
                    if ok:
                        sent_this_round += 1
                        sub_sent += 1
                        total_sent += 1
                        await self._push_status("running", {
                            "sent_today": total_sent,
                            "sub_index": sub_index,
                            "sub_sent": sub_sent,
                            "last_msg": card.get("title"),
                        })
                        await self._sleep_with_jitter(self.interval)

                # 本轮有成功招呼 → 重置跳过计数，正常翻页
                if sent_this_round > 0:
                    all_skipped_rounds = 0
                    if not await self._goto_next_page():
                        await self._log("INFO", "已到末页，回到第一页继续")
                        await self._navigate_search()
                else:
                    # 本轮全部跳过 → 尝试滚动列表加载更多
                    all_skipped_rounds += 1
                    if all_skipped_rounds >= 5:
                        await self._log("WARN", f"连续 {all_skipped_rounds} 轮全部跳过，无新岗位，子任务结束")
                        break
                    await self._log("INFO", f"本轮全部跳过，滚动加载更多岗位（第 {all_skipped_rounds} 次）")
                    await self._scroll_list_for_more()

        await self._log("SUCCESS", "所有子任务完成")
        await self._push_status("finished", {"sent_today": total_sent})

    async def _collect_cards(self) -> List[dict]:
        """抓取列表页所有岗位卡片的关键信息。

        BOSS 列表 DOM 结构（截至 2025/2026）：
          .recommend-result-job > .job-list-container > [li | .job-card-wrap | div]
        策略：先找列表容器，再在容器内扫所有候选；类名兜底多套，避免 BOSS 改一次 class 就失效。
        """
        page = self._page
        assert page

        # 等任意一种候选容器/卡片出现即可
        wait_selectors = (
            ".job-list-container, .recommend-job-list, .job-list-box, "
            "li.job-card-wrapper, .job-card-wrap, .job-card-box, [class*='job-card']"
        )
        try:
            await page.wait_for_selector(wait_selectors, timeout=15000)
        except PWTimeoutError:
            return []

        # 让懒加载/虚拟滚动尽可能渲染（短滚一下回到顶部）
        try:
            await page.evaluate(
                "() => { window.scrollTo(0, 600); return new Promise(r => setTimeout(r, 400)); }"
            )
            await page.evaluate("() => window.scrollTo(0, 0)")
        except Exception:
            pass

        cards = await page.evaluate(
            """
            () => {
              const containerSel = ['.job-list-container', '.recommend-job-list', '.job-list-box'];
              let container = null;
              for (const s of containerSel) {
                const c = document.querySelector(s);
                if (c) { container = c; break; }
              }
              const root = container || document;
              // 从容器里挑所有可能的卡片节点（按出现频率排）
              const cardSel = [
                'li.job-card-wrapper', '.job-card-wrap', '.job-card-box',
                'li[class*="job-card"]', 'div[class*="job-card-wrap"]',
                'li.job-card', '.recommend-job-card'
              ];
              let items = [];
              for (const s of cardSel) {
                const found = root.querySelectorAll(s);
                if (found.length) { items = Array.from(found); break; }
              }
              // 仍然空：兜底取 a[href*="/job_detail/"] 的最近列表项
              if (!items.length) {
                items = Array.from(root.querySelectorAll('a[href*="/job_detail/"]'))
                  .map(a => a.closest('li, [class*="job-card"]') || a.parentElement)
                  .filter(Boolean);
              }
              // BOSS 用自定义 web font 把薪资数字映射到 PUA 区（U+E000-U+F8FF），
              // innerText 取出来是乱码方框；克隆节点后剥掉薪资/标签子节点，再清掉残留 PUA 字符
              const PUA = /[\uE000-\uF8FF]/g;
              const clean = (s) => (s || '').replace(PUA, '').replace(/\s+/g, ' ').trim();
              const pickClean = (el, sel) => {
                const node = el.querySelector(sel);
                if (!node) return '';
                const c = node.cloneNode(true);
                c.querySelectorAll(
                  '.salary, [class*="salary"], .job-info, [class*="job-info"], '
                  + '.tag-list, [class*="tag-list"], .job-limit'
                ).forEach(n => n.remove());
                return clean(c.innerText || c.textContent || '');
              };
              return items.map((el, i) => {
                const link = el.querySelector('a[href*="/job_detail/"], a.job-card-left');
                const title = pickClean(el, '.job-name, .job-title, [class*="job-name"]');
                const company = pickClean(el, '.company-name, [class*="company-name"], [class*="company"] a');
                const tags = Array.from(el.querySelectorAll('.tag-list li, .job-info .tag, .tag-list span, [class*="tag-list"] *'))
                  .map(t => clean(t.innerText)).filter(Boolean).join(' ');
                const href = link?.getAttribute('href') || '';
                const greeted = !!el.querySelector('.start-chat-btn.greet-disable, [class*="greeted"], [class*="greet-disable"]');
                return { idx: i, title, company, tags, href, greeted };
              }).filter(c => c.title || c.href);
            }
            """
        )
        cards = cards or []
        await self._log("INFO", f"列表抓到 {len(cards)} 个岗位")
        return cards

    async def _try_greet_card(self, card: dict) -> bool:
        """对单个岗位走完整流程：过滤判断 → 点左侧 → 右侧立即沟通 → 发招呼语。"""
        title = card.get("title") or ""
        company = card.get("company") or ""
        href = card.get("href") or ""
        key = _job_key(href)

        if not key:
            return False

        if card.get("greeted"):
            await self._log("INFO", f"[跳过-已沟通] {title} @ {company}")
            return False

        if storage.has_greeted_today(self.task_id, key):
            await self._log("INFO", f"[跳过-本地已记录] {title} @ {company}")
            return False

        # AI 缓存：今日已被 AI 判断过且不匹配的岗位，直接跳过，不点击卡片浪费等待
        if self.ai_config and self.ai_config.enabled and self.ai_config.api_key:
            if storage.has_ai_judged_today(self.task_id, key):
                await self._log("INFO", f"[AI-跳过] 今日已判断过，不重复调用：{title} @ {company}")
                return False

        text_blob = f"{title} {company} {card.get('tags','')}"
        if _matches_blacklist(text_blob, self.filter.exclude_keywords):
            await self._log("INFO", f"[跳过-黑名单] {title} @ {company}")
            return False

        ok = await self._open_detail_and_greet(card)
        if ok:
            storage.mark_greeted(
                self.task_id, key, title, company,
                datetime.now().isoformat(timespec="seconds"),
                sub_index=self._sub_index,
            )
            await self._log("SUCCESS", f"[已招呼] {title} @ {company}")
        return ok

    async def _open_detail_and_greet(self, card: dict) -> bool:
        """点左侧岗位卡片 → 等 N 秒 → 右侧详情页点「立即沟通」→ 弹窗发送 → 关闭弹窗。"""
        page = self._page
        assert page
        title = card.get("title", "")
        href = card.get("href", "")

        # 1. 用 href 重新定位左侧卡片并点击（比 idx 抗 DOM 变动）
        try:
            await self._log("INFO", f"[查看详情] {title}")
            clicked = await page.evaluate(
                """(href) => {
                  if (!href) return false;
                  const link = document.querySelector(`a[href="${href}"]`)
                            || Array.from(document.querySelectorAll('a[href*="/job_detail/"]'))
                                 .find(a => a.getAttribute('href') === href);
                  if (!link) return false;
                  const card = link.closest('li, [class*="job-card"], .job-card-wrap') || link;
                  card.scrollIntoView({block: 'center'});
                  link.click();
                  return true;
                }""",
                href,
            )
            if not clicked:
                await self._log("WARN", f"未在 DOM 中找到岗位链接：{href}")
                return False
        except Exception as e:
            await self._log("WARN", f"点击卡片失败：{e}")
            return False

        # 2. 等右侧详情加载（默认 5 秒，模拟真人浏览，可配置）
        await asyncio.sleep(self.click_delay_seconds)
        if self._stop_event.is_set(): return False

        # 2.5 如果启用了 AI，抓取 JD 文本并生成招呼语
        ai_greeting: Optional[str] = None
        if self.ai_config and self.ai_config.enabled and self.ai_config.api_key:
            jd_text = await self._extract_jd_text(page)
            if jd_text:
                try:
                    keyword = self.filter.keyword or ""
                    await self._log("INFO", f"[AI] 正在根据 JD 判断匹配并生成招呼语...")
                    should_greet, greeting = await generate_greeting(self.ai_config, jd_text, keyword, self.ai_config.resume, self.ai_config.expect_jd)
                    # 无论匹配与否，都记录 AI 判断结果，避免同岗位今日重复调用
                    job_key = _job_key(card.get("href", ""))
                    if job_key:
                        storage.mark_ai_judged(self.task_id, job_key, should_greet)
                    if not should_greet:
                        await self._log("INFO", f"[AI-跳过] JD 与求职意向不匹配：{title}")
                        return False
                    ai_greeting = greeting
                    await self._log("INFO", f"[AI] 生成招呼语：{ai_greeting[:50]}...")
                except Exception as e:
                    await self._log("WARN", f"[AI] 生成招呼语失败，回退到默认：{e}")
            else:
                await self._log("WARN", "[AI] 未能抓取到 JD 文本，回退到默认招呼语")

        # 3. 严格按文本「立即沟通」定位按钮（避免误点 继续沟通 / 已投递 等）
        # 在 BOSS 详情区域里扫所有候选 op-btn，仅当文本严格等于「立即沟通」才点击
        click_result = await page.evaluate(
            """() => {
              const root = document.querySelector('.job-detail-container, .recommend-result-job, .job-detail-box') || document;
              const candidates = root.querySelectorAll(
                '.job-detail-op a, .job-detail-header a, a.op-btn, a.op-btn-chat, a[ka*="chat"], .btn-startchat'
              );
              for (const el of candidates) {
                const text = (el.innerText || el.textContent || '').trim();
                if (text !== '立即沟通') continue;
                const cls = el.className || '';
                if (/(disabled|disable|btn-disabled|greet-disable)/.test(cls) || el.disabled) continue;
                el.scrollIntoView({block: 'center'});
                el.click();
                return { clicked: true, text };
              }
              const allTexts = Array.from(candidates).map(e => (e.innerText || '').trim()).filter(Boolean);
              return { clicked: false, allTexts };
            }"""
        )

        if not click_result or not click_result.get("clicked"):
            seen = click_result.get("allTexts") if click_result else []
            await self._log("INFO", f"[跳过] 详情无可点的「立即沟通」(候选文本={seen})：{title}")
            return False

        await page.wait_for_timeout(1500)

        # 6. 处理弹窗：填招呼语 / 点「留在此页」；兜底跳转到 chat 详情页
        dialog_handled, greeting_sent = await self._send_in_dialog(page, ai_greeting)
        if not greeting_sent and ai_greeting:
            # 弹窗中没找到输入框（form B），尝试在聊天页发送 AI 招呼语
            await page.wait_for_timeout(2000)  # 等待可能的页面跳转
            chat_sent = False
            pages = self._ctx.pages or []  # type: ignore[union-attr]
            # "继续沟通"可能SPA导航当前页，也搜索当前页
            for p in pages:
                if p is page and "/chat" not in p.url and "/job" in p.url:
                    continue  # 跳过仍在列表页的原页面
                try:
                    chat_sent = await self._send_in_chat_page(p, ai_greeting)
                    if chat_sent:
                        if p is not page:
                            try: await p.close()
                            except Exception: pass
                        break
                except Exception:
                    continue
            greeting_sent = chat_sent
        sent_ok = dialog_handled or greeting_sent

        # 7. 如果当前页已导航离开列表页（如点了"继续沟通"跳到聊天页），返回上一页继续
        # 用 go_back 而非 _navigate_search：保持当前分页位置和滚动位置，避免回到第一页从头开始
        try:
            current_url = page.url
            if "/job" not in current_url and "/geek" not in current_url:
                await self._log("INFO", f"[返回] 页面已离开列表页，返回上一页继续搜索")
                await page.go_back(wait_until="domcontentloaded")
                await page.wait_for_timeout(1500)
                # 兜底：go_back 后仍不在列表页，才重新导航
                if "/job" not in page.url and "/geek" not in page.url:
                    await self._log("WARN", "[返回] 返回失败，重新导航到搜索页")
                    await self._navigate_search()
        except Exception:
            pass

        # 8. 等 N 秒（默认 5），再交回主循环（不滚动到顶部，保持当前位置继续向下遍历）
        if sent_ok:
            await asyncio.sleep(self.click_delay_seconds)
        return sent_ok

    async def _send_in_dialog(self, page: Page, ai_greeting: Optional[str] = None) -> tuple[bool, bool]:
        """点完「立即沟通」后处理弹窗。返回 (弹窗已处理, 招呼语已发送)。

        BOSS 现在两种弹窗形态：
          A. 输入弹窗：textarea + 发送按钮（旧版/部分账号）
          B. 确认弹窗：「已向 BOSS 发送消息」+「留在此页」/「继续沟通」（新版常见）

        形态 A：找到 textarea → 填入 AI 招呼语 → 回车发送 → 关弹窗
        形态 B：无 textarea → 如果有 AI 招呼语，优先点「继续沟通」跳聊天页发送；
                否则点「留在此页」关弹窗
        """
        greeting_sent = False

        # 形态 A：能找到 textarea 就填字回车
        try:
            box = await page.wait_for_selector(
                ".dialog-container textarea, .chat-input textarea, textarea#chat-input, .greet-content textarea",
                timeout=2500,
            )
            if box:
                msg = ai_greeting or self._pick_greeting()
                if msg:
                    await box.fill(msg)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(1200)
                greeting_sent = True
        except PWTimeoutError:
            pass  # 没输入框 → form B

        # 形态 B：无 textarea，如果有 AI 招呼语，点「继续沟通」跳聊天页发送
        if not greeting_sent and ai_greeting:
            try:
                clicked = await page.evaluate(
                    """() => {
                      const els = document.querySelectorAll('button, a, [role="button"], span, div');
                      for (const el of els) {
                        const t = (el.innerText || el.textContent || '').trim();
                        if (t === '继续沟通') {
                          const target = el.closest('button, a, [role="button"]') || el;
                          target.click();
                          return true;
                        }
                      }
                      return false;
                    }"""
                )
                if clicked:
                    await self._log("INFO", "[AI] 点击「继续沟通」跳转聊天页发送招呼语")
                    await page.wait_for_timeout(2000)
                    # 不关弹窗，让调用方在聊天页发送
                    return True, False
            except Exception:
                pass

        # 关闭弹窗
        handled = await self._dismiss_after_send(page)
        return handled, greeting_sent

    async def _dismiss_after_send(self, page: Page) -> bool:
        """关闭发送后可能出现的弹窗。

        BOSS 已知的几种弹窗：
          1. 「已向 BOSS 发送消息」→ 点「留在此页」
          2. 「温馨提示：您今天已与 N 位 BOSS 沟通，还剩 M 次沟通机会哦」→ 点「好」
          3. 「无法进行沟通：您今天已与 150 位 BOSS 沟通，休息一下，明天再来吧」→ 点「确定」+ 标记上限触达
          4. 老版输入弹窗 → 点「确定」「知道了」

        策略：先尝试在弹窗容器内匹配按钮（精确），失败再全页扫描兜底。
        如果命中硬上限弹窗（无法进行沟通/明天再来），会设 self._daily_limit_hit = True，
        让 _loop_greet 在下次循环时整体结束任务。
        """
        # 0. 优先识别「无法进行沟通 / 明天再来」硬上限弹窗，设 flag（按钮会在下面统一点掉）
        try:
            limit_text = await page.evaluate(
                """() => {
                  const SCOPES = ['[role="dialog"]', '.dialog-container', '.dialog-wrap',
                                  '.greet-dialog', '.boss-popup', '.ant-modal',
                                  '.boss-dialog', '.modal-dialog', '.ui-dialog'];
                  const HIT = /无法进行沟通|明天再来|休息一下|沟通上限|今日已达|达到今日|已达今日/;
                  for (const sel of SCOPES) {
                    for (const c of document.querySelectorAll(sel)) {
                      const t = (c.innerText || c.textContent || '').trim();
                      if (t && HIT.test(t)) return t.replace(/\\s+/g, ' ').slice(0, 120);
                    }
                  }
                  return null;
                }"""
            )
            if limit_text and not self._daily_limit_hit:
                self._daily_limit_hit = True
                await self._log("ERROR", f"BOSS 已达每日沟通上限：{limit_text}")
        except Exception:
            pass

        # 1. 给弹窗 3 秒入场动画时间，间隔重试
        for _ in range(6):
            clicked = await page.evaluate(
                """() => {
                  const TARGETS = ['留在此页', '好', '知道了', '我知道了', '确定'];
                  // 候选弹窗容器：优先在弹窗作用域内点击，避免误点页面其他位置的同名按钮
                  const SCOPES = [
                    '[role="dialog"]', '.dialog-container', '.dialog-wrap',
                    '.greet-dialog', '.boss-popup', '.ant-modal',
                    '.boss-dialog', '.modal-dialog', '.ui-dialog',
                  ];
                  const tryClick = (root) => {
                    const els = root.querySelectorAll('button, a, [role="button"], span, div, p');
                    for (const el of els) {
                      const t = (el.innerText || el.textContent || '').trim();
                      if (TARGETS.includes(t)) {
                        const tag = el.tagName;
                        // 短文本「好」「确定」要求自身就是 button 类元素，避免误点纯文本
                        const strict = t.length <= 2;
                        if (strict && tag !== 'BUTTON' && tag !== 'A' && el.getAttribute('role') !== 'button') {
                          const btnAncestor = el.closest('button, a, [role="button"]');
                          if (!btnAncestor) continue;
                          btnAncestor.click();
                          return t;
                        }
                        const target = el.closest('button, a, [role="button"]') || el;
                        target.click();
                        return t;
                      }
                    }
                    return null;
                  };
                  // 1) 弹窗 scope 内匹配
                  for (const sel of SCOPES) {
                    const containers = document.querySelectorAll(sel);
                    for (const c of containers) {
                      const r = tryClick(c);
                      if (r) return r;
                    }
                  }
                  // 2) 全页兜底（仅严格匹配 button/a，避免误伤）
                  const all = document.body.querySelectorAll('button, a, [role="button"]');
                  for (const el of all) {
                    const t = (el.innerText || el.textContent || '').trim();
                    if (TARGETS.includes(t)) { el.click(); return t; }
                  }
                  return null;
                }"""
            )
            if clicked:
                if clicked != "留在此页":
                    self.log.info(f"已关闭弹窗：{clicked}")
                return True
            await page.wait_for_timeout(500)

        # 兜底：点弹窗的关闭 X
        try:
            await page.evaluate(
                """() => {
                  const close = document.querySelector(
                    '.dialog-container .icon-close, .dialog-wrap .close, '
                    + '.greet-dialog .close, [role="dialog"] .close, '
                    + '.boss-popup .close, .ant-modal-close'
                  );
                  if (close) close.click();
                }"""
            )
        except Exception:
            pass
        return False

    async def _send_in_chat_page(self, page: Page, ai_greeting: Optional[str] = None) -> bool:
        """在聊天页发送招呼语。用 keyboard.type 模拟真实键盘输入。"""
        try:
            msg = ai_greeting or self._pick_greeting()
            if not msg:
                return False

            await self._log("INFO", f"[AI] 尝试在页面发送，URL: {page.url}")

            # 找到输入元素并让它可见、聚焦
            found = await page.evaluate(
                """() => {
                  // 1. 尝试 textarea
                  let tas = Array.from(document.querySelectorAll('textarea'));
                  // 2. 尝试 contenteditable
                  let ces = Array.from(document.querySelectorAll('[contenteditable="true"]'));

                  // 优先选 class/placeholder 含 chat/input/message/edit 的
                  const isChatEl = (el) => /chat|input|message|edit|greet|send/i.test(
                    (el.className || '') + (el.placeholder || '') + (el.id || '')
                  );
                  tas.sort((a, b) => (isChatEl(b) ? 1 : 0) - (isChatEl(a) ? 1 : 0));

                  if (tas.length) {
                    const ta = tas[0];
                    // 强制可见
                    ta.style.cssText += ';display:block !important;visibility:visible !important;opacity:1 !important;';
                    ta.focus();
                    return { type: 'textarea', cls: ta.className || '', placeholder: ta.placeholder || '' };
                  }
                  if (ces.length) {
                    const ce = ces[0];
                    ce.focus();
                    return { type: 'contenteditable', cls: ce.className || '' };
                  }
                  return null;
                }"""
            )

            if not found:
                await self._log("WARN", "[AI] 页面上未找到任何输入元素")
                return False

            await self._log("INFO", f"[AI] 找到输入元素: {found}")

            # 用真实键盘输入（React/Vue 都能识别）
            await page.wait_for_timeout(300)
            await page.keyboard.type(msg, delay=30)
            await page.wait_for_timeout(500)

            # 尝试点发送按钮
            sent = await page.evaluate(
                """() => {
                  const candidates = document.querySelectorAll(
                    'button, a, [role="button"], span, div'
                  );
                  for (const el of candidates) {
                    const t = (el.innerText || el.textContent || '').trim();
                    if (t === '发送' || t === 'Send') {
                      const target = el.closest('button, a, [role="button"]') || el;
                      target.click();
                      return 'button';
                    }
                  }
                  return null;
                }"""
            )
            if not sent:
                await page.keyboard.press("Enter")
                sent = "Enter"

            await page.wait_for_timeout(1500)
            await self._log("INFO", f"[AI] 已在聊天页发送招呼语（方式: {sent}）")
            return True
        except Exception as e:
            await self._log("WARN", f"[AI] 聊天页发送失败：{e}")
        return False

    async def _extract_jd_text(self, page: Page) -> str:
        """从右侧岗位详情区域抓取 JD 文本。"""
        try:
            text = await page.evaluate(
                """() => {
                  // BOSS 详情页容器候选
                  const containers = [
                    '.job-detail-content', '.job-sec-text', '.job-detail',
                    '.recommend-result-job .job-detail', '.job-detail-box'
                  ];
                  for (const sel of containers) {
                    const el = document.querySelector(sel);
                    if (el) return (el.innerText || el.textContent || '').slice(0, 2000);
                  }
                  // 兜底：取详情区域里所有文本
                  const detail = document.querySelector('.job-detail-container, .recommend-result-job');
                  if (detail) return (detail.innerText || '').slice(0, 2000);
                  return '';
                }"""
            )
            # 清理 PUA 乱码字符
            import re
            text = re.sub(r'[\uE000-\uF8FF]', '', text or '')
            text = re.sub(r'\s+', ' ', text).strip()
            return text
        except Exception:
            return ""

    async def _goto_next_page(self) -> bool:
        page = self._page
        assert page
        try:
            ok = await page.evaluate(
                """() => {
                  const next = document.querySelector('.options-pages a:last-child, .pager .next:not(.disabled)');
                  if (next && !next.classList.contains('disabled')) { next.click(); return true; }
                  return false;
                }"""
            )
            if ok:
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(1500)
            return bool(ok)
        except Exception:
            return False

    async def _scroll_list_for_more(self) -> None:
        """向下滚动列表容器，触发 BOSS 懒加载/无限滚动加载更多岗位。"""
        page = self._page
        assert page
        try:
            await page.evaluate(
                """() => {
                  const list = document.querySelector('.job-list-container, .recommend-job-list, .job-list-box');
                  if (list) list.scrollTo({top: list.scrollHeight, behavior: 'smooth'});
                  window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'});
                }"""
            )
            await page.wait_for_timeout(2000)
        except Exception:
            pass

    def _pick_greeting(self) -> Optional[str]:
        if not self.greetings: return None
        return random.choice(self.greetings)

    async def _sleep_with_jitter(self, base: int) -> None:
        """带抖动的等待。打日志让用户看到"在等而不是死了"。支持暂停中断。"""
        jitter = random.uniform(-2, 4)
        total = max(5.0, base + jitter)
        await self._log("INFO", f"等 {int(total)}s 后处理下一个岗位...")
        end = asyncio.get_event_loop().time() + total
        while asyncio.get_event_loop().time() < end:
            if self._stop_event.is_set(): return
            await self._pause_event.wait()  # 暂停时阻塞在这里
            await asyncio.sleep(0.5)

    # ---------------- 工具 ----------------
    async def _log(self, level: str, msg: str) -> None:
        entry = self.logger.log(level, msg)
        await self.on_log(entry)

    async def _push_status(self, status: str, payload: Optional[dict] = None) -> None:
        await self.on_status(status, payload or {})

    async def _cleanup(self) -> None:
        try:
            if self._ctx: await self._ctx.close()
        except Exception:
            pass
        try:
            if self._pw: await self._pw.stop()
        except Exception:
            pass
