#!/usr/bin/env python3
"""
依赖分析脚本
分析各模块的导入依赖图，输出文本版依赖树，标记循环依赖
"""

import ast
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import defaultdict


class DependencyAnalyzer:
    """依赖分析器"""

    def __init__(self, project_root: str = "scripts"):
        self.project_root = Path(project_root)
        self.dependencies: Dict[str, Set[str]] = defaultdict(set)
        self.circular_deps: List[Tuple[str, str, str]] = []

    def analyze_file(self, file_path: Path) -> Set[str]:
        """
        分析单个文件的依赖

        Args:
            file_path: 文件路径

        Returns:
            依赖列表
        """
        deps = set()

        try:
            if not file_path.exists():
                return deps

            if file_path.suffix != ".py":
                return deps

            # 跳过测试文件和缓存
            if "test_" in file_path.name or "__pycache__" in str(file_path):
                return deps

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            tree = ast.parse(content, filename=str(file_path))

            for node in ast.walk(tree):
                # 分析from ... import ...
                if isinstance(node, ast.ImportFrom):
                    if node.module:
                        # 只关心本地模块（scripts.）
                        if node.module.startswith('scripts.'):
                            module_name = node.module.replace('scripts.', '')
                            deps.add(module_name)

                        # 也记录直接import scripts.xxx
                        for alias in node.names:
                            if alias.name.startswith('scripts.'):
                                module_name = alias.name.replace('scripts.', '').split('.')[0]
                                deps.add(module_name)

                # 分析import ...
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith('scripts.'):
                            module_name = alias.name.replace('scripts.', '').split('.')[0]
                            deps.add(module_name)

        except Exception as e:
            print(f"分析失败 {file_path}: {e}")

        return deps

    def analyze_directory(self):
        """分析整个目录"""
        print("分析模块依赖...")

        for py_file in self.project_root.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue

            deps = self.analyze_file(py_file)

            if deps:
                module_name = py_file.stem
                self.dependencies[module_name] = deps

        print(f"发现 {len(self.dependencies)} 个模块")

    def detect_circular_dependencies(self):
        """检测循环依赖"""
        print("检测循环依赖...")

        # 使用深度优先搜索检测循环
        visited = set()
        rec_stack = set()

        def dfs(node, path):
            if node in rec_stack:
                # 找到循环
                cycle_start = path.index(node)
                cycle = path[cycle_start:] + [node]
                self.circular_deps.append(tuple(cycle))
                return True

            if node in visited:
                return False

            visited.add(node)
            rec_stack.add(node)

            # 遍历依赖
            for dep in self.dependencies.get(node, []):
                if dfs(dep, path + [node]):
                    return True

            rec_stack.remove(node)
            return False

        # 对每个节点执行DFS
        for node in self.dependencies:
            if node not in visited:
                dfs(node, [])

        print(f"发现 {len(self.circular_deps)} 个循环依赖")

    def generate_dependency_tree(self) -> str:
        """生成依赖树"""
        lines = [
            "=" * 80,
            "模块依赖分析报告",
            "=" * 80,
            f"\n总模块数: {len(self.dependencies)}",
            f"循环依赖数: {len(self.circular_deps)}",
            "\n---\n",
            "## 依赖树"
        ]

        # 按字母顺序排序
        sorted_modules = sorted(self.dependencies.keys())

        for module in sorted_modules:
            deps = sorted(self.dependencies[module])

            if deps:
                lines.append(f"\n{module}:")
                for dep in deps:
                    lines.append(f"  ├─ {dep}")

        # 循环依赖
        if self.circular_deps:
            lines.append("\n\n---\n")
            lines.append("## 循环依赖警告")

            for i, cycle in enumerate(self.circular_deps, 1):
                lines.append(f"\n{i}. {' → '.join(cycle)} → {cycle[0]}")

        lines.append("\n" + "=" * 80)

        return "\n".join(lines)

    def generate_report(self) -> str:
        """生成完整报告"""
        self.analyze_directory()
        self.detect_circular_dependencies()

        return self.generate_dependency_tree()

    def run(self):
        """运行分析"""
        print("=" * 80)
        print("启动依赖分析")
        print("=" * 80)
        print()

        report = self.generate_report()

        print()
        print(report)

        # 保存报告
        report_path = self.project_root / "references" / "dependency_analysis.md"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)

        print(f"\n报告已保存: {report_path}")


def main():
    """主函数"""
    import sys

    target_dir = sys.argv[1] if len(sys.argv) > 1 else "scripts"

    analyzer = DependencyAnalyzer(target_dir)
    analyzer.run()


if __name__ == "__main__":
    main()
