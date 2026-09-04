# RSI计算断裂修复记录（09-02）

## 问题
fund_nav_update.py只计算当天的RSI/MA/MACD/trend指标。历史批量插入的nav_daily记录没有技术指标，导致：
- 011036 RSI从08-28起=None
- 018301 RSI覆盖率只有33%
- 总计700/751条记录RSI=None（6.8%）

## 根因
fund_nav_update.py只写入当天的记录。历史记录是通过其他方式批量插入的，没有计算技术指标。

## 解决方案
创建backfill_rsi.py脚本：对每只基金拉取完整净值历史，对每个交易日计算RSI/MA/MACD/trend，更新nav_daily表。

## 修复结果
- 修复前：51/751条RSI有值（6.8%）
- 修复后：751/751条RSI有值（100%）

## 防止复发
如果未来再出现RSI=None，运行`python3 backfill_rsi.py`即可。
