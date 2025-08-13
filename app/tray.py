from __future__ import annotations
import threading
import io
from pathlib import Path
from typing import Callable, Optional

import pystray
from PIL import Image

# Try to load ICO for Windows or PNG fallback for other OSes
def _load_icon(app_root: Path) -> Image.Image:
    # Preferred: app/assets/icon.ico
    ico = app_root / "assets" / "icon.ico"
    if ico.exists():
        try:
            return Image.open(ico)
        except Exception:
            pass
    # Fallback: simple generated circle with TG
    img = Image.new("RGBA", (256, 256), (255, 255, 255, 0))
    from PIL import ImageDraw, ImageFont
    d = ImageDraw.Draw(img)
    d.ellipse((16, 16, 240, 240), outline=(0, 0, 0, 255), width=8, fill=(255, 215, 0, 255))
    # Text: best-effort default font
    d.text((100, 110), "TG", fill=(0, 0, 0, 255))
    return img

class TrayManager:
    def __init__(self, app_root: Path, on_show: Callable[[], None], on_quit: Callable[[], None]):
        self.on_show = on_show
        self.on_quit = on_quit
        self._icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None
        image = _load_icon(app_root)
        self._icon = pystray.Icon(
            "todo_gamble_tray",
            image,
            "Todo Gamble",
            menu=pystray.Menu(
                pystray.MenuItem("Show", lambda _: self.on_show()),
                pystray.MenuItem("Quit", lambda _: self._quit())
            ),
        )

    def start(self) -> None:
        if not self._icon:
            return
        def run():
            try:
                self._icon.run()
            except Exception:
                pass
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        try:
            if self._icon:
                self._icon.stop()
        except Exception:
            pass

    def _quit(self) -> None:
        # ensure tray stops then delegate to app quit
        self.stop()
        self.on_quit()
