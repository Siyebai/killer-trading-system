#!/usr/bin/env python3
"""
批量修复JSON语法错误 v3.0
精确修复json.dumps语法错误
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
            lines = f.readlines()

        modified = False

        for i, line in enumerate(lines):
            # 检查是否有json.dumps后跟多余括号
            if 'json.dumps' in line and '),' in line:
                # 模式: json.dumps({...},)
                # 修复: json.dumps({...},
                if re.search(r'json\.dumps\(\{[^}]*\}\),\s*$', line):
                    lines[i] = line.replace('),', ',')
                    modified = True
                    print(f"  修复第 {i+1} 行: {line.strip()[:60]}...")

        if modified:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            return True

        return False

    except Exception as e:
        print(f"修复失败 {file_path}: {e}")
        return False


def main():
    """主函数"""
    import sys

    fixed_count = 0

    for py_file in Path('scripts').rglob('*.py'):
        if '__pycache__' in str(py_file):
            continue

        if fix_json_syntax_in_file(py_file):
            fixed_count += 1
            print(f"✓ 修复: {py_file.name}")

    print(f"\n修复完成: {fixed_count} 个文件")


if __name__ == "__main__":
    main()
