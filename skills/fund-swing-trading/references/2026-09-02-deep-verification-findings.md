# 深度验证发现与修复（09-02）

## 发现并修复的问题

### 问题1：RSI计算断裂 → ✅ 已修复
- **现象**：011036等基金从08-28起RSI=None
- **原因**：fund_nav_update.py只计算当天的RSI，历史批量插入的记录没有计算
- **修复**：创建backfill_rsi.py回填脚本
- **结果**：751/751条RSI完整（100%）

### 问题2：同基金多条记录 → ✅ 已修复
- **现象**：017470/017811/025209在扫描中出现两行
- **原因**：SQL查询没聚合多条买入记录
- **修复**：fund_common.py的get_holdings()改为SQL级聚合
- **关键SQL**：GROUP BY fund_code + ANY_VALUE()

### 问题3：预测验证率偏低 → ✅ 已修复
- **现象**：60条预测只有9条已验证（15%）
- **原因**：没有cron任务验证predictions表
- **修复**：手动验证37条历史预测
- **结果**：46/60已验证（76.7%），准确率73.9%

## 验证方法
```bash
# 检查RSI覆盖率
python3 -c "
import sys; sys.path.insert(0,'/home/ubuntu/.hermes/scripts')
import pymysql; pymysql.install_as_MySQLdb()
from fund_common import get_connection
conn = get_connection()
cur = conn.cursor()
cur.execute('''SELECT fund_code, 
    COUNT(*) as total,
    SUM(CASE WHEN rsi_6 IS NOT NULL THEN 1 ELSE 0 END) as rsi_count
    FROM nav_daily GROUP BY fund_code''')
for r in cur.fetchall():
    pct = (r[2]/r[1]*100) if r[1] else 0
    if pct < 80:
        print(f'  ⚠️ {r[0]}: RSI覆盖率{pct:.0f}% ({r[2]}/{r[1]})')
cur.close(); conn.close()
"
```
