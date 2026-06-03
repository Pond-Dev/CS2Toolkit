"""Logging helpers for the overlay package."""
import ctypes

STD_INPUT_HANDLE = -10
ENABLE_INSERT_MODE = 0x0020
ENABLE_QUICK_EDIT_MODE = 0x0040
ENABLE_EXTENDED_FLAGS = 0x0080


def log(msg, _level=None):
    print(msg, flush=True)


def disable_console_quick_edit(kernel32=None):
    """Disable Windows console QuickEdit so selecting text cannot pause the bot."""
    try:
        kernel32 = kernel32 or ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        if not handle:
            return False
        mode = ctypes.c_uint()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        new_mode = (mode.value | ENABLE_EXTENDED_FLAGS) & ~ENABLE_QUICK_EDIT_MODE
        return bool(kernel32.SetConsoleMode(handle, new_mode))
    except Exception:
        return False


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def d_print(msg):
    from . import config
    if config.DEBUG:
        print(f"[DEBUG] {msg}", flush=True)
