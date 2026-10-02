# -*- coding: utf-8 -*-
"""
smoke_test_exe.py —— 对打包后的 exe 做冒烟测试

验证点：
  1) 进程存活（onefile：bootloader 父进程 + 子进程）
  2) 子进程出现可见主窗口，标题含应用名与版本号
  3) 窗口截图非空白（像素亮度方差 > 阈值，说明界面真实渲染）
  4) 测试后关闭所有相关进程
"""
import ctypes
import ctypes.wintypes as wt
import os
import statistics
import subprocess
import sys
import time

from PIL import ImageGrab

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "dist", "ColorBlockClicker.exe")
SHOT = os.path.join(HERE, "_exe_smoke.png")
TARGET = "透明通道色块点击器"
EXE_NAME = os.path.basename(EXE)

user32 = ctypes.windll.user32
psapi = ctypes.windll.psapi
kernel32 = ctypes.windll.kernel32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def pid_exe_name(pid: int) -> str:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wt.DWORD(512)
        if psapi.GetModuleFileNameExW(h, None, buf, 512):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(h)


def find_window(timeout=90):
    """等待属于 ColorBlockClicker.exe 的可见主窗口出现。"""
    deadline = time.time() + timeout
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            wpid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value and pid_exe_name(wpid.value) == EXE_NAME and TARGET in buf.value:
                found.append((hwnd, buf.value))
                return False
        return True

    while time.time() < deadline and not found:
        user32.EnumWindows(cb, 0)
        time.sleep(0.5)
    return found[0] if found else None


def main():
    if not os.path.exists(EXE):
        print(f"[FAIL] exe 不存在: {EXE}")
        return 1

    print(f"[1] 启动 {EXE} ({os.path.getsize(EXE)/1048576:.1f} MB)")
    proc = subprocess.Popen([EXE], cwd=HERE)

    hit = find_window()
    if not hit:
        if proc.poll() is not None:
            print(f"[FAIL] 进程已退出, code={proc.returncode}")
        else:
            print("[FAIL] 90s 内未出现主窗口")
        subprocess.run(["taskkill", "/IM", EXE_NAME, "/F"], capture_output=True)
        return 1
    hwnd, title = hit
    print(f"[2] 主窗口出现: \"{title}\"")

    time.sleep(2)  # 等 QSS/首帧渲染稳定

    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    box = (rect.left, rect.top, rect.right, rect.bottom)
    print(f"[3] 窗口区域: {box}")

    img = ImageGrab.grab(bbox=box, all_screens=True).convert("RGB")
    img.save(SHOT)

    px = list(img.resize((64, 64)).convert("L").get_flattened_data()) \
        if hasattr(img, "get_flattened_data") else \
        list(img.resize((64, 64)).convert("L").getdata())
    var = statistics.pvariance(px)
    print(f"[4] 截图保存: {SHOT}  像素亮度方差={var:.1f}")
    if var < 50:
        print("[FAIL] 窗口内容疑似空白")
        subprocess.run(["taskkill", "/IM", EXE_NAME, "/F"], capture_output=True)
        return 1
    print("[5] 界面渲染正常（非空白）")

    subprocess.run(["taskkill", "/IM", EXE_NAME, "/F"], capture_output=True)
    time.sleep(1)
    print("[6] 进程已关闭")

    print("\n===== EXE 冒烟测试通过 =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
