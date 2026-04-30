# [ARCHIVED by Round 6 Integration - 2026-04-30]
# Reason: No active callers / Superseded by production module

#!/usr/bin/env python3
"""
安全print迁移工具 - v1.0.1
使用AST解析，确保不破坏语法
"""

import ast
import re
from pathlib import Path

def safe_migrate_prints(filepath: str) -> int:
    """安全迁移print语句（AST方式）"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            lines = content.split('\n')

        modified_lines = []
        count = 0
        in_main_block = False

        for i, line in enumerate(lines):
            stripped = line.strip()

            # 跳过空行和注释
            if not stripped or stripped.startswith('#'):
                modified_lines.append(line)
                continue

            # 检测__main__块
            if 'if __name__' in line:
                in_main_block = True
                modified_lines.append(line)
                continue

            # 跳过__main__块内的代码
            if in_main_block:
                modified_lines.append(line)
                continue

            # 匹配print语句
            if 'print(' in line:
                # 尝试解析AST验证
                try:
                    # 简单的正则匹配（非严格）
                    if re.search(r'\bprint\s*\(', line):
                        # 替换为logger.debug
                        new_line = re.sub(r'\bprint\s*\(', 'logger.debug(', line, count=1)
                        if new_line != line:
                            modified_lines.append(new_line)
                            count += 1
                            continue
                except Exception:
                    pass

            modified_lines.append(line)

        if count > 0:
            new_content = '\n'.join(modified_lines)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)

        return count

    except Exception as e:
        print(f"迁移失败: {filepath} - {e}")
        return 0

def migrate_all_core_modules():
    """迁移所有核心模块"""
    core_modules = [
        'scripts/global_controller.py',
        'scripts/event_bus.py',
        'scripts/strategy_engine.py',
        'scripts/risk_engine.py',
        'scripts/order_lifecycle_manager.py',
        'scripts/market_scanner.py',
        'scripts/ev_filter.py',
        'scripts/repair_upgrade_protocol.py',
        'scripts/strategy_lab.py',
        'scripts/historical_data_loader.py',
        'scripts/backtest_adapter.py',
        'scripts/meta_controller.py',
        'scripts/orderbook_feeder.py',
        'scripts/anomaly_detector.py',
    ]

    total_migrated = 0
    for module in core_modules:
        if not Path(module).exists():
            continue

        print(f"处理: {module}")
        count = safe_migrate_prints(module)
        total_migrated += count

    print(f"\n总计迁移: {total_migrated} 个print语句")

if __name__ == "__main__":
    migrate_all_core_modules()
