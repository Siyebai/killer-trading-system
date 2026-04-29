#!/usr/bin/env python3
"""
批量修复跨行json.dumps错误
"""

from pathlib import Path


def fix_multiline_json_dumps(file_path: Path) -> bool:
    """修复跨行json.dumps错误"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        modified = False

        for i in range(len(lines) - 1):
            # 查找第1行: json.dumps({... if ... else ...,)
            line1 = lines[i]
            line2 = lines[i + 1]

            if ('json.dumps(' in line1 and '),' in line1 and
                ' if ' in line1 and
                line2.strip().startswith('"')):

                # 移除第1行末尾的),添加,
                if line1.rstrip().endswith('),'):
                    lines[i] = line1.rstrip()[:-1] + ',\n'
                    modified = True
                    print(f"  修复第 {i+1}-{i+2} 行")

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

    fixed = 0
    for py_file in error_files:
        if fix_multiline_json_dumps(py_file):
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
