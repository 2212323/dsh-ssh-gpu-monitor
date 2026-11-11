#!/usr/bin/env python3
"""用密码连接 SSH 服务器（不需要公钥）。

用法（在本仓库根目录）：
    python ssh/connect.py                  进入交互式 shell
    python ssh/connect.py -c "nvidia-smi"  在服务器上执行一条命令

配置在 ssh/.env：SSH_HOST / SSH_PORT / SSH_USER / SSH_PASSWORD
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import warnings

# 老版本 paramiko 会刷一堆 CryptographyDeprecationWarning，对使用者没意义
warnings.filterwarnings("ignore")

import paramiko

HERE = os.path.dirname(os.path.abspath(__file__))


def die(message: str, code: int = 1) -> "None":
    print("[ssh] " + message, file=sys.stderr, flush=True)
    sys.exit(code)


def load_env(path: str) -> dict:
    """读 .env：KEY=VALUE，支持 # 注释和成对引号。"""
    if not os.path.exists(path):
        die("找不到配置文件：%s" % path, 2)

    cfg = {}
    with open(path, "r", encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            cfg[name] = value
    return cfg


def _write(stream, data: bytes) -> None:
    text = data.decode("utf-8", "replace")
    try:
        stream.write(text)
    except UnicodeEncodeError:
        # 终端编码（比如 GBK）表示不了的字符，用 ? 代替，别让脚本崩掉
        encoding = getattr(stream, "encoding", None) or "utf-8"
        stream.write(text.encode(encoding, "replace").decode(encoding, "replace"))
    stream.flush()


def write_out(data: bytes) -> None:
    _write(sys.stdout, data)


def write_err(data: bytes) -> None:
    _write(sys.stderr, data)


def run_command(client: "paramiko.SSHClient", command: str) -> int:
    """执行一条命令，边收边打印，返回远端退出码。"""
    _stdin, stdout, stderr = client.exec_command(command)
    chan = stdout.channel
    while True:
        drained = False
        while chan.recv_ready():
            write_out(chan.recv(65536))
            drained = True
        while chan.recv_stderr_ready():
            write_err(chan.recv_stderr(65536))
            drained = True
        if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
            break
        if not drained:
            time.sleep(0.02)
    return chan.recv_exit_status()


def read_output(chan: "paramiko.Channel", stop: threading.Event) -> None:
    while not stop.is_set():
        if chan.recv_ready():
            try:
                data = chan.recv(65536)
            except (OSError, paramiko.SSHException):
                break
            if not data:
                break
            write_out(data)
        elif chan.closed or chan.eof_received:
            break
        else:
            time.sleep(0.01)


def pipe_stdin(chan: "paramiko.Channel") -> None:
    """stdin 不是终端时（管道/重定向），直接转发字节。"""
    while True:
        data = sys.stdin.buffer.read(1024)
        if not data:
            return
        if not chan.send_ready():
            return
        chan.send(data)


def windows_keys(chan: "paramiko.Channel") -> None:
    """Windows 终端逐键转发；方向键等特殊键转成 ANSI 序列。"""
    import msvcrt

    special = {
        "H": b"\x1b[A",  # 上
        "P": b"\x1b[B",  # 下
        "M": b"\x1b[C",  # 右
        "K": b"\x1b[D",  # 左
        "S": b"\x1b[3~",  # Delete
        "G": b"\x1b[H",  # Home
        "O": b"\x1b[F",  # End
    }
    while True:
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            seq = special.get(msvcrt.getwch())
            if seq is None:
                continue
        elif ch == "\x08":
            seq = b"\x7f"  # Backspace
        else:
            seq = ch.encode("utf-8", "replace")
        if not chan.send_ready():
            return
        chan.send(seq)


def posix_tty(chan: "paramiko.Channel") -> None:
    """Linux/macOS 终端：raw 模式逐字节转发。"""
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if not ready:
                continue
            data = os.read(fd, 4096)
            if not data:
                return
            if not chan.send_ready():
                return
            chan.send(data)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def run_interactive(client: "paramiko.SSHClient") -> int:
    try:
        size = os.get_terminal_size()
        cols, lines = size.columns, size.lines
    except OSError:
        cols, lines = 120, 30

    try:
        chan = client.invoke_shell(
            term=os.environ.get("TERM", "xterm-256color"), width=cols, height=lines
        )
    except paramiko.SSHException as exc:
        die("服务器不允许打开 shell：%s" % exc)

    stop = threading.Event()
    reader = threading.Thread(target=read_output, args=(chan, stop), daemon=True)
    reader.start()
    try:
        if not sys.stdin.isatty():
            pipe_stdin(chan)
        elif os.name == "nt":
            windows_keys(chan)
        else:
            posix_tty(chan)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            chan.shutdown_write()
        except Exception:
            pass
        # 先让远端把剩余输出发完、通道自然关闭；最多等 5 秒
        reader.join(timeout=5.0)
        stop.set()
        reader.join(timeout=1.0)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="用密码连接 SSH 服务器")
    parser.add_argument("-c", "--command", help="只执行一条命令，不进入 shell")
    parser.add_argument("--env-file", default=os.path.join(HERE, ".env"), help="配置文件路径")
    parser.add_argument("--host", help="SSH host")
    parser.add_argument("--port", help="SSH port")
    parser.add_argument("--user", help="SSH user")
    parser.add_argument("--password", help="SSH password")
    args = parser.parse_args()

    cfg = load_env(args.env_file) if os.path.exists(args.env_file) else {}
    host = (args.host or cfg.get("SSH_HOST", "")).strip()
    user = (args.user or cfg.get("SSH_USER", "")).strip()
    password = args.password or cfg.get("SSH_PASSWORD", "")
    port_text = (args.port or cfg.get("SSH_PORT", "")).strip() or "22"

    if not host or host == "YOUR_SERVER_IP":
        die("ssh/.env 里的 SSH_HOST 还没填（当前：%r）" % host, 2)
    if not user:
        die("ssh/.env 里的 SSH_USER 还没填", 2)
    if not password or password == "YOUR_PASSWORD":
        die("ssh/.env 里的 SSH_PASSWORD 还没填", 2)
    try:
        port = int(port_text)
    except ValueError:
        die("ssh/.env 里的 SSH_PORT 不是合法端口：%r" % port_text, 2)

    client = paramiko.SSHClient()
    # 先能用为主：自动接受服务器指纹（不做严格校验）
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print("[ssh] 连接 %s@%s:%d ..." % (user, host, port), flush=True)
    try:
        client.connect(
            host,
            port=port,
            username=user,
            password=password,
            look_for_keys=False,
            allow_agent=False,
            timeout=20,
            banner_timeout=20,
            auth_timeout=20,
        )
    except paramiko.AuthenticationException:
        die("用户名或密码不对；也可能是服务器禁用了密码登录（PasswordAuthentication no）")
    except paramiko.SSHException as exc:
        die("SSH 握手失败：%s（可以试试 pip install -U paramiko）" % exc)
    except (OSError, EOFError) as exc:
        die("连不上 %s:%d：%s" % (host, port, exc))

    try:
        code = run_command(client, args.command) if args.command else run_interactive(client)
    finally:
        client.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
