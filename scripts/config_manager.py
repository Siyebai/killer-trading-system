#!/usr/bin/env python3
"""
统一配置管理器 — 杀手锏交易系统 v1.0.2
解决14版本配置碎片化问题,提供验证、点号路径访问、热加载。
"""

import argparse
import json
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from scripts.logger_factory import get_logger

logger = get_logger("config_manager")

# 配置Schema定义 — 用于验证配置完整性
REQUIRED_TOP_KEYS = ["version", "risk", "execution"]
RISK_REQUIRED_KEYS = ["max_position_pct", "circuit_breaker"]
EXECUTION_REQUIRED_KEYS = ["taker_fee"]
# 以下为可选但建议存在的字段
RECOMMENDED_TOP_KEYS = ["strategy", "controller", "scan"]

# 数值范围约束
RANGE_CONSTRAINTS = {
    "risk.max_position_pct": (0.01, 1.0),
    "risk.circuit_breaker.soft_breaker_threshold": (0.01, 0.5),
    "risk.circuit_breaker.hard_breaker_threshold": (0.01, 0.5),
    "execution.taker_fee": (0.0, 0.01),
}


class ConfigValidationError(Exception):
    """配置验证错误"""
    pass


class ConfigManager:
    """
    统一配置管理器(单例)。

    功能:
    - 单一配置源(唯一 killer_config.json)
    - Schema 验证(必需字段 + 数值范围)
    - 点号路径访问: get("risk.max_position_pct")
    - 热加载: reload() 无需重启
    - 变更回调: register_watcher()
    - 配置指纹: 防止配置漂移
    """

    _instance: Optional["ConfigManager"] = None
    _config: Dict[str, Any] = field(default_factory=dict)
    _watchers: List[Callable] = field(default_factory=list)
    _fingerprint: str = ""
    _loaded_at: float = 0.0
    _config_path: str = ""

    @classmethod
    def get_instance(cls) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load(self, config_path: str) -> Dict[str, Any]:
        """
        加载配置文件。

        Args:
            config_path: 配置文件路径

        Returns:
            加载后的配置字典

        Raises:
            FileNotFoundError: 配置文件不存在
            ConfigValidationError: 配置验证失败
        """
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)

        self._validate(config)
        self._config = config
        self._config_path = config_path
        self._fingerprint = self._calc_fingerprint(config)
        self._loaded_at = time.time()

        logger.info("Config loaded", extra={"extra_data": {
            "path": config_path,
            "version": config.get("version", "unknown"),
            "fingerprint": self._fingerprint[:12],
        }})
        return config

    def reload(self) -> Dict[str, Any]:
        """热加载配置(不重启进程)"""
        if not self._config_path:
            raise RuntimeError("No config path set, call load() first")

        old_fp = self._fingerprint
        config = self.load(self._config_path)

        if self._fingerprint != old_fp:
            logger.warning("Config changed on reload", extra={"extra_data": {
                "old_fp": old_fp[:12], "new_fp": self._fingerprint[:12]
            }})
            for watcher in self._watchers:
                try:
                    watcher(config)
                except Exception as e:
                    logger.error("Config watcher error", extra={"extra_data": {"error": str(e)}})

        return config

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        点号路径访问配置值。

        Args:
            key_path: 如 "risk.max_position_pct"
            default: 键不存在时的默认值

        Returns:
            配置值或默认值
        """
        keys = key_path.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key_path: str, value: Any) -> None:
        """
        运行时修改配置(不持久化,仅影响当前进程)。

        Args:
            key_path: 如 "risk.max_position_pct"
            value: 新值
        """
        keys = key_path.split(".")
        cfg = self._config
        for k in keys[:-1]:
            if k not in cfg or not isinstance(cfg[k], dict):
                cfg[k] = {}
            cfg = cfg[k]
        old_value = cfg.get(keys[-1])
        cfg[keys[-1]] = value

        logger.info("Config runtime override", extra={"extra_data": {
            "key": key_path, "old": str(old_value), "new": str(value)
        }})

        for watcher in self._watchers:
            try:
                watcher(self._config)
            except Exception as e:
                logger.error("Config watcher error on set", extra={"extra_data": {"error": str(e)}})

    def register_watcher(self, callback: Callable) -> None:
        """注册配置变更回调"""
        self._watchers.append(callback)

    def get_all(self) -> Dict[str, Any]:
        """返回完整配置(只读副本)"""
        return json.loads(json.dumps(self._config))

    def get_fingerprint(self) -> str:
        """返回配置指纹(SHA256前16位)"""
        return self._fingerprint[:16]

    def get_loaded_at(self) -> float:
        """返回配置加载时间戳"""
        return self._loaded_at

    def _validate(self, config: Dict[str, Any]) -> None:
        """验证配置Schema"""
        errors = []

        # 顶层必需字段
        for key in REQUIRED_TOP_KEYS:
            if key not in config:
                errors.append(f"Missing top-level key: {key}")

        # 风控必需字段
        risk = config.get("risk", {})
        for key in RISK_REQUIRED_KEYS:
            if key not in risk:
                errors.append(f"Missing risk key: risk.{key}")

        # 执行必需字段
        execution = config.get("execution", {})
        for key in EXECUTION_REQUIRED_KEYS:
            if key not in execution:
                errors.append(f"Missing execution key: execution.{key}")

        # 可选字段警告
        for key in RECOMMENDED_TOP_KEYS:
            if key not in config:
                logger.warning(f"Recommended key missing: {key}", extra={"extra_data": {"key": key}})

        # 数值范围约束
        for key_path, (min_val, max_val) in RANGE_CONSTRAINTS.items():
            val = self._resolve_path(config, key_path)
            if val is not None:
                if not isinstance(val, (int, float)):
                    errors.append(f"{key_path} must be numeric, got {type(val).__name__}")
                elif val < min_val or val > max_val:
                    errors.append(f"{key_path}={val} out of range [{min_val}, {max_val}]")

        # 逻辑约束: soft_breaker < hard_breaker
        cb = risk.get("circuit_breaker", {})
        soft = cb.get("soft_breaker_threshold")
        hard = cb.get("hard_breaker_threshold")
        if soft is not None and hard is not None and soft >= hard:
            errors.append(f"soft_breaker_threshold({soft}) must be < hard_breaker_threshold({hard})")

        if errors:
            for e in errors:
                logger.error(f"Config validation error: {e}")
            raise ConfigValidationError("; ".join(errors))

    @staticmethod
    def _resolve_path(data: Dict, key_path: str) -> Any:
        keys = key_path.split(".")
        value = data
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return None
        return value

    @staticmethod
    def _calc_fingerprint(config: Dict) -> str:
        """计算配置指纹"""
        raw = json.dumps(config, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description="配置管理器命令行工具")
    parser.add_argument("--config", required=True, help="配置文件路径")
    parser.add_argument("--key", default=None, help="查询指定键(点号路径)")
    parser.add_argument("--validate", action="store_true", help="仅验证配置")
    parser.add_argument("--fingerprint", action="store_true", help="输出配置指纹")
    args = parser.parse_args()

    mgr = ConfigManager.get_instance()

    try:
        config = mgr.load(args.config)
    except (FileNotFoundError, ConfigValidationError) as e:
        logger.error(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
        return

    if args.validate:
        logger.info(json.dumps({"status": "ok", "message": "Config validation passed"}, ensure_ascii=False))
        return

    if args.fingerprint:
        logger.info(json.dumps({"status": "ok", "fingerprint": mgr.get_fingerprint()}, ensure_ascii=False))
        return

    if args.key:
        value = mgr.get(args.key)
        logger.info(json.dumps({"status": "ok", "key": args.key, "value": value}, ensure_ascii=False, default=str))
        return

    logger.info(json.dumps({"status": "ok", "version": config.get("version"), "fingerprint": mgr.get_fingerprint()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
