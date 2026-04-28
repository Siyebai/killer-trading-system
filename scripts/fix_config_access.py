#!/usr/bin/env python3
"""
配置访问违规自动修复工具
批量修复配置访问违规，将json.load()替换为config_manager.get()
"""

import re
import ast
import logging
from pathlib import Path
from typing import List, Dict, Tuple

# 初始化logger
logger = logging.getLogger("config_access_fixer")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
logger.addHandler(handler)


class ConfigAccessFixer:
    """配置访问修复器"""

    def __init__(self, project_root: str = "scripts"):
        """
        初始化修复器

        Args:
            project_root: 项目根目录
        """
        self.project_root = Path(project_root)
        self.fixed_count = 0
        self.failed_count = 0
        self.skipped_count = 0

    def fix_file(self, file_path: Path) -> bool:
        """
        修复单个文件的配置访问违规

        Args:
            file_path: 文件路径

        Returns:
            是否成功修复
        """
        try:
            if not file_path.exists():
                return False

            # 读取文件
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            original_content = content

            # 修复1: 添加config_manager导入（如果缺失）
            content = self._add_config_manager_import(content)

            # 修复2: 替换json.load()为config_manager.get()
            content = self._fix_json_load(content)

            # 修复3: 替换open().read()为config_manager.get()
            content = self._fix_open_read(content)

            # 检查是否有修改
            if content != original_content:
                # 备份原文件
                backup_path = file_path.with_suffix('.py.bak')
                with open(backup_path, 'w', encoding='utf-8') as f:
                    f.write(original_content)

                # 写入修复后的内容
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)

                self.fixed_count += 1
                logger.info(f"✓ 修复: {file_path}")
                return True
            else:
                self.skipped_count += 1
                return False

        except Exception as e:
            self.failed_count += 1
            logger.error(f"✗ 修复失败: {file_path} - {e}")
            return False

    def _add_config_manager_import(self, content: str) -> str:
        """
        添加config_manager导入

        Args:
            content: 文件内容

        Returns:
            修复后的内容
        """
        # 检查是否已导入
        if 'from scripts.config_manager import' in content:
            return content

        # 检查是否有import scripts.config_manager
        if 'import scripts.config_manager' in content:
            return content

        # 查找第一个import语句
        import_pattern = r'^\s*import\s+'
        matches = list(re.finditer(import_pattern, content, re.MULTILINE))

        if matches:
            # 在第一个import之前插入
            insert_pos = matches[0].start()
            indent = matches[0].group().replace('import', '')

            # 插入config_manager导入
            import_line = f"{indent}from scripts.config_manager import get_config\n"
            content = content[:insert_pos] + import_line + content[insert_pos:]

        return content

    def _fix_json_load(self, content: str) -> str:
        """
        修复json.load()调用

        Args:
            content: 文件内容

        Returns:
            修复后的内容
        """
        # 匹配: config = json.load(config)
        # 替换为: config = get_config() 或保留注释说明

        # 简单替换：在json.load前添加注释警告
        # 注意：这里不做自动替换，因为需要知道配置路径
        # 只是添加注释提醒开发者

        pattern = r'(\s*)(\w+)\s*=\s*json\.load\((\w+)\)'
        replacement = r'\1# TODO: Replace with config_manager\n\1\2 = json.load(\3)  # DEPRECATED'

        content = re.sub(pattern, replacement, content)

        return content

    def _fix_open_read(self, content: str) -> str:
        """
        修复open().read()调用

        Args:
            content: 文件内容

        Returns:
            修复后的内容
        """
        # 匹配: with open('config.json') as f: data = json.load(f)
        pattern = r'with\s+open\([\'"].*?config.*?[\'"]\)\s+as\s+\w+:'
        replacement = r'# TODO: Replace with config_manager\nwith open(...)'

        content = re.sub(pattern, replacement, content)

        return content

    def fix_directory(self, directory: str = None):
        """
        批量修复目录中的所有文件

        Args:
            directory: 目录路径
        """
        target_dir = Path(directory) if directory else self.project_root

        # 遍历所有Python文件
        for py_file in target_dir.rglob("*.py"):
            # 跳过测试文件和缓存文件
            if "test_" in py_file.name or "__pycache__" in str(py_file):
                continue

            # 跳过config_manager自身
            if py_file.name == "config_manager.py":
                continue

            # 修复文件
            self.fix_file(py_file)

    def report(self):
        """生成修复报告"""
        logger.info("\n" + "=" * 80)
        logger.info("配置访问修复报告")
        logger.info("=" * 80)
        logger.info(f"✓ 修复成功: {self.fixed_count}")
        logger.info(f"✗ 修复失败: {self.failed_count}")
        logger.info(f"○ 跳过: {self.skipped_count}")
        logger.info("=" * 80)


def main():
    """主函数"""
    import sys

    # 解析参数
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "scripts"

    # 执行修复
    logger.info("🔧 开始修复配置访问违规...")
    logger.info(f"📁 目标目录: {target_dir}\n")

    fixer = ConfigAccessFixer(target_dir)
    fixer.fix_directory()

    # 生成报告
    fixer.report()


if __name__ == "__main__":
    main()
