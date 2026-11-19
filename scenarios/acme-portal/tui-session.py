#!/usr/bin/env python3
"""Drive the Argus TUI through a real pty and record what the screen shows.

Usage: tui-session.py <steps.json> <outdir>

Steps (list of [op, ...]):
  ["wait_text", "substring", seconds]   wait until the screen contains it
  ["wait_gone", "substring", seconds]   wait until it is gone
  ["send", "literal text"]              type text (no Enter)
  ["key", "Enter"]                      Enter, Escape, Tab, Space, Up/Down/Left/Right,
                                        CtrlC, CtrlD, Backspace
  ["sleep", seconds]
  ["snap", "label"]                     write the current screen to outdir/label.txt
  ["exit_wait", seconds]                wait for the child to exit

The raw byte stream, every snapshot, the action log and the child's exit status
all land in outdir. Run it with the repository root as the working directory
(DRIVE_CWD overrides that) so ./start-argus.sh resolves.
"""

import fcntl
import json
import os
import pty
import select
import signal
import struct
import sys
import termios
import time

import pyte

KEYS = {
    "Enter": b"\r",
    "Escape": b"\x1b",
    "Tab": b"\t",
    "Space": b" ",
    "Up": b"\x1b[A",
    "Down": b"\x1b[B",
    "Right": b"\x1b[C",
    "Left": b"\x1b[D",
    "CtrlC": b"\x03",
    "CtrlD": b"\x04",
    "Backspace": b"\x7f",
}

COLS, ROWS = 150, 50


def main() -> int:
    steps_path, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    steps = json.load(open(steps_path))

    workdir = os.environ.get("DRIVE_CWD", os.getcwd())
    env = dict(os.environ)
    env.update(
        TERM="xterm-256color",
        COLORTERM="truecolor",
        LANG="C.UTF-8",
        LC_ALL="C.UTF-8",
        ARGUS_ALLOW_INTERNAL_TARGETS="1",
        REDIS_URL="redis://127.0.0.1:6379/0",
    )

    # DRIVE_ENTRY lets the caller drive ./start-argus.sh from another directory
    # (the engagement directory, where argus.config.yaml lives).
    entry = os.environ.get("DRIVE_ENTRY", "./start-argus.sh")
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(workdir)
        os.execvpe(entry, [entry, "tui"], env)
        os._exit(127)

    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
    os.set_blocking(fd, False)

    screen = pyte.Screen(COLS, ROWS)
    stream = pyte.ByteStream(screen)
    raw = open(os.path.join(outdir, "raw.log"), "wb", buffering=0)
    actions = open(os.path.join(outdir, "actions.log"), "a", buffering=1)
    started = time.time()
    exited = None

    def pump(timeout: float = 0.2) -> bool:
        nonlocal exited
        try:
            ready, _, _ = select.select([fd], [], [], timeout)
        except (OSError, ValueError):
            return False
        if not ready:
            return exited is None
        try:
            data = os.read(fd, 65536)
        except OSError:
            return False
        if not data:
            return False
        raw.write(data)
        stream.feed(data)
        return True

    def text() -> str:
        return "\n".join(screen.display)

    def snap(label: str) -> None:
        with open(os.path.join(outdir, f"{label}.txt"), "w") as fh:
            fh.write(f"# label={label} t={time.time() - started:.1f}s\n")
            fh.write(text() + "\n")

    def log(line: str) -> None:
        actions.write(f"t={time.time() - started:7.1f} {line}\n")

    def wait_for(needle: str, seconds: float, gone: bool = False) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            pump(0.25)
            if (needle in text()) != gone:
                return True
            if exited is not None:
                return False
        return False

    def child_status():
        nonlocal exited
        try:
            wp, status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return 0
        if wp == 0:
            return None
        if os.WIFEXITED(status):
            exited = os.WEXITSTATUS(status)
        elif os.WIFSIGNALED(status):
            exited = 128 + os.WTERMSIG(status)
        else:
            exited = 1
        return exited

    try:
        for step in steps:
            op = step[0]
            if op == "wait_text":
                ok = wait_for(step[1], float(step[2]) if len(step) > 2 else 30)
                log(f"wait_text {step[1]!r} -> {ok}")
            elif op == "wait_gone":
                ok = wait_for(step[1], float(step[2]) if len(step) > 2 else 30, gone=True)
                log(f"wait_gone {step[1]!r} -> {ok}")
            elif op == "send":
                os.write(fd, step[1].encode())
                log(f"send {step[1]!r}")
            elif op == "key":
                os.write(fd, KEYS[step[1]])
                log(f"key {step[1]}")
            elif op == "sleep":
                end = time.time() + float(step[1])
                while time.time() < end:
                    pump(0.25)
                log(f"sleep {step[1]}")
            elif op == "snap":
                pump(0.6)
                snap(step[1])
                log(f"snap {step[1]}")
            elif op == "exit_wait":
                deadline = time.time() + float(step[1])
                while time.time() < deadline:
                    pump(0.25)
                    if child_status() is not None:
                        break
                log("exit_wait done")
            else:
                log(f"unknown step {op}")
    finally:
        try:
            pump(0.5)
        except Exception:
            pass
        snap("final")
        status = child_status()
        if status is None:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            time.sleep(0.5)
            status = child_status()
        json.dump(
            {"exit": status, "seconds": round(time.time() - started, 1)},
            open(os.path.join(outdir, "exit.json"), "w"),
        )
        log(f"exit status={status}")
        raw.close()
        actions.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
