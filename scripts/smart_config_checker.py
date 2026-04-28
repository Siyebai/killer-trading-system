#!/usr/bin/env python3
"""
智能配置访问检查器
只检查真正需要访问配置但未使用config_manager的文件
"""

import re
import ast
from pathlib import Path
from typing import List, Dict, Set


class SmartConfigChecker:
    """智能配置检查器"""

    def __init__(self, project_root: str = "scripts"):
        self.project_root = Path(project_root)
        self.violations: List[Dict] = []

    def check_file(self, file_path: Path) -> List[Dict]:
        """
        检查单个文件

        Args:
            file_path: 文件路径

        Returns:
            违规列表
        """
        violations = []

        try:
            # 跳过测试文件
            if "test_" in file_path.name or "__pycache__" in str(file_path):
                return violations

            # 跳过config_manager自身
            if file_path.name == "config_manager.py":
                return violations

            # 读取文件
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 解析AST
            tree = ast.parse(content, filename=str(file_path))

            # 检查是否使用了json.load()
            uses_json_load = self._check_json_load_usage(tree)

            # 检查是否导入了config_manager
            imports_config_manager = self._check_config_manager_import(tree)

            # 如果使用了json.load()但未导入config_manager，且加载的是配置文件
            if uses_json_load and not imports_config_manager:
                # 进一步检查json.load()是否用于配置文件
                config_loads = self._check_config_file_loads(content)
                if config_loads:
                    violations.extend(config_loads)

        except Exception as e:
            # 忽略解析错误
            pass

        return violations

    def _check_json_load_usage(self, tree: ast.AST) -> bool:
        """
        检查是否使用了json.load()

        Args:
            tree: AST树

        Returns:
            是否使用
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == 'load':
                        # 检查是否是json.load()
                        if isinstance(node.func.value, ast.Name):
                            if node.func.value.id == 'json':
                                return True
        return False

    def _check_config_manager_import(self, tree: ast.AST) -> bool:
        """
        检查是否导入了config_manager

        Args:
            tree: AST树

        Returns:
            是否导入
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and 'config_manager' in node.module:
                    return True
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if 'config_manager' in alias.name:
                        return True
        return False

    def _check_config_file_loads(self, content: str) -> List[Dict]:
        """
        检查是否加载了配置文件

        Args:
            content: 文件内容

        Returns:
            违规列表
        """
        violations = []

        # 匹配配置文件名
        config_patterns = [
            r'open\([\'"]config\.json[\'"]\)',
            r'open\([\'"]settings\.json[\'"]\)',
            r'open\([\'"]config/.*?\.json[\'"]\)',
        ]

        for pattern in config_patterns:
            if re.search(pattern, content):
                violations.append({
                    "file": "unknown",
                    "type": "config_file_direct_load",
                    "message": "直接加载配置文件，应使用config_manager"
                })
                break

        return violations


def main():
    """主函数"""
    import sys

    target_dir = sys.argv[1] if len(sys.argv) > 1 else "scripts"
    checker = SmartConfigChecker(target_dir)

    # 扫描目录
    for py_file in Path(target_dir).rglob("*.py"):
        violations = checker.check_file(py_file)
        for v in violations:
            print(f"违规: {py_file} - {v['message']}")

    print(f"\n总计: {len(checker.violations)} 处违规")


if __name__ == "__main__":
    main()
