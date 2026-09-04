#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易净值回填脚本 v2
22:00净值更新后自动运行，把nav_daily的净值回填到trades表
包含：actual_sell_nav、actual_return、fee、hold_days
使用sell_date计算持有天数（不是CURDATE()）
"""

import pymysql
from datetime import datetime, timedelta

DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3306,
    'user': 'fund_admin',
    'password': '<REDACTED>',
    'database': 'fund_research',
    'charset': 'utf8mb4'
}

def get_connection():
    return pymysql.connect(**DB_CONFIG)

def calc_fee(fund_name, amount, hold_days):
    """计算C类基金赎回手续费：持有<7天=1.5%，>=7天=0%"""
    is_c = 'C' in fund_name or 'c' in fund_name
    if is_c and hold_days < 7:
        return round(float(amount) * 0.015, 4)
    return 0.0

def backfill_sell_nav():
    """回填已卖出交易的实际卖出净值、收益率、手续费、持有天数"""
    conn = get_connection()
    cur = conn.cursor()
    
    # 找出所有已卖出但没有actual_sell_nav的交易
    cur.execute("""
        SELECT id, fund_code, fund_name, amount, nav_price, trade_date, sell_date, trade_status
        FROM trades 
        WHERE trade_status = '已卖出' 
          AND actual_sell_nav IS NULL
        ORDER BY trade_date, id
    """)
    
    trades = cur.fetchall()
    
    if not trades:
        print("✅ 无需回填：所有已卖出交易都有actual_sell_nav")
        return
    
    print(f"📋 待回填交易：{len(trades)}笔")
    print()
    
    updated = 0
    failed = 0
    
    for trade in trades:
        trade_id, fund_code, fund_name, amount, nav_price, trade_date, sell_date, trade_status = trade
        
        # 使用sell_date计算持有天数（不是CURDATE()）
        if sell_date:
            if isinstance(trade_date, str):
                trade_date_obj = datetime.strptime(trade_date, '%Y-%m-%d').date()
            else:
                trade_date_obj = trade_date
            if isinstance(sell_date, str):
                sell_date_obj = datetime.strptime(sell_date, '%Y-%m-%d').date()
            else:
                sell_date_obj = sell_date
            hold_days = (sell_date_obj - trade_date_obj).days
        else:
            # 如果没有sell_date，用今天
            hold_days = 0
            print(f"  ⚠️ #{trade_id} {fund_name[:8]} | 缺少sell_date，默认hold_days=0")
        
        # 尝试从nav_daily获取最近的净值（卖出日期或之后）
        cur.execute("""
            SELECT nav, trade_date 
            FROM nav_daily 
            WHERE fund_code = %s 
              AND trade_date >= %s
            ORDER BY trade_date ASC 
            LIMIT 1
        """, (fund_code, sell_date or trade_date))
        
        nav_row = cur.fetchone()
        
        if nav_row:
            actual_nav, nav_date = nav_row
            actual_return = round((float(actual_nav) - float(nav_price)) / float(nav_price) * 100, 4)
            fee = calc_fee(fund_name, amount, hold_days)
            
            cur.execute("""
                UPDATE trades 
                SET actual_sell_nav = %s, 
                    actual_return = %s,
                    fee = %s,
                    hold_days = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (actual_nav, actual_return, fee, hold_days, trade_id))
            
            profit_yuan = round(float(amount) * actual_return / 100, 2)
            net_profit = round(profit_yuan - fee, 2)
            sign = "+" if profit_yuan >= 0 else ""
            fee_str = f"费¥{fee:.2f}" if fee > 0 else "免赎回费"
            
            print(f"  ✅ #{trade_id} {fund_name[:8]} | 买入{nav_price} → 卖出{actual_nav} | {sign}{actual_return:.2f}% | {sign}¥{profit_yuan} | {fee_str} | 持有{hold_days}天")
            updated += 1
        else:
            print(f"  ❌ #{trade_id} {fund_name[:8]} | {fund_code} 在 {sell_date or trade_date} 之后无净值数据")
            failed += 1
    
    conn.commit()
    
    print()
    print(f"{'='*60}")
    print(f"  回填完成：成功 {updated} 笔，失败 {failed} 笔")
    
    # 输出总账
    if updated > 0:
        cur.execute("""
            SELECT 
                COUNT(*) as trades,
                SUM(amount) as total_invested,
                ROUND(SUM(amount * actual_return / 100), 2) as market_loss,
                ROUND(SUM(fee), 2) as total_fee,
                ROUND(SUM(amount * actual_return / 100) - SUM(fee), 2) as net_loss
            FROM trades 
            WHERE trade_status = '已卖出' AND actual_sell_nav IS NOT NULL
        """)
        
        row = cur.fetchone()
        if row:
            trades_cnt, invested, market_loss, total_fee, net_loss = row
            print(f"  总投入：¥{invested:.0f}")
            print(f"  市值亏损：¥{market_loss:.2f}")
            print(f"  手续费：¥{total_fee:.2f}")
            print(f"  净亏损：¥{net_loss:.2f}")
            if invested > 0:
                print(f"  收益率：{net_loss/invested*100:.2f}%")
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    print(f"{'='*60}")
    print(f"📊 交易净值回填 v2 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    print()
    backfill_sell_nav()
