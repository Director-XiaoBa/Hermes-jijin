#!/usr/bin/env python3
"""
14:00扫描持久化 — 两层保存
Layer 1: MySQL scan_recommendations表（结构化数据，可查询）
Layer 2: 文件归档 ~/fund-reports/1400/YYYY-MM-DD/report.md（完整报告）


用法:
    python3 fund_persist_1400.py                    # 自动读取最新数据
    python3 fund_persist_1400.py --report /tmp/final.md  # 指定报告文件
"""
import json, os, sys
from datetime import datetime, date

import pymysql

DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3306,
    'user': 'fund_admin',
    'password': 'FundR2026!db',
    'database': 'fund_research',
    'charset': 'utf8mb4'
}

REPORT_ARCHIVE = os.path.expanduser("~/fund-reports/1400")
def get_connection():
    return pymysql.connect(**DB_CONFIG)

def load_scan_data():
    """从scan_summary.json加载市场数据"""
    path = "/tmp/fund_data/scan_summary.json"
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)

def extract_market_snapshot(data):
    """提取市场快照"""
    sources = data.get('sources', {})
    indices = sources.get('indices_holdings', {}).get('data', {}).get('indices', [])
    
    snapshot = {}
    for idx in indices:
        name = idx.get('name', '')
        if '上证' in name:
            snapshot['sh_index'] = idx.get('price')
            snapshot['sh_change_pct'] = idx.get('pct')
        elif '创业板' in name:
            snapshot['sz_index'] = idx.get('price')
            snapshot['sz_change_pct'] = idx.get('pct')
        elif '科创50' in name:
            snapshot['kc_index'] = idx.get('price')
            snapshot['kc_change_pct'] = idx.get('pct')
    
    stats = data.get('stats', {})
    snapshot['data_sources_ok'] = stats.get('ok', 0)
    
    return snapshot

def save_to_mysql(scan_time, snapshot, danger_signal, has_catalyst, 
                  position_pct, recommendation, confidence, reasoning, 
                  catalyst_summary, signal_count):
    """Layer 1: 写入MySQL"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO scan_recommendations 
                (scan_date, scan_time, scan_type,
                 sh_index, sh_change_pct, sz_index, sz_change_pct,
                 kc_index, kc_change_pct,
                 danger_signal, has_catalyst, position_pct,
                 recommendation, confidence, reasoning,
                 catalyst_summary, signal_count, data_sources_ok)
                VALUES (%s, %s, '1400',
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                date.today(), scan_time,
                snapshot.get('sh_index'), snapshot.get('sh_change_pct'),
                snapshot.get('sz_index'), snapshot.get('sz_change_pct'),
                snapshot.get('kc_index'), snapshot.get('kc_change_pct'),
                danger_signal, has_catalyst, position_pct,
                recommendation, confidence, reasoning,
                catalyst_summary, signal_count, snapshot.get('data_sources_ok', 0)
            ))
        conn.commit()
        return True
    except Exception as e:
        print(f"  MySQL写入失败: {e}", file=sys.stderr)
        return False
    finally:
        conn.close()

def save_report_archive(scan_date, report_content):
    """Layer 2: 文件归档"""
    day_dir = os.path.join(REPORT_ARCHIVE, scan_date)
    os.makedirs(day_dir, exist_ok=True)
    
    report_path = os.path.join(day_dir, "report.md")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_content)
    
    return report_path

def parse_analysis_from_report(report_path):
    """从报告中解析3问题框架的分析数据"""
    danger_signal = 0
    has_catalyst = 0
    position_pct = 0
    recommendation = 'watch'
    confidence = 3
    reasoning = ''
    catalyst_summary = ''
    
    if not os.path.exists(report_path):
        return danger_signal, has_catalyst, position_pct, recommendation, confidence, reasoning, catalyst_summary
    
    with open(report_path, encoding='utf-8') as f:
        content = f.read()
    
    # 解析3问题框架
    # 问题1: 危险信号
    danger_keywords = ['危险信号', '不买', '等一等', '等结果', '观望', '等企稳']
    if any(kw in content for kw in danger_keywords):
        danger_signal = 1
    
    # 问题2: 有催化剂
    if '有催化剂' in content or '有理由' in content or '可以买' in content or '可以考虑' in content:
        has_catalyst = 1
    
    # 问题3: 仓位比例
    if '30%' in content or '30%仓位' in content:
        position_pct = 30
    elif '10%' in content or '10%仓位' in content:
        position_pct = 10
    else:
        position_pct = 0
    
    # 解析建议
    if position_pct > 0 and danger_signal == 0:
        recommendation = 'buy'
        confidence = 4 if position_pct >= 30 else 3
    elif danger_signal == 1:
        recommendation = 'cautious'
        confidence = 2
    else:
        recommendation = 'watch'
        confidence = 3
    
    # 提取催化剂摘要
    if '## 7. 催化剂分析' in content:
        start = content.index('## 7. 催化剂分析') + len('## 7. 催化剂分析')
        end = content.index('---', start) if '---' in content[start:] else len(content)
        catalyst_summary = content[start:end].strip()[:500]
    
    # 提取分析理由
    if '## 8. 操作建议' in content:
        start = content.index('## 8. 操作建议') + len('## 8. 操作建议')
        end = content.index('---', start) if '---' in content[start:] else len(content)
        reasoning = content[start:end].strip()[:500]
    
    return danger_signal, has_catalyst, position_pct, recommendation, confidence, reasoning, catalyst_summary

def main():
    report_path = None
    if '--report' in sys.argv:
        idx = sys.argv.index('--report')
        if idx + 1 < len(sys.argv):
            report_path = sys.argv[idx + 1]
    
    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scan_date = date.today().isoformat()
    
    print(f"[{scan_time}] 两层持久化开始...")
    
    # 加载数据
    data = load_scan_data()
    if not data:
        print("  ❌ 无扫描数据", file=sys.stderr)
        sys.exit(1)
    
    snapshot = extract_market_snapshot(data)
    
    # 如果没有指定报告文件，尝试读取最新生成的
    if not report_path:
        default_report = "/tmp/fund_data/report_data.md"
        if os.path.exists(default_report):
            report_path = default_report
    
    # 解析分析数据（3问题框架）
    danger_signal, has_catalyst, position_pct, recommendation, confidence, reasoning, catalyst_summary = parse_analysis_from_report(report_path)
    
    # 统计信号数
    signals = data.get('signals', [])
    signal_count = len(signals)
    
    # Layer 1: MySQL
    mysql_ok = save_to_mysql(scan_time, snapshot, danger_signal, has_catalyst,
                             position_pct, recommendation, confidence, reasoning,
                             catalyst_summary, signal_count)
    print(f"  {'✅' if mysql_ok else '❌'} MySQL: scan_recommendations")
    
    # Layer 2: 文件归档
    if report_path and os.path.exists(report_path):
        archive_path = save_report_archive(scan_date, open(report_path, encoding='utf-8').read())
        print(f"  ✅ 归档: {archive_path}")
    else:
        print("  ⚠️ 无报告文件，跳过归档")
    
    
    print(f"[{scan_time}] 两层持久化完成")

if __name__ == "__main__":
    main()
