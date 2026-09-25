#!/usr/bin/env python3
import glob
import json
import os
import struct
import subprocess
import threading
import time

# keydは物理キーボード(event6)をEVIOCGRABで専有するため、
# 別プロセスからは物理デバイスのイベントを読めない。
# そのためkeydが再送出する仮想キーボード側を監視する。
KEYBOARD_NAME = "keyd virtual keyboard"
DEBOUNCE_SEC = 0.35
RETRY_INTERVAL_SEC = 1.0  # swaymsg失敗時にwatchdogが再試行する間隔(spawnの連打を防ぐ)
SWAY_UID = 1000
SWAY_USER = "user"

# struct input_event は64bit Linux (long=8byte) 前提のレイアウト。
# 32bit環境やABIが異なる環境ではサイズが合わずデータが正しく読めない。
assert struct.calcsize("l") == 8, "64bit Linux以外では動作しません"
EVENT_FMT = "qqHHi"  # timeval(long,long) type code value
EVENT_SIZE = struct.calcsize(EVENT_FMT)
EV_KEY = 1


def find_keyboard_device():
    for path in glob.glob("/sys/class/input/event*/device/name"):
        with open(path) as f:
            if f.read().strip() == KEYBOARD_NAME:
                ev = path.split("/")[4]
                return f"/dev/input/{ev}"
    return None


def sway_env():
    runtime_dir = f"/run/user/{SWAY_UID}"
    socks = glob.glob(f"{runtime_dir}/sway-ipc.{SWAY_UID}.*.sock")
    if not socks:
        return None
    # Sway再起動で古いソケットが残っている場合があるので最新のものを使う
    sock = max(socks, key=os.path.getmtime)
    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = runtime_dir
    env["SWAYSOCK"] = sock
    return env


def swaymsg(env, *args):
    return subprocess.run(
        ["runuser", "-u", SWAY_USER, "--", "swaymsg", *args],
        env=env, capture_output=True, text=True, timeout=2,
    )


def get_touchpad_identifier(env):
    result = swaymsg(env, "-t", "get_inputs")
    if result.returncode != 0:
        return None
    try:
        inputs = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    for dev in inputs:
        if dev.get("type") == "touchpad":
            return dev["identifier"]
    return None


def set_touchpad(env, identifier, enabled):
    state = "enabled" if enabled else "disabled"
    result = swaymsg(env, f"input {identifier} events {state}")
    return result.returncode == 0


def main():
    dev_path = None
    while dev_path is None:
        dev_path = find_keyboard_device()
        if dev_path is None:
            time.sleep(2)

    state = {"last_press": 0.0, "disabled": False, "identifier": None}
    lock = threading.Lock()

    def watchdog():
        last_retry = 0.0
        while True:
            time.sleep(0.05)
            with lock:
                if not (state["disabled"] and
                        time.monotonic() - state["last_press"] > DEBOUNCE_SEC):
                    continue
                now = time.monotonic()
                if now - last_retry < RETRY_INTERVAL_SEC:
                    continue
                last_retry = now
                env = sway_env()
                if env is None:
                    continue
                if state["identifier"] is None:
                    state["identifier"] = get_touchpad_identifier(env)
                if state["identifier"] and set_touchpad(env, state["identifier"], True):
                    state["disabled"] = False
                else:
                    # 有効化に失敗した = 識別子が古い可能性があるので破棄して次回再取得する
                    state["identifier"] = None

    threading.Thread(target=watchdog, daemon=True).start()

    while True:
        try:
            with open(dev_path, "rb") as f:
                while True:
                    data = f.read(EVENT_SIZE)
                    if len(data) < EVENT_SIZE:
                        continue
                    _, _, ev_type, _code, value = struct.unpack(EVENT_FMT, data)
                    if ev_type != EV_KEY or value not in (1, 2):
                        continue
                    with lock:
                        state["last_press"] = time.monotonic()
                        if not state["disabled"]:
                            env = sway_env()
                            if env:
                                if state["identifier"] is None:
                                    state["identifier"] = get_touchpad_identifier(env)
                                if state["identifier"]:
                                    if set_touchpad(env, state["identifier"], False):
                                        state["disabled"] = True
                                    else:
                                        # 無効化に失敗した = 識別子が古い可能性が
                                        # あるので破棄し、次のキー入力で再取得する
                                        state["identifier"] = None
        except OSError:
            # keydの再起動やデバイス消失時は再検出してリトライする
            time.sleep(1)
            new_path = find_keyboard_device()
            if new_path:
                dev_path = new_path


if __name__ == "__main__":
    main()
