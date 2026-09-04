#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
14:00任务增强 - 添加分量评估和综合判断
"""

import pymysql
from datetime import datetime

DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3306,
    'user': 'fund_admin',
    'password': '<REDACTED>',
    'database': 'fund_research',
    'charset': 'utf8mb4'
}

TIME_WEIGHTS = {'short': 0.7, 'medium': 0.2, 'long': 0.1}


def get_connection():
    return pymysql.connect(**DB_CONFIG)


def determine_time_horizon(time_horizon):
    if time_horizon in ['1d', '3d', '5d', 'short']:
        return 'short', TIME_WEIGHTS['short']
    elif time_horizon in ['1w', '2w', 'medium']:
        return 'medium', TIME_WEIGHTS['medium']
    elif time_horizon in ['1m', '3m', 'long']:
        return 'long', TIME_WEIGHTS['long']
    else:
        return 'medium', TIME_WEIGHTS['medium']


def get_recent_predictions(days=7):
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


def analyze_event(event):
    confidence = event.get('confidence', 3)
    weight = event.get('weight', 3.0)
    direction = '中性'
    
    if any(word in event['prediction'] for word in ['利好', '正面', '支撑', '反弹']):
        direction = '利好'
    elif any(word in event['prediction'] for word in ['利空', '负面', '承压', '下跌', '低开']):
        direction = '利空'
    
    time_horizon = event.get('time_horizon', 'medium')
    time_dim, time_weight = determine_time_horizon(time_horizon)
    weighted_weight = float(weight) * time_weight
    
    return {
        'confidence': confidence,
        'weight': float(weight),
        'time_horizon': time_dim,
        'time_weight': time_weight,
        'weighted_weight': weighted_weight,
        'direction': direction
    }


def analyze_events(events):
    bullish_score = 0.0
    bearish_score = 0.0
    
    for event in events:
        analysis = analyze_event(event)
        if analysis['direction'] == '利好':
            bullish_score += analysis['weighted_weight']
        elif analysis['direction'] == '利空':
            bearish_score += analysis['weighted_weight']
    
    net_score = bearish_score - bullish_score
    
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


def generate_enhanced_report(days=7):
    predictions = get_recent_predictions(days)
    
    if not predictions:
        return "暂无预测记录"
    
    analysis = analyze_events(predictions)
    
    report = "## 10. 分量评估（新增）\n\n"
    report += "### 利空分量\n\n"
    report += "| 事件 | 置信度 | 影响力 | 分量 |\n"
    report += "|------|--------|--------|------|\n"
    
    bearish_events = [e for e in predictions if any(word in e['prediction'] for word in ['利空', '负面', '承压', '下跌', '低开'])]
    if bearish_events:
        for event in bearish_events[:5]:
            analysis_result = analyze_event(event)
            report += "| %s %s | %d | %.2f | %.2f |\n" % (
                event['prediction_date'], event['target'][:20],
                event['confidence'], analysis_result['weight'], analysis_result['weighted_weight'])
    else:
        report += "| 无利空事件 | - | - | - |\n"
    
    report += "\n> **利空总分量**：%.2f\n\n" % analysis['bearish_score']
    
    report += "### 利好分量\n\n"
    report += "| 事件 | 置信度 | 影响力 | 分量 |\n"
    report += "|------|--------|--------|------|\n"
    
    bullish_events = [e for e in predictions if any(word in e['prediction'] for word in ['利好', '正面', '支撑', '反弹'])]
    if bullish_events:
        for event in bullish_events[:5]:
            analysis_result = analyze_event(event)
            report += "| %s %s | %d | %.2f | %.2f |\n" % (
                event['prediction_date'], event['target'][:20],
                event['confidence'], analysis_result['weight'], analysis_result['weighted_weight'])
    else:
        report += "| 无利好事件 | - | - | - |\n"
    
    report += "\n> **利好总分量**：%.2f\n\n" % analysis['bullish_score']
    
    report += "### 综合判断\n\n"
    report += "| 指标 | 数值 |\n"
    report += "|------|------|\n"
    report += "| 利空分量 | %.2f |\n" % analysis['bearish_score']
    report += "| 利好分量 | %.2f |\n" % analysis['bullish_score']
    report += "| 综合分量 | %.2f |\n" % analysis['net_score']
    report += "| 市场情绪 | %s |\n" % analysis['judgment']
    report += "| 操作建议 | %s |\n" % analysis['suggestion']
    report += "\n---\n"
    
    return report


if __name__ == "__main__":
    report = generate_enhanced_report(7)
    print(report)
