#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("state_manager")
except ImportError:
    import logging
    logger = logging.getLogger("state_manager")
"""
状态管理器 - 持久化存储和状态恢复
支持跨平台文件锁（Windows/Linux/macOS）
"""

import json
import os
import time
import threading
import sys
from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime


# ================== 跨平台文件锁 ==================
class CrossPlatformFileLock:
    """跨平台文件锁"""

    def __init__(self, file_handle):
        self.file_handle = file_handle
        self.locked = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

    def acquire(self, exclusive: bool = True):
        """获取文件锁"""
        try:
            if sys.platform == 'win32':
                # Windows: 使用 msvcrt
                import msvcrt
                lock_type = msvcrt.LK_LOCK if exclusive else msvcrt.LK_RLOCK
                msvcrt.locking(self.file_handle.fileno(), lock_type, 1)
            else:
                # Linux/macOS: 使用 fcntl
                import fcntl
                lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                fcntl.flock(self.file_handle.fileno(), lock_type)
            self.locked = True
            return True
        except Exception as e:
            # 锁失败不阻塞，继续执行
            logger.error(f"[Warning] 文件锁获取失败: {e}")
            return False

    def release(self):
        """释放文件锁"""
        if not self.locked:
            return

        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(self.file_handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file_handle.fileno(), fcntl.LOCK_UN)
            self.locked = False
        except Exception as e:
            logger.error(f"[Warning] 文件锁释放失败: {e}")


# ================== 状态管理器 ==================
class StateManager:
    """状态管理器，提供持久化和恢复功能"""

    def __init__(self, state_dir: str = "./state"):
        """
        初始化状态管理器

        Args:
            state_dir: 状态文件存储目录
        """
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.state_files = {
            'portfolio': self.state_dir / 'portfolio.json',
            'positions': self.state_dir / 'positions.json',
            'trades': self.state_dir / 'trades.json',
            'strategy_weights': self.state_dir / 'strategy_weights.json',
            'risk_stats': self.state_dir / 'risk_stats.json',
            'system_state': self.state_dir / 'system_state.json'
        }

    def save_portfolio(self, portfolio_data: Dict[str, Any]) -> bool:
        """保存投资组合状态"""
        return self._save_state('portfolio', portfolio_data)

    def load_portfolio(self) -> Optional[Dict[str, Any]]:
        """加载投资组合状态"""
        return self._load_state('portfolio')

    def save_positions(self, positions: Dict[str, Any]) -> bool:
        """保存持仓状态"""
        return self._save_state('positions', positions)

    def load_positions(self) -> Optional[Dict[str, Any]]:
        """加载持仓状态"""
        return self._load_state('positions')

    def save_trade(self, trade: Dict[str, Any]) -> bool:
        """保存单笔交易"""
        with self.lock:
            trades = self._load_state('trades') or []
            trades.append(trade)
            # 只保留最近1000笔交易
            if len(trades) > 1000:
                trades = trades[-1000:]
            return self._save_state('trades', trades)

    def load_trades(self) -> Optional[list]:
        """加载所有交易记录"""
        return self._load_state('trades')

    def save_strategy_weights(self, weights: Dict[str, float]) -> bool:
        """保存策略权重"""
        return self._save_state('strategy_weights', weights)

    def load_strategy_weights(self) -> Optional[Dict[str, float]]:
        """加载策略权重"""
        return self._load_state('strategy_weights')

    def save_risk_stats(self, stats: Dict[str, Any]) -> bool:
        """保存风控统计"""
        return self._save_state('risk_stats', stats)

    def load_risk_stats(self) -> Optional[Dict[str, Any]]:
        """加载风控统计"""
        return self._load_state('risk_stats')

    def save_system_state(self, state: Dict[str, Any]) -> bool:
        """保存系统状态"""
        state['last_saved'] = time.time()
        return self._save_state('system_state', state)

    def load_system_state(self) -> Optional[Dict[str, Any]]:
        """加载系统状态"""
        return self._load_state('system_state')

    def _save_state(self, key: str, data: Any) -> bool:
        """内部：保存状态"""
        try:
            file_path = self.state_files.get(key)
            if not file_path:
                return False

            # 使用临时文件+原子替换
            temp_path = file_path.with_suffix('.tmp')

            with open(temp_path, 'w', encoding='utf-8') as f:
                # 获取文件锁
                with CrossPlatformFileLock(f):
                    json.dump(data, f, ensure_ascii=False, indent=2)

            # 原子替换
            temp_path.replace(file_path)

            return True
        except Exception as e:
            logger.error(f"[StateManager] 保存状态失败 ({key}): {e}")
            return False

    def _load_state(self, key: str) -> Optional[Any]:
        """内部：加载状态"""
        try:
            file_path = self.state_files.get(key)
            if not file_path or not file_path.exists():
                return None

            with open(file_path, 'r', encoding='utf-8') as f:
                # 获取文件锁
                with CrossPlatformFileLock(f):
                    data = json.load(f)

            return data
        except json.JSONDecodeError as e:
            logger.error(f"[StateManager] JSON解析失败 ({key}): {e}")
            return None
        except Exception as e:
            logger.error(f"[StateManager] 加载状态失败 ({key}): {e}")
            return None

    def backup_all_states(self) -> str:
        """备份所有状态"""
        import shutil

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = self.state_dir.parent / f'backup_{timestamp}'
        backup_dir.mkdir(parents=True, exist_ok=True)

        for key, file_path in self.state_files.items():
            if file_path.exists():
                shutil.copy2(file_path, backup_dir / file_path.name)

        return str(backup_dir)

    def restore_from_backup(self, backup_path: str) -> bool:
        """从备份恢复"""
        import shutil

        backup_dir = Path(backup_path)
        if not backup_dir.exists():
            return False

        for key, file_path in self.state_files.items():
            backup_file = backup_dir / file_path.name
            if backup_file.exists():
                shutil.copy2(backup_file, file_path)

        return True

    def clear_all_states(self) -> bool:
        """清除所有状态（谨慎使用）"""
        try:
            for file_path in self.state_files.values():
                if file_path.exists():
                    file_path.unlink()
            return True
        except Exception as e:
            logger.error(f"[StateManager] 清除状态失败: {e}")
            return False
