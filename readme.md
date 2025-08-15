

# Todo Gamble App (Starter + History + Window)

A minimal Windows-friendly Python desktop app that gamifies todos with buy-ins/payouts. This version adds:
- **History tab** (auto-purges each Monday)
- **Daily creation window** (disables Add button outside window)
- **Auto-forfeit** of pending tasks at window end (adds `-buy_in` to ledger & history)
- **Settings** for window start/end
- **PyInstaller spec** + simple icon generator

## Run (dev)
```bash
python -m app.main
```

## Build a Windows .exe (PyInstaller)
Install PyInstaller:
```bash
pip install pyinstaller
```
Build with the spec (uses `app/assets/icon.ico` if present):
```bash
pyinstaller TodoGamble.spec
```
Executable outputs to `dist/TodoGamble.exe`.

> **Icon**: Place a 64×64+ (multi-size) ICO at `app/assets/icon.ico`, or run:
> ```bash
> python app/tools/make_icon.py
> ```

## Where data is stored
- Tasks: `~/.todo_gamble_app/tasks.json`
- Ledger (JSONL): `~/.todo_gamble_app/ledger.txt`
- History (JSONL): `~/.todo_gamble_app/history.jsonl` (auto-purged Mondays)
- Settings: `~/.todo_gamble_app/settings.json`

## Daily creation window behavior
- You can create tasks only between **Start** and **End** times (local time).
- At **window end**, all `pending` tasks are **forfeited** (adds negative entry to ledger & history, removed from active list).
- On startup, the app **retro-processes** overdue tasks you missed while the app was closed.

## Testing on macOS
- You can **develop and run** the app on macOS (Tkinter works cross‑platform).
- The daily window / auto‑forfeit logic is platform-agnostic.
- To build a **Windows .exe**, use a Windows environment:
  - Spin up a Windows VM, or
  - Use **GitHub Actions** with a Windows runner. Example workflow:

```yaml
# .github/workflows/windows-build.yml
name: Windows build
on: [push, workflow_dispatch]
jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install pyinstaller
      - run: pyinstaller TodoGamble.spec
      - uses: actions/upload-artifact@v4
        with:
          name: TodoGamble-dist
          path: dist/
```
### Finance & Spending
- **Record Purchase / Withdrawal**: subtract from balance and log to History (`purchase` event).
- History tab can **filter**: All, Tasks Only, Purchases Only.
- **Export CSV** of history for budgeting.
---