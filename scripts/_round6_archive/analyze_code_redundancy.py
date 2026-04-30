# [ARCHIVED by Round 8 Integration - 2025-04-30]
# Reason: No active callers / Superseded

#!/usr/bin/env python3
"""
代码冗余分析工具
识别重复代码、未使用导入、重复函数
"""

import ast
import os
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Tuple


class CodeRedundancyAnalyzer:
    """代码冗余分析器"""

    def __init__(self, project_root: str = "scripts"):
        self.project_root = Path(project_root)
        self.imports: Dict[str, Set[str]] = defaultdict(set)
        self.defined_functions: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        self.used_functions: Dict[str, Set[str]] = defaultdict(set)

    def analyze_file(self, file_path: Path):
        """分析单个文件"""
        try:
            if not file_path.exists() or file_path.suffix != ".py":
                return

            if "test_" in file_path.name or "__pycache__" in str(file_path):
                return

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            tree = ast.parse(content, filename=str(file_path))
            module_name = file_path.stem

            # 分析导入
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.imports[module_name].add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for alias in node.names:
                            full_name = f"{node.module}.{alias.name}"
                            self.imports[module_name].add(full_name)

            # 分析函数定义
            for node in tree.body:
                if isinstance(node, ast.FunctionDef):
                    self.defined_functions[module_name].append((node.name, node.lineno))

                    # 分析函数内部使用的函数
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call):
                            if isinstance(child.func, ast.Name):
                                self.used_functions[module_name].add(child.func.id)
                            elif isinstance(child.func, ast.Attribute):
                                self.used_functions[module_name].add(child.func.attr)

        except Exception as e:
            print(f"分析失败 {file_path}: {e}")

    def analyze_directory(self):
        """分析整个目录"""
        for py_file in self.project_root.rglob("*.py"):
            self.analyze_file(py_file)

    def find_unused_imports(self) -> Dict[str, List[str]]:
        """查找未使用的导入"""
        unused = {}

        for module, imports in self.imports.items():
            unused_imports = []
            used = self.used_functions.get(module, set())

            for imp in imports:
                # 提取导入名称
                imp_name = imp.split('.')[-1]
                if imp_name not in used and imp_name not in ['logger', 'Optional', 'List', 'Dict']:
                    unused_imports.append(imp)

            if unused_imports:
                unused[module] = unused_imports

        return unused

    def find_duplicate_functions(self) -> List[Tuple[str, List[str]]]:
        """查找重复的函数名"""
        function_names = defaultdict(list)

        for module, functions in self.defined_functions.items():
            for func_name, line in functions:
                function_names[func_name].append(f"{module}:{line}")

        # 找出在多个文件中定义的函数
        duplicates = []
        for func_name, locations in function_names.items():
            if len(locations) > 1:
                duplicates.append((func_name, locations))

        return sorted(duplicates, key=lambda x: len(x[1]), reverse=True)

    def generate_report(self) -> str:
        """生成报告"""
        self.analyze_directory()

        unused_imports = self.find_unused_imports()
        duplicate_functions = self.find_duplicate_functions()

        lines = [
            "=" * 80,
            "代码冗余分析报告",
            "=" * 80,
            "\n---\n",
            "## 1. 未使用的导入"
        ]

        total_unused = 0
        for module, imports in sorted(unused_imports.items()):
            lines.append(f"\n{module}:")
            for imp in imports:
                lines.append(f"  - {imp}")
                total_unused += 1

        lines.extend([
            f"\n总计: {total_unused} 个未使用的导入",
            "\n---\n",
            "## 2. 重复的函数定义（可能需要合并）"
        ])

        for func_name, locations in duplicate_functions[:20]:
            lines.append(f"\n{func_name}: {len(locations)} 处")
            for loc in locations:
                lines.append(f"  - {loc}")

        lines.append("\n" + "=" * 80)

        return "\n".join(lines)


def main():
    """主函数"""
    import sys

    target_dir = sys.argv[1] if len(sys.argv) > 1 else "scripts"

    analyzer = CodeRedundancyAnalyzer(target_dir)
    report = analyzer.generate_report()
    print(report)


if __name__ == "__main__":
    main()
