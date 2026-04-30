# [ARCHIVED by Round 8 Integration - 2025-04-30]
# Reason: No active callers / Superseded

#!/usr/bin/env python3
"""
代码风格检查脚本
检查命名规范、导入顺序、缩进等
"""

import ast
import re
from pathlib import Path
from typing import List, Dict, Tuple


class CodeStyleChecker:
    """代码风格检查器"""

    def __init__(self, project_root: str = "scripts"):
        self.project_root = Path(project_root)
        self.issues: List[Dict] = []

    def check_file(self, file_path: Path) -> List[Dict]:
        """
        检查单个文件

        Args:
            file_path: 文件路径

        Returns:
            问题列表
        """
        issues = []

        try:
            if not file_path.exists():
                return issues

            if file_path.suffix != ".py":
                return issues

            # 跳过测试文件和缓存
            if "test_" in file_path.name or "__pycache__" in str(file_path):
                return issues

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 检查命名规范
            issues.extend(self._check_naming(file_path, content))

            # 检查导入顺序
            issues.extend(self._check_imports(file_path, content))

            # 检查空except块
            issues.extend(self._check_bare_except(file_path, content))

        except Exception as e:
            issues.append({
                "file": str(file_path),
                "type": "check_error",
                "line": 0,
                "message": f"检查失败: {e}"
            })

        return issues

    def _check_naming(self, file_path: Path, content: str) -> List[Dict]:
        """检查命名规范"""
        issues = []

        # 检查函数名是否为snake_case
        tree = ast.parse(content, filename=str(file_path))

        for node in ast.walk(tree):
            # 检查函数名
            if isinstance(node, ast.FunctionDef):
                if not node.name.islower() or not node.name.replace('_', '').isalnum():
                    if node.name[0].isupper():  # 排除特殊命名
                        continue
                    if re.match(r'^[A-Z_]+$', node.name):  # 排除常量
                        continue
                    issues.append({
                        "file": str(file_path),
                        "type": "naming",
                        "line": node.lineno,
                        "message": f"函数名应使用snake_case: {node.name}"
                    })

        return issues

    def _check_imports(self, file_path: Path, content: str) -> List[Dict]:
        """检查导入顺序"""
        issues = []

        # 检查是否有import语句
        if not re.search(r'^import |^from ', content, re.MULTILINE):
            return issues

        # 简单检查：标准库导入应该在前面
        standard_libs = {'os', 'sys', 'time', 'json', 're', 'pathlib', 'typing', 'logging'}
        third_party = {'numpy', 'pandas', 'requests'}

        lines = content.split('\n')
        imports = []
        for i, line in enumerate(lines, 1):
            if line.strip().startswith('import ') or line.strip().startswith('from '):
                imports.append((i, line))

        # 检查顺序
        has_std = False
        has_local = False
        has_third = False

        for line_no, line in imports:
            if any(lib in line for lib in standard_libs):
                has_std = True
            elif any(lib in line for lib in third_party):
                has_third = True
            elif 'scripts.' in line or '.' in line:
                has_local = True

        # 如果有本地导入但没有标准库导入，提示添加
        if has_local and not has_std:
            issues.append({
                "file": str(file_path),
                "type": "import_order",
                "line": 0,
                "message": "建议添加标准库导入"
            })

        return issues

    def _check_bare_except(self, file_path: Path, content: str) -> List[Dict]:
        """检查空except块"""
        issues = []

        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            if re.search(r'except:\s*$', line.strip()):
                # 检查下一行是否为pass或logger.debug
                if i < len(lines) and not re.search(r'pass|logger\.debug', lines[i]):
                    issues.append({
                        "file": str(file_path),
                        "type": "bare_except",
                        "line": i,
                        "message": "空except块应包含pass或logger.debug"
                    })

        return issues

    def scan_directory(self) -> Dict:
        """扫描目录"""
        total_issues = 0
        by_type = {}

        for py_file in self.project_root.rglob("*.py"):
            issues = self.check_file(py_file)
            self.issues.extend(issues)
            total_issues += len(issues)

            # 按类型分组
            for issue in issues:
                itype = issue['type']
                if itype not in by_type:
                    by_type[itype] = []
                by_type[itype].append(issue)

        return {
            "total_issues": total_issues,
            "by_type": by_type,
            "top_files": self._get_top_files()
        }

    def _get_top_files(self) -> List[Dict]:
        """获取问题最多的文件"""
        file_counts = {}
        for issue in self.issues:
            f = issue['file']
            if f not in file_counts:
                file_counts[f] = 0
            file_counts[f] += 1

        return sorted(
            [{"file": f, "count": c} for f, c in file_counts.items()],
            key=lambda x: x['count'],
            reverse=True
        )[:10]

    def generate_report(self) -> str:
        """生成报告"""
        result = self.scan_directory()

        lines = [
            "=" * 80,
            "代码风格检查报告",
            "=" * 80,
            f"\n总问题数: {result['total_issues']}",
            "\n按类型分类:"
        ]

        for itype, issues in result['by_type'].items():
            lines.append(f"\n  {itype}: {len(issues)} 处")

        if result['top_files']:
            lines.append("\n问题最多的文件 (Top 10):")
            for item in result['top_files']:
                lines.append(f"  {item['file']}: {item['count']} 处")

        lines.append("\n" + "=" * 80)

        return "\n".join(lines)


def main():
    """主函数"""
    import sys

    target_dir = sys.argv[1] if len(sys.argv) > 1 else "scripts"

    checker = CodeStyleChecker(target_dir)
    report = checker.generate_report()
    print(report)


if __name__ == "__main__":
    main()
