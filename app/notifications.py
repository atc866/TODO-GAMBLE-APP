import platform, subprocess
from dataclasses import dataclass

@dataclass
class Notifier:
    app_name: str = "Todo Gamble"

    def notify(self, title: str, message: str) -> None:
        try:
            if platform.system() == "Darwin":
                try:
                    print("SEND")
                    from pync import Notifier as MacNotifier
                    MacNotifier.notify(
                        message,
                        title=title,
                        sound="default",
                        group="todo-gamble",
                        activate="com.apple.finder"
                    )
                    return
                except Exception:
                    pass
            elif platform.system() == "Windows":
                from winotify import Notification
                Notification(app_id=self.app_name, title=title, msg=message).show()
                return
            else:
                subprocess.run(["notify-send", title, message], check=False)
        except Exception:
            pass