#!/usr/bin/env python3
"""
批量修复JSON语法错误
修复模式：json.dumps({
        ) -> json.dumps({
"""

import re
from pathlib import Path


def fix_json_dumps_syntax(file_path: Path) -> bool:
    """
    修复json.dumps语法错误

    Returns:
        是否修复
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        original = content

        # 模式1: json.dumps({
        -> json.dumps({
        pattern1 = r'json\.dumps\(\{\}\s*'
        content = re.sub(pattern1, 'json.dumps({\n        ', content)

        # 模式2: json.dumps({
        )后面跟着换行和字符串
        pattern2 = r'json\.dumps\(\{\}\s*\n'
        content = re.sub(pattern2, 'json.dumps({\n        ', content)

        if content != original:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True

        return False

    except Exception as e:
        print(f"修复失败 {file_path}: {e}")
        return False


def main():
    """主函数"""
    import sys

    fixed_count = 0
    total_count = 0

    for py_file in Path('scripts').rglob('*.py'):
        if '__pycache__' in str(py_file):
            continue

        total_count += 1
        if fix_json_dumps_syntax(py_file):
            fixed_count += 1
            print(f"✓ 修复: {py_file}")

    print(f"\n总计: {fixed_count}/{total_count} 文件已修复")


if __name__ == "__main__":
    main()
