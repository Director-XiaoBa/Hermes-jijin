# 系统监控与错误处理优化（09-03）

## 系统监控脚本

**文件**：`~/.hermes/scripts/system_monitor.py`

**功能**：
- 检查数据库连接
- 检查最近24小时cron任务执行状态
- 检查数据新鲜度（净值是否最新）
- 检查错误日志
- 检查磁盘空间
- 检查投资组合状态

**使用方式**：
```bash
python3 ~/.hermes/scripts/system_monitor.py
```

**输出格式**：
```
============================================================
🔍 基金系统监控报告 | 2026-09-03 11:00:51
============================================================
✅ 数据库连接: 数据库连接正常
✅ Cron任务: 最近24小时: 13个任务, 13成功, 0失败
✅ 数据新鲜度: 净值数据最新: 2026-09-02
❌ 错误日志: 最近24小时有4个错误
❌ 磁盘空间: 磁盘空间不足: 8.0GB可用
✅ 投资组合: 当前市值: ¥4490, 盈亏: ¥-110 (-2.38%)
============================================================
```

**检查项说明**：

| 检查项 | 数据源 | 正常条件 | 异常处理 |
|--------|--------|----------|----------|
| 数据库连接 | MySQL | 连接成功 | 检查MySQL服务 |
| Cron任务 | executions.db | 最近24小时有成功任务 | 检查cron配置 |
| 数据新鲜度 | nav_daily | 最新日期=今天或昨天 | 运行净值更新 |
| 错误日志 | fund_error.log | 最近24小时无错误 | 检查错误日志 |
| 磁盘空间 | os.statvfs | 剩余>10GB | 清理大文件 |
| 投资组合 | portfolio_daily | 有最新记录 | 运行收益记录 |

---

## 错误处理增强

**文件**：`~/.hermes/scripts/fund_error_handler.py`

**新增功能**：
1. 错误通知能力（预留微信通知接口）
2. 统一错误日志格式
3. 重试、降级、熔断器

**核心函数**：

### log_error
```python
def log_error(func_name: str, error: Exception, context: str = "", notify: bool = False):
    """记录错误日志到文件，可选发送通知"""
```

### retry
```python
@retry(max_attempts=3, delay=2, backoff=2)
def risky_function():
    """自动重试装饰器"""
```

### fallback
```python
@fallback(default_value=None, log_error=True)
def optional_function():
    """降级装饰器，失败时返回默认值"""
```

### safe_execute
```python
result = safe_execute(func, *args, default_value=None, **kwargs)
"""安全执行函数，失败时返回默认值"""
```

### CircuitBreaker
```python
breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=300)
result = breaker.call(func, *args, **kwargs)
"""熔断器：连续失败N次后暂停调用"""
```

---

## 验证流程

### 完整验证
```bash
# 1. 系统监控
python3 ~/.hermes/scripts/system_monitor.py

# 2. 完整性检查
python3 ~/.hermes/scripts/verify_system.py

# 3. 同步检查
python3 ~/.hermes/scripts/sync_portfolio.py verify
```

### 验证清单
- [ ] 数据库连接正常
- [ ] Cron任务执行成功
- [ ] 数据新鲜度正常
- [ ] 无严重错误
- [ ] 磁盘空间充足
- [ ] 投资组合数据正常

---

## 相关文件

- `~/.hermes/scripts/system_monitor.py` - 系统监控脚本
- `~/.hermes/scripts/fund_error_handler.py` - 错误处理模块
- `~/.hermes/scripts/verify_system.py` - 完整性检查脚本
- `~/user_files/documents/fund_error.log` - 错误日志文件
