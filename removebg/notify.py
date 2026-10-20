import ctypes
import threading

TITLE = "Remove Background (AI)"
_MB_OK, _MB_ICONWARNING, _MB_TOPMOST, _MB_SETFOREGROUND = 0x0, 0x30, 0x40000, 0x10000


def show_error(message: str, wait: bool = False) -> None:
    def box():
        ctypes.windll.user32.MessageBoxW(None, message, TITLE,
                                         _MB_OK | _MB_ICONWARNING | _MB_TOPMOST | _MB_SETFOREGROUND)

    if wait:
        box()
    else:
        threading.Thread(target=box, daemon=True).start()
