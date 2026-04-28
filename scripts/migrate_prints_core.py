#!/usr/bin/env python3
"""
日志迁移工具 - v1.0.0 Stable (Core Only)
只迁移核心模块，跳过有语法错误的文件
"""

import os
import re
from pathlib import Path

class PrintMigratorCore:
    """Print语句迁移器（仅核心模块）"""

    def __init__(self, directory: str):
        self.directory = directory
        self.migrated = 0
        self.failed = 0

    def migrate_file(self, filepath: str) -> bool:
        """迁移单个文件"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            new_content = content
            lines = content.split('\n')

            modified = False
            for i, line in enumerate(lines):
                stripped = line.strip()

                # 匹配print语句
                if not stripped.startswith('print('):
                    continue

                # 跳过测试脚本
                if 'test' in filepath.lower() or 'quick' in filepath.lower() or 'e2e' in filepath.lower():
                    continue

                # 替换print为logger
                if '"✓"' in line or '"✗"' in line:
                    replacement = stripped.replace('print(', 'logger.info(')
                elif '"WARNING"' in line or '"ERROR"' in line:
                    replacement = stripped.replace('print(', 'logger.error(')
                else:
                    replacement = stripped.replace('print(', 'logger.debug(')

                if replacement != stripped:
                    lines[i] = replacement
                    modified = True

            if modified:
                new_content = '\n'.join(lines)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                self.migrated += 1
                return True

            return False

        except Exception as e:
            self.failed += 1
            return False

    def migrate_core_modules(self):
        """仅迁移核心模块"""
        core_modules = [
            'global_controller.py',
            'event_bus.py',
            'strategy_engine.py',
            'risk_engine.py',
            'order_lifecycle_manager.py',
            'market_scanner.py',
            'ev_filter.py',
            'repair_upgrade_protocol.py',
            'strategy_lab.py',
            'historical_data_loader.py',
            'backtest_adapter.py',
            'meta_controller.py',
            'orderbook_feeder.py',
            'anomaly_detector.py',
            'health_check.py',
        ]

        for module in core_modules:
            filepath = os.path.join(self.directory, module)
            if not os.path.exists(filepath):
                continue

            print(f"处理: {module}")
            self.migrate_file(filepath)

        print(f"\n核心模块迁移完成:")
        print(f"  成功: {self.migrated}")
        print(f"  失败: {self.failed}")

if __name__ == "__main__":
    directory = "scripts"
    migrator = PrintMigratorCore(directory)
    migrator.migrate_core_modules()
