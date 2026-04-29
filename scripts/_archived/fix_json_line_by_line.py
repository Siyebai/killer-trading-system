#!/usr/bin/env python3
"""
批量修复JSON语法错误 - 逐行精确版
"""

from pathlib import Path


def fix_json_line_by_line(file_path: Path) -> bool:
    """逐行精确修复"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        modified = False

        for i in range(len(lines)):
            original_line = lines[i]

            # 修复: logger.info((json.dumps({ -> logger.info(json.dumps({
            if '(json.dumps({' in original_line:
                # 确保是logger调用
                if any(f'logger.{level}(' in original_line for level in ['info', 'error', 'warning', 'debug']):
                    # 替换双重左括号为单括号
                    lines[i] = original_line.replace('(json.dumps({', '(json.dumps({').replace('((json.dumps({', '(json.dumps({')
                    if lines[i] != original_line:
                        modified = True
                        print(f"  修复第{i+1}行")

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
    fixed_count = 0
    for py_file in error_files:
        if fix_json_line_by_line(py_file):
            fixed_count += 1
            print(f"✓ 修复: {py_file.name}")

    # 验证修复结果
    remaining_count = 0
    for py_file in error_files:
        try:
            with open(py_file) as f:
                ast.parse(f.read())
        except:
            remaining_count += 1

    print(f"\n修复: {fixed_count} 个文件")
    print(f"仍有错误: {remaining_count} 个文件")

    if remaining_count == 0:
        print("\n🎉 所有语法错误已修复！")
    else:
        print(f"\n⚠️ 仍有 {remaining_count} 个文件需要进一步处理")


if __name__ == "__main__":
    main()
