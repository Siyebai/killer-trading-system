#!/usr/bin/env python3
"""
配置访问规范化检查脚本 - Phase 5.5 P0
检查所有模块是否通过config_manager读取配置
"""

import os
import re
import ast
import json
import logging
from pathlib import Path
from typing import List, Dict, Set, Tuple

# 初始化logger
logger = logging.getLogger("config_access_checker")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
logger.addHandler(handler)


class ConfigAccessChecker:
    """配置访问检查器"""

    def __init__(self, project_root: str = "scripts"):
        """
        初始化检查器

        Args:
            project_root: 项目根目录
        """
        self.project_root = Path(project_root)
        self.violations: List[Dict] = []
        self.whitelist = {
            "config_manager.py",  # 配置管理器自身
            "test_",  # 测试文件
            "__pycache__",  # 缓存目录
            "event_bus.py",  # 事件总线（可能需要临时加载）
        }

    def check_file(self, file_path: Path) -> List[Dict]:
        """
        检查单个文件

        Args:
            file_path: 文件路径

        Returns:
            违规列表
        """
        violations = []

        try:
            # 第一层防御：文件存在性检查
            if not file_path.exists():
                return violations

            # 第二层防御：文件类型检查
            if not file_path.suffix == ".py":
                return violations

            # 白名单过滤
            if any(pattern in file_path.name for pattern in self.whitelist):
                return violations

            # 读取文件内容
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 检查非法配置访问模式
            violations.extend(self._check_illegal_json_load(file_path, content))
            violations.extend(self._check_illegal_open_json(file_path, content))
            violations.extend(self._check_missing_config_manager(file_path, content))

        except Exception as e:
            violations.append({
                "file": str(file_path),
                "type": "check_error",
                "line": 0,
                "message": f"检查文件时出错: {e}"
            })

        return violations

    def _check_illegal_json_load(self, file_path: Path, content: str) -> List[Dict]:
        """
        检查非法的 json.load() 调用

        Args:
            file_path: 文件路径
            content: 文件内容

        Returns:
            违规列表
        """
        violations = []

        # 匹配 json.load() 模式（不包括 config_manager 内部）
        pattern = r'\bjson\.load\s*\('

        for match in re.finditer(pattern, content):
            # 获取匹配位置的行号
            line_num = content[:match.start()].count('\n') + 1
            line_content = content.split('\n')[line_num - 1]

            # 第三层防御：过滤误报
            # 1. 如果是 import 语句中的 json.load（如 from json import load），忽略
            if 'import json' in line_content or 'from json import' in line_content:
                continue

            # 2. 如果是注释，忽略
            if line_content.strip().startswith('#'):
                continue

            # 3. 如果是字符串中的内容，忽略
            if '"json.load"' in line_content or "'json.load'" in line_content:
                continue

            violations.append({
                "file": str(file_path),
                "type": "illegal_json_load",
                "line": line_num,
                "code": line_content.strip(),
                "message": "发现 json.load() 调用，应通过 config_manager.get() 读取配置"
            })

        return violations

    def _check_illegal_open_json(self, file_path: Path, content: str) -> List[Dict]:
        """
        检查非法的 open(json_file) 模式

        Args:
            file_path: 文件路径
            content: 文件内容

        Returns:
            违规列表
        """
        violations = []

        # 匹配 open("xxx.json") 模式
        pattern = r'\bopen\s*\(\s*["\'][^"\']+\.json["\']'

        for match in re.finditer(pattern, content):
            line_num = content[:match.start()].count('\n') + 1
            line_content = content.split('\n')[line_num - 1]

            # 过滤误报
            if line_content.strip().startswith('#'):
                continue

            if '"open(' in line_content or "'open('" in line_content:
                continue

            violations.append({
                "file": str(file_path),
                "type": "illegal_open_json",
                "line": line_num,
                "code": line_content.strip(),
                "message": "发现直接打开 .json 文件，应通过 config_manager.get() 读取配置"
            })

        return violations

    def _check_missing_config_manager(self, file_path: Path, content: str) -> List[Dict]:
        """
        检查缺少 config_manager 导入但使用了配置的文件

        Args:
            file_path: 文件路径
            content: 文件内容

        Returns:
            违规列表
        """
        violations = []

        # 检查是否导入了 config_manager
        has_config_manager = bool(
            re.search(r'from.*config_manager.*import', content) or
            re.search(r'import.*config_manager', content)
        )

        # 检查是否使用了配置相关关键词
        config_keywords = [
            r'\bconfig\s*[\[\.]',
            r'config_manager',
            r'\.json\s*\)',
            r'["\']assets/configs'
        ]

        has_config_usage = any(re.search(keyword, content) for keyword in config_keywords)

        if has_config_usage and not has_config_manager:
            violations.append({
                "file": str(file_path),
                "type": "missing_config_manager",
                "line": 1,
                "code": "N/A",
                "message": "文件使用了配置相关功能，但未导入 config_manager"
            })

        return violations

    def scan_directory(self) -> Dict:
        """
        扫描整个目录

        Returns:
            扫描结果字典
        """
        total_files = 0
        violations_by_type: Dict[str, int] = {}

        # 遍历所有Python文件
        for file_path in self.project_root.rglob("*.py"):
            file_violations = self.check_file(file_path)

            if file_violations:
                self.violations.extend(file_violations)

                # 统计违规类型
                for v in file_violations:
                    vtype = v['type']
                    violations_by_type[vtype] = violations_by_type.get(vtype, 0) + 1

            total_files += 1

        return {
            "total_files": total_files,
            "violations_by_type": violations_by_type,
            "total_violations": len(self.violations)
        }

    def generate_report(self) -> str:
        """
        生成检查报告

        Returns:
            报告文本
        """
        if not self.violations:
            return "✅ 配置访问规范化检查通过！未发现违规。"

        report_lines = [
            f"❌ 配置访问规范化检查失败！发现 {len(self.violations)} 处违规：\n",
            "=" * 80
        ]

        # 按类型分组
        violations_by_type: Dict[str, List[Dict]] = {}
        for v in self.violations:
            vtype = v['type']
            if vtype not in violations_by_type:
                violations_by_type[vtype] = []
            violations_by_type[vtype].append(v)

        # 输出各类型违规
        for vtype, vlist in violations_by_type.items():
            report_lines.append(f"\n【{vtype}】 ({len(vlist)} 处)")
            report_lines.append("-" * 80)

            for v in vlist[:20]:  # 每种类型最多显示20个
                report_lines.append(f"  文件: {v['file']}")
                report_lines.append(f"  行号: {v['line']}")
                report_lines.append(f"  原因: {v['message']}")
                if 'code' in v:
                    report_lines.append(f"  代码: {v['code']}")
                report_lines.append("")

            if len(vlist) > 20:
                report_lines.append(f"  ... 还有 {len(vlist) - 20} 处未显示\n")

        # 修复建议
        report_lines.extend([
            "=" * 80,
            "\n📝 修复建议：",
            "1. 所有配置读取应通过 config_manager.get('path.to.key') 完成",
            "2. 禁止直接使用 json.load() 读取配置文件",
            "3. 在文件顶部添加: from scripts.config_manager import get_config",
            "4. 使用方式示例: stop_loss_threshold = get_config('stop_loss.threshold', default=0.02)\n"
        ])

        return "\n".join(report_lines)

    def save_report(self, output_path: str = "references/config_access_check_report.json"):
        """
        保存检查报告

        Args:
            output_path: 输出路径
        """
        report = {
            "timestamp": __import__('time').time(),
            "scan_result": self.scan_directory(),
            "violations": self.violations
        }

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)


def main():
    """主函数"""
    import sys

    # 解析参数
    scan_dir = sys.argv[1] if len(sys.argv) > 1 else "scripts"

    # 执行检查
    logger.debug(f"🔍 开始检查配置访问规范化...")
    logger.debug(f"📁 扫描目录: {scan_dir}\n")
    checker = ConfigAccessChecker(scan_dir)
    checker.scan_directory()
    
    # 生成并输出报告
    report_text = checker.generate_report()
    logger.debug(report_text)
    # 保存JSON报告
    checker.save_report()
    logger.debug(f"\n📄 详细报告已保存: references/config_access_check_report.json")
    
    # 返回退出码
    if checker.violations:
        sys.exit(1)
    else:
        sys.exit(0)



if __name__ == "__main__":
    main()
