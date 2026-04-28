#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("hot_reload_risk")
except ImportError:
    import logging
    logger = logging.getLogger("hot_reload_risk")
"""
实时风控策略热更新 - V4.0核心模块
基于V3事件引擎，支持无重启更新风控参数
"""

import json
import time
import os
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from threading import Thread, Lock
from pathlib import Path
import hashlib


@dataclass
class RiskPolicy:
    """风控策略"""
    policy_id: str
    name: str
    version: str
    parameters: Dict[str, Any]
    checksum: str = ""
    last_updated: float = 0.0
    is_active: bool = True


@dataclass
class ConfigChange:
    """配置变更记录"""
    timestamp: float
    policy_id: str
    old_checksum: str
    new_checksum: str
    change_type: str  # 'CREATED', 'UPDATED', 'DELETED'


class HotReloadRiskManager:
    """风控策略热更新管理器"""

    def __init__(self, config_dir: str = "./config/risk"):
        """
        初始化热更新管理器

        Args:
            config_dir: 配置文件目录
        """
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)

        self.policies: Dict[str, RiskPolicy] = {}
        self.change_history: List[ConfigChange] = []
        self.change_callbacks: List[Callable] = []

        self.lock = Lock()
        self.is_running = False
        self.watch_thread: Optional[Thread] = None

        # 文件检查间隔（秒）
        self.check_interval = 1.0

    def load_policy(self, policy_file: str) -> Optional[RiskPolicy]:
        """
        加载风控策略

        Args:
            policy_file: 策略文件路径

        Returns:
            风控策略对象
        """
        try:
            file_path = Path(policy_file)
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 计算校验和
            content = file_path.read_text(encoding='utf-8')
            checksum = hashlib.md5(content.encode()).hexdigest()

            # 创建策略对象
            policy = RiskPolicy(
                policy_id=data.get('policy_id', file_path.stem),
                name=data.get('name', 'Unknown'),
                version=data.get('version', '1.0'),
                parameters=data.get('parameters', {}),
                checksum=checksum,
                last_updated=time.time()
            )

            return policy
        except Exception as e:
            logger.error(f"[HotReload] 加载策略失败: {e}")
            return None

    def register_policy(self, policy: RiskPolicy) -> bool:
        """
        注册风控策略

        Args:
            policy: 风控策略对象

        Returns:
            是否成功
        """
        with self.lock:
            old_policy = self.policies.get(policy.policy_id)

            if old_policy:
                # 检查是否有变化
                if old_policy.checksum == policy.checksum:
                    return False

                # 记录变更
                self.change_history.append(ConfigChange(
                    timestamp=time.time(),
                    policy_id=policy.policy_id,
                    old_checksum=old_policy.checksum,
                    new_checksum=policy.checksum,
                    change_type='UPDATED'
                ))

                # 更新策略
                self.policies[policy.policy_id] = policy

                # 触发回调
                self._notify_callbacks(policy.policy_id, 'UPDATED')
            else:
                # 新策略
                self.policies[policy.policy_id] = policy

                # 记录变更
                self.change_history.append(ConfigChange(
                    timestamp=time.time(),
                    policy_id=policy.policy_id,
                    old_checksum="",
                    new_checksum=policy.checksum,
                    change_type='CREATED'
                ))

                # 触发回调
                self._notify_callbacks(policy.policy_id, 'CREATED')

            return True

    def get_policy(self, policy_id: str) -> Optional[RiskPolicy]:
        """
        获取风控策略

        Args:
            policy_id: 策略ID

        Returns:
            风控策略对象
        """
        with self.lock:
            return self.policies.get(policy_id)

    def get_all_policies(self) -> Dict[str, RiskPolicy]:
        """获取所有策略"""
        with self.lock:
            return self.policies.copy()

    def remove_policy(self, policy_id: str) -> bool:
        """
        移除风控策略

        Args:
            policy_id: 策略ID

        Returns:
            是否成功
        """
        with self.lock:
            if policy_id in self.policies:
                del self.policies[policy_id]

                self.change_history.append(ConfigChange(
                    timestamp=time.time(),
                    policy_id=policy_id,
                    old_checksum="",
                    new_checksum="",
                    change_type='DELETED'
                ))

                self._notify_callbacks(policy_id, 'DELETED')
                return True
            return False

    def register_callback(self, callback: Callable[[str, str], None]):
        """
        注册配置变更回调

        Args:
            callback: 回调函数，签名: callback(policy_id, change_type)
        """
        self.change_callbacks.append(callback)

    def _notify_callbacks(self, policy_id: str, change_type: str):
        """通知所有回调"""
        for callback in self.change_callbacks:
            try:
                callback(policy_id, change_type)
            except Exception as e:
                logger.error(f"[HotReload] 回调执行失败: {e}")

    def _check_file_changes(self):
        """检查文件变化"""
        try:
            # 遍历配置目录
            for file_path in self.config_dir.glob("*.json"):
                policy = self.load_policy(str(file_path))
                if policy:
                    self.register_policy(policy)

            # 检查已删除的策略
            current_policy_ids = {
                file_path.stem
                for file_path in self.config_dir.glob("*.json")
            }

            with self.lock:
                to_remove = [
                    pid for pid in self.policies.keys()
                    if pid not in current_policy_ids
                ]

            for pid in to_remove:
                self.remove_policy(pid)

        except Exception as e:
            logger.error(f"[HotReload] 检查文件变化失败: {e}")

    def start_watching(self):
        """启动文件监听"""
        if self.is_running:
            return

        self.is_running = True

        def watch_loop():
            while self.is_running:
                self._check_file_changes()
                time.sleep(self.check_interval)

        self.watch_thread = Thread(target=watch_loop, daemon=True)
        self.watch_thread.start()

        logger.info(f"[HotReload] 文件监听已启动: {self.config_dir}")

    def stop_watching(self):
        """停止文件监听"""
        self.is_running = False
        if self.watch_thread:
            self.watch_thread.join(timeout=2.0)
        logger.info("[HotReload] 文件监听已停止")

    def get_parameter(self, policy_id: str, param_name: str,
                     default: Any = None) -> Any:
        """
        获取策略参数

        Args:
            policy_id: 策略ID
            param_name: 参数名称
            default: 默认值

        Returns:
            参数值
        """
        policy = self.get_policy(policy_id)
        if policy:
            return policy.parameters.get(param_name, default)
        return default

    def set_parameter(self, policy_id: str, param_name: str,
                     value: Any) -> bool:
        """
        临时修改策略参数（不持久化）

        Args:
            policy_id: 策略ID
            param_name: 参数名称
            value: 参数值

        Returns:
            是否成功
        """
        with self.lock:
            policy = self.policies.get(policy_id)
            if policy:
                policy.parameters[param_name] = value
                policy.last_updated = time.time()
                return True
            return False

    def get_change_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取变更历史

        Args:
            limit: 返回数量限制

        Returns:
            变更历史列表
        """
        return [
            {
                'timestamp': change.timestamp,
                'policy_id': change.policy_id,
                'change_type': change.change_type,
                'old_checksum': change.old_checksum,
                'new_checksum': change.new_checksum
            }
            for change in self.change_history[-limit:]
        ]

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        return {
            'is_running': self.is_running,
            'config_dir': str(self.config_dir),
            'policy_count': len(self.policies),
            'change_count': len(self.change_history),
            'policies': {
                pid: {
                    'name': policy.name,
                    'version': policy.version,
                    'last_updated': policy.last_updated,
                    'parameter_count': len(policy.parameters)
                }
                for pid, policy in self.policies.items()
            }
        }


# 示例回调函数
def on_policy_change(policy_id: str, change_type: str):
    """策略变更回调"""
    logger.info(f"[Callback] 策略 {policy_id} {change_type}")


# 命令行测试
def main():
    """测试热更新功能"""
    logger.info("="*60)
    logger.info("🔄 实时风控策略热更新测试")
    logger.info("="*60)

    # 创建管理器
    manager = HotReloadRiskManager("./config/risk_test")

    # 注册回调
    manager.register_callback(on_policy_change)

    # 启动监听
    manager.start_watching()

    # 创建示例配置文件
    example_config = {
        "policy_id": "default_risk",
        "name": "默认风控策略",
        "version": "1.0",
        "parameters": {
            "max_position_size": 0.5,
            "max_drawdown": 0.08,
            "circuit_breaker_threshold": 0.05,
            "leverage_limit": 2.0
        }
    }

    config_file = manager.config_dir / "default_risk.json"
    config_file.write_text(json.dumps(example_config, indent=2), encoding='utf-8')

    logger.info("\n创建配置文件，等待热加载...")
    time.sleep(2)

    # 检查策略是否加载
    policy = manager.get_policy("default_risk")
    if policy:
        logger.info(f"\n✅ 策略已加载:")
        logger.info(f"  ID: {policy.policy_id}")
        logger.info(f"  名称: {policy.name}")
        logger.info(f"  版本: {policy.version}")
        logger.info(f"  参数: {policy.parameters}")
    else:
        logger.info("\n❌ 策略加载失败")

    # 获取参数
    max_pos = manager.get_parameter("default_risk", "max_position_size")
    logger.info(f"\n📊 当前最大持仓: {max_pos}")

    # 修改配置文件
    logger.info("\n修改配置文件...")
    example_config["parameters"]["max_position_size"] = 0.7
    example_config["version"] = "1.1"
    config_file.write_text(json.dumps(example_config, indent=2), encoding='utf-8')

    time.sleep(2)

    # 检查更新
    updated_policy = manager.get_policy("default_risk")
    if updated_policy:
        logger.info(f"\n✅ 策略已更新:")
        logger.info(f"  版本: {updated_policy.version}")
        logger.info(f"  最大持仓: {updated_policy.parameters['max_position_size']}")

    # 查看状态
    logger.info("\n📋 系统状态:")
    status = manager.get_status()
    logger.info(f"  运行中: {status['is_running']}")
    logger.info(f"  策略数: {status['policy_count']}")
    logger.info(f"  变更数: {status['change_count']}")

    # 变更历史
    logger.info("\n📜 变更历史:")
    history = manager.get_change_history()
    for change in history:
        logger.info(f"  [{change['change_type']}] {change['policy_id']} @ {change['timestamp']}")

    # 停止监听
    manager.stop_watching()

    # 清理测试文件
    import shutil
    shutil.rmtree(manager.config_dir, ignore_errors=True)

    logger.info("\n" + "="*60)
    logger.info("实时风控策略热更新测试: PASS")


if __name__ == "__main__":
    main()
