# SearXNG本地搜索引擎部署（09-01 完成）

## 部署信息
- **容器名**: searxng
- **端口**: 8888 (映射到容器8080)
- **Docker**: `sudo docker run -d --name searxng --restart unless-stopped -p 8888:8080 -e SEARXNG_BASE_URL=http://localhost:8888 searxng/searxng:latest`
- **配置文件**: ~/searxng/searxng/settings.yml
- **Hermes配置**: config.yaml `search_backend: searxng`，.env `SEARXNG_URL=http://localhost:8888`

## 关键配置
```yaml
# ~/searxng/searxng/settings.yml
use_default_settings: true
server:
  secret_key: "LMusdJa4lwOe61qyIxhFn0An2XTTIFww"
  image_proxy: true
search:
  formats:
    - html
    - json
engines:
  # 禁用不通的引擎
  - name: google
    disabled: true
  - name: duckduckgo
    disabled: true
  - name: brave
    disabled: true
  - name: startpage
    disabled: true
  - name: wikipedia
    disabled: true
  - name: wikidata
    disabled: true
  # 启用中国引擎
  - name: bing
    disabled: false
  - name: baidu
    disabled: false
  - name: sogou
    disabled: false
  - name: quark
    disabled: false
  - name: wiki_zh
    disabled: false
```

## 测试命令
```bash
# 测试中文搜索
curl -s "http://localhost:8888/search?q=%E5%8D%9A%E9%80%9A+%E8%B4%A2%E6%8A%A5&format=json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d[\"results\"])} results')"

# 测试英文搜索
curl -s "http://localhost:8888/search?q=Broadcom+earnings&format=json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d[\"results\"])} results')"
```

## 故障排查
```bash
# 查看日志
sudo docker logs searxng --tail 30

# 重启
sudo docker restart searxng

# 检查状态
sudo docker ps --filter name=searxng

# 检查内存占用
sudo docker stats searxng --no-stream
```

## 注意事项
1. 首次启动时SearXNG会初始化引擎，可能有超时错误（wikidata等），这是正常的
2. 搜索结果依赖上游引擎（百度/搜狗/必应），如果上游反爬可能影响结果质量
3. 内存占用约100-150MB
4. 配置修改后需要`sudo docker cp`回容器+`sudo docker restart searxng`
