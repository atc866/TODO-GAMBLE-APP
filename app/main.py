from __future__ import annotations
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from datetime import datetime, timedelta

import platform, subprocess, os  # already suggested before
from pathlib import Path
from datetime import datetime, timedelta
from app.app_state import AppState
from app import storage
from app.notifications import Notifier
import csv 
from app.tray import TrayManager
import threading


REFRESH_MS = 60 * 1000 

class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Todo Gamble")
        self.geometry("840x560")
        self.minsize(760, 480)
        self.state = AppState()


        # Notifications & tray
        self.notifier = Notifier()
        app_root = Path(__file__).resolve().parents[0]
        self.tray = TrayManager(
            app_root=app_root,
            on_show=self._show_from_tray,
            on_quit=self._quit_app
        )

        # Remember what we’ve notified today to avoid duplicates
        self._notified_day_key: str | None = None  # e.g., "2025-08-13"
        self._notified_open = False
        self._notified_pre_end = False

        # override close to hide to tray
        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)


        self._history_row_data = {}  # iid -> dict from history.jsonl
        self._history_selected_iid = None
        self._build_menu()
        self._build_header()
        self._build_tabs()
        self._refresh_all()
        self._tick_worker_running = False

        # Periodic checks: window status + forfeits + Monday purge
        self.after(2000, self._tick)
        self._last_tick: datetime = datetime.now()

        #tray
        self.tray.start()

    # ---------- UI ----------
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        filemenu = tk.Menu(menubar, tearoff=0)

        filemenu.add_command(label="Record Purchase…", command=self._on_record_purchase)
        filemenu.add_command(label="Open Data Folder", command=self._open_data_folder) 
        filemenu.add_command(label="Minimize to Tray", command=self._hide_to_tray)
        filemenu.add_command(label="Exit", command=self.destroy)
        filemenu.add_separator()
        filemenu.add_command(label="Purge Data…", command=self._on_purge_data)          # new
        filemenu.add_command(label="Compact Ledger…", command=self._on_compact_ledger)  # new
        filemenu.add_command(label="Send Test Notification", command=self._send_test_notification)
        filemenu.add_separator()

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

        ttk.Button(header, text="Record Purchase…", command=self._on_record_purchase).pack(side=tk.LEFT, padx=(0, 12))
        
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

        #delete button
        ttk.Button(actions, text="Delete Selected Task", command=self._on_delete_task).pack(side=tk.LEFT, padx=(8, 0))

    def _build_history(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, padding=(12, 10))
        top.pack(fill=tk.X)
        ttk.Label(top, text="Filter:").pack(side=tk.LEFT)
        self.history_filter_var = tk.StringVar(value="All")
        self.history_filter = ttk.Combobox(
            top, textvariable=self.history_filter_var,
            values=["All", "Tasks Only", "Purchases Only"], width=16, state="readonly"
        )
        self.history_filter.pack(side=tk.LEFT, padx=(6, 12))
        self.history_filter.bind("<<ComboboxSelected>>", lambda e: self._refresh_history_table())

        # Buttons
        ttk.Button(top, text="Open Data Folder", command=self._open_data_folder).pack(side=tk.LEFT)
        ttk.Button(top, text="Export CSV", command=self._on_export_history_csv).pack(side=tk.RIGHT)
        ttk.Button(top, text="Purge Now (Monday clean)", command=self._on_purge_history).pack(side=tk.RIGHT, padx=(6,0))
        ttk.Button(top, text="Revert Selected…", command=self._on_history_revert).pack(side=tk.LEFT, padx=(8, 0))

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
        # Context menu for revert — parented to the tree to avoid focus weirdness
        self.h_context = tk.Menu(self.h_tree, tearoff=0)
        self.h_context.add_command(label="Revert…", command=self._on_history_revert)

        # Bind common right-click variants across OSes:
        # - Windows/Linux: Button-3 (press & release)
        # - mac trackpad: Button-2 (press & release)
        # - mac control-click: Control-Button-1
        for seq in ("<Button-3>", "<ButtonRelease-3>", "<Button-2>", "<ButtonRelease-2>", "<Control-Button-1>"):
            self.h_tree.bind(seq, self._on_history_context, add="+")

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
    def _on_delete_task(self) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Nothing selected", "Select a task to delete.")
            return
        item_id = sel[0]
        # Confirm
        if not messagebox.askyesno("Delete Task", "Delete this task?\n\nNo payout will be earned."):
            return
        try:
            result = self.state.delete_task(item_id)
        except KeyError as e:
            messagebox.showerror("Error", str(e))
            return
        # Remove row and refresh
        self.tree.delete(item_id)
        if result.get("penalized"):
            self._refresh_balance()
            self._refresh_history_table()
            message = f"Task deleted with penalty: ${abs(result['penalty']):.2f}"
        else:
            self._refresh_history_table()
            message = "Task deleted (no penalty)."
        messagebox.showinfo("Deleted", message)


    def _on_purge_history(self) -> None:
        if storage.HISTORY_PATH.exists():
            storage.HISTORY_PATH.unlink(missing_ok=True)
        self._refresh_history_table()

    def _tick(self) -> None:
      # Skip if already running
      if getattr(self, "_tick_worker_running", False):
          self.after(REFRESH_MS, self._tick)
          return

      self._tick_worker_running = True
      threading.Thread(target=self._tick_worker, daemon=True).start()
      self.after(REFRESH_MS, self._tick)


    def _tick_worker(self) -> None:
        """Runs off the Tk thread. Do I/O here; marshal UI updates with .after()."""
        try:
            now = datetime.now()
            last = getattr(self, "_last_tick", now)
            self._last_tick = now

            # 1) Forfeit overdue tasks (disk I/O)
            forfeited = self.state.forfeit_overdue()
            if forfeited:
                self.after(0, self._refresh_table)
                self.after(0, self._refresh_balance)
                self.after(0, self._refresh_history_table)
                self.after(0, lambda: self.notifier.notify("Tasks Forfeited",
                                                        f"{forfeited} task(s) forfeited at window end."))

            # 2) Monday purge (disk I/O)
            if storage.purge_history_if_monday():
                self.after(0, self._refresh_history_table)

            # 3) Window status + notifications
            start, end = self.state.window_today()
            pre_end = end - timedelta(minutes=10)

            # Reset flags each new day
            today_key = now.strftime("%Y-%m-%d")
            if getattr(self, "_notified_day_key", None) != today_key:
                self._notified_day_key = today_key
                self._notified_open = False
                self._notified_pre_end = False

            # Fire when crossing start boundary
            if not self._notified_open and last < start <= now:
                self._notified_open = True
                self.after(0, lambda: self.notifier.notify(
                    "Task window open",
                    f"You can create tasks until {end.strftime('%I:%M %p').lstrip('0')}."
                ))

            # Fire when crossing 10-min-before-end boundary
            if not self._notified_pre_end and last < pre_end <= now:
                self._notified_pre_end = True
                self.after(0, lambda: self.notifier.notify(
                    "10 minutes left",
                    "Finish or mark tasks complete to avoid forfeits."
                ))

            # If app starts while already inside the window, notify once
            if not self._notified_open and start <= now <= end:
                self._notified_open = True
                self.after(0, lambda: self.notifier.notify(
                    "Task window open",
                    f"You can create tasks until {end.strftime('%I:%M %p').lstrip('0')}."
                ))

            # Lightweight UI state updates
            self.after(0, self._refresh_add_enabled)
            self.after(0, self._refresh_window_label)

        finally:
            self._tick_worker_running = False

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
        # clear table + mapping
        for row in self.h_tree.get_children():
            self.h_tree.delete(row)
        self._history_row_data.clear()

        rows = self._filter_history_rows(storage.read_history())
        for idx, obj in enumerate(rows):
            iid = f"h{idx}"
            self._history_row_data[iid] = obj
            self.h_tree.insert(
                "", tk.END, iid=iid,
                values=(
                    obj.get("ts",""),
                    obj.get("event",""),
                    obj.get("description",""),
                    f"{float(obj.get('buy_in', 0.0)):.2f}",
                    f"{float(obj.get('payout', 0.0)):.2f}",
                )
            )

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
    def _on_record_purchase(self) -> None:
        desc = simpledialog.askstring("Record Purchase", "What did you buy?", parent=self)
        if desc is None:
            return
        amt = simpledialog.askstring("Record Purchase", "Amount (e.g., 12.34)", parent=self)
        if amt is None:
            return
        try:
            amount = float(amt)
            self.state.record_purchase(desc, amount)
        except ValueError as e:
            messagebox.showerror("Invalid input", str(e))
            return
        self._refresh_balance()
        self._refresh_history_table()
        messagebox.showinfo("Recorded", f"Purchase recorded: -${amount:,.2f}")

    def _on_export_history_csv(self) -> None:
        # Choose destination file
        default_name = f"todo_gamble_history_{datetime.now().strftime('%Y%m%d')}.csv"
        path = filedialog.asksaveasfilename(
            title="Export History CSV",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not path:
            return

        # Gather filtered history
        data = storage.read_history()
        filtered = self._filter_history_rows(data)
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["ts", "event", "description", "buy_in", "payout"])
                for obj in filtered:
                    w.writerow([
                        obj.get("ts", ""),
                        obj.get("event", ""),
                        obj.get("description", ""),
                        f"{float(obj.get('buy_in', 0.0)):.2f}",
                        f"{float(obj.get('payout', 0.0)):.2f}",
                    ])
            messagebox.showinfo("Exported", f"History exported to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))
    def _filter_history_rows(self, rows):
        mode = (self.history_filter_var.get() if hasattr(self, "history_filter_var") else "All")
        if mode == "Purchases Only":
            return [r for r in rows if r.get("event") == "purchase"]
        if mode == "Tasks Only":
            return [r for r in rows if r.get("event") in ("completed", "forfeited")]
        return rows
    def _on_history_context(self, event) -> None:
        # Identify row under cursor
        row_id = self.h_tree.identify_row(event.y)
        if not row_id:
            return
        # Focus + select the row that was clicked
        self.h_tree.focus(row_id)
        self.h_tree.selection_set(row_id)
        self._history_selected_iid = row_id
        try:
            # Some Tk builds prefer tk_popup with a default index arg
            self.h_context.tk_popup(event.x_root, event.y_root, 0)
        finally:
            # Always release the grab so other widgets remain responsive
            try:
                self.h_context.grab_release()
            except Exception:
                pass

    def _on_history_revert(self) -> None:
        iid = self._history_selected_iid
        if not iid or iid not in self._history_row_data:
            messagebox.showinfo("Revert", "Select a history row to revert.")
            return
        obj = self._history_row_data[iid]
        event = (obj.get("event") or "").lower()

        if event == "purchase":
            desc = obj.get("description", "")
            amt = abs(float(obj.get("payout", 0.0)))  # payout is stored negative for purchases
            if not messagebox.askyesno("Refund purchase?", f"Refund this purchase?\n\n{desc}\n${amt:.2f}"):
                return
            try:
                self.state.revert_purchase(desc, amt)
            except Exception as e:
                messagebox.showerror("Revert failed", str(e))
                return
            self._refresh_balance()
            self._refresh_history_table()
            messagebox.showinfo("Reverted", f"Refunded ${amt:.2f} for: {desc}")
            return

        if event in ("completed", "forfeited"):
            # Build a snapshot for restore
            snap = {
                "id": obj.get("task_id") or obj.get("id"),
                "task_id": obj.get("task_id"),
                "description": obj.get("description", ""),
                "buy_in": float(obj.get("buy_in", 0.0)),
                "payout": float(obj.get("payout", 0.0)),
            }
            restore = messagebox.askyesno(
                "Revert",
                "Also restore this task back to Pending?\n\n"
                f"{snap['description']}\n"
                f"Buy-in ${snap['buy_in']:.2f} | Payout ${snap['payout']:.2f}"
            )
            try:
                if event == "completed":
                    self.state.revert_completion(snap, restore=restore)
                else:
                    self.state.revert_forfeit(snap, restore=restore)
            except Exception as e:
                messagebox.showerror("Revert failed", str(e))
                return
            self._refresh_balance()
            self._refresh_history_table()
            if restore:
                self._refresh_table()
            messagebox.showinfo("Reverted", f"Reverted {event} for: {snap['description']}")
            return

        # Other events (refund, reverted_*) — no-op or future support
        messagebox.showinfo("Revert", "This history event type cannot be reverted.")

    def _on_purge_data(self) -> None:
        msg = (
            "Purge Data will remove:\n"
            " • History (all)\n"
            " • Pending Tasks\n\n"
            "Ledger options:\n"
            " • Keep balance (ledger becomes a 1-line snapshot), or\n"
            " • Reset balance to $0 (delete ledger)\n\n"
            "Do you want to KEEP your current balance?"
        )
        keep = messagebox.askyesno("Purge Data", msg, icon="warning")
        try:
            storage.purge_data(save_balance=keep)
            # Refresh in-memory state
            self.state.tasks = []
            self.state.balance = storage.compute_balance()
            self._refresh_balance()
            self._refresh_table()
            self._refresh_history_table()
            messagebox.showinfo("Purge complete",
                                f"Data purged. Balance is now ${self.state.balance:,.2f}.")
        except Exception as e:
            messagebox.showerror("Purge failed", str(e))

    def _on_compact_ledger(self) -> None:
        # Ask retain days
        retain = simpledialog.askinteger(
            "Compact Ledger",
            "Keep how many days of ledger history? (default 30)",
            minvalue=1, maxvalue=3650
        )
        if retain is None:
            return
        try:
            n = storage.compact_ledger(retain_days=int(retain))
            # recompute (snapshot may have changed first line)
            self.state.balance = storage.compute_balance()
            self._refresh_balance()
            messagebox.showinfo("Ledger compacted",
                                f"Ledger compacted to last {retain} days.\nLines now: {n}\n"
                                f"Balance: ${self.state.balance:,.2f}")
        except Exception as e:
            messagebox.showerror("Compact failed", str(e))





    def _hide_to_tray(self) -> None:
        try:
            self.withdraw()  # hides window, keeps mainloop alive
            # Tiny toast to confirm background mode
            self.notifier.notify("Todo Gamble", "Running in background (tray).")
        except Exception:
            self.withdraw()

    def _show_from_tray(self) -> None:
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _quit_app(self) -> None:
        try:
            self.tray.stop()
        except Exception:
            pass
        self.destroy()
    def _send_test_notification(self) -> None:
        try:
            self.notifier.notify("Test Notification", "If you see this, notifications are working.")
        except Exception as e:
            messagebox.showerror("Notification Error", str(e))


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
