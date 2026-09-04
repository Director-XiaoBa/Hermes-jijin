#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
综合分析脚本 - 整合分量评估和时间维度分析

功能：
1. 获取最近的预测记录
2. 计算分量和时间维度权重
3. 生成综合分析报告
4. 给出操作建议
"""

import pymysql
from datetime import datetime, date
from typing import Dict, List, Tuple

# 数据库配置
DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3306,
    'user': 'fund_admin',
    'password': '<REDACTED>',
    'database': 'fund_research',
    'charset': 'utf8mb4'
}

# 时间维度权重
TIME_WEIGHTS = {
    'short': 0.7,    # 短期（1-2周）
    'medium': 0.2,   # 中期（1个月）
    'long': 0.1      # 长期（3个月）
}


def get_connection():
    """获取数据库连接"""
    return pymysql.connect(**DB_CONFIG)


def determine_time_horizon(time_horizon: str) -> Tuple[str, float]:
    """确定时间维度和权重"""
    if time_horizon in ['1d', '3d', '5d', 'short']:
        return 'short', TIME_WEIGHTS['short']
    elif time_horizon in ['1w', '2w', 'medium']:
        return 'medium', TIME_WEIGHTS['medium']
    elif time_horizon in ['1m', '3m', 'long']:
        return 'long', TIME_WEIGHTS['long']
    else:
        return 'medium', TIME_WEIGHTS['medium']


def get_recent_predictions(days: int = 7) -> List[Dict]:
    """获取最近的预测记录"""
    conn = get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("""
                SELECT prediction_date, target, prediction, confidence, 
                       weight, prediction_type, time_horizon
                FROM predictions
                WHERE prediction_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                ORDER BY prediction_date DESC, weight DESC
            """, (days,))
            return cur.fetchall()
    finally:
        conn.close()


def analyze_event(event: Dict) -> Dict:
    """分析单个事件的分量和时间维度"""
    confidence = event.get('confidence', 3)
    weight = event.get('weight', 3.0)
    direction = '中性'
    
    # 判断方向
    if any(word in event['prediction'] for word in ['利好', '正面', '支撑', '反弹']):
        direction = '利好'
    elif any(word in event['prediction'] for word in ['利空', '负面', '承压', '下跌', '低开']):
        direction = '利空'
    
    # 确定时间维度和权重
    time_horizon = event.get('time_horizon', 'medium')
    time_dim, time_weight = determine_time_horizon(time_horizon)
    
    # 计算加权分量
    weighted_weight = float(weight) * time_weight
    
    return {
        'confidence': confidence,
        'weight': weight,
        'time_horizon': time_dim,
        'time_weight': time_weight,
        'weighted_weight': weighted_weight,
        'direction': direction
    }


def analyze_events(events: List[Dict]) -> Dict:
    """分析多个事件的综合分量"""
    bullish_score = 0.0
    bearish_score = 0.0
    
    for event in events:
        analysis = analyze_event(event)
        
        if analysis['direction'] == '利好':
            bullish_score += analysis['weighted_weight']
        elif analysis['direction'] == '利空':
            bearish_score += analysis['weighted_weight']
    
    # 计算综合分量
    net_score = bearish_score - bullish_score
    
    # 判断市场情绪
    if net_score > 3:
        judgment = '强烈悲观'
        suggestion = '不加仓，观望，甚至减仓'
    elif net_score > 1:
        judgment = '悲观'
        suggestion = '不加仓，观望'
    elif net_score > -1:
        judgment = '中性'
        suggestion = '小仓试错'
    elif net_score > -3:
        judgment = '乐观'
        suggestion = '可以加仓'
    else:
        judgment = '强烈乐观'
        suggestion = '可以重仓'
    
    return {
        'bullish_score': bullish_score,
        'bearish_score': bearish_score,
        'net_score': net_score,
        'judgment': judgment,
        'suggestion': suggestion
    }


def generate_analysis_report(days: int = 7) -> str:
    """生成分析报告"""
    predictions = get_recent_predictions(days)
    
    if not predictions:
        return "暂无预测记录"
    
    # 分析事件
    analysis = analyze_events(predictions)
    
    # 生成报告
    report = """
============================================================
📊 基金综合分析报告
============================================================
分析时间: %s
分析天数: 最近%d天

## 分量评估结果

| 指标 | 数值 |
|------|------|
| 利好分量 | %.2f |
| 利空分量 | %.2f |
| 综合分量 | %.2f |

## 市场情绪判断

| 判断 | 结果 |
|------|------|
| 市场情绪 | %s |
| 操作建议 | %s |

## 详细分析

### 高分量事件（分量≥4）
""" % (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), days,
       analysis['bullish_score'], analysis['bearish_score'], analysis['net_score'],
       analysis['judgment'], analysis['suggestion'])
    
    # 统计高分量事件
    high_weight_events = [e for e in predictions if e.get('weight', 0) >= 4]
    if high_weight_events:
        for event in high_weight_events[:10]:  # 只显示前10个
            analysis_result = analyze_event(event)
            report += "- %s %s: 分量%.2f, 加权%.2f (%s)\n" % (
                event['prediction_date'], event['target'], 
                analysis_result['weight'], analysis_result['weighted_weight'],
                analysis_result['direction'])
    else:
        report += "- 无高分量事件\n"
    
    report += """
### 低分量事件（分量<4）
"""
    
    # 统计低分量事件
    low_weight_events = [e for e in predictions if e.get('weight', 0) < 4]
    if low_weight_events:
        for event in low_weight_events[:5]:  # 只显示前5个
            analysis_result = analyze_event(event)
            report += "- %s %s: 分量%.2f, 加权%.2f (%s)\n" % (
                event['prediction_date'], event['target'], 
                analysis_result['weight'], analysis_result['weighted_weight'],
                analysis_result['direction'])
    else:
        report += "- 无低分量事件\n"
    
    report += """
============================================================
总结：根据分量评估和时间维度分析，当前市场情绪为%s，建议%s。
============================================================
""" % (analysis['judgment'], analysis['suggestion'])
    
    return report


if __name__ == "__main__":
    # 生成分析报告
    report = generate_analysis_report(7)
    print(report)
