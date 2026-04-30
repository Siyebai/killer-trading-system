# [ARCHIVED by Round 6 Integration - 2026-04-30]
# Reason: No active callers / Superseded by production module

#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("monitoring_dashboard")
except ImportError:
    import logging
    logger = logging.getLogger("monitoring_dashboard")
"""
实时监控仪表板 - V3核心模块
提供Web UI实时监控系统状态
"""

import json
import time
from typing import Dict, Any, List
from datetime import datetime
from pathlib import Path


class MonitoringDashboard:
    """实时监控仪表板"""

    def __init__(self, output_dir: str = "./dashboard"):
        """
        初始化监控仪表板

        Args:
            output_dir: 输出目录
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.metrics = {
            'portfolio': {},
            'trades': [],
            'strategies': {},
            'risk': {},
            'system': {},
            'last_updated': 0
        }

    def update_portfolio(self, balance: float, equity: float, positions: Dict[str, float]):
        """更新投资组合数据"""
        self.metrics['portfolio'] = {
            'balance': balance,
            'equity': equity,
            'pnl': equity - balance,
            'pnl_pct': ((equity - balance) / balance * 100) if balance > 0 else 0,
            'positions': positions,
            'position_count': len(positions)
        }
        self.metrics['last_updated'] = time.time()

    def add_trade(self, trade: Dict[str, Any]):
        """添加交易记录"""
        self.metrics['trades'].append(trade)
        # 保留最近100条
        if len(self.metrics['trades']) > 100:
            self.metrics['trades'] = self.metrics['trades'][-100:]
        self.metrics['last_updated'] = time.time()

    def update_strategy_stats(self, strategy_id: str, stats: Dict[str, Any]):
        """更新策略统计"""
        self.metrics['strategies'][strategy_id] = stats
        self.metrics['last_updated'] = time.time()

    def update_risk_metrics(self, risk_data: Dict[str, Any]):
        """更新风控指标"""
        self.metrics['risk'] = risk_data
        self.metrics['last_updated'] = time.time()

    def update_system_stats(self, system_data: Dict[str, Any]):
        """更新系统统计"""
        self.metrics['system'] = system_data
        self.metrics['last_updated'] = time.time()

    def generate_dashboard(self) -> str:
        """生成HTML仪表板"""
        html = self._get_html_template()

        # 填充数据
        data_json = json.dumps(self.metrics, ensure_ascii=False, indent=2)

        # 替换占位符
        html = html.replace('{{DATA_JSON}}', data_json)
        html = html.replace('{{LAST_UPDATED}}', datetime.fromtimestamp(
            self.metrics['last_updated']).strftime('%Y-%m-%d %H:%M:%S')
        )

        # 保存到文件
        output_file = self.output_dir / 'dashboard.html'
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html)

        return str(output_file)

    def _get_html_template(self) -> str:
        """获取HTML模板"""
        return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>交易系统实时监控</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial, sans-serif; background: #f0f2f5; }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        .header { background: #1890ff; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        .card h3 { color: #333; margin-bottom: 15px; border-bottom: 2px solid #1890ff; padding-bottom: 10px; }
        .metric { display: flex; justify-content: space-between; margin: 10px 0; }
        .metric-label { color: #666; }
        .metric-value { font-weight: bold; color: #1890ff; }
        .metric-value.positive { color: #52c41a; }
        .metric-value.negative { color: #ff4d4f; }
        .trade-item { padding: 10px; border-bottom: 1px solid #eee; }
        .trade-item:last-child { border-bottom: none; }
        .status-bar { background: #333; color: white; padding: 10px; text-align: center; margin-top: 20px; border-radius: 8px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 交易系统实时监控 V3</h1>
        </div>

        <div class="grid">
            <!-- 投资组合 -->
            <div class="card">
                <h3>💰 投资组合</h3>
                <div id="portfolio-stats"></div>
            </div>

            <!-- 风控指标 -->
            <div class="card">
                <h3>⚠️ 风控指标</h3>
                <div id="risk-stats"></div>
            </div>

            <!-- 系统状态 -->
            <div class="card">
                <h3>🖥️ 系统状态</h3>
                <div id="system-stats"></div>
            </div>
        </div>

        <div class="grid" style="margin-top: 20px;">
            <!-- 策略性能 -->
            <div class="card">
                <h3>📈 策略性能</h3>
                <div id="strategy-stats"></div>
            </div>

            <!-- 最近交易 -->
            <div class="card">
                <h3>📋 最近交易</h3>
                <div id="recent-trades"></div>
            </div>
        </div>

        <div class="status-bar">
            最后更新: {{LAST_UPDATED}} | 自动刷新: 5秒
        </div>
    </div>

    <script>
        const data = {{DATA_JSON}};

        // 渲染投资组合
        function renderPortfolio() {
            const p = data.portfolio;
            const pnlClass = p.pnl >= 0 ? 'positive' : 'negative';
            const html = `
                <div class="metric">
                    <span class="metric-label">账户余额:</span>
                    <span class="metric-value">$${p.balance?.toFixed(2) || '0.00'}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">权益总额:</span>
                    <span class="metric-value">$${p.equity?.toFixed(2) || '0.00'}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">浮动盈亏:</span>
                    <span class="metric-value ${pnlClass}">$${p.pnl?.toFixed(2) || '0.00'}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">盈亏比例:</span>
                    <span class="metric-value ${pnlClass}">${p.pnl_pct?.toFixed(2) || '0.00'}%</span>
                </div>
                <div class="metric">
                    <span class="metric-label">持仓数量:</span>
                    <span class="metric-value">${p.position_count || 0}</span>
                </div>
            `;
            document.getElementById('portfolio-stats').innerHTML = html;
        }

        // 渲染风控指标
        function renderRisk() {
            const r = data.risk;
            const html = `
                <div class="metric">
                    <span class="metric-label">当前回撤:</span>
                    <span class="metric-value">${(r.current_drawdown * 100)?.toFixed(2) || '0.00'}%</span>
                </div>
                <div class="metric">
                    <span class="metric-label">最大回撤:</span>
                    <span class="metric-value">${(r.max_drawdown * 100)?.toFixed(2) || '0.00'}%</span>
                </div>
                <div class="metric">
                    <span class="metric-label">夏普比率:</span>
                    <span class="metric-value">${r.sharpe_ratio?.toFixed(2) || '0.00'}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">风险等级:</span>
                    <span class="metric-value">${r.risk_level || 'LOW'}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">熔断状态:</span>
                    <span class="metric-value">${r.circuit_breaker_active ? '触发' : '正常'}</span>
                </div>
            `;
            document.getElementById('risk-stats').innerHTML = html;
        }

        // 渲染系统状态
        function renderSystem() {
            const s = data.system;
            const html = `
                <div class="metric">
                    <span class="metric-label">运行时间:</span>
                    <span class="metric-value">${s.uptime || '0m'}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">总交易数:</span>
                    <span class="metric-value">${s.total_trades || 0}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">事件处理数:</span>
                    <span class="metric-value">${s.events_processed || 0}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">内存使用:</span>
                    <span class="metric-value">${s.memory_mb || 0} MB</span>
                </div>
                <div class="metric">
                    <span class="metric-label">状态:</span>
                    <span class="metric-value ${s.status === 'RUNNING' ? 'positive' : 'negative'}">${s.status || 'UNKNOWN'}</span>
                </div>
            `;
            document.getElementById('system-stats').innerHTML = html;
        }

        // 渲染策略性能
        function renderStrategies() {
            const strategies = data.strategies || {};
            let html = '';
            for (const [id, stats] of Object.entries(strategies)) {
                const winRate = stats.total_trades > 0
                    ? ((stats.win_trades / stats.total_trades) * 100).toFixed(1)
                    : '0.0';
                html += `
                    <div class="trade-item">
                        <strong>${id}</strong>
                        <br>交易: ${stats.total_trades || 0} | 胜率: ${winRate}% | 盈亏: $${stats.total_pnl?.toFixed(2) || '0.00'}
                    </div>
                `;
            }
            document.getElementById('strategy-stats').innerHTML = html || '暂无数据';
        }

        // 渲染最近交易
        function renderTrades() {
            const trades = data.trades || [];
            let html = '';
            for (const trade of trades.slice(-10).reverse()) {
                const sideClass = trade.side === 'BUY' ? 'positive' : 'negative';
                html += `
                    <div class="trade-item">
                        <span class="${sideClass}">${trade.side}</span> ${trade.symbol}
                        <br>价格: $${trade.price?.toFixed(2)} | 数量: ${trade.quantity}
                        <br>策略: ${trade.strategy}
                    </div>
                `;
            }
            document.getElementById('recent-trades').innerHTML = html || '暂无数据';
        }

        // 初始化渲染
        renderPortfolio();
        renderRisk();
        renderSystem();
        renderStrategies();
        renderTrades();

        // 自动刷新
        setTimeout(() => location.reload(), 5000);
    </script>
</body>
</html>"""

    def print_summary(self):
        """打印监控摘要"""
        logger.info("\n" + "="*60)
        logger.info("📊 监控仪表板摘要")
        logger.info("="*60)

        # 投资组合
        if self.metrics.get('portfolio'):
            p = self.metrics['portfolio']
            logger.info(f"\n💰 投资组合:")
            logger.info(f"  余额: ${p.get('balance', 0):.2f}")
            logger.info(f"  权益: ${p.get('equity', 0):.2f}")
            logger.info(f"  盈亏: ${p.get('pnl', 0):.2f} ({p.get('pnl_pct', 0):.2f}%)")

        # 风控
        if self.metrics.get('risk'):
            r = self.metrics['risk']
            logger.info(f"\n⚠️  风控指标:")
            logger.info(f"  当前回撤: {r.get('current_drawdown', 0)*100:.2f}%")
            logger.info(f"  最大回撤: {r.get('max_drawdown', 0)*100:.2f}%")
            logger.info(f"  夏普比率: {r.get('sharpe_ratio', 0):.2f}")

        # 系统
        if self.metrics.get('system'):
            s = self.metrics['system']
            logger.info(f"\n🖥️  系统状态:")
            logger.info(f"  运行时间: {s.get('uptime', '0m')}")
            logger.info(f"  交易数: {s.get('total_trades', 0)}")

        logger.info("\n" + "="*60)


# 命令行测试
def main():
    """测试监控仪表板"""
    dashboard = MonitoringDashboard("./dashboard")

    # 模拟数据
    dashboard.update_portfolio(100000, 101500, {'BTCUSDT': 0.5})
    dashboard.update_risk_metrics({
        'current_drawdown': 0.015,
        'max_drawdown': 0.025,
        'sharpe_ratio': 2.5,
        'risk_level': 'LOW',
        'circuit_breaker_active': False
    })
    dashboard.update_system_stats({
        'uptime': '120m',
        'total_trades': 50,
        'events_processed': 1500,
        'memory_mb': 256,
        'status': 'RUNNING'
    })
    dashboard.update_strategy_stats('MA_CROSS', {
        'total_trades': 30,
        'win_trades': 21,
        'total_pnl': 800.0
    })
    dashboard.add_trade({
        'trade_id': '001',
        'symbol': 'BTCUSDT',
        'side': 'BUY',
        'price': 50000.0,
        'quantity': 0.1,
        'strategy': 'MA_CROSS'
    })

    # 生成仪表板
    dashboard_file = dashboard.generate_dashboard()
    logger.info(f"仪表板已生成: {dashboard_file}")

    # 打印摘要
    dashboard.print_summary()

    logger.info("\n监控仪表板测试: PASS")


if __name__ == "__main__":
    main()
