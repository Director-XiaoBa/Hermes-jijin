# 09-01 事件日历集成记录

## 变更概述
14:00扫描脚本（fund_scan_data.py）新增MySQL events表查询，自动输出未来7天重大事件。

## 实现方式
在fund_scan_data.py第6.5段（快讯段之后）新增：
```python
# 查询events表未来7天事件
cursor.execute("""
    SELECT event_time, event_type, title, intensity, related_funds
    FROM events
    WHERE event_time BETWEEN NOW() AND DATE_ADD(NOW(), INTERVAL 7 DAY)
      AND verified = 1
    ORDER BY event_time
""")
```

## 事件入库流程
1. fund_event_collect.py：自动抓东财7x24快讯→筛选→写入events表
2. 手动入库：重要事件（如华为发布会、IPO）由AI分析后手动INSERT
3. 三处同步：MySQL events表 + catalyst_analysis表 + 台账md

## 当前9月事件（已验证）
| 日期 | 事件 | 强度 | 影响基金 |
|:--|:--|:--|:--|
| 9/2 | 燧原科技IPO申购 | ⭐⭐⭐⭐ | 017470/017811/018123 |
| 9/4 | 燧原缴款+非农20:30 | ⭐⭐⭐⭐ | 全部 |
| 9/7 | 摩尔线程解禁+华为三折叠 | ⭐⭐⭐⭐⭐ | 018123⚠️+018301 |
| 9/9-11 | 光博会 | ⭐⭐⭐ | 025422 |
| 9/10 | 苹果发布会 | ⭐⭐⭐⭐⭐ | 018301 |
| 9/11-13 | 算力大会（待确认） | ⭐⭐⭐⭐ | 017470/017811 |
| 9/16-17 | FOMC议息 | ⭐⭐⭐⭐⭐ | 全部 |

## 关联板块映射（fund_sector_map表）
基金→板块映射已建立，扫描时可输出关联板块实时涨跌。
详见 fund-research-system/references/2026-09-01-infrastructure-changes.md
