#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基金组合收益追踪与记录
每日记录收益、计算风险指标、生成收益曲线

使用方式：
    python3 fund_portfolio_task.py  # 记录今日收益
    python3 fund_portfolio_task.py --summary  # 显示摘要
    python3 fund_portfolio_task.py --curve 30  # 显示收益曲线
"""

import json
import pymysql
import math
import sys
import os
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

# 导入共享模块
sys.path.insert(0, os.path.dirname(__file__))
from fund_common import get_holdings, get_connection
from fund_error_handler import retry, fallback, log_error

# 数据库配置
DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3306,
    'user': 'fund_admin',
    'password': '<REDACTED>',
    'database': 'fund_research',
    'charset': 'utf8mb4'
}


class PortfolioTracker:
    """组合收益追踪器"""
    
    def __init__(self):
        self.conn = None
        
    def connect(self):
        """连接数据库"""
        self.conn = pymysql.connect(**DB_CONFIG)
        
    def close(self):
        """关闭连接"""
        if self.conn:
            self.conn.close()
            
    @retry(max_attempts=3, delay=1)
    def get_current_holdings(self) -> List[Dict]:
        """获取当前持仓及市值"""
        holdings = get_holdings()
        result = []
        today = date.today()
        
        if not self.conn:
            self.connect()
        
        with self.conn.cursor(pymysql.cursors.DictCursor) as cur:
            for h in holdings:
                fund_code = h['fund_code']
                amount = h['total_amount']
                buy_nav = float(h.get('nav_price', 0) or 0)
                buy_date = h['buy_date']
                
                # 检查是否是今天买入的
                is_today_buy = (buy_date == today)
                
                if is_today_buy:
                    # 今天买入的基金，明天才出净值，市值=投入金额
                    current_value = amount
                    profit = 0
                    profit_rate = 0
                else:
                    # 非今天买入的，获取最新净值计算市值
                    cur.execute("""
                        SELECT nav FROM nav_daily 
                        WHERE fund_code = %s 
                        ORDER BY trade_date DESC LIMIT 1
                    """, (fund_code,))
                    row = cur.fetchone()
                    
                    if row and buy_nav > 0:
                        current_nav = float(row['nav'])
                        shares = amount / buy_nav
                        current_value = current_nav * shares
                        profit = current_value - amount
                        profit_rate = (current_nav / buy_nav - 1) * 100
                    else:
                        current_value = amount
                        profit = 0
                        profit_rate = 0
                
                result.append({
                    'fund_code': fund_code,
                    'fund_name': h['fund_name'],
                    'amount': amount,
                    'buy_nav': buy_nav,
                    'current_value': current_value,
                    'profit': profit,
                    'profit_rate': profit_rate,
                    'is_today_buy': is_today_buy,
                })
        
        return result
    
    def calculate_max_drawdown(self, daily_returns: List[float]) -> float:
        """计算最大回撤"""
        if not daily_returns:
            return 0
        
        cumulative = 1.0
        peak = 1.0
        max_drawdown = 0
        
        for ret in daily_returns:
            cumulative *= (1 + ret / 100)
            if cumulative > peak:
                peak = cumulative
            drawdown = (peak - cumulative) / peak * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        return round(max_drawdown, 2)
    
    def calculate_sharpe_ratio(self, daily_returns: List[float], risk_free_rate: float = 2.0) -> float:
        """计算夏普比率"""
        if len(daily_returns) < 2:
            return 0
        
        # 计算平均日收益
        avg_return = sum(daily_returns) / len(daily_returns)
        
        # 计算日收益标准差
        variance = sum((r - avg_return) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
        std_dev = math.sqrt(variance)
        
        # 标准差太小，无法计算有意义的夏普比率
        if std_dev < 0.001:
            return 0
        
        # 年化夏普比率
        daily_risk_free = risk_free_rate / 252
        sharpe = (avg_return - daily_risk_free) / std_dev * math.sqrt(252)
        
        # 限制范围在-999.99到999.99之间
        sharpe = max(-999.99, min(999.99, sharpe))
        
        return round(sharpe, 2)
    
    def calculate_win_rate(self, trades: List[Dict]) -> float:
        """计算胜率"""
        if not trades:
            return 0
        
        wins = sum(1 for t in trades if t.get('actual_return', 0) > 0)
        return round(wins / len(trades) * 100, 2)
    
    @retry(max_attempts=3, delay=1)
    def record_daily(self) -> Dict:
        """记录每日收益"""
        holdings = self.get_current_holdings()
        
        total_invested = sum(h['amount'] for h in holdings)
        total_value = sum(h['current_value'] for h in holdings)
        total_profit = total_value - total_invested
        profit_rate = (total_profit / total_invested * 100) if total_invested > 0 else 0
        
        # 获取历史日收益（用于计算最大回撤和夏普）
        daily_returns = self.get_daily_returns(days=30)
        
        # 添加今日收益
        daily_returns.append(profit_rate)
        
        # 计算风险指标
        max_drawdown = self.calculate_max_drawdown(daily_returns)
        sharpe_ratio = self.calculate_sharpe_ratio(daily_returns)
        
        # 计算胜率（从trades表）
        win_rate = self.calculate_win_rate_from_trades()
        
        # 保存到数据库
        if not self.conn:
            self.connect()
        
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO portfolio_daily (trade_date, total_invested, total_value, 
                                           total_profit, profit_rate, daily_return,
                                           max_drawdown, sharpe_ratio, win_rate)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    total_invested = VALUES(total_invested),
                    total_value = VALUES(total_value),
                    total_profit = VALUES(total_profit),
                    profit_rate = VALUES(profit_rate),
                    daily_return = VALUES(daily_return),
                    max_drawdown = VALUES(max_drawdown),
                    sharpe_ratio = VALUES(sharpe_ratio),
                    win_rate = VALUES(win_rate)
            """, (
                date.today(),
                total_invested,
                total_value,
                total_profit,
                profit_rate,
                profit_rate,  # 当日收益
                max_drawdown,
                sharpe_ratio,
                win_rate
            ))
        self.conn.commit()
        
        return {
            'trade_date': date.today().isoformat(),
            'total_invested': total_invested,
            'total_value': round(total_value, 2),
            'total_profit': round(total_profit, 2),
            'profit_rate': round(profit_rate, 2),
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'win_rate': win_rate,
            'holdings_count': len(holdings),
        }
    
    @fallback(default_value=[])
    def get_daily_returns(self, days: int = 30) -> List[float]:
        """获取最近N天的日收益率"""
        if not self.conn:
            self.connect()
        
        with self.conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("""
                SELECT daily_return
                FROM portfolio_daily
                WHERE trade_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                ORDER BY trade_date
            """, (days,))
            rows = cur.fetchall()
            return [float(r['daily_return']) for r in rows if r['daily_return'] is not None]
    
    @fallback(default_value=0)
    def calculate_win_rate_from_trades(self) -> float:
        """从trades表计算胜率"""
        if not self.conn:
            self.connect()
        
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN actual_return > 0 THEN 1 ELSE 0 END) as wins
                FROM trades
                WHERE actual_return IS NOT NULL
            """)
            row = cur.fetchone()
            if row and row[0] > 0:
                return round(row[1] / row[0] * 100, 2)
            return 0
    
    @fallback(default_value={})
    def generate_curve(self, days: int = 30) -> Dict:
        """生成收益曲线数据"""
        if not self.conn:
            self.connect()
        
        with self.conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("""
                SELECT trade_date, total_value, daily_return, max_drawdown
                FROM portfolio_daily
                WHERE trade_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                ORDER BY trade_date
            """, (days,))
            records = cur.fetchall()
        
        return {
            'dates': [r['trade_date'].isoformat() for r in records],
            'values': [float(r['total_value']) for r in records],
            'returns': [float(r['daily_return']) for r in records if r['daily_return'] is not None],
            'drawdowns': [float(r['max_drawdown']) for r in records if r['max_drawdown'] is not None],
        }
    
    @fallback(default_value={})
    def get_summary(self) -> Dict:
        """获取组合摘要"""
        if not self.conn:
            self.connect()
        
        with self.conn.cursor(pymysql.cursors.DictCursor) as cur:
            # 最新记录
            cur.execute("""
                SELECT * FROM portfolio_daily
                ORDER BY trade_date DESC LIMIT 1
            """)
            latest = cur.fetchone()
            
            # 历史统计
            cur.execute("""
                SELECT 
                    COUNT(*) as total_days,
                    AVG(daily_return) as avg_daily_return,
                    MAX(daily_return) as best_day,
                    MIN(daily_return) as worst_day,
                    SUM(CASE WHEN daily_return > 0 THEN 1 ELSE 0 END) as up_days,
                    SUM(CASE WHEN daily_return < 0 THEN 1 ELSE 0 END) as down_days
                FROM portfolio_daily
            """)
            stats = cur.fetchone()
        
        if not latest:
            return {}
        
        return {
            'latest_date': latest['trade_date'].isoformat(),
            'total_invested': float(latest['total_invested']),
            'total_value': float(latest['total_value']),
            'total_profit': float(latest['total_profit']),
            'profit_rate': float(latest['profit_rate']),
            'max_drawdown': float(latest['max_drawdown']),
            'sharpe_ratio': float(latest['sharpe_ratio']),
            'win_rate': float(latest['win_rate']),
            'total_days': stats['total_days'],
            'avg_daily_return': float(stats['avg_daily_return'] or 0),
            'best_day': float(stats['best_day'] or 0),
            'worst_day': float(stats['worst_day'] or 0),
            'up_days': stats['up_days'],
            'down_days': stats['down_days'],
        }


def main():
    """主函数"""
    tracker = PortfolioTracker()
    
    try:
        tracker.connect()
        
        if len(sys.argv) > 1 and sys.argv[1] == '--summary':
            # 显示摘要
            summary = tracker.get_summary()
            if summary:
                print(f"📊 组合摘要（{summary['latest_date']}）")
                print(f"  总投入: ¥{summary['total_invested']:.0f}")
                print(f"  总市值: ¥{summary['total_value']:.0f}")
                print(f"  总盈亏: ¥{summary['total_profit']:.0f} ({summary['profit_rate']:.2f}%)")
                print(f"  最大回撤: {summary['max_drawdown']:.2f}%")
                print(f"  夏普比率: {summary['sharpe_ratio']:.2f}")
                print(f"  胜率: {summary['win_rate']:.2f}%")
                print(f"  记录天数: {summary['total_days']}")
            else:
                print("暂无数据")
        
        elif len(sys.argv) > 1 and sys.argv[1] == '--curve':
            # 显示收益曲线
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
            curve = tracker.generate_curve(days)
            if curve['dates']:
                print(f"📈 收益曲线（最近{days}天）")
                for i, (d, v) in enumerate(zip(curve['dates'], curve['values'])):
                    print(f"  {d}: ¥{v:.0f}")
            else:
                print("暂无数据")
        
        else:
            # 记录今日收益
            print("[收益记录] 开始运行...")
            result = tracker.record_daily()
            print(f"✅ 记录完成")
            print(f"  日期: {result['trade_date']}")
            print(f"  总投入: ¥{result['total_invested']:.0f}")
            print(f"  总市值: ¥{result['total_value']:.0f}")
            print(f"  总盈亏: ¥{result['total_profit']:.0f} ({result['profit_rate']:.2f}%)")
            print(f"  最大回撤: {result['max_drawdown']:.2f}%")
            print(f"  夏普比率: {result['sharpe_ratio']:.2f}")
            print(f"  胜率: {result['win_rate']:.2f}%")
    
    finally:
        tracker.close()


if __name__ == "__main__":
    main()
