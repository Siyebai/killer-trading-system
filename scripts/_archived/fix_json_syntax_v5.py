#!/usr/bin/env python3
"""
批量修复三元表达式中的json.dumps错误
修复模式: json.dumps({"key": value if condition else "default",)
"""

import re
from pathlib import Path


def fix_ternary_json_dumps(file_path: Path) -> bool:
    """修复三元表达式中的json.dumps错误"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        original = content

        # 修复模式: json.dumps({"key": value if condition else "default",)
        # 这是因为在三元表达式后错误地添加了逗号和右括号

        # 匹配: json.dumps({... if ... else ...,)
        pattern = r'json\.dumps\(\{([^}]+if\s+[^,]+,[)\]'
        replacement = r'json.dumps({\1\})'

        content = re.sub(pattern, replacement, content)

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
    fixed = 0

    for py_file in Path('scripts').rglob('*.py'):
        if '__pycache__' in str(py_file):
            continue

        if fix_ternary_json_dumps(py_file):
            fixed += 1
            print(f"✓ 修复: {py_file.name}")

    print(f"\n修复: {fixed} 个文件")


if __name__ == "__main__":
    main()
