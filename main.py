"""Entry point: python main.py [image_folder]"""

import os
import sys
import tkinter as tk


def main() -> None:
    if sys.platform == "win32":
        try:  # crisp rendering on high-DPI displays
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    from mylabel.gui.app import App

    root = tk.Tk()  # colors/ttk styling are applied by App (light/dark theme)
    folder = sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else None
    App(root, folder)
    root.mainloop()


if __name__ == "__main__":
    main()
