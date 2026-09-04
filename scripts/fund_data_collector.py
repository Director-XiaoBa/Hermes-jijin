#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
并行数据采集脚本 — 8个独立数据源并发抓取，各自超时、各自写文件，最终合并为 scan_summary.json

用法:
    python3 fund_data_collector.py          # 采集并合并
    python3 fund_data_collector.py --merge   # 只合并已有的 JSON 文件（跳过采集）

输出:
    /tmp/fund_data/indices_holdings.json    — A: 指数 + 持仓 + 重仓股
    /tmp/fund_data/etf_realtime.json        — B: ETF 实时
    /tmp/fund_data/global_markets.json      — C: 全球市场（美股+期货）
    /tmp/fund_data/sector_fund_flows.json   — D: 板块资金流向
    /tmp/fund_data/north_flow.json          — E: 北向资金
    /tmp/fund_data/news.json                — F: 7x24 快讯
    /tmp/fund_data/events.json              — G: 事件日历
    /tmp/fund_data/sector_scan.json         — H: 全市场板块 TOP5/BOTTOM5
    /tmp/fund_data/scan_summary.json        — 合并结果
"""
import os, sys, json, time, threading, traceback
import urllib.request, re, ssl
from datetime import datetime, date, timedelta

# ---------- 路径 & 共享模块 ----------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from fund_common import (
    get_connection, get_holdings_for_scan, get_watchlist_codes,
    get_fund_sectors, get_fund_etf_map, DB_CONFIG,
)
import pymysql

DATA_DIR = "/tmp/fund_data"
os.makedirs(DATA_DIR, exist_ok=True)

# ---------- HTTP 工具 ----------
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def http_get(url: str, headers: dict = None, timeout: int = 10) -> bytes:
    """带默认 UA + SSL 的 HTTP GET"""
    h = dict(_UA)
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    return urllib.request.urlopen(req, timeout=timeout, context=_CTX).read()


# ---------- 结果写入工具 ----------
def write_source_result(source_name: str, result: dict):
    """将单个数据源的结果写入 /tmp/fund_data/<source>.json"""
    path = os.path.join(DATA_DIR, f"{source_name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def ok_result(data) -> dict:
    return {"status": "ok", "data": data, "error": None}


def err_result(error_str: str) -> dict:
    return {"status": "error", "data": None, "error": error_str}


def timeout_result() -> dict:
    return {"status": "timeout", "data": None, "error": "timeout"}


# ---------- 持仓快照（多个源共用，提前一次性拉取） ----------
_holdings_snapshot = None
_holdings_lock = threading.Lock()


def get_holdings_snapshot():
    global _holdings_snapshot
    if _holdings_snapshot is None:
        with _holdings_lock:
            if _holdings_snapshot is None:
                _holdings_snapshot = get_holdings_for_scan()
    return _holdings_snapshot


# ================================================================
#  数据源 A: 指数 + 持仓基金净值 + 重仓股  (timeout 10s)
# ================================================================
def collect_indices_holdings(timeout: int = 10) -> dict:
    """A: 主要指数、持仓基金净值、重仓股实时"""
    try:
        result = {"indices": [], "holdings": [], "top_stocks": [], "summary": {}}

        # ---- 指数实时（腾讯 qt.gtimg.cn） ----
        idx_raw = http_get(
            "https://qt.gtimg.cn/q=sh000001,sz399006,sh000688,sh000852",
            headers={"Referer": "https://finance.qq.com"},
            timeout=timeout,
        ).decode("gbk", "ignore")

        for line in idx_raw.strip().split(";"):
            line = line.strip()
            m = re.search(r'v_(\w+)="([^"]*)"', line)
            if not m:
                continue
            code, data_str = m.group(1), m.group(2)
            parts = data_str.split("~")
            if len(parts) < 45:
                continue
            try:
                name = parts[1]
                price = float(parts[3]) if parts[3] else 0
                pct = float(parts[32]) if parts[32] else 0
                result["indices"].append({
                    "code": code, "name": name, "price": price, "pct": pct,
                })
            except (ValueError, IndexError):
                continue

        # ---- 持仓基金净值 ----
        holdings = get_holdings_snapshot()
        for h in holdings:
            c = h["fund_code"]
            try:
                txt = http_get(
                    f"https://fund.eastmoney.com/pingzhongdata/{c}.js",
                    timeout=timeout,
                ).decode("utf-8", "ignore")
                nm = re.search(r'fS_name\s*=\s*"([^"]+)"', txt)
                name = nm.group(1)[:12] if nm else c
                # 提取最新净值
                nav_m = re.search(r'Data_netWorthTrend\s*=\s*(\[.*?\]);', txt, re.S)
                latest_nav = None
                latest_pct = None
                if nav_m:
                    arr = json.loads(nav_m.group(1))
                    if len(arr) >= 2:
                        latest_nav = arr[-1].get("y")
                        prev_nav = arr[-2].get("y")
                        if latest_nav and prev_nav:
                            latest_pct = round((latest_nav / prev_nav - 1) * 100, 2)
                result["holdings"].append({
                    "fund_code": c, "fund_name": name,
                    "latest_nav": latest_nav, "today_pct": latest_pct,
                    "amount": h.get("total_amount", 0),
                    "buy_date": str(h.get("buy_date", "")),
                })
            except Exception as e:
                result["holdings"].append({
                    "fund_code": c, "fund_name": c,
                    "error": str(e),
                })

        # ---- 重仓股实时（腾讯 qt.gtimg.cn） ----
        TOP_STOCKS = "sh688256,sz300308,sz300502,sh688072,sh688012,sh688082,sz002008,sh688017,sz002472,sh601689,sz002050,sh688981,sh600111,sz300750"
        stk_raw = http_get(
            f"https://qt.gtimg.cn/q={TOP_STOCKS}",
            headers={"Referer": "https://finance.qq.com"},
            timeout=timeout,
        ).decode("gbk", "ignore")

        for line in stk_raw.strip().split(";"):
            line = line.strip()
            m = re.search(r'v_(\w+)="([^"]*)"', line)
            if not m:
                continue
            code, data_str = m.group(1), m.group(2)
            parts = data_str.split("~")
            if len(parts) < 45:
                continue
            try:
                name = parts[1]
                price = float(parts[3]) if parts[3] else 0
                pct = float(parts[32]) if parts[32] else 0
                result["top_stocks"].append({
                    "code": code, "name": name, "price": price, "pct": pct,
                })
            except (ValueError, IndexError):
                continue

        # ---- 汇总 ----
        result["summary"] = {
            "index_count": len(result["indices"]),
            "holding_count": len(result["holdings"]),
            "stock_count": len(result["top_stocks"]),
        }
        return ok_result(result)

    except Exception as e:
        return err_result(f"{e}" + chr(10) + traceback.format_exc())


# ================================================================
#  数据源 B: ETF 实时 (timeout 10s)
# ================================================================
def collect_etf_realtime(timeout: int = 10) -> dict:
    """B: 持仓基金对应 ETF 实时行情"""
    try:
        result = {"etf_list": [], "estimates": {}}
        holdings = get_holdings_snapshot()
        etf_map = {h["fund_code"]: h["etf_code"] for h in holdings if h.get("etf_code")}

        if not etf_map:
            return ok_result(result)

        etf_codes = ",".join(
            f"sh{v}" if v.startswith("5") else f"sz{v}"
            for v in etf_map.values()
        )
        raw = http_get(
            f"https://qt.gtimg.cn/q={etf_codes}",
            headers={"Referer": "https://finance.qq.com"},
            timeout=timeout,
        ).decode("gbk", "ignore")

        etf_to_fund = {v: k for k, v in etf_map.items()}
        ETF_NAME = {
            "588200": "科创芯片", "562500": "机器人", "516150": "稀土",
            "159638": "数字经济", "512480": "半导体",
        }

        for line in raw.strip().split(";"):
            line = line.strip()
            m = re.search(r'v_(\w+)="([^"]*)"', line)
            if not m:
                continue
            code_full = m.group(1)
            code_num = code_full[2:]  # 去掉 sh/sz
            parts = m.group(2).split("~")
            if len(parts) < 45:
                continue
            try:
                name = parts[1] or ETF_NAME.get(code_num, code_num)
                price = float(parts[3]) if parts[3] else 0
                pct = float(parts[32]) if parts[32] else 0
                result["etf_list"].append({
                    "code": code_num, "name": name, "price": price, "pct": pct,
                })
                fund_code = etf_to_fund.get(code_num)
                if fund_code:
                    result["estimates"][fund_code] = {
                        "etf_code": code_num, "etf_pct": pct,
                    }
            except (ValueError, IndexError):
                continue

        return ok_result(result)

    except Exception as e:
        return err_result(f"{e}" + chr(10) + traceback.format_exc())


# ================================================================
#  数据源 C: 全球市场 — 美股指数 + 期货 (timeout 10s)
# ================================================================
def collect_global_markets(timeout: int = 10) -> dict:
    """C: 道琼斯、纳斯达克、标普500、半导体指数、纳指期货"""
    try:
        result = {"indices": [], "futures": []}

        # 腾讯接口: 美股主要指数
        raw = http_get(
            "https://qt.gtimg.cn/q=usDJIA,usNDAQ,usSPX,usSOXX,usNVDA,usAAPL",
            headers={"Referer": "https://finance.qq.com"},
            timeout=timeout,
        ).decode("gbk", "ignore")

        for line in raw.strip().split(";"):
            line = line.strip()
            m = re.search(r'v_(\w+)="([^"]*)"', line)
            if not m:
                continue
            code, data_str = m.group(1), m.group(2)
            parts = data_str.split("~")
            if len(parts) < 10 or not parts[1]:
                continue
            try:
                name = parts[1]
                price = float(parts[3]) if parts[3] else 0
                pct = float(parts[32]) if parts[32] and len(parts) > 32 else 0
                item = {"code": code, "name": name, "price": price, "pct": pct}
                if code.startswith("us"):
                    result["indices"].append(item)
            except (ValueError, IndexError):
                continue

        # 期货: 纳指期货 (腾讯)
        try:
            fut_raw = http_get(
                "https://qt.gtimg.cn/q=hf_NQ",
                headers={"Referer": "https://finance.qq.com"},
                timeout=timeout,
            ).decode("gbk", "ignore")
            m = re.search(r'v_hf_NQ="([^"]*)"', fut_raw)
            if m:
                parts = m.group(1).split("~")
                if len(parts) >= 8:
                    price = float(parts[0]) if parts[0] else 0
                    prev = float(parts[7]) if parts[7] else 0
                    pct = round((price / prev - 1) * 100, 2) if prev else 0
                    result["futures"].append({
                        "code": "hf_NQ", "name": "纳指期货",
                        "price": price, "pct": pct,
                    })
        except Exception:
            pass

        return ok_result(result)

    except Exception as e:
        return err_result(f"{e}" + chr(10) + traceback.format_exc())


# ================================================================
#  数据源 D: 板块资金流向 (timeout 15s)
# ================================================================
def _http_get_with_retry(url: str, headers: dict = None, timeout: int = 10,
                         retries: int = 3, backoff: float = 1.0) -> bytes:
    """带重试的 HTTP GET，应对 push2 限流"""
    last_err = None
    for attempt in range(retries):
        try:
            return http_get(url, headers=headers, timeout=timeout)
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    raise last_err


def collect_sector_fund_flows(timeout: int = 15) -> dict:
    """D: 板块涨跌排行（新浪API，替代被封的push2）"""
    try:
        result = {"sectors": [], "top_inflow": [], "top_outflow": [], "fund_signals": []}

        # 新浪板块数据（含涨跌幅/成交额/领涨股）
        req = urllib.request.Request(
            "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php",
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        raw = resp.read().decode("gbk", "ignore")

        match = re.search(r'\{(.+)\}', raw)
        if not match:
            return ok_result(result)

        pairs = match.group(1).split('","')
        sectors = []
        for p in pairs:
            p = p.strip('"')
            parts = p.split(",")
            if len(parts) >= 8:
                name = parts[1]
                change_pct = float(parts[4]) if parts[4] else 0
                amount = float(parts[7]) if parts[7] else 0
                leader = parts[12] if len(parts) > 12 else ""
                sectors.append({
                    "name": name,
                    "pct_change": change_pct,
                    "amount_yi": round(amount / 1e8, 2),
                    "leader": leader,
                })

        result["sectors"] = sectors

        # TOP5涨幅（=资金流入方向）
        sorted_up = sorted(sectors, key=lambda x: x["pct_change"], reverse=True)
        result["top_inflow"] = sorted_up[:5]

        # TOP5跌幅（=资金流出方向）
        sorted_dn = sorted(sectors, key=lambda x: x["pct_change"])
        result["top_outflow"] = sorted_dn[:5]

        return ok_result(result)

    except Exception as e:
        return err_result(str(e) + "\n" + traceback.format_exc())


# ================================================================
#  数据源 E: 北向资金 (timeout 15s)
# ================================================================
def collect_north_flow(timeout: int = 15) -> dict:
    """E: 东财 push2 北向资金 + MySQL 历史"""
    try:
        result = {"latest": None, "recent_3d": [], "source": ""}

        # 方案1: MySQL 历史数据（优先）
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT trade_date, total_netflow, is_inflow
                    FROM north_flow_daily ORDER BY trade_date DESC LIMIT 3
                """)
                rows = cur.fetchall()
            conn.close()

            if rows:
                result["source"] = "mysql"
                latest = rows[0]
                result["latest"] = {
                    "date": str(latest[0]),
                    "netflow_yi": float(latest[1]),
                    "is_inflow": bool(latest[2]),
                }
                for r in rows:
                    result["recent_3d"].append({
                        "date": str(r[0]),
                        "netflow_yi": float(r[1]),
                        "is_inflow": bool(r[2]),
                    })
                return ok_result(result)
        except Exception:
            pass

        # 方案2: 东财 push2 实时
        raw = _http_get_with_retry(
            "https://push2.eastmoney.com/api/qt/kamt.rtmin/get?"
            "fields1=f1,f2,f3,f4&fields2=f51,f52,f53,f54,f55,f56",
            headers={"Referer": "https://data.eastmoney.com/"},
            timeout=timeout, retries=2, backoff=1.0,
        ).decode("utf-8", "ignore")
        d = json.loads(raw)

        s2n = d.get("data", {}).get("s2n", {})
        if s2n:
            snap = s2n.get("s2n", [])
            if snap:
                latest_line = snap[-1].split(",")
                if len(latest_line) >= 2:
                    result["source"] = "eastmoney_realtime"
                    north_net = float(latest_line[1]) if latest_line[1] else 0
                    result["latest"] = {
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "netflow_yi": round(north_net / 1e4, 2),
                        "is_inflow": north_net > 0,
                    }

        return ok_result(result)

    except Exception as e:
        return err_result(f"{e}" + chr(10) + traceback.format_exc())


# ================================================================
#  数据源 F: 7x24 快讯 (timeout 8s)
# ================================================================
def collect_news(timeout: int = 8) -> dict:
    """F: 东财 7x24 财经快讯"""
    try:
        result = {"items": [], "count": 0}

        raw = http_get(
            "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?"
            "client=web&biz=web_724&column=345&order=1&needInteractData=0"
            "&page_index=1&page_size=20&req_trace=1"
            "&fields=code,showTime,title",
            timeout=timeout,
        ).decode("utf-8", "ignore")
        d = json.loads(raw)
        items = d.get("data", {}).get("list", [])

        for it in items[:20]:
            result["items"].append({
                "time": it.get("showTime", "")[:16],
                "title": it.get("title", ""),
                "code": it.get("code", ""),
            })
        result["count"] = len(result["items"])

        return ok_result(result)

    except Exception as e:
        return err_result(f"{e}" + chr(10) + traceback.format_exc())


# ================================================================
#  数据源 G: 事件日历 — MySQL (timeout 5s)
# ================================================================
def collect_events(timeout: int = 5) -> dict:
    """G: MySQL events 表 — 未来7天重大事件"""
    try:
        result = {"events": [], "count": 0}

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT event_time, event_type, title, intensity, related_funds
                    FROM events
                    WHERE event_time BETWEEN NOW() AND DATE_ADD(NOW(), INTERVAL 7 DAY)
                      AND verified = 1
                    ORDER BY event_time
                """)
                rows = cur.fetchall()
        finally:
            conn.close()

        for row in rows:
            result["events"].append({
                "time": row[0].strftime("%Y-%m-%d %H:%M") if row[0] else "",
                "type": row[1] or "",
                "title": row[2] or "",
                "intensity": row[3] or 0,
                "related_funds": row[4] or "",
            })
        result["count"] = len(result["events"])

        return ok_result(result)

    except Exception as e:
        return err_result(f"{e}" + chr(10) + traceback.format_exc())


# ================================================================
#  数据源 H: 全市场板块 TOP5 / BOTTOM5 (timeout 15s)
# ================================================================
def collect_sector_scan(timeout: int = 15) -> dict:
    """H: 全市场板块涨幅榜+跌幅榜（新浪API，替代被封的push2）"""
    try:
        result = {"top5": [], "bottom5": [], "total_sectors": 0}

        req = urllib.request.Request(
            "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php",
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        raw = resp.read().decode("gbk", "ignore")

        match = re.search(r'\{(.+)\}', raw)
        if not match:
            return ok_result(result)

        pairs = match.group(1).split('","')
        sectors = []
        for p in pairs:
            p = p.strip('"')
            parts = p.split(",")
            if len(parts) >= 8:
                name = parts[1]
                change_pct = float(parts[4]) if parts[4] else 0
                amount = float(parts[7]) if parts[7] else 0
                leader = parts[12] if len(parts) > 12 else ""
                sectors.append({
                    "name": name,
                    "pct": change_pct,
                    "amount_yi": round(amount / 1e8, 2),
                    "leader": leader,
                })

        sectors.sort(key=lambda x: x["pct"], reverse=True)
        result["top5"] = sectors[:5]
        result["bottom5"] = sectors[-5:]
        result["total_sectors"] = len(sectors)

        return ok_result(result)

    except Exception as e:
        return err_result(str(e) + "\n" + traceback.format_exc())


# ================================================================
#  并行调度器
# ================================================================
# (source_name, collector_fn, timeout_seconds)
SOURCES = [
    ("indices_holdings",   collect_indices_holdings, 10),
    ("etf_realtime",       collect_etf_realtime,     10),
    ("global_markets",     collect_global_markets,   10),
    ("sector_fund_flows",  collect_sector_fund_flows, 15),
    ("north_flow",         collect_north_flow,        15),
    ("news",               collect_news,               8),
    ("events",             collect_events,             5),
    ("sector_scan",        collect_sector_scan,       15),
]


def _run_with_timeout(collector_fn, timeout, result_slot):
    """在线程中执行 collector，超过 timeout 秒未完成则标记 timeout"""
    start = time.time()
    try:
        res = collector_fn(timeout=timeout)
        elapsed = round(time.time() - start, 2)
        res["elapsed_s"] = elapsed
        result_slot["result"] = res
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        result_slot["result"] = {
            "status": "error", "data": None,
            "error": f"{e}\n{traceback.format_exc()}",
            "elapsed_s": elapsed,
        }


def collect_all() -> dict:
    """并行启动所有数据源，等待完成，写入各自的 JSON，返回结果字典"""
    threads = []
    results = {}  # source_name -> {result: ...}

    for name, fn, timeout in SOURCES:
        results[name] = {}
        t = threading.Thread(
            target=_run_with_timeout,
            args=(fn, timeout, results[name]),
            name=f"src-{name}",
            daemon=True,
        )
        threads.append((name, t, timeout))
        t.start()

    # 等待所有线程完成，每个线程额外有 2s 缓冲
    deadline = time.time() + max(t for _, _, t in threads) + 2
    for name, t, timeout in threads:
        remaining = deadline - time.time()
        t.join(timeout=max(remaining, 1))

    # 收集结果，处理超时
    final = {}
    for name, t, timeout in threads:
        if t.is_alive():
            res = timeout_result()
            res["elapsed_s"] = timeout
        else:
            slot = results[name]
            res = slot.get("result", timeout_result())
        final[name] = res
        write_source_result(name, res)

    return final


# ================================================================
#  合并步骤
# ================================================================
def merge_all() -> dict:
    """读取所有 /tmp/fund_data/<source>.json，合并为 scan_summary.json"""
    summary = {
        "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sources": {},
        "stats": {"total": 0, "ok": 0, "error": 0, "timeout": 0},
    }

    for name, _, _ in SOURCES:
        path = os.path.join(DATA_DIR, f"{name}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                source_data = json.load(f)
        else:
            source_data = {"status": "error", "data": None, "error": "file not found"}

        summary["sources"][name] = source_data
        summary["stats"]["total"] += 1
        status = source_data.get("status", "error")
        if status in summary["stats"]:
            summary["stats"][status] += 1

    # 写入合并文件
    out_path = os.path.join(DATA_DIR, "scan_summary.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return summary


# ================================================================
#  CLI 入口
# ================================================================
if __name__ == "__main__":
    merge_only = "--merge" in sys.argv

    print("=" * 60)
    print(f"  基金数据并行采集器  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if not merge_only:
        print("\n[阶段1] 并行采集 8 个数据源 ...")
        t0 = time.time()
        results = collect_all()
        elapsed = round(time.time() - t0, 2)
        print(f"\n采集完成，总耗时: {elapsed}s")
        print()
        for name, _, timeout in SOURCES:
            r = results[name]
            status = r.get("status", "?")
            et = r.get("elapsed_s", "?")
            icon = {"ok": "✅", "error": "❌", "timeout": "⏰"}.get(status, "?")
            print(f"  {icon} {name:<22s}  status={status}  elapsed={et}s  (timeout={timeout}s)")

    print(f"\n[阶段2] 合并结果 ...")
    summary = merge_all()
    stats = summary["stats"]
    print(f"  总计: {stats['total']}  ✅ 成功: {stats['ok']}  ❌ 失败: {stats['error']}  ⏰ 超时: {stats['timeout']}")
    print(f"\n输出: /tmp/fund_data/scan_summary.json")
    print("=" * 60)
