# 数据源限制与替代方案（09-02 实测）

## 被封/不可用的数据源

| 数据源 | 状态 | 原因 | 发现日期 |
|:--|:--|:--|:--|
| 东财push2 API | ❌ 从云服务器被封 | HTTP 000连接被拒，专封云IP | 09-02 |
| 新浪hq.sinajs.cn | ❌ 被封 | Forbidden | 08-27 |
| fundgz估值接口 | ❌ 不可用 | SSL错误+天天基金下线净值估算 | 08-24 |
| 360搜索 | ❌ 被封 | 返回0字节/验证码 | 09-01 |
| 百度搜索 | ❌ 被封 | 返回0字节/验证码 | 09-01 |
| DDGS | ❌ 不可用 | 国内服务器无法访问Google/Yahoo | - |

## 可用的免费替代方案

| 数据类型 | 推荐数据源 | 备注 |
|:--|:--|:--|
| A股指数/个股/ETF | 腾讯qt.gtimg.cn | 稳定，支持sh/sz/us前缀 |
| 美股/期货 | 腾讯qt.gtimg.cn | usNDX/usSPX/usDJI可用 |
| 板块涨跌（49行业） | 新浪板块API | vip.stock.finance.sina.com.cn/q/view/newSinaHy.php |
| 基金净值 | MySQL nav_daily | 22:00更新，最可靠 |
| 快讯/事件 | 东财7x24 API | np-listapi.eastmoney.com |
| 搜索 | SearXNG本地 | localhost:8888，Docker部署 |

## Tushare Pro免费版限制

- 123积分能用：stock_basic, trade_cal, daily, index_daily
- 123积分不能用：moneyflow（需1000+积分）, ths_index（需500+积分）
- **结论：对我们的价值有限，不推荐付费升级**

## fund_data_collector.py 8源状态（09-02实测）

| 数据源 | 状态 | 数据源 | 状态 |
|:--|:--|:--|:--|
| indices_holdings | ✅ | north_flow | ✅ |
| etf_realtime | ✅ | news | ✅ |
| global_markets | ✅ | events | ✅ |
| sector_fund_flows | ✅（新浪API） | sector_scan | ✅（新浪API） |

总耗时：0.61秒（8源并行）
