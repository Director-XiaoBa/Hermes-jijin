# 基金关联板块映射（09-01 新建）

## 表结构
```sql
CREATE TABLE fund_sector_map (
    fund_code VARCHAR(10) PRIMARY KEY,
    fund_name VARCHAR(50),
    sector_name VARCHAR(50) COMMENT '关联板块名称',
    sector_index_code VARCHAR(20) COMMENT '东财指数代码',
    sector_bk_code VARCHAR(20) COMMENT '东财板块代码（BK开头）'
);
```

## 当前映射数据（09-01）
| 基金代码 | 基金名称 | 关联板块 | 板块代码 |
|:--|:--|:--|:--|
| 017470 | 嘉实上证科创板芯片ETF联接C | 上证科创芯片 | BK1036 |
| 017811 | 东方人工智能主题混合C | 半导体材料 | BK1325 |
| 011036 | 嘉实中证稀土产业ETF联接C | 稀土产业 | BK0560 |
| 025209 | 永赢先锋半导体智选混合C | 存储芯片 | BK1137 |
| 025422 | 浦银数字经济混合C | CPO | BK1101 |
| 018301 | 华夏消费电子ETF联接C | 国证消费电子 | BK0738 |
| 018345 | 华夏中证机器人ETF联接C | 中证机器人 | BK1408 |
| 018123 | 永赢数字经济智选混合C | 国产算力 | BK1325 |

## 查询方式
```sql
-- 查某只基金的关联板块
SELECT sector_name, sector_bk_code FROM fund_sector_map WHERE fund_code = '017470';

-- 查所有持仓基金的关联板块
SELECT f.fund_code, f.fund_name, m.sector_name, m.sector_bk_code
FROM fund_sector_map m
JOIN funds f ON m.fund_code = f.code
WHERE f.is_watchlist = 0;
```

## 实时板块涨跌获取
用东财push2接口（概念板块）：
```bash
curl -s "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=50&po=1&np=1&fltt=2&invt=2&fid=f62&fs=m:90+t:2+f:!50&fields=f12,f14,f62,f184" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: https://data.eastmoney.com/"
```

## 新基金入库时
新基金加入时必须同步设置关联板块：
1. 确定基金跟踪的板块指数（用东财搜索API）
2. INSERT到fund_sector_map
3. 在fund_scan_data.py的关联板块段加入该基金
