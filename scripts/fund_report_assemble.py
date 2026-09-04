#!/usr/bin/env python3
"""
14:00报告组装 — 合并数据填充报告 + LLM分析 → 最终完整报告

用法:
    python3 fund_report_assemble.py "LLM分析内容"    # 传入LLM输出
    python3 fund_report_assemble.py -f /tmp/llm.md   # 从文件读取

流程:
    1. 读取fund_report_data.py生成的半成品报告
    2. 读取LLM分析内容
    3. 替换占位符 → 输出最终报告
"""
import sys, os

DATA_REPORT = "/tmp/fund_data/report_data.md"
LLM_OUTPUT_FILE = "/tmp/fund_data/llm_analysis_output.md"

def load_data_report():
    """读取半成品报告"""
    if not os.path.exists(DATA_REPORT):
        print("❌ 半成品报告不存在，请先运行fund_report_data.py", file=sys.stderr)
        sys.exit(1)
    with open(DATA_REPORT, encoding='utf-8') as f:
        return f.read()

def extract_analysis(llm_text):
    """从LLM输出中提取催化剂分析和操作建议"""
    analysis = {"catalyst": "", "recommendation": ""}

    lines = llm_text.strip().split("\n")
    current_section = None
    buffer = []

    for line in lines:
        if "催化剂分析" in line or "## 7" in line:
            if current_section and buffer:
                analysis[current_section] = "\n".join(buffer).strip()
            current_section = "catalyst"
            buffer = []
        elif "操作建议" in line or "## 8" in line:
            if current_section and buffer:
                analysis[current_section] = "\n".join(buffer).strip()
            current_section = "recommendation"
            buffer = []
        elif line.startswith("## ") and current_section:
            # 新章节，结束当前
            if buffer:
                analysis[current_section] = "\n".join(buffer).strip()
            current_section = None
            buffer = []
        else:
            if current_section:
                buffer.append(line)

    # 最后一个section
    if current_section and buffer:
        analysis[current_section] = "\n".join(buffer).strip()

    return analysis

def assemble(data_report, analysis):
    """组装最终报告"""
    # 替换催化剂分析占位符
    placeholder = "⚠️ 待LLM分析填充"

    if analysis.get("catalyst"):
        data_report = data_report.replace(
            f"## 7. 催化剂分析\n{placeholder}",
            f"## 7. 催化剂分析\n{analysis['catalyst']}"
        )

    if analysis.get("recommendation"):
        data_report = data_report.replace(
            f"## 8. 操作建议\n{placeholder}",
            f"## 8. 操作建议\n{analysis['recommendation']}"
        )

    # 如果占位符没被替换（LLM输出格式不匹配），追加到末尾
    if placeholder in data_report:
        data_report = data_report.replace(
            placeholder,
            (analysis.get("catalyst") or "分析未完成") + "\n\n" +
            (analysis.get("recommendation") or "建议未生成")
        )

    return data_report

def main():
    data_report = load_data_report()

    # 读取LLM分析
    if len(sys.argv) > 1:
        if sys.argv[1] == "-f" and len(sys.argv) > 2:
            with open(sys.argv[2], encoding='utf-8') as f:
                llm_text = f.read()
        else:
            llm_text = " ".join(sys.argv[1:])
    elif os.path.exists(LLM_OUTPUT_FILE):
        with open(LLM_OUTPUT_FILE, encoding='utf-8') as f:
            llm_text = f.read()
    else:
        print("❌ 未提供LLM分析内容", file=sys.stderr)
        sys.exit(1)

    analysis = extract_analysis(llm_text)
    final_report = assemble(data_report, analysis)

    print(final_report)

if __name__ == "__main__":
    main()
