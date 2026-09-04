# 09-01 搜索后端问题与MIMO联网搜索发现

## 问题背景
用户要求搜索博通Q3财报信息时，360搜索(so.com)返回0字节，百度返回验证码，无法获取实时金融数据。

## 诊断结果

### 被封的搜索引擎
| 引擎 | 状态 | 原因 |
|:--|:--|:--|
| 360搜索 (so.com) | ❌ 返回0字节 | 服务器IP被反爬封禁 |
| 百度 | ❌ 返回验证码 | 触发人机验证 |
| Google/Yahoo/DuckDuckGo | ❌ 连接超时 | 国内服务器无法直接访问 |

### 可用的数据源
| 数据源 | 状态 | 适用场景 |
|:--|:--|:--|
| 老虎证券 (laohu8.com) | ✅ | 美股/港股金融分析、社区讨论 |
| 雪球 (xueqiu.com) | ✅ | A股/港股金融分析 |
| 东财个股页面 | ✅ | A股基本面数据 |
| Bing中文 (cn.bing.com) | ⚠️ 能通但质量差 | 中文搜索不精准 |
| 东财搜索API | ✅ | 只能搜股票/基金代码 |
| 浏览器工具 | ✅ | 直接访问任意网页 |

## Hermes搜索架构

```
用户发消息 → MIMO(大脑)决定需要搜索
           → Hermes(手脚)用terminal执行curl命令
           → 访问搜索引擎/金融网站
           → Python解析HTML提取内容
           → MIMO阅读分析
```

**关键点**：
- MIMO本身不能搜索，是语言模型
- 搜索是Hermes用curl直接访问网站
- Hermes有内置`web_search`工具，但需要配置搜索后端
- 当前`search_backend: ddgs`配置了但不工作（国内服务器访问不到DuckDuckGo）

## MIMO联网搜索（发现未集成）

小米MIMO有自带的联网搜索服务：
- 国内联网：¥16/1000次（含网页搜索+网页解析）
- 海外联网：$5/1000次
- 通过MIMO API调用

**但Hermes没有原生集成MIMO搜索**。Hermes的`web_search`工具支持的后端是：
Firecrawl, SearXNG, Brave, DDGS, Tavily, Exa, Parallel, xAI

MIMO不在列表中。要使用需要：
1. 自定义开发适配器
2. 或通过MIMO API直接curl调用

## 解决方案：SearXNG本地部署 ✅ 已完成（09-01）

Docker容器运行在localhost:8888，聚合百度/搜狗/必应，绕过反爬。永久免费，无限次调用。
- Hermes config.yaml已配置 `search_backend: searxng`
- .env已配置 `SEARXNG_URL=http://localhost:8888`
- 容器自动重启（unless-stopped）
- 详见 `references/2026-09-01-searxng-deployment.md`

## 仍可用的数据源
| 数据源 | 状态 | 用途 |
|:--|:--|:--|
| SearXNG本地 | ✅ 正常 | 通用搜索（中英文） |
| 老虎证券(laohu8.com) | ✅ 正常 | 金融分析/讨论 |
| 雪球(xueqiu.com) | ✅ 正常 | 金融分析/讨论 |
| 东财个股页面 | ✅ 正常 | 基金/个股信息 |
| 东财push2 | ✅ 正常（偶尔限流） | A股指数/板块实时 |
| 东财7x24快讯 | ✅ 正常 | 新闻/消息面 |
| 新浪hq.sinajs.cn | ✅ 仍可用（需Referer头） | A股行情数据 |

## 已失效的数据源
| 数据源 | 失效时间 | 原因 |
|:--|:--|:--|
| 360搜索(so.com) | 09-01 | 返回0字节，IP被封 |
| 百度搜索 | 09-01 | 返回验证码页面 |
| DDGS(DuckDuckGo) | 09-01 | 国内服务器无法访问Google/Yahoo |
| 新浪MoneyFlow | 09-01 | 数据口径错误（行业板块vs概念板块） |

## 配置变更记录
- `~/.hermes/config.yaml`: `search_backend: searxng`（09-01更新）
- `~/.hermes/.env`: `SEARXNG_URL=http://localhost:8888`（09-01新增）
- `~/.hermes/skills/personal/fund-swing-trading/SKILL.md`: 数据源优先级已更新
- `~/.hermes/memory`: 搜索源信息已更新
