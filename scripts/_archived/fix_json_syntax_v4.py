#!/usr/bin/env python3
"""
批量修复JSON语法错误 v4.0 - 最终版
使用多模式精确修复
"""

import ast
from pathlib import Path


def fix_json_dumps_syntax(file_path: Path) -> bool:
    """修复json.dumps语法错误"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        original = content

        # 修复模式1: json.dumps({...},) -> json.dumps({...},
        # 这种情况是因为三元表达式中的逗号误放
        import re

        # 匹配: json.dumps({"key": value,)} 并移除多余括号
        content = re.sub(r'json\.dumps\(\{([^}]+),\)\s*\)', r'json.dumps({\1\})', content)

        # 匹配: json.dumps({"key": value if condition else value,)}
        content = re.sub(
            r'json\.dumps\(\{([^}]+if[^,]+,\)\}',
            lambda m: m.group(0).replace('),)', '})'),
            content
        )

        if content != original:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True

        return False

    except Exception as e:
        return False


def verify_and_fix_all():
    """验证并修复所有文件"""
    import ast

    files_with_errors = []

    # 第一次扫描
    for py_file in Path('scripts').rglob('*.py'):
        if '__pycache__' in str(py_file):
            continue
        try:
            with open(py_file) as f:
                ast.parse(f.read())
        except:
            files_with_errors.append(py_file)

    print(f"发现 {len(files_with_errors)} 个有语法错误的文件")

    # 逐个修复
    fixed = 0
    for py_file in files_with_errors:
        if fix_json_dumps_syntax(py_file):
            fixed += 1
            print(f"✓ 修复: {py_file.name}")

    # 验证修复结果
    remaining = 0
    for py_file in files_with_errors:
        try:
            with open(py_file) as f:
                ast.parse(f.read())
        except:
            remaining += 1

    print(f"\n修复: {fixed} 个文件")
    print(f"仍有错误: {remaining} 个文件")


if __name__ == "__main__":
    verify_and_fix_all()
