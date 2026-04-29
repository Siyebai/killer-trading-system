#!/usr/bin/env python3
"""
杀手锏 守护进程启动器 v1.0
════════════════════════════════════════════════════════════
解决的根本问题：
  [ROOT-1] 引擎被SIGTERM杀死根因：
    - nohup启动后PGID属于父shell会话，父shell退出时OS向整个进程组发SIGTERM
    - 使用 setsid + double-fork 创建真正脱离终端的守护进程
    - 引擎PID=SID=PGID，完全独立于任何终端会话

  [ROOT-2] 崩溃无法自动恢复：
    - 守护进程内置看门狗循环（watchdog），引擎崩溃后5秒自动重启
    - 最大连续失败次数限制（超过则等待更长时间防止CPU暴冲）
    - 所有异常都被捕获并记录，永不静默崩溃

  [ROOT-3] 多实例问题：
    - 守护进程本身用独立PID锁（daemon.pid）
    - 引擎进程用自己的锁（paper_engine.pid）
    - 双重防护，不可能出现多个引擎实例

  [ROOT-4] 进程数量限制：
    - 守护进程严格限制只启动1个引擎实例
    - 启动前强制检查并清理僵尸进程

使用方法：
  启动: python3 scripts/daemon.py start
  停止: python3 scripts/daemon.py stop
  状态: python3 scripts/daemon.py status
  重启: python3 scripts/daemon.py restart
════════════════════════════════════════════════════════════
"""
import os
import sys
import time
import signal
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 路径配置 ─────────────────────────────────────────
BASE_DIR  = Path(__file__).parent.parent
LOG_DIR   = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

DAEMON_PID_FILE  = LOG_DIR / "daemon.pid"
DAEMON_LOG_FILE  = LOG_DIR / "daemon.log"
ENGINE_PID_FILE  = LOG_DIR / "paper_engine.pid"
ENGINE_SCRIPT    = BASE_DIR / "scripts" / "paper_engine_v106.py"

CST = timezone(timedelta(hours=8))

# 看门狗参数
RESTART_DELAY     = 5     # 正常重启等待秒数
MAX_FAIL_DELAY    = 120   # 连续失败后最长等待秒数
MAX_QUICK_FAILS   = 5     # 连续快速失败次数超此值则长等待
QUICK_FAIL_SEC    = 30    # 运行不足此秒数视为"快速失败"


# ── 日志 ─────────────────────────────────────────────
def _log(msg: str):
    ts   = datetime.now(tz=CST).strftime("%Y-%m-%d %H:%M:%S CST")
    line = f"[{ts}] [DAEMON] {msg}"
    print(line, flush=True)
    try:
        with open(DAEMON_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass


# ── 守护进程化（double-fork） ─────────────────────────
def daemonize():
    """
    Double-fork：使进程完全脱离终端和父进程组
    第一次fork：创建子进程，父进程退出（脱离shell前台）
    setsid：子进程成为新会话领导者，脱离终端
    第二次fork：再次创建孙进程，孙进程不是会话领导者，
                永远无法重新获取终端
    """
    # 第一次 fork
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)  # 父进程退出
    except OSError as e:
        print(f"Fork #1 失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 成为新会话领导者
    os.setsid()

    # 第二次 fork（防止重新获取终端）
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)  # 第一子进程退出
    except OSError as e:
        print(f"Fork #2 失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 孙进程：真正的守护进程
    # 重定向标准IO到/dev/null
    sys.stdout.flush()
    sys.stderr.flush()
    with open(os.devnull, 'r') as f:
        os.dup2(f.fileno(), sys.stdin.fileno())
    with open(DAEMON_LOG_FILE, 'a') as f:
        os.dup2(f.fileno(), sys.stdout.fileno())
        os.dup2(f.fileno(), sys.stderr.fileno())


# ── PID文件管理 ──────────────────────────────────────
def write_daemon_pid():
    DAEMON_PID_FILE.write_text(str(os.getpid()))

def read_pid(pid_file: Path):
    try:
        if pid_file.exists():
            return int(pid_file.read_text().strip())
    except (ValueError, OSError):
        pass
    return None

def is_running(pid: int) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False

def cleanup_stale_pid(pid_file: Path):
    pid = read_pid(pid_file)
    if pid and not is_running(pid):
        pid_file.unlink(missing_ok=True)
        _log(f"清理僵尸PID文件: {pid_file.name} (PID={pid} 已不存在)")


# ── 看门狗主循环 ─────────────────────────────────────
_daemon_stop = False

def _handle_stop(signum, frame):
    global _daemon_stop
    _daemon_stop = True
    _log(f"收到信号 {signum}，守护进程准备退出...")

def watchdog_loop():
    """看门狗：监控引擎进程，崩溃自动重启"""
    global _daemon_stop
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT,  _handle_stop)

    write_daemon_pid()
    _log(f"守护进程启动 PID={os.getpid()} SID={os.getsid(0)} PGID={os.getpgid(0)}")
    _log(f"引擎脚本: {ENGINE_SCRIPT}")

    fail_count   = 0
    engine_proc  = None

    while not _daemon_stop:
        # ── 检查引擎是否在运行 ──
        engine_pid = read_pid(ENGINE_PID_FILE)
        engine_alive = is_running(engine_pid) if engine_pid else False

        if not engine_alive:
            # 清理僵尸PID文件
            ENGINE_PID_FILE.unlink(missing_ok=True)

            # 计算等待时间
            if fail_count >= MAX_QUICK_FAILS:
                delay = min(RESTART_DELAY * (2 ** (fail_count - MAX_QUICK_FAILS)), MAX_FAIL_DELAY)
                _log(f"⚠️  连续失败 {fail_count} 次，等待 {delay:.0f}s 后重启...")
                for _ in range(int(delay)):
                    if _daemon_stop:
                        break
                    time.sleep(1)
            else:
                if fail_count > 0:
                    time.sleep(RESTART_DELAY)

            if _daemon_stop:
                break

            # ── 启动引擎 ──
            _log(f"🚀 启动引擎 (第{fail_count+1}次尝试)...")
            start_time = time.time()
            try:
                engine_proc = subprocess.Popen(
                    [sys.executable, str(ENGINE_SCRIPT)],
                    cwd=str(BASE_DIR),
                    start_new_session=False,  # 与守护进程同会话，方便管理
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                _log(f"引擎已启动 PID={engine_proc.pid}")
            except Exception as e:
                _log(f"❌ 引擎启动失败: {e}")
                fail_count += 1
                time.sleep(RESTART_DELAY)
                continue

            # ── 等待引擎退出 ──
            while not _daemon_stop:
                try:
                    engine_proc.wait(timeout=10)
                    break  # 引擎退出了
                except subprocess.TimeoutExpired:
                    pass   # 还在运行，继续等

            run_duration = time.time() - start_time

            if _daemon_stop:
                # 守护进程要退出，先优雅停止引擎
                if engine_proc and engine_proc.poll() is None:
                    _log("向引擎发送SIGTERM...")
                    engine_proc.terminate()
                    try:
                        engine_proc.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        _log("引擎未响应SIGTERM，强制SIGKILL")
                        engine_proc.kill()
                break

            exit_code = engine_proc.returncode if engine_proc else -1
            _log(f"引擎退出 code={exit_code} 运行时长={run_duration:.0f}s")

            # 判断是否"快速失败"
            if run_duration < QUICK_FAIL_SEC:
                fail_count += 1
                _log(f"快速失败计数: {fail_count}/{MAX_QUICK_FAILS}")
            else:
                fail_count = 0  # 运行超过30s，重置失败计数

        else:
            # 引擎正在运行，每30秒检查一次
            for _ in range(30):
                if _daemon_stop:
                    break
                time.sleep(1)

    # ── 清理退出 ──
    ENGINE_PID_FILE.unlink(missing_ok=True)
    DAEMON_PID_FILE.unlink(missing_ok=True)
    _log("守护进程已退出")


# ── CLI命令 ──────────────────────────────────────────
def cmd_start(foreground=False):
    """启动守护进程"""
    daemon_pid = read_pid(DAEMON_PID_FILE)
    if is_running(daemon_pid):
        print(f"✅ 守护进程已在运行 PID={daemon_pid}")
        return

    cleanup_stale_pid(DAEMON_PID_FILE)
    cleanup_stale_pid(ENGINE_PID_FILE)

    if foreground:
        print("前台模式启动（Ctrl+C 停止）...")
        watchdog_loop()
    else:
        print("启动守护进程（后台模式）...")
        daemonize()
        watchdog_loop()


def cmd_stop():
    """停止守护进程（同时停止引擎）"""
    daemon_pid = read_pid(DAEMON_PID_FILE)
    if not is_running(daemon_pid):
        print("⚠️  守护进程未运行")
        cleanup_stale_pid(DAEMON_PID_FILE)
        # 也尝试停止可能残留的引擎
        engine_pid = read_pid(ENGINE_PID_FILE)
        if is_running(engine_pid):
            print(f"停止残留引擎 PID={engine_pid}")
            os.kill(engine_pid, signal.SIGTERM)
        return

    print(f"停止守护进程 PID={daemon_pid}...")
    os.kill(daemon_pid, signal.SIGTERM)

    # 等待退出
    for i in range(20):
        time.sleep(1)
        if not is_running(daemon_pid):
            print("✅ 守护进程已停止")
            return

    print("守护进程未响应，强制SIGKILL...")
    try:
        os.kill(daemon_pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    cleanup_stale_pid(DAEMON_PID_FILE)
    cleanup_stale_pid(ENGINE_PID_FILE)
    print("✅ 已强制停止")


def cmd_status():
    """查看状态"""
    CST_ = timezone(timedelta(hours=8))
    now  = datetime.now(tz=CST_).strftime("%H:%M:%S CST")

    daemon_pid = read_pid(DAEMON_PID_FILE)
    engine_pid = read_pid(ENGINE_PID_FILE)

    d_alive = is_running(daemon_pid)
    e_alive = is_running(engine_pid)

    print(f"{'='*45}")
    print(f"⚔️  杀手锏 守护进程状态  ({now})")
    print(f"{'='*45}")
    print(f"守护进程: {'✅ 运行中' if d_alive else '❌ 未运行'}"
          + (f" PID={daemon_pid}" if d_alive else ""))
    print(f"交易引擎: {'✅ 运行中' if e_alive else '❌ 未运行'}"
          + (f" PID={engine_pid}" if e_alive else ""))

    # 读取最新日志
    if DAEMON_LOG_FILE.exists():
        lines = DAEMON_LOG_FILE.read_text().strip().splitlines()
        if lines:
            print(f"\n最新守护日志:")
            for l in lines[-3:]:
                print(f"  {l}")

    state_file = BASE_DIR / "logs" / "paper_trade_state.json"
    if state_file.exists():
        import json
        try:
            s = json.loads(state_file.read_text())
            print(f"\n持仓: {len(s.get('positions',{}))}个  "
                  f"已交易: {len(s.get('trades',[]))}笔  "
                  f"资金: ${s.get('capital',0):,.0f}")
        except Exception:
            pass
    print(f"{'='*45}")


def cmd_restart():
    cmd_stop()
    time.sleep(3)
    cmd_start()


# ── 入口 ─────────────────────────────────────────────
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "start":
        foreground = "--fg" in sys.argv
        cmd_start(foreground=foreground)
    elif cmd == "stop":
        cmd_stop()
    elif cmd == "restart":
        cmd_restart()
    elif cmd == "status":
        cmd_status()
    else:
        print(f"用法: python3 {sys.argv[0]} start|stop|restart|status [--fg]")
        sys.exit(1)
