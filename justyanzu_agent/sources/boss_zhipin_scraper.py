"""
Boss 直聘：DrissionPage 监听 joblist。

约定：
1. dp.listen.start('joblist.json')   # 必须先监听，再访问页面
2. dp.get(搜索页 URL)
3. for 每一页：dp.scroll.to_bottom() → dp.listen.wait() → 解析 resp.response.body['zpData']['jobList']

Boss 改版或风控时字段可能变化；仅供学习/自用，请遵守网站条款。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

try:
    from DrissionPage import ChromiumPage
    from DrissionPage.common import ChromiumOptions
except ImportError:
    ChromiumPage = None  # type: ignore
    ChromiumOptions = None  # type: ignore


@dataclass
class BossJobBrief:
    title: str
    company: str
    salary_raw: str
    area: str
    url: str
    card_text: str


def _build_search_url(city_code: str, query: str) -> str:
    q = quote_plus((query or "").strip())
    return f"https://www.zhipin.com/web/geek/job?city={city_code}&query={q}"


def _job_detail_url(job: dict[str, Any]) -> str:
    jid = job.get("link") or job.get("pcJobDetailLink")
    if jid:
        return str(jid)
    enc = job.get("encryptJobId") or job.get("encryptId") or ""
    if not enc:
        return ""
    base = f"https://www.zhipin.com/job_detail/{enc}.html"
    sec = job.get("securityId")
    lid = job.get("lid")
    q = []
    if lid:
        q.append(f"lid={lid}")
    if sec:
        q.append(f"securityId={sec}")
    return base + ("?" + "&".join(q) if q else "")


def _labels_join(job: dict[str, Any]) -> str:
    raw = job.get("jobLabels") or []
    if not isinstance(raw, list):
        return str(raw)
    parts: list[str] = []
    for x in raw[:12]:
        if isinstance(x, dict):
            parts.append(str(x.get("name") or x))
        else:
            parts.append(str(x))
    return ",".join(parts)


def _job_row_to_brief(job: dict[str, Any]) -> BossJobBrief:
    """按接口常见字段映射；与教程中 print 的字段同一来源。"""
    city = str(job.get("cityName") or "")
    dist = str(job.get("areaDistrict") or "")
    biz = str(job.get("businessDistrict") or job.get("businessName") or "")
    loc_parts = [p for p in (city, dist, biz) if p]
    area = "-".join(loc_parts) if loc_parts else ""
    card = "|".join(
        x
        for x in (
            _labels_join(job),
            str(job.get("brandScaleName") or ""),
            str(job.get("brandIndustry") or ""),
        )
        if x
    )[:600]

    return BossJobBrief(
        title=str(job.get("jobName") or ""),
        company=str(job.get("brandName") or ""),
        salary_raw=str(job.get("salaryDesc") or ""),
        area=area,
        url=_job_detail_url(job),
        card_text=card,
    )


def _as_dict(body: Any) -> dict[str, Any] | None:
    if body is None:
        return None
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            return json.loads(body)
        except Exception:
            return None
    if isinstance(body, (bytes, bytearray)):
        try:
            return json.loads(body.decode("utf-8", errors="replace"))
        except Exception:
            return None
    return None


def extract_job_list(json_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    与文章一致：优先 zpData['jobList']；
    若 jobList 被包成 dict（部分版本），再取 list/sortList。
    """
    zp = json_data.get("zpData") or {}
    if not isinstance(zp, dict):
        return []
    jl = zp.get("jobList")
    if isinstance(jl, list):
        return [x for x in jl if isinstance(x, dict)]
    if isinstance(jl, dict):
        for k in ("list", "sortList"):
            v = jl.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def _new_page(headless: bool) -> ChromiumPage:
    if ChromiumOptions is None:
        raise RuntimeError("请安装 DrissionPage：pip install DrissionPage")
    co = ChromiumOptions()
    if hasattr(co, "set_argument"):
        if headless:
            co.set_argument("--headless=new")
        co.set_argument("--window-size=1920,1080")
        co.set_argument("--lang=zh-CN")
    try:
        return ChromiumPage(addr_or_opts=co)
    except TypeError:
        return ChromiumPage(co)


def _collect_one_keyword(
    dp: ChromiumPage,
    city_code: str,
    keyword: str,
    *,
    max_pages: int,
    listen_timeout: float,
    scroll_pause_sec: float,
    listen_target: str,
) -> list[dict[str, Any]]:
    """单关键词、结构与教程 for page in range(n) 一致。"""
    try:
        dp.listen.stop()
    except Exception:
        pass

    dp.listen.start(listen_target)
    dp.get(_build_search_url(city_code, keyword))
    time.sleep(scroll_pause)

    out: dict[str, dict[str, Any]] = {}

    for page_idx in range(max_pages):
        resp = dp.listen.wait(timeout=listen_timeout, fit_count=False)
        if resp is False or not resp:
            break

        json_data = _as_dict(resp.response.body)
        if not json_data:
            continue

        job_list = extract_job_list(json_data)
        for job in job_list:
            k = str(job.get("encryptJobId") or job.get("jobId") or "")
            if k:
                out[k] = job

        if page_idx >= max_pages - 1:
            break

        try:
            dp.scroll.to_bottom()
        except Exception:
            dp.run_js("window.scrollTo(0, document.body.scrollHeight);")

        time.sleep(scroll_pause_sec)

    try:
        dp.listen.stop()
    except Exception:
        pass

    return list(out.values())


def scrape_boss_jobs(
    *,
    queries: list[str] | None = None,
    city_code: str = "101020100",
    headless: bool = True,
    max_pages_per_query: int = 8,
    listen_timeout: float = 25.0,
    scroll_pause_sec: float = 1.8,
    listen_target: str = "joblist.json",
    try_visible_browser_on_listen_fail: bool = True,
) -> tuple[list[BossJobBrief], list[dict[str, Any]]]:
    """
    监听 joblist，按页滚动采集；返回 (简要行, 接口原始 dict 列表)。
    """
    if ChromiumPage is None:
        raise RuntimeError("请先安装 DrissionPage：pip install DrissionPage")

    def run(head: bool) -> tuple[list[BossJobBrief], list[dict[str, Any]]]:
        dp = _new_page(head)
        try:
            ql = [x.strip() for x in (queries or []) if x.strip()]
            if not ql:
                ql = [""]

            merged: dict[str, dict[str, Any]] = {}
            for kw in ql:
                rows = _collect_one_keyword(
                    dp,
                    city_code.strip(),
                    kw,
                    max_pages=max_pages_per_query,
                    listen_timeout=listen_timeout,
                    scroll_pause_sec=scroll_pause_sec,
                    listen_target=listen_target,
                )
                for j in rows:
                    k = str(j.get("encryptJobId") or j.get("jobId") or "")
                    if k:
                        merged[k] = j

            ordered = list(merged.values())
            briefs = [_job_row_to_brief(x) for x in ordered]
            return briefs, ordered
        finally:
            try:
                dp.quit()
            except Exception:
                pass

    try:
        return run(headless)
    except Exception:
        if headless and try_visible_browser_on_listen_fail:
            time.sleep(1.0)
            return run(False)
        raise
