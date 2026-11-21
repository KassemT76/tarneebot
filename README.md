# Tarneebot

A local Python Tarneeb simulator and AI agent project for COMP 3106.

The original nested-project README is preserved at [readmenest.md](readmenest.md).

## Requirements

- Python 3.11 or newer
- Tkinter for the desktop GUI

The engine and agents use only the Python standard library. No runtime
third-party Python packages are required.

## Linux setup

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

On Debian or Ubuntu, install Python Tk support if it is missing:

```bash
sudo apt update
sudo apt install python3-tk
```

For Fedora:

```bash
sudo dnf install python3-tkinter
```

For Arch Linux:

```bash
sudo pacman -S tk
```

## Run the tests

```bash
python -m unittest discover -s tests -v
```

## Run from Linux

Desktop GUI:

```bash
python -m tarneebot gui
python -m tarneebot gui --seed 42
```

Terminal play:

```bash
python -m tarneebot play --seed 42
python -m tarneebot play --agents rule human sampled rule --samples 10 --seed 42
```

Run headless simulations:

```bash
python -m tarneebot simulate --deals 10 \
  --agents random rule random rule \
  --seed 42 --agent-seed 7 \
  --log runs/baseline.json

python -m tarneebot simulate --match \
  --seed 42 --agent-seed 7 --max-deals 500 \
  --log runs/match.json
```

Replay a simulation:

```bash
python -m tarneebot replay runs/match.json
```

Run the search solver:

```bash
python -m tarneebot solve --seed 42 --bidder 1 --bid 8 \
  --trump S --remaining-tricks 2
```

Generate bidding data:

```bash
python -m tarneebot dataset \
  --output data/week2_bidding.csv \
  --base-deals 25 --duplicates \
  --seed 3106 --agent-seed 40 --policy rule
```

## Windows

Run the GUI or commands in PowerShell with `python` instead of `python3`:

```powershell
python -m tarneebot gui
python -m tarneebot gui --seed 42
python -m unittest discover -s tests -v
```

Build the Windows executable:

```powershell
.\build_exe.ps1
.\dist\Tarneebot.exe
```

The build script creates `.venv`, installs the pinned PyInstaller build
dependency, and writes the executable to `dist/`. Build output is ignored by
Git.

## Project layout

- `tarneebot/`: cards, rules, engine, agents, search, sampling, CLI, dataset, and GUI
- `tests/`: unit and integration tests
- `data/`: generated bidding dataset
- `docs/`: rules, implementation notes, and screenshots
- `runs/`: generated experiment logs and smoke-test artifacts
- `build/`, `dist/`, `*.egg-info/`: generated packaging/build output
