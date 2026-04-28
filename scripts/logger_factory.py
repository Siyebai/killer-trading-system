#!/usr/bin/env python3
"""
统一日志工厂 — 杀手锏交易系统 v1.0.2
替代所有 print() 调用,提供结构化JSON日志、级别控制、模块标识。
"""

import json
import logging
import sys
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class StructuredFormatter(logging.Formatter):
    """结构化JSON日志格式器,便于机器解析和日志平台采集"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
            "msg": record.getMessage(),
        }
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exc_type"] = record.exc_info[0].__name__
            log_entry["exc_msg"] = str(record.exc_info[1])
        return json.dumps(log_entry, ensure_ascii=False)


class CompactFormatter(logging.Formatter):
    """紧凑格式,用于开发环境终端输出"""

    COLORS = {
        "DEBUG": "\033[36m",    # cyan
        "INFO": "\033[32m",     # green
        "WARNING": "\033[33m",  # yellow
        "ERROR": "\033[31m",    # red
        "CRITICAL": "\033[35m", # magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        base = f"{color}{record.levelname:<8}{self.RESET} [{ts}] {record.module}:{record.funcName}:{record.lineno} | {record.getMessage()}"
        if hasattr(record, "extra_data") and record.extra_data:
            base += f" | data={json.dumps(record.extra_data, ensure_ascii=False, default=str)}"
        return base


_LOGGERS: Dict[str, logging.Logger] = {}
_DEFAULT_LEVEL = os.environ.get("KILLER_LOG_LEVEL", "INFO").upper()


def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """
    获取命名日志器(单例模式)。

    Args:
        name: 模块名称,如 "ev_filter", "order_lifecycle"
        level: 日志级别,默认从环境变量 KILLER_LOG_LEVEL 读取,否则 INFO

    Returns:
        配置好的 Logger 实例

    Usage:
        logger = get_logger("ev_filter")
        logger.info("EV calculated", extra={"extra_data": {"symbol": "BTCUSDT", "ev": 0.015}})
    """
    if name in _LOGGERS:
        return _LOGGERS[name]

    logger = logging.getLogger(f"killer.{name}")
    effective_level = (level or _DEFAULT_LEVEL).upper()
    logger.setLevel(getattr(logging, effective_level, logging.INFO))
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        # 结构化模式用于生产,紧凑模式用于开发
        fmt = os.environ.get("KILLER_LOG_FMT", "compact").lower()
        if fmt == "json":
            handler.setFormatter(StructuredFormatter())
        else:
            handler.setFormatter(CompactFormatter())
        logger.addHandler(handler)

    _LOGGERS[name] = logger
    return logger


def set_global_level(level: str) -> None:
    """动态调整所有日志器级别"""
    lvl = getattr(logging, level.upper(), logging.INFO)
    for logger in _LOGGERS.values():
        logger.setLevel(lvl)


def get_log_stats() -> Dict[str, str]:
    """获取当前日志配置状态(用于健康检查)"""
    return {
        "registered_loggers": list(_LOGGERS.keys()),
        "default_level": _DEFAULT_LEVEL,
        "format": os.environ.get("KILLER_LOG_FMT", "compact"),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="日志工厂验证")
    parser.add_argument("--level", default="DEBUG", help="日志级别")
    parser.add_argument("--format", default="compact", choices=["compact", "json"], help="输出格式")
    args = parser.parse_args()

    os.environ["KILLER_LOG_FMT"] = args.format
    logger = get_logger("demo", args.level)
    logger.debug("Debug message", extra={"extra_data": {"key": "debug_val"}})
    logger.info("Info message", extra={"extra_data": {"symbol": "BTCUSDT", "ev": 0.015}})
    logger.warning("Warning message", extra={"extra_data": {"attempts": 3}})
    logger.error("Error message", extra={"extra_data": {"error": "connection_timeout"}})
    logger.critical("Critical message", extra={"extra_data": {"action": "hard_breaker_triggered"}})

    logger.info(f"\n--- Log Stats ---")
    logger.info(json.dumps(get_log_stats(), indent=2))
