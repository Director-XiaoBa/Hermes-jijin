#!/usr/bin/env python3
"""
14:00盘中扫描 — 统一数据采集+信号评分
调用fund_data_collector采集8源数据，调用fund_signal_task做信号评分，
合并后输出结构化JSON到stdout，供agent直接读取。

用法:
    python3 fund_scan_1400.py          # 完整采集+信号评分
    python3 fund_scan_1400.py --dry    # 只采集，跳过信号评分
"""
import sys, os, json, subprocess, time
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(os.path.expanduser("~"), ".hermes", "venv-fund", "bin", "python3")
if not os.path.exists(VENV_PYTHON):
    VENV_PYTHON = sys.executable

def run_script(script_name, args=None, timeout=60):
    """运行指定脚本，返回stdout"""
    cmd = [VENV_PYTHON, os.path.join(SCRIPT_DIR, script_name)]
    if args:
        cmd.extend(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout, result.returncode
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT] {script_name} 超时{timeout}秒", 1
    except Exception as e:
        return f"[ERROR] {script_name}: {e}", 1

def main():
    dry_run = "--dry" in sys.argv
    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    output = {
        "collected_at": collected_at,
        "sources": {},
        "signals": [],
        "stats": {"total": 0, "ok": 0, "error": 0}
    }

    # Phase 1: 并行数据采集
    print(f"[{collected_at}] 14:00盘中扫描 — 数据采集...", file=sys.stderr)
    t0 = time.time()
    json_out, rc = run_script("fund_data_collector.py", timeout=30)
    elapsed_collect = round(time.time() - t0, 2)

    # 读取采集结果
    summary_path = "/tmp/fund_data/scan_summary.json"
    if os.path.exists(summary_path):
        with open(summary_path) as f:
            summary = json.load(f)
        output["sources"] = summary.get("sources", {})
        output["stats"] = summary.get("stats", {})
        output["collect_elapsed_s"] = elapsed_collect
        print(f"[{collected_at}] 数据采集完成: {elapsed_collect}s, "
              f"成功{output['stats'].get('ok',0)}/{output['stats'].get('total',0)}", file=sys.stderr)
    else:
        output["error"] = "scan_summary.json不存在"
        print(f"[{collected_at}] ❌ 数据采集失败: 无输出文件", file=sys.stderr)

    # Phase 2: 信号评分
    if not dry_run:
        print(f"[{collected_at}] 信号评分...", file=sys.stderr)
        t1 = time.time()
        signal_out, rc = run_script("fund_signal_task.py", timeout=30)
        elapsed_signal = round(time.time() - t1, 2)

        # 解析信号输出
        signals = []
        for line in signal_out.strip().split("\n"):
            if "🟢" in line or "🔴" in line:
                # 格式: "🟢 基金名(代码) | buy | 评分:8.5/10"
                parts = line.strip().split("|")
                if len(parts) >= 2:
                    name_part = parts[0].replace("🟢", "").replace("🔴", "").strip()
                    signal_type = parts[1].strip()
                    score_part = parts[2].strip() if len(parts) > 2 else ""
                    signals.append({
                        "name": name_part,
                        "signal": signal_type,
                        "score": score_part
                    })

        output["signals"] = signals
        output["signal_elapsed_s"] = elapsed_signal
        output["signal_raw"] = signal_out.strip()
        print(f"[{collected_at}] 信号评分完成: {elapsed_signal}s, "
              f"高质量信号{len(signals)}条", file=sys.stderr)

    # 输出最终JSON到stdout
    print(json.dumps(output, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
