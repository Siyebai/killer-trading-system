#!/usr/bin/env python3
"""
批量修复json.dumps三元表达式错误 - 最终简单版
"""

from pathlib import Path


def fix_json_ternary(file_path: Path) -> bool:
    """修复json.dumps三元表达式错误"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        modified = False

        for i, line in enumerate(lines):
            # 查找: json.dumps({"key": value if condition else "default",)
            if 'json.dumps(' in line and '),' in line and ' if ' in line:
                # 移除多余的逗号和右括号
                new_line = line.replace('),)', '})')
                if new_line != line:
                    lines[i] = new_line
                    modified = True
                    print(f"  修复第 {i+1} 行")

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
    import ast

    # 找出有错误的文件
    error_files = []
    for py_file in Path('scripts').rglob('*.py'):
        if '__pycache__' in str(py_file):
            continue
        try:
            with open(py_file) as f:
                ast.parse(f.read())
        except:
            error_files.append(py_file)

    print(f"发现 {len(error_files)} 个有语法错误的文件")

    # 逐个修复
    fixed = 0
    for py_file in error_files:
        if fix_json_ternary(py_file):
            fixed += 1
            print(f"✓ 修复: {py_file.name}")

    # 验证
    remaining = 0
    for py_file in error_files:
        try:
            with open(py_file) as f:
                ast.parse(f.read())
        except:
            remaining += 1

    print(f"\n修复: {fixed} 个文件")
    print(f"仍有错误: {remaining} 个文件")


if __name__ == "__main__":
    main()
