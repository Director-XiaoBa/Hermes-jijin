#!/usr/bin/env python3
"""
14:00扫描持久化 — 记录扫描完成状态
追加决策日志，标记扫描时间。

用法:
    python3 fund_persist_1400.py
"""
import json, os, sys
from datetime import datetime

def append_decision_log(scan_time):
    """追加决策日志"""
    log_path = os.path.expanduser("~/user_files/documents/基金决策日志.md")
    entry = f"\n\n---\n## {scan_time} 盘中扫描\n"
    entry += "- 状态: 扫描完成，报告已推送\n"
    try:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(entry)
        return True
    except Exception as e:
        print(f"  ⚠️ 写入决策日志失败: {e}", file=sys.stderr)
        return False

def main():
    summary_path = "/tmp/fund_data/scan_summary.json"
    if not os.path.exists(summary_path):
        print("❌ scan_summary.json不存在", file=sys.stderr)
        sys.exit(1)

    with open(summary_path) as f:
        summary = json.load(f)

    collected_at = summary.get('collected_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    stats = summary.get('stats', {})

    print(f"[{collected_at}] 持久化...")

    log_ok = append_decision_log(collected_at)
    print(f"  {'✅' if log_ok else '⚠️'} 决策日志: {'追加成功' if log_ok else '写入失败'}")
    print(f"[{collected_at}] 持久化完成")

if __name__ == "__main__":
    main()
