#!/usr/bin/env python3
"""
日志迁移工具 - v1.0.2 Stable
将print语句迁移到结构化日志
"""

import ast
import os
import sys
import subprocess
import tempfile
from pathlib import Path

class PrintMigrator:
    """Print语句迁移器"""

    def __init__(self, directory: str):
        self.directory = directory
        self.migrated = 0
        self.failed = 0
        self.skipped = 0

    def migrate_file(self, filepath: str) -> bool:
        """迁移单个文件"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            # 解析AST
            tree = ast.parse(content)

            # 查找print调用
            print_calls = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id == 'print':
                        print_calls.append(node)

            if not print_calls:
                return True

            # 转换print调用
            new_content = content
            offset = 0

            for call in print_calls:
                # 获取print语句的行号和内容
                lineno = call.lineno
                lines = content.split('\n')
                if lineno > len(lines):
                    continue

                line = lines[lineno - 1]
                stripped = line.strip()

                # 跳过测试脚本中的print（保留用于测试输出）
                if 'test' in filepath.lower() or 'quick' in filepath.lower():
                    self.skipped += 1
                    continue

                # 转换print为logger调用
                if '"✓"' in line or '"✗"' in line:
                    # 状态输出
                    replacement = stripped.replace('print(', 'logger.info(')
                elif '"WARNING"' in line or '"ERROR"' in line:
                    # 错误输出
                    replacement = stripped.replace('print(', 'logger.error(')
                else:
                    # 默认info级别
                    replacement = stripped.replace('print(', 'logger.debug(')

                # 替换内容
                new_content = new_content.replace(line, replacement)
                offset += 1

            if new_content != content:
                # 写回文件
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                self.migrated += 1
                return True

            self.skipped += 1
            return True

        except Exception as e:
            self.failed += 1
logger.debug(f"迁移失败: {filepath} - {e}")
            return False

    def migrate_directory(self):
        """迁移整个目录"""
        python_files = list(Path(self.directory).rglob('*.py'))
        python_files = [f for f in python_files if not any(x in str(f) for x in ['_archived', 'test', 'quick', 'e2e'])]

        for filepath in python_files:
logger.debug(f"处理: {filepath}")
            self.migrate_file(str(filepath))

logger.debug(f"\n迁移完成:")
logger.debug(f"  成功: {self.migrated}")
logger.debug(f"  跳过: {self.skipped}")
logger.debug(f"  失败: {self.failed}")

if __name__ == "__main__":
    directory = "scripts"
    migrator = PrintMigrator(directory)
    migrator.migrate_directory()
