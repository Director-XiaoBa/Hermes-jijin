#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基金系统共享模块 - 单一数据源
所有脚本从这里读取持仓、基金信息、ETF映射等
"""
import pymysql
import urllib.request
import ssl
from datetime import datetime, date
from typing import List, Dict, Optional

# 数据库配置
DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3306,
    'user': 'fund_admin',
    'password': '<REDACTED>',
    'database': 'fund_research',
    'charset': 'utf8mb4'
}

# SSL配置
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# User-Agent
UA = {'User-Agent': 'Mozilla/5.0'}


def http_get(url: str, headers: dict = None, timeout: int = 12) -> bytes:
    """统一的HTTP GET请求"""
    h = dict(UA)
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    return urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX).read()


def get_connection():
    """获取数据库连接"""
    return pymysql.connect(**DB_CONFIG)


def get_holdings() -> List[Dict]:
    """
    获取当前持仓（从trades表）
    同一基金多次买入时：SUM(amount)汇总，计算加权平均成本
    返回: [{fund_code, fund_name, trade_date, amount, nav_price, stop_loss, take_profit, notes}, ...]
    """
    conn = get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("""
                SELECT
                    t.fund_code,
                    t.fund_name,
                    latest.trade_date,
                    agg.total_amount,
                    agg.avg_cost as nav_price,
                    t.stop_loss,
                    t.take_profit,
                    t.notes
                FROM trades t
                INNER JOIN (
                    SELECT 
                        fund_code, 
                        SUM(amount) AS total_amount,
                        SUM(amount * nav_price) / SUM(amount) as avg_cost
                    FROM trades
                    WHERE direction = '买入' AND trade_status = '持有'
                    GROUP BY fund_code
                ) agg ON t.fund_code = agg.fund_code
                INNER JOIN (
                    SELECT fund_code, MAX(trade_date) AS trade_date
                    FROM trades
                    WHERE direction = '买入' AND trade_status = '持有'
                    GROUP BY fund_code
                ) latest ON t.fund_code = latest.fund_code
                         AND t.trade_date = latest.trade_date
                WHERE t.direction = '买入' AND t.trade_status = '持有'
                ORDER BY t.trade_date
            """)
            holdings = []
            for t in cur.fetchall():
                holdings.append({
                    'fund_code': t['fund_code'],
                    'fund_name': t['fund_name'],
                    'total_amount': float(t['total_amount']),
                    'buy_date': t['trade_date'],
                    'nav_price': float(t['nav_price']) if t.get('nav_price') else None,
                    'stop_loss': t.get('stop_loss'),
                    'take_profit': t.get('take_profit'),
                    'notes': t.get('notes'),
                })
            return holdings
    finally:
        conn.close()


def get_fund_info(fund_code: str = None) -> List[Dict]:
    """
    获取基金信息（从funds表）
    fund_code: 指定基金代码，None则返回所有
    返回: [{code, name, etf_code, sectors, is_watchlist, ...}, ...]
    """
    conn = get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            if fund_code:
                cur.execute("SELECT * FROM funds WHERE code = %s", (fund_code,))
            else:
                cur.execute("SELECT * FROM funds")
            return cur.fetchall()
    finally:
        conn.close()


def get_watchlist() -> List[Dict]:
    """
    获取观察列表（从funds表 where is_watchlist=1）
    返回: [{code, name, watchlist_reason, watchlist_conditions, ...}, ...]
    """
    conn = get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("SELECT * FROM funds WHERE is_watchlist = 1")
            return cur.fetchall()
    finally:
        conn.close()


def get_fund_etf_map() -> Dict[str, str]:
    """
    获取基金→ETF映射（从funds表）
    返回: {'017470': '588200', '011036': '516150', ...}
    """
    funds = get_fund_info()
    return {f['code']: f['etf_code'] for f in funds if f.get('etf_code')}


def get_fund_sectors() -> Dict[str, List[str]]:
    """
    获取基金→行业标签（从funds表）
    返回: {'017470': ['电子', '芯片'], '017811': ['计算机', 'AI'], ...}
    """
    funds = get_fund_info()
    result = {}
    for f in funds:
        if f.get('sectors'):
            result[f['code']] = [s.strip() for s in f['sectors'].split(',')]
    return result


def get_holdings_for_scan() -> List[Dict]:
    """
    获取当前持仓基金+买入日期（用于14:00扫描，T+1计算）
    返回: [{fund_code, fund_name, buy_date, total_amount, etf_code}, ...]
    """
    holdings = get_holdings()
    etf_map = get_fund_etf_map()
    result = []
    for h in holdings:
        result.append({
            'fund_code': h['fund_code'],
            'fund_name': h['fund_name'],
            'buy_date': h['buy_date'],
            'total_amount': h['total_amount'],
            'etf_code': etf_map.get(h['fund_code']),
        })
    return result


def get_all_tracked_funds() -> List[str]:
    """
    获取所有需要跟踪的基金代码（持仓+观察列表）
    返回: ['017470', '017811', '025209', ...]
    """
    # 持仓基金
    holdings = get_holdings()
    holding_codes = [h['fund_code'] for h in holdings]
    
    # 观察列表基金
    watchlist = get_watchlist()
    watchlist_codes = [w['code'] for w in watchlist]
    
    # 合并去重
    return list(set(holding_codes + watchlist_codes))


def get_watchlist_codes() -> List[str]:
    """
    获取观察列表基金代码（不含持仓）
    返回: ['004433', '011613', '012738', ...]
    """
    watchlist = get_watchlist()
    return [w['code'] for w in watchlist]


def get_position_for_fund(fund_code: str) -> Optional[Dict]:
    """
    获取单只基金的持仓信息
    返回: {fund_code, fund_name, total_amount, buy_date, stop_loss, take_profit, notes} 或 None
    """
    holdings = get_holdings()
    for h in holdings:
        if h['fund_code'] == fund_code:
            return h
    return None


def is_holding(fund_code: str) -> bool:
    """
    判断是否持有某只基金
    """
    return get_position_for_fund(fund_code) is not None


def is_watchlist(fund_code: str) -> bool:
    """
    判断是否在观察列表
    """
    conn = get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("SELECT is_watchlist FROM funds WHERE code = %s", (fund_code,))
            result = cur.fetchone()
            return result and result.get('is_watchlist') == 1
    finally:
        conn.close()


def add_fund(code: str, name: str, etf_code: str = None, 
             sectors: str = None, is_watchlist: int = 0,
             watchlist_reason: str = None, watchlist_conditions: str = None):
    """
    添加新基金到funds表
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO funds (code, name, etf_code, sectors, is_watchlist, 
                                   watchlist_reason, watchlist_conditions)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    etf_code = VALUES(etf_code),
                    sectors = VALUES(sectors),
                    is_watchlist = VALUES(is_watchlist),
                    watchlist_reason = VALUES(watchlist_reason),
                    watchlist_conditions = VALUES(watchlist_conditions)
            """, (code, name, etf_code, sectors, is_watchlist, 
                  watchlist_reason, watchlist_conditions))
        conn.commit()
    finally:
        conn.close()


def add_trade(fund_code: str, fund_name: str, direction: str, amount: float,
              nav_price: float = None, reason: str = None, signal_source: str = None,
              stop_loss: float = None, take_profit: float = None, notes: str = None):
    """
    添加交易记录到trades表
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            trade_date = date.today()
            cur.execute("""
                INSERT INTO trades (fund_code, fund_name, trade_date, direction, amount,
                                    nav_price, reason, signal_source, stop_loss, take_profit, 
                                    trade_status, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '持有', %s)
            """, (fund_code, fund_name, trade_date, direction, amount,
                  nav_price, reason, signal_source, stop_loss, take_profit, notes))
        conn.commit()
    finally:
        conn.close()


def add_decision(fund_code: str, decision_type: str, reason: str,
                 signal_source: str = None, market_state: str = None,
                 confidence: float = None):
    """
    记录决策日志
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            decision_date = date.today()
            cur.execute("""
                INSERT INTO decisions (fund_code, decision_type, decision_date, reason,
                                       signal_source, market_state, confidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (fund_code, decision_type, decision_date, reason,
                  signal_source, market_state, confidence))
        conn.commit()
    finally:
        conn.close()


# 测试函数
if __name__ == "__main__":
    print("=== 测试 fund_common.py ===\n")
    
    print("1. 测试 get_holdings():")
    holdings = get_holdings()
    for h in holdings:
        print(f"   {h['fund_code']} {h['fund_name']}: ¥{h['total_amount']:.0f}")
    
    print("\n2. 测试 get_fund_etf_map():")
    etf_map = get_fund_etf_map()
    for code, etf in etf_map.items():
        print(f"   {code} → {etf}")
    
    print("\n3. 测试 get_fund_sectors():")
    sectors = get_fund_sectors()
    for code, sects in sectors.items():
        print(f"   {code} → {sects}")
    
    print("\n4. 测试 get_watchlist():")
    watchlist = get_watchlist()
    for w in watchlist:
        print(f"   {w['code']} {w['name']}")
    
    print("\n5. 测试 get_all_tracked_funds():")
    all_funds = get_all_tracked_funds()
    print(f"   共{len(all_funds)}只: {all_funds}")
    
    print("\n=== 测试完成 ===")
