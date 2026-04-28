#!/usr/bin/env python3

# 自动添加的日志导入(由log_migration.py生成)
try:
    from scripts.logger_factory import get_logger
    logger = get_logger("web_dashboard")
except ImportError:
    import logging
    logger = logging.getLogger("web_dashboard")
"""
Web可视化仪表板（FastAPI） - v1.0.3扩展
定位：系统的运维层，提升监控与干预能力
核心策略：FastAPI后端、实时监控、远程控制、数据可视化
"""

import argparse
import json
import sys
import time
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
import sqlite3
import os

# FastAPI导入（如果可用）
try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

# Pydantic导入（如果可用）
try:
    from pydantic import BaseModel
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False


@dataclass
class TradingSignal:
    """交易信号"""
    signal_id: str
    timestamp: int
    signal_type: str  # 'OPEN', 'CLOSE', 'STOP_LOSS', 'TAKE_PROFIT'
    symbol: str
    side: str  # 'LONG', 'SHORT'
    price: float
    size: float
    confidence: float
    strategy: str


@dataclass
class SystemStatus:
    """系统状态"""
    is_running: bool
    total_trades: int
    total_pnl: float
    win_rate: float
    max_drawdown: float
    current_positions: int
    last_update: int


class DashboardDataStore:
    """仪表板数据存储"""

    def __init__(self, db_path: str = "state/dashboard_data.db"):
        """
        初始化数据存储

        Args:
            db_path: 数据库路径
        """
        self.db_path = db_path

        # 创建数据库目录
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # 初始化数据库
        self._init_db()

    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 创建交易信号表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trading_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT UNIQUE,
                timestamp INTEGER NOT NULL,
                signal_type TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                size REAL NOT NULL,
                confidence REAL NOT NULL,
                strategy TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)

        # 创建系统状态表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                is_running INTEGER NOT NULL,
                total_trades INTEGER NOT NULL,
                total_pnl REAL NOT NULL,
                win_rate REAL NOT NULL,
                max_drawdown REAL NOT NULL,
                current_positions INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)

        # 创建策略权重表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS strategy_weights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_name TEXT NOT NULL,
                weight REAL NOT NULL,
                performance REAL NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(strategy_name)
            )
        """)

        # 创建远程命令表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS remote_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command_type TEXT NOT NULL,
                command_data TEXT,
                status TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                executed_at INTEGER
            )
        """)

        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_signal_timestamp ON trading_signals(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_command_status ON remote_commands(status)")

        conn.commit()
        conn.close()

    def add_signal(self, signal: TradingSignal):
        """添加交易信号"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO trading_signals
            (signal_id, timestamp, signal_type, symbol, side, price, size, confidence, strategy, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal.signal_id, signal.timestamp, signal.signal_type, signal.symbol,
            signal.side, signal.price, signal.size, signal.confidence, signal.strategy,
            int(time.time() * 1000)
        ))
        conn.commit()
        conn.close()

    def update_system_status(self, status: SystemStatus):
        """更新系统状态"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO system_status
            (is_running, total_trades, total_pnl, win_rate, max_drawdown, current_positions, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            1 if status.is_running else 0, status.total_trades, status.total_pnl,
            status.win_rate, status.max_drawdown, status.current_positions,
            int(time.time() * 1000)
        ))
        conn.commit()
        conn.close()

    def update_strategy_weights(self, weights: Dict[str, float], performances: Dict[str, float]):
        """更新策略权重"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        for strategy, weight in weights.items():
            performance = performances.get(strategy, 0.0)
            cursor.execute("""
                INSERT OR REPLACE INTO strategy_weights
                (strategy_name, weight, performance, updated_at)
                VALUES (?, ?, ?, ?)
            """, (strategy, weight, performance, int(time.time() * 1000)))
        conn.commit()
        conn.close()

    def add_remote_command(self, command_type: str, command_data: Dict) -> int:
        """添加远程命令"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO remote_commands
            (command_type, command_data, status, created_at)
            VALUES (?, ?, ?, ?)
        """, (command_type, json.dumps(command_data), "PENDING", int(time.time() * 1000)))
        command_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return command_id

    def get_recent_signals(self, limit: int = 20) -> List[Dict]:
        """获取最近信号"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT signal_id, timestamp, signal_type, symbol, side, price, size, confidence, strategy
            FROM trading_signals
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))

        signals = []
        for row in cursor.fetchall():
            signals.append({
                "signal_id": row[0],
                "timestamp": row[1],
                "signal_type": row[2],
                "symbol": row[3],
                "side": row[4],
                "price": row[5],
                "size": row[6],
                "confidence": row[7],
                "strategy": row[8]
            })

        conn.close()
        return signals

    def get_system_status(self) -> Optional[SystemStatus]:
        """获取系统状态"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT is_running, total_trades, total_pnl, win_rate, max_drawdown, current_positions, updated_at
            FROM system_status
            ORDER BY updated_at DESC
            LIMIT 1
        """)

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return SystemStatus(
            is_running=bool(row[0]),
            total_trades=row[1],
            total_pnl=row[2],
            win_rate=row[3],
            max_drawdown=row[4],
            current_positions=row[5],
            last_update=row[6]
        )

    def get_strategy_weights(self) -> List[Dict]:
        """获取策略权重"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT strategy_name, weight, performance, updated_at
            FROM strategy_weights
            ORDER BY weight DESC
        """)

        weights = []
        for row in cursor.fetchall():
            weights.append({
                "strategy_name": row[0],
                "weight": row[1],
                "performance": row[2],
                "updated_at": row[3]
            })

        conn.close()
        return weights

    def get_pending_commands(self) -> List[Dict]:
        """获取待处理命令"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, command_type, command_data, created_at
            FROM remote_commands
            WHERE status = 'PENDING'
            ORDER BY created_at ASC
        """)

        commands = []
        for row in cursor.fetchall():
            commands.append({
                "command_id": row[0],
                "command_type": row[1],
                "command_data": json.loads(row[2]),
                "created_at": row[3]
            })

        conn.close()
        return commands


class TradingDashboard:
    """交易仪表板"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8000):
        """
        初始化仪表板

        Args:
            host: 主机地址
            port: 端口
        """
        self.host = host
        self.port = port

        # 数据存储
        self.data_store = DashboardDataStore()

        # 创建FastAPI应用（如果可用）
        if FASTAPI_AVAILABLE:
            self.app = FastAPI(title="杀手锏交易系统仪表板")

            # 配置CORS
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

            # 注册路由
            self._register_routes()

    def _register_routes(self):
        """注册路由"""

        @self.app.get("/", response_class=HTMLResponse)
        async def root():
            """主页"""
            return self._generate_html_dashboard()

        @self.app.get("/api/status")
        async def get_status():
            """获取系统状态"""
            status = self.data_store.get_system_status()
            if not status:
                return {"status": "no_data"}
            return {
                "is_running": status.is_running,
                "total_trades": status.total_trades,
                "total_pnl": status.total_pnl,
                "win_rate": status.win_rate,
                "max_drawdown": status.max_drawdown,
                "current_positions": status.current_positions,
                "last_update": status.last_update
            }

        @self.app.get("/api/signals")
        async def get_signals(limit: int = 20):
            """获取最近信号"""
            signals = self.data_store.get_recent_signals(limit)
            return {"signals": signals}

        @self.app.get("/api/strategy_weights")
        async def get_strategy_weights():
            """获取策略权重"""
            weights = self.data_store.get_strategy_weights()
            return {"weights": weights}

        if PYDANTIC_AVAILABLE:
            class RemoteCommand(BaseModel):
                command_type: str
                command_data: Dict

            @self.app.post("/api/command")
            async def send_command(command: RemoteCommand):
                """发送远程命令"""
                command_id = self.data_store.add_remote_command(command.command_type, command.command_data)
                return {"command_id": command_id, "status": "queued"}

        @self.app.get("/api/commands/pending")
        async def get_pending_commands():
            """获取待处理命令"""
            commands = self.data_store.get_pending_commands()
            return {"commands": commands}

    def _generate_html_dashboard(self) -> str:
        """生成HTML仪表板"""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>杀手锏交易系统仪表板</title>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body { font-family: Arial, sans-serif; background: #1a1a2e; color: #fff; }
                .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
                .header { text-align: center; padding: 20px; background: #16213e; border-radius: 10px; margin-bottom: 20px; }
                .header h1 { color: #0f3460; }
                .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
                .card { background: #16213e; padding: 20px; border-radius: 10px; }
                .card h2 { color: #e94560; margin-bottom: 15px; }
                .metric { display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #0f3460; }
                .metric:last-child { border-bottom: none; }
                .signal-list { max-height: 400px; overflow-y: auto; }
                .signal-item { padding: 10px; margin: 5px 0; background: #0f3460; border-radius: 5px; }
                .signal-item.open { border-left: 3px solid #4caf50; }
                .signal-item.close { border-left: 3px solid #f44336; }
                .btn { background: #e94560; color: #fff; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; }
                .btn:hover { background: #c73659; }
                .btn-danger { background: #f44336; }
                .btn-danger:hover { background: #d32f2f; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🚀 杀手锏交易系统仪表板</h1>
                    <p>v1.0.3 基础设施优化版</p>
                </div>

                <div class="grid">
                    <div class="card">
                        <h2>系统状态</h2>
                        <div id="system-status">
                            <div class="metric"><span>状态</span><span id="status-running">加载中...</span></div>
                            <div class="metric"><span>总交易数</span><span id="status-trades">-</span></div>
                            <div class="metric"><span>总盈亏</span><span id="status-pnl">-</span></div>
                            <div class="metric"><span>胜率</span><span id="status-winrate">-</span></div>
                            <div class="metric"><span>最大回撤</span><span id="status-drawdown">-</span></div>
                            <div class="metric"><span>当前持仓</span><span id="status-positions">-</span></div>
                        </div>
                    </div>

                    <div class="card">
                        <h2>策略权重</h2>
                        <div id="strategy-weights">
                            <p>加载中...</p>
                        </div>
                    </div>

                    <div class="card">
                        <h2>远程控制</h2>
                        <button class="btn" onclick="startTrading()">▶️ 启动交易</button>
                        <button class="btn btn-danger" onclick="stopTrading()">⏹️ 紧急停止</button>
                        <div style="margin-top: 10px;">
                            <input type="text" id="manual-command" placeholder="手动命令" style="width: 70%; padding: 8px;">
                            <button class="btn" onclick="sendManualCommand()">发送</button>
                        </div>
                    </div>
                </div>

                <div class="card" style="margin-top: 20px;">
                    <h2>最近信号</h2>
                    <div class="signal-list" id="signal-list">
                        <p>加载中...</p>
                    </div>
                </div>
            </div>

            <script>
                // 加载系统状态
                async function loadStatus() {
                    const response = await fetch('/api/status');
                    const data = await response.json();
                    document.getElementById('status-running').textContent = data.is_running ? '✅ 运行中' : '❌ 已停止';
                    document.getElementById('status-trades').textContent = data.total_trades || 0;
                    document.getElementById('status-pnl').textContent = '$' + (data.total_pnl || 0).toFixed(2);
                    document.getElementById('status-winrate').textContent = (data.win_rate * 100 || 0).toFixed(1) + '%';
                    document.getElementById('status-drawdown').textContent = (data.max_drawdown * 100 || 0).toFixed(2) + '%';
                    document.getElementById('status-positions').textContent = data.current_positions || 0;
                }

                // 加载策略权重
                async function loadStrategyWeights() {
                    const response = await fetch('/api/strategy_weights');
                    const data = await response.json();
                    let html = '';
                    data.weights.forEach(w => {
                        html += `<div class="metric"><span>${w.strategy_name}</span><span>${(w.weight * 100).toFixed(1)}%</span></div>`;
                    });
                    document.getElementById('strategy-weights').innerHTML = html || '<p>无数据</p>';
                }

                // 加载最近信号
                async function loadSignals() {
                    const response = await fetch('/api/signals?limit=20');
                    const data = await response.json();
                    let html = '';
                    data.signals.forEach(s => {
                        html += `<div class="signal-item ${s.signal_type.toLowerCase()}">
                            <strong>${s.symbol}</strong> ${s.side} @ $${s.price.toFixed(2)}
                            <br>策略: ${s.strategy} | 置信度: ${(s.confidence * 100).toFixed(1)}%
                        </div>`;
                    });
                    document.getElementById('signal-list').innerHTML = html || '<p>无信号</p>';
                }

                // 启动交易
                async function startTrading() {
                    await fetch('/api/command', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ command_type: 'START_TRADING', command_data: {} })
                    });
                    alert('交易启动命令已发送');
                }

                // 紧急停止
                async function stopTrading() {
                    if (confirm('确定要紧急停止交易吗？')) {
                        await fetch('/api/command', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ command_type: 'EMERGENCY_STOP', command_data: {} })
                        });
                        alert('紧急停止命令已发送');
                    }
                }

                // 发送手动命令
                async function sendManualCommand() {
                    const command = document.getElementById('manual-command').value;
                    if (!command) return;
                    await fetch('/api/command', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ command_type: 'MANUAL', command_data: { command: command } })
                    });
                    alert('命令已发送');
                    document.getElementById('manual-command').value = '';
                }

                // 定时刷新
                setInterval(() => {
                    loadStatus();
                    loadStrategyWeights();
                    loadSignals();
                }, 5000);

                // 初始加载
                loadStatus();
                loadStrategyWeights();
                loadSignals();
            </script>
        </body>
        </html>
        """
        return html

    def run(self):
        """运行仪表板"""
        if not FASTAPI_AVAILABLE:
            logger.info("❌ FastAPI未安装，请运行: pip install fastapi uvicorn")
            return

        logger.info(f"🚀 启动交易仪表板...")
        logger.info(f"📊 访问地址: http://{self.host}:{self.port}")
        logger.info(f"📖 API文档: http://{self.host}:{self.port}/docs")
        logger.info(f"⏹️  按 Ctrl+C 停止服务")

        uvicorn.run(self.app, host=self.host, port=self.port)

    def add_sample_data(self):
        """添加示例数据"""
        # 示例系统状态
        status = SystemStatus(
            is_running=True,
            total_trades=156,
            total_pnl=12345.67,
            win_rate=0.58,
            max_drawdown=0.12,
            current_positions=3,
            last_update=int(time.time() * 1000)
        )
        self.data_store.update_system_status(status)

        # 示例策略权重
        weights = {
            "ema_trend": 0.35,
            "supertrend": 0.30,
            "rsi_mean_reversion": 0.20,
            "breakout": 0.15
        }
        performances = {
            "ema_trend": 0.65,
            "supertrend": 0.58,
            "rsi_mean_reversion": 0.52,
            "breakout": 0.48
        }
        self.data_store.update_strategy_weights(weights, performances)

        # 示例交易信号
        for i in range(10):
            signal = TradingSignal(
                signal_id=f"signal_{i}",
                timestamp=int(time.time() * 1000) - i * 60000,
                signal_type="OPEN" if i % 2 == 0 else "CLOSE",
                symbol="BTCUSDT",
                side="LONG" if i % 3 == 0 else "SHORT",
                price=50000 + i * 100,
                size=0.1,
                confidence=0.7 + i * 0.02,
                strategy="ema_trend" if i % 2 == 0 else "supertrend"
            )
            self.data_store.add_signal(signal)

        logger.info(f"✅ 示例数据已添加")


def main():
    parser = argparse.ArgumentParser(description="Web可视化仪表板")
    parser.add_argument("--action", choices=["run", "add_sample_data"], default="run", help="操作类型")
    parser.add_argument("--host", default="0.0.0.0", help="主机地址")
    parser.add_argument("--port", type=int, default=8000, help="端口")

    args = parser.parse_args()

    try:
        # 创建仪表板
        dashboard = TradingDashboard(host=args.host, port=args.port)

        if args.action == "add_sample_data":
            dashboard.add_sample_data()
            logger.info(f"✅ 示例数据已添加")

        elif args.action == "run":
            logger.info("=" * 70)
            logger.info("✅ Web可视化仪表板 - v1.0.3扩展")
            logger.info("=" * 70)

            # 检查依赖
            if not FASTAPI_AVAILABLE:
                logger.info("\n❌ 缺少依赖包")
                logger.info("请安装: pip install fastapi uvicorn pydantic")
                sys.exit(1)

            dashboard.run()

    except KeyboardInterrupt:
        logger.error("\n\n⏹️  仪表板已停止")
    except Exception as e:
        logger.error(f"\n❌ 错误: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
