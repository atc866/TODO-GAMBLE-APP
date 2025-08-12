from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime, timedelta
import platform, subprocess, os  # <-- add this
from .app_state import AppState
from . import storage


REFRESH_MS = 60 * 1000  # check once per minute for window & forfeits


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Todo Gamble")
        self.geometry("840x560")
        self.minsize(760, 480)
        self.state = AppState()

        self._build_menu()
        self._build_header()
        self._build_tabs()
        self._refresh_all()

        # Periodic checks: window status + forfeits + Monday purge
        self.after(2000, self._tick)

    # ---------- UI ----------
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Open Data Folder", command=self._open_data_folder) 
        filemenu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=filemenu)

        settingsmenu = tk.Menu(menubar, tearoff=0)
        settingsmenu.add_command(label="Set Creation Window", command=self._on_set_window)
        menubar.add_cascade(label="Settings", menu=settingsmenu)
        self.config(menu=menubar)

    def _build_header(self) -> None:
        header = ttk.Frame(self, padding=(12, 10))
        header.pack(fill=tk.X)

        ttk.Label(header, text="Balance:", font=("Segoe UI", 12)).pack(side=tk.LEFT)
        self.balance_var = tk.StringVar(value="$0.00")
        ttk.Label(header, textvariable=self.balance_var, font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT, padx=(6, 12))

        self.window_var = tk.StringVar()
        ttk.Label(header, textvariable=self.window_var).pack(side=tk.LEFT)

    def _build_tabs(self) -> None:
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill=tk.BOTH, expand=True)

        # Today tab
        self.today = ttk.Frame(self.nb)
        self.nb.add(self.today, text="Today")
        self._build_today(self.today)

        # History tab
        self.history = ttk.Frame(self.nb)
        self.nb.add(self.history, text="History")
        self._build_history(self.history)

    def _build_today(self, parent: ttk.Frame) -> None:
        form = ttk.Labelframe(parent, text="Create Task", padding=(12, 10))
        form.pack(fill=tk.X, padx=12, pady=8)

        self.desc_var = tk.StringVar()
        self.buyin_var = tk.StringVar()
        self.payout_var = tk.StringVar()

        ttk.Label(form, text="Description").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        ttk.Entry(form, textvariable=self.desc_var, width=44).grid(row=0, column=1, sticky=tk.W, pady=4)
        ttk.Label(form, text="Buy-in").grid(row=0, column=2, sticky=tk.W, padx=(16, 8))
        ttk.Entry(form, textvariable=self.buyin_var, width=10).grid(row=0, column=3, sticky=tk.W)
        ttk.Label(form, text="Payout").grid(row=0, column=4, sticky=tk.W, padx=(16, 8))
        ttk.Entry(form, textvariable=self.payout_var, width=10).grid(row=0, column=5, sticky=tk.W)
        self.add_btn = ttk.Button(form, text="Add Task", command=self._on_add_task)
        self.add_btn.grid(row=0, column=6, padx=(16, 0))
        form.columnconfigure(1, weight=1)

        table_frame = ttk.Frame(parent, padding=(12, 0))
        table_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("description", "buy_in", "payout")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=12)
        self.tree.heading("description", text="Description")
        self.tree.heading("buy_in", text="Buy-in")
        self.tree.heading("payout", text="Payout")
        self.tree.column("description", minwidth=220, width=520, stretch=True)
        self.tree.column("buy_in", anchor=tk.E, width=90, stretch=False)
        self.tree.column("payout", anchor=tk.E, width=90, stretch=False)
        self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(fill=tk.Y, side=tk.RIGHT)

        actions = ttk.Frame(parent, padding=(12, 8))
        actions.pack(fill=tk.X)
        ttk.Button(actions, text="Mark Selected as Complete", command=self._on_complete).pack(side=tk.LEFT)

    def _build_history(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, padding=(12, 10))
        top.pack(fill=tk.X)
        ttk.Button(top, text="Open Data Folder", command=self._open_data_folder).pack(side=tk.LEFT)
        ttk.Button(top, text="Purge Now (Monday clean)", command=self._on_purge_history).pack(side=tk.RIGHT)

        table_frame = ttk.Frame(parent, padding=(12, 0))
        table_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("ts", "event", "description", "buy_in", "payout")
        self.h_tree = ttk.Treeview(table_frame, columns=cols, show="headings")
        for c, label in zip(cols, ("Time", "Event", "Description", "Buy-in", "Payout")):
            self.h_tree.heading(c, text=label)
        self.h_tree.column("ts", width=180, stretch=False)
        self.h_tree.column("event", width=100, stretch=False)
        self.h_tree.column("description", width=420, stretch=True)
        self.h_tree.column("buy_in", width=80, anchor=tk.E)
        self.h_tree.column("payout", width=80, anchor=tk.E)
        self.h_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.h_tree.yview)
        self.h_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(fill=tk.Y, side=tk.RIGHT)

    # ---------- Events ----------
    def _on_set_window(self) -> None:
        cur = self.state.settings.get("creation_window", {"start": "11:00", "end": "12:00"})
        start = simpledialog.askstring("Creation window", "Start time (HH:MM)", initialvalue=cur["start"], parent=self)
        if start is None:
            return
        end = simpledialog.askstring("Creation window", "End time (HH:MM)", initialvalue=cur["end"], parent=self)
        if end is None:
            return
        try:
            self.state.set_window_times(start, end)
            self._refresh_window_label()
            self._refresh_add_enabled()
        except Exception as e:
            messagebox.showerror("Invalid time", str(e))

    def _on_add_task(self) -> None:
        desc = self.desc_var.get()
        buyin_s = self.buyin_var.get()
        payout_s = self.payout_var.get()

        try:
            buyin = float(buyin_s)
            payout = float(payout_s)
        except ValueError:
            messagebox.showerror("Invalid input", "Buy-in and Payout must be numbers.")
            return

        try:
            t = self.state.add_task(desc, buyin, payout)
        except PermissionError as e:
            messagebox.showwarning("Outside creation window", str(e))
            return
        except ValueError as e:
            messagebox.showerror("Missing description", str(e))
            return

        self.desc_var.set("")
        self.buyin_var.set("")
        self.payout_var.set("")
        self._insert_task_row(t)

    def _on_complete(self) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Nothing selected", "Select a task to mark complete.")
            return
        item_id = sel[0]
        try:
            self.state.complete_task(item_id)
        except KeyError:
            messagebox.showerror("Error", "Could not find the selected task.")
            return
        self.tree.delete(item_id)
        self._refresh_balance()
        self._refresh_history_table()

    def _on_purge_history(self) -> None:
        if storage.HISTORY_PATH.exists():
            storage.HISTORY_PATH.unlink(missing_ok=True)
        self._refresh_history_table()

    # ---------- Periodic ----------
    def _tick(self) -> None:
        # Forfeit overdue tasks, refresh balance/table/history
        forfeited = self.state.forfeit_overdue()
        if forfeited:
            self._refresh_table()
            self._refresh_balance()
            self._refresh_history_table()
        # Monday purge (no-op if not Monday)
        if storage.purge_history_if_monday():
            self._refresh_history_table()
        self._refresh_add_enabled()
        self._refresh_window_label()
        self.after(REFRESH_MS, self._tick)

    # ---------- Helpers ----------
    def _refresh_all(self) -> None:
        self._refresh_table()
        self._refresh_history_table()
        self._refresh_balance()
        self._refresh_window_label()
        self._refresh_add_enabled()

    def _refresh_table(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)
        for t in self.state.tasks:
            self._insert_task_row(t)

    def _insert_task_row(self, t) -> None:
        self.tree.insert("", tk.END, iid=t.id, values=(t.description, f"{t.buy_in:.2f}", f"{t.payout:.2f}"))

    def _refresh_history_table(self) -> None:
        for row in self.h_tree.get_children():
            self.h_tree.delete(row)
        for obj in storage.read_history():
            self.h_tree.insert("", tk.END, values=(obj.get("ts",""), obj.get("event",""), obj.get("description",""), f"{obj.get('buy_in', 0):.2f}", f"{obj.get('payout', 0):.2f}"))

    def _refresh_balance(self) -> None:
        self.balance_var.set(f"${self.state.balance:,.2f}")

    def _refresh_add_enabled(self) -> None:
        enabled = self.state.in_creation_window()
        self.add_btn.state(["!disabled"] if enabled else ["disabled"])

    def _refresh_window_label(self) -> None:
        start, end = self.state.window_today()
        now = datetime.now()
        status = "OPEN" if start <= now <= end else "Closed"
        self.window_var.set(f"Creation window: {start.strftime('%H:%M')}–{end.strftime('%H:%M')}  ({status})")
    def _open_data_folder(self) -> None:
        try:
            storage.ensure_dirs()
            path = storage.APP_DIR
            system = platform.system()
            if system == "Windows":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif system == "Darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as e:
            messagebox.showerror("Open Data Folder", f"Could not open data folder:\n{e}")


if __name__ == "__main__":
    App().mainloop()


# =============================
# File: app/tools/make_icon.py
# =============================
from PIL import Image, ImageDraw
from pathlib import Path

# Quick-and-dirty ICO generator so you have an icon on Windows builds
# Usage: python app/tools/make_icon.py

def main():
    dst = Path(__file__).resolve().parents[1] / 'assets' / 'icon.ico'
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Draw a simple coin-like circle with TG letters
    img = Image.new('RGBA', (256, 256), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((16, 16, 240, 240), outline=(0, 0, 0, 255), width=8, fill=(255, 215, 0, 255))
    d.text((86, 100), 'TG', fill=(0, 0, 0, 255))

    # Save multiple sizes into ICO
    sizes = [(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)]
    imgs = [img.resize(s) for s in sizes]
    imgs[0].save(dst, format='ICO', sizes=sizes)
    print(f"Wrote {dst}")

if __name__ == '__main__':
    try:
        from PIL import Image  # type: ignore
    except Exception:
        print('This script requires Pillow: pip install Pillow')
    else:
        main()
