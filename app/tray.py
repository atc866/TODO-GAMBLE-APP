# app/tray.py
import threading
import platform
import pystray
from PIL import Image

class TrayManager:
    def __init__(self, app):
        self.app = app
        self.icon = None

    def start(self):
        img = Image.new("RGB", (64, 64), (255, 255, 255))
        self.icon = pystray.Icon("todo_gamble", img, "Todo Gamble", menu=pystray.Menu(
            pystray.MenuItem("Show", lambda: self.app.after(0, self.app.deiconify)),
            pystray.MenuItem("Exit", lambda: self.app.after(0, self.app.destroy))
        ))
        threading.Thread(target=self.icon.run, daemon=True).start()

    def stop(self):
        if self.icon:
            self.icon.stop()
