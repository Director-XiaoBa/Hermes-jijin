#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基金分析系统升级 - 分量评估、时间维度分析、综合判断

核心改进：
1. 分量评估：从数量统计升级为分量评估
2. 时间维度：区分短期、中期、长期的影响
3. 综合判断：根据分量和时间维度给出综合建议
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

# 影响力系数
IMPACT_FACTORS = {
    '重大': 1.5,
    '重要': 1.2,
    '一般': 1.0,
    '轻微': 0.8
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


def assess_impact_level(confidence: int, event_type: str) -> str:
    """
    评估事件影响力级别
    
    Args:
        confidence: 置信度（1-5）
        event_type: 事件类型
    
    Returns:
        影响力级别：重大、重要、一般、轻微
    """
    if confidence >= 5:
        return '重大'
    elif confidence >= 4:
        return '重要'
    elif confidence >= 3:
        return '一般'
    else:
        return '轻微'


def calculate_weight(confidence: int, impact_level: str) -> float:
    """
    计算事件分量
    
    Args:
        confidence: 置信度（1-5）
        impact_level: 影响力级别
    
    Returns:
        分量值
    """
    impact_factor = IMPACT_FACTORS.get(impact_level, 1.0)
    return confidence * impact_factor


def determine_time_horizon(time_horizon: str) -> Tuple[str, float]:
    """
    确定时间维度和权重
    
    Args:
        time_horizon: 时间范围（short/medium/long）
    
    Returns:
        (时间维度名称, 权重)
    """
    if time_horizon in ['1d', '3d', '5d', 'short']:
        return 'short', TIME_WEIGHTS['short']
    elif time_horizon in ['1w', '2w', 'medium']:
        return 'medium', TIME_WEIGHTS['medium']
    elif time_horizon in ['1m', '3m', 'long']:
        return 'long', TIME_WEIGHTS['long']
    else:
        return 'medium', TIME_WEIGHTS['medium']


def analyze_event(event: Dict) -> Dict:
    """
    分析单个事件的分量和时间维度
    
    Args:
        event: 事件信息
    
    Returns:
        分析结果
    """
    confidence = event.get('confidence', 3)
    event_type = event.get('event_type', '其他')
    direction = event.get('direction', '中性')
    time_horizon = event.get('time_horizon', 'medium')
    
    # 评估影响力级别
    impact_level = assess_impact_level(confidence, event_type)
    
    # 计算分量
    weight = calculate_weight(confidence, impact_level)
    
    # 确定时间维度和权重
    time_dim, time_weight = determine_time_horizon(time_horizon)
    
    # 计算加权分量
    weighted_weight = weight * time_weight
    
    return {
        'confidence': confidence,
        'impact_level': impact_level,
        'weight': weight,
        'time_horizon': time_dim,
        'time_weight': time_weight,
        'weighted_weight': weighted_weight,
        'direction': direction
    }


def analyze_events(events: List[Dict]) -> Dict:
    """
    分析多个事件的综合分量
    
    Args:
        events: 事件列表
    
    Returns:
        综合分析结果
    """
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


def get_recent_predictions(days: int = 7) -> List[Dict]:
    """
    获取最近的预测记录
    
    Args:
        days: 天数
    
    Returns:
        预测记录列表
    """
    conn = get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("""
                SELECT prediction_date, target, prediction, confidence, 
                       prediction_type, time_horizon
                FROM predictions
                WHERE prediction_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                ORDER BY prediction_date DESC, confidence DESC
            """, (days,))
            return cur.fetchall()
    finally:
        conn.close()


def generate_analysis_report(days: int = 7) -> str:
    """
    生成分析报告
    
    Args:
        days: 分析天数
    
    Returns:
        分析报告
    """
    predictions = get_recent_predictions(days)
    
    if not predictions:
        return "暂无预测记录"
    
    # 转换为事件格式
    events = []
    for pred in predictions:
        # 判断方向
        direction = '中性'
        if any(word in pred['prediction'] for word in ['利好', '正面', '支撑', '反弹']):
            direction = '利好'
        elif any(word in pred['prediction'] for word in ['利空', '负面', '承压', '下跌', '低开']):
            direction = '利空'
        
        events.append({
            'confidence': pred['confidence'],
            'event_type': pred.get('prediction_type', '其他'),
            'direction': direction,
            'time_horizon': pred.get('time_horizon', 'medium')
        })
    
    # 分析事件
    analysis = analyze_events(events)
    
    # 生成报告
    report = """
============================================================
📊 基金分析系统升级报告
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

### 利好事件
""" % (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), days,
       analysis['bullish_score'], analysis['bearish_score'], analysis['net_score'],
       analysis['judgment'], analysis['suggestion'])
    
    # 统计利好事件
    bullish_events = [e for e in events if e['direction'] == '利好']
    if bullish_events:
        for event in bullish_events:
            analysis_result = analyze_event(event)
            report += "- 置信度%d: 分量%.2f, 加权%.2f\n" % (
                event['confidence'], analysis_result['weight'], analysis_result['weighted_weight'])
    else:
        report += "- 无利好事件\n"
    
    report += "\n### 利空事件\n"
    
    # 统计利空事件
    bearish_events = [e for e in events if e['direction'] == '利空']
    if bearish_events:
        for event in bearish_events:
            analysis_result = analyze_event(event)
            report += "- 置信度%d: 分量%.2f, 加权%.2f\n" % (
                event['confidence'], analysis_result['weight'], analysis_result['weighted_weight'])
    else:
        report += "- 无利空事件\n"
    
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
