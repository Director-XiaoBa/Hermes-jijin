#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基金信号评分引擎
多维度打分，只推高质量信号（7分以上）
"""
import json
import pymysql
from datetime import datetime, date
from typing import Dict, List, Optional

# 导入共享模块
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from fund_common import get_holdings, get_fund_sectors, get_connection
from fund_error_handler import retry, fallback, log_error

# 数据库配置
DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3306,
    'user': 'fund_admin',
    'password': 'FundR2026!db',
    'database': 'fund_research',
    'charset': 'utf8mb4'
}

# 信号评分权重
SCORE_WEIGHTS = {
    'rsi': 2,        # RSI位置（0-2分）
    'trend': 2,      # 趋势确认（0-2分）
    'pattern': 2,    # 形态确认（0-2分）
    'position': 2,   # 位置标签（0-2分）
    'flow': 2,       # 资金流向（0-2分）
}

# 高质量信号阈值
HIGH_SCORE_THRESHOLD = 7


class SignalEngine:
    """信号评分引擎"""
    
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
    def get_indicators(self, fund_code: str) -> Dict:
        """
        获取基金技术指标
        返回: {rsi_6, trend, price_pattern, position_label, net_flow}
        """
        if not self.conn:
            self.connect()
        
        with self.conn.cursor(pymysql.cursors.DictCursor) as cur:
            # 获取最新技术指标
            cur.execute("""
                SELECT rsi_6, trend, price_pattern, position_label
                FROM nav_daily 
                WHERE fund_code = %s 
                ORDER BY trade_date DESC 
                LIMIT 1
            """, (fund_code,))
            nav_data = cur.fetchone()
            
            # 获取资金流向（使用sector_flow_daily表）
            cur.execute("""
                SELECT main_netflow
                FROM sector_flow_daily 
                WHERE trade_date = CURDATE()
                LIMIT 1
            """)
            flow_data = cur.fetchone()
            
            result = {
                'rsi_6': nav_data.get('rsi_6') if nav_data and nav_data.get('rsi_6') is not None else 50,
                'trend': nav_data.get('trend') if nav_data and nav_data.get('trend') is not None else '震荡',
                'price_pattern': nav_data.get('price_pattern') if nav_data and nav_data.get('price_pattern') is not None else '横盘',
                'position_label': nav_data.get('position_label') if nav_data and nav_data.get('position_label') is not None else '中部',
                'net_flow': float(flow_data.get('main_netflow', 0)) / 100000000 if flow_data else 0,
            }
            
            return result
    
    def calculate_score(self, fund_code: str, indicators: Dict) -> float:
        """
        计算信号评分（0-10分）
        
        评分维度：
        1. RSI位置（2分）：超卖30以下=2分，30-50=1分，50以上=0分
        2. 趋势确认（2分）：上升=2分，震荡=1分，下降=0分
        3. 形态确认（2分）：探底回升=2分，横盘=1分，冲高回落=0分
        4. 位置标签（2分）：底部=2分，中部=1分，顶部=0分
        5. 资金流向（2分）：大幅流入=2分，小幅流入=1分，流出=0分
        """
        score = 0
        
        # 1. RSI评分
        rsi = indicators.get('rsi_6', 50)
        if rsi < 30:
            score += SCORE_WEIGHTS['rsi']  # 超卖，满分
        elif rsi < 50:
            score += SCORE_WEIGHTS['rsi'] / 2  # 中性，半分
        
        # 2. 趋势评分（支持中英文）
        trend = indicators.get('trend', '震荡')
        if trend in ('上升', 'up'):
            score += SCORE_WEIGHTS['trend']
        elif trend in ('震荡', 'sideways'):
            score += SCORE_WEIGHTS['trend'] / 2
        
        # 3. 形态评分（支持完整形态名）
        pattern = indicators.get('price_pattern', '横盘')
        if pattern in ('探底回升', '小阳线', '大涨', '低开高走'):
            score += SCORE_WEIGHTS['pattern']
        elif pattern in ('横盘', '小涨', '小跌', '小阴线', '中阴线', '中阳线'):
            score += SCORE_WEIGHTS['pattern'] / 2
        
        # 4. 位置评分（支持"low-high"格式）
        position = indicators.get('position_label', '中部')
        pos_pct = self._parse_position(position)
        if pos_pct < 30:
            score += SCORE_WEIGHTS['position']
        elif pos_pct < 70:
            score += SCORE_WEIGHTS['position'] / 2
        
        # 5. 资金流向评分
        flow = indicators.get('net_flow', 0)
        if flow > 1:
            score += SCORE_WEIGHTS['flow']
        elif flow > 0:
            score += SCORE_WEIGHTS['flow'] / 2
        
        return round(score, 1)
    
    def _parse_position(self, position: str) -> float:
        """
        解析位置标签，返回0-100的百分比
        支持两种格式：
        - "底部/中部/顶部" → 10/50/90
        - "low-high" (如 "2.5488-3.0860") → 返回中间位置
        """
        if position in ('底部', 'bottom'):
            return 10
        elif position in ('顶部', 'top'):
            return 90
        elif position in ('中部', 'middle'):
            return 50
        
        # 解析 "low-high" 格式
        try:
            parts = position.split('-')
            if len(parts) == 2:
                low = float(parts[0])
                high = float(parts[1])
                if high > low:
                    return 50  # 默认中间位置
        except (ValueError, TypeError):
            pass
        
        return 50  # 默认中部
    
    def determine_signal_type(self, score: float, indicators: Dict) -> str:
        """
        根据评分和指标判断信号类型
        """
        rsi = indicators.get('rsi_6', 50)
        trend = indicators.get('trend', '震荡')
        position = indicators.get('position_label', '中部')
        pos_pct = self._parse_position(position)
        
        # 买入信号：评分>=3 且（超卖或底部位置）
        if score >= 3 and (rsi < 40 or pos_pct < 30):
            return 'buy'
        
        # 卖出信号：评分<=3 且（超买或顶部位置）
        elif score <= 3 and (rsi > 70 or pos_pct > 70):
            return 'sell'
        
        # 其他 = 持有
        else:
            return 'hold'
    
    def generate_reason(self, fund_code: str, indicators: Dict, score: float) -> str:
        """
        生成信号理由
        """
        rsi = indicators.get('rsi_6', 50)
        trend = indicators.get('trend', '震荡')
        pattern = indicators.get('price_pattern', '横盘')
        position = indicators.get('position_label', '中部')
        flow = indicators.get('net_flow', 0)
        pos_pct = self._parse_position(position)
        
        reasons = []
        
        if rsi < 30:
            reasons.append(f"RSI={rsi:.1f}超卖")
        elif rsi < 50:
            reasons.append(f"RSI={rsi:.1f}中性")
        
        if trend in ('上升', 'up'):
            reasons.append("上升趋势")
        elif trend in ('下降', 'down'):
            reasons.append("下降趋势")
        
        if pattern in ('探底回升', '小阳线', '低开高走'):
            reasons.append("探底回升形态")
        elif pattern in ('冲高回落', '中阴线', '小阴线'):
            reasons.append("冲高回落形态")
        
        if pos_pct < 30:
            reasons.append("底部位置")
        elif pos_pct > 70:
            reasons.append("顶部位置")
        
        if flow > 1:
            reasons.append(f"资金大幅流入{flow:.1f}亿")
        elif flow > 0:
            reasons.append(f"资金小幅流入{flow:.1f}亿")
        
        return f"评分{score}/10: " + ", ".join(reasons) if reasons else f"评分{score}/10"
    
    @retry(max_attempts=3, delay=1)
    def save_signal(self, fund_code: str, signal_type: str, score: float, 
                    confidence: float, reason: str, indicators: Dict, 
                    market_state: str = None):
        """
        保存信号到数据库
        """
        if not self.conn:
            self.connect()
        
        # 转换Decimal为float
        indicators_json = {}
        for k, v in indicators.items():
            if hasattr(v, 'as_tuple'):  # Decimal
                indicators_json[k] = float(v)
            else:
                indicators_json[k] = v
        
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO signals (fund_code, signal_date, source, direction, 
                                    confidence, reason, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                fund_code,
                date.today(),
                'signal_engine',
                signal_type,
                confidence,
                reason,
                json.dumps({'score': score, 'indicators': indicators_json}, ensure_ascii=False)
            ))
        self.conn.commit()
    
    @fallback(default_value=[])
    def generate_signals(self) -> List[Dict]:
        """
        为所有持仓基金生成信号
        返回: [{fund_code, signal_type, score, reason, indicators}, ...]
        """
        holdings = get_holdings()
        signals = []
        
        for h in holdings:
            fund_code = h['fund_code']
            
            # 获取指标
            indicators = self.get_indicators(fund_code)
            
            # 计算评分
            score = self.calculate_score(fund_code, indicators)
            
            # 判断信号类型
            signal_type = self.determine_signal_type(score, indicators)
            
            # 生成理由
            reason = self.generate_reason(fund_code, indicators, score)
            
            # 计算置信度（基于评分）
            confidence = min(score / 10, 1.0)
            
            # 保存信号
            self.save_signal(fund_code, signal_type, score, confidence, reason, indicators)
            
            # 只返回买入或卖出信号
            if signal_type in ['buy', 'sell']:
                signals.append({
                    'fund_code': fund_code,
                    'fund_name': h['fund_name'],
                    'signal_type': signal_type,
                    'score': score,
                    'confidence': confidence,
                    'reason': reason,
                    'indicators': indicators
                })
        
        return signals
    
    def get_recent_signals(self, days: int = 7) -> List[Dict]:
        """
        获取最近N天的信号
        """
        if not self.conn:
            self.connect()
        
        with self.conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("""
                SELECT s.*, f.name as fund_name
                FROM signals s
                LEFT JOIN funds f ON s.fund_code = f.code
                WHERE s.signal_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                ORDER BY s.confidence DESC, s.signal_date DESC
            """, (days,))
            return cur.fetchall()


# 命令行入口
if __name__ == "__main__":
    import sys
    
    engine = SignalEngine()
    
    try:
        engine.connect()
        
        if len(sys.argv) > 1 and sys.argv[1] == '--recent':
            # 显示最近信号
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
            signals = engine.get_recent_signals(days)
            print(f"最近{days}天的信号：")
            for s in signals:
                print(f"  {s.get('fund_name', s['fund_code'])} | {s['direction']} | 置信度:{s['confidence']} | {s['reason']}")
        else:
            # 生成新信号
            print("正在生成信号...")
            signals = engine.generate_signals()
            
            if signals:
                print(f"\n高质量信号（{len(signals)}条）：")
                for s in signals:
                    emoji = '🟢' if s['signal_type'] == 'buy' else '🔴' if s['signal_type'] == 'sell' else '⚪'
                    print(f"  {emoji} {s['fund_name']}({s['fund_code']}) | {s['signal_type']} | 评分:{s['score']}/10")
                    print(f"     {s['reason']}")
            else:
                print("\n无高质量信号")
    
    finally:
        engine.close()
