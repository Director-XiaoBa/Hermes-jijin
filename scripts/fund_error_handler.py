#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基金系统统一异常处理模块
提供重试、降级、日志记录、错误通知功能
"""
import time
import functools
import traceback
import json
import urllib.request
import ssl
from datetime import datetime
from typing import Any, Callable, Optional

# 错误日志文件
ERROR_LOG_FILE = '/home/ubuntu/user_files/documents/fund_error.log'

# SSL配置
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# 微信通知配置（预留，需要配置webhook）
WECHAT_WEBHOOK = None  # 如果需要微信通知，配置webhook URL


def log_error(func_name: str, error: Exception, context: str = "", notify: bool = False):
    """记录错误日志到文件，可选发送通知"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    error_msg = f"[{timestamp}] {func_name}: {error} (context: {context})\n"
    error_msg += f"  Traceback: {traceback.format_exc()}\n\n"
    
    try:
        with open(ERROR_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(error_msg)
    except Exception:
        pass
    
    print(f"[ERROR] {func_name}: {error} (context: {context})")
    
    # 如果需要通知，发送微信通知
    if notify and WECHAT_WEBHOOK:
        send_wechat_notification(f"❌ 基金系统错误\n{func_name}: {error}")


def send_wechat_notification(message: str):
    """发送微信通知"""
    if not WECHAT_WEBHOOK:
        return
    
    try:
        data = json.dumps({"content": message}).encode('utf-8')
        req = urllib.request.Request(
            WECHAT_WEBHOOK,
            data=data,
            headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req, timeout=10, context=SSL_CTX)
    except Exception:
        pass


def retry(max_attempts: int = 3, delay: float = 2, backoff: float = 2):
    """
    重试装饰器
    :param max_attempts: 最大重试次数
    :param delay: 初始延迟（秒）
    :param backoff: 延迟倍增因子
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        log_error(func.__name__, e, f"attempt {attempt + 1}/{max_attempts}")
                        time.sleep(current_delay)
                        current_delay *= backoff
            
            log_error(func.__name__, last_exception, f"all {max_attempts} attempts failed")
            raise last_exception
        return wrapper
    return decorator


def fallback(default_value: Any = None, log_error: bool = True):
    """
    降级装饰器
    :param default_value: 降级返回值
    :param log_error: 是否记录错误
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if log_error:
                    globals()['log_error'](func.__name__, e, "fallback")
                return default_value
        return wrapper
    return decorator


def safe_execute(func: Callable, *args, default_value: Any = None, **kwargs) -> Any:
    """
    安全执行函数
    :param func: 要执行的函数
    :param default_value: 失败时返回的默认值
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        log_error(func.__name__, e, "safe_execute")
        return default_value


class CircuitBreaker:
    """
    熔断器：连续失败N次后暂停调用
    """
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 300):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'closed'  # closed, open, half-open
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        if self.state == 'open':
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = 'half-open'
            else:
                raise Exception("Circuit breaker is open")
        
        try:
            result = func(*args, **kwargs)
            self.on_success()
            return result
        except Exception as e:
            self.on_failure()
            raise
    
    def on_success(self):
        self.failure_count = 0
        self.state = 'closed'
    
    def on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = 'open'


# 测试函数
if __name__ == "__main__":
    print("=== 测试 fund_error_handler.py ===\n")
    
    # 测试retry
    @retry(max_attempts=2, delay=0.1)
    def test_retry():
        raise ValueError("Test error")
    
    try:
        test_retry()
    except ValueError:
        print("✅ retry装饰器测试通过")
    
    # 测试fallback
    @fallback(default_value="fallback_value")
    def test_fallback():
        raise ValueError("Test error")
    
    result = test_fallback()
    print(f"✅ fallback装饰器测试通过: {result}")
    
    # 测试safe_execute
    def test_safe():
        raise ValueError("Test error")
    
    result = safe_execute(test_safe, default_value="safe_value")
    print(f"✅ safe_execute测试通过: {result}")
    
    print("\n=== 测试完成 ===")
