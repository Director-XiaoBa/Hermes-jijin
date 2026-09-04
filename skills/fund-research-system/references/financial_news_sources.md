# 财经新闻源（服务器可直接curl抓取）

## 可用源（按推荐优先级）

| 源 | 域名 | 特点 | 抓取方式 |
|:--|:--|:--|:--|
| **华尔街见闻** | wallstreetcn.com | 质量最高，文章嵌在HTML中 | `curl -sL` 解析页面内嵌JSON |
| **第一财经** | yicai.com | 专业财经，7x24快讯流 | `curl -sL` HTML解析 |
| **证券时报** | stcn.com | A股深度，存储/半导体分析多 | `curl -sL` HTML解析 |
| **21世纪经济报道** | 21jingji.com | 宏观+美股覆盖好 | `curl -sL` HTML解析 |
| **中国新闻网** | chinanews.com.cn | 综合，财经频道可用 | `curl -sL` HTML解析 |

## 不可用/已失效

| 源 | 问题 |
|:--|:--|
| 中新经纬 jwnews.com | 域名已停用（跳转到域名出售页） |
| 经济观察报 jjckb.cn | 返回空HTML（SPA渲染，curl抓不到内容） |

## 抓取技巧

**华尔街见闻**：文章数据嵌在页面script标签的JSON中，搜resource_type可提取文章列表+摘要。

**关键词搜索示例**（抓取英伟达/美股相关新闻）：
```bash
curl -sL "https://www.stcn.com/" | grep -i "英伟达|nvidia|美股|收盘" | head -10
curl -sL "https://www.21jingji.com/" | grep -i "英伟达|nvidia|美股|收盘" | head -10
```

**单篇文章抓取**：
```bash
curl -sL "https://www.stcn.com/article/detail/ARTICLE_ID.html" | grep -i "关键词"
```

## 数据时效说明

- 这些网站的快讯流（7x24）更新频率：5-15分钟
- 收盘总结/财报分析通常在美股收盘后（北京时间早上5-8点）发布
- 适合用于：14:00盘中扫描补充海外信息、22:30收益报告前确认美股走势
