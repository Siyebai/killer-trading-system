#!/usr/bin/env python3
"""
批量修复JSON语法错误 v2.0
修复所有json.dumps({})语法错误
"""

import re
from pathlib import Path


def fix_json_syntax_in_file(file_path: Path) -> bool:
    """
    修复单个文件的JSON语法错误

    Returns:
        是否修复
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        original = content

        # 模式1: json.dumps({} 后跟换行和字符串
        pattern1 = r'json\.dumps\(\{\}\s*\n\s*(["\'])'
        replacement1 = r'json.dumps({\n        \1'
        content = re.sub(pattern1, replacement1, content)

        # 模式2: json.dumps({}) 后跟缩进和字符串
        pattern2 = r'json\.dumps\(\{\}\s*\n\s*([a-z_]+["\'])'
        replacement2 = r'json.dumps({\n            \1'
        content = re.sub(pattern2, replacement2, content)

        # 模式3: json.dumps({}) 后跟其他字符
        pattern3 = r'json\.dumps\(\{\}\s*\n\s*'
        replacement3 = r'json.dumps({\n        '
        content = re.sub(pattern3, replacement3, content)

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
    failed_count = 0

    for py_file in Path('scripts').rglob('*.py'):
        if '__pycache__' in str(py_file):
            continue

        if fix_json_syntax_in_file(py_file):
            fixed_count += 1
            print(f"✓ 修复: {py_file.name}")
        else:
            # 检查是否仍有错误
            try:
                import ast
                with open(py_file) as f:
                    ast.parse(f.read())
            except:
                failed_count += 1

    print(f"\n修复完成: {fixed_count} 个文件")
    print(f"仍有错误: {failed_count} 个文件")


if __name__ == "__main__":
    main()
