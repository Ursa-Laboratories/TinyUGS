# Tiny UGS Agent Guide

This directory is intended to be portable and easy to move into its own git repo.

## Purpose

`tiny_ugs.py` is a minimal GRBL browser panel for remote use over SSH port forwarding.
It is intentionally closer to UGS than to Zoo:

- talks directly to GRBL over serial
- shows raw controller-space `WPos`, `MPos`, and `WCO`
- supports connect, settings read/edit, home, unlock, reset+unlock, hold, resume, jog, jog-cancel, and absolute move

It does **not** use CubOS coordinate translation.

## Setup Workflow

When setting this up on a Pi or any remote Linux host, use a local venv in this directory:

```bash
cd tiny_ugs
python3 -m venv venv
source venv/bin/activate
pip uninstall -y serial
pip install -r requirements.txt
python -c "from serial.tools import list_ports; print('pyserial ok')"
```

Important:

- install `pyserial`, not the unrelated `serial` package
- if `import serial.tools.list_ports` fails, the environment is wrong
- keep the HTTP server bound to `127.0.0.1` unless the user explicitly wants network exposure
- when changing settings UI or backend behavior, preserve support for generic `$<n>=<value>` updates

## Run Workflow

On the remote host:

```bash
cd tiny_ugs
source venv/bin/activate
python tiny_ugs.py --serial-port /dev/ttyUSB0 --web-port 8765 --auto-connect
```

On the local machine:

```bash
ssh -L 8765:127.0.0.1:8765 <user>@<remote-host>
```

Then open:

```text
http://127.0.0.1:8765
```

## Safety

- homing, jogging, and absolute moves cause real hardware motion
- do not invent coordinate sign conventions; trust the live `WPos` / `MPos` readout
- if the machine is in alarm, prefer `Unlock` or `Reset + Unlock` before retrying motion
- if behavior looks mechanically wrong, stop debugging software and treat it as a hardware-state problem first

## Editing Rules

- keep this tool dependency-light
- prefer the Python standard library plus `pyserial`
- do not add frontend build tooling unless explicitly requested
- if you change setup or run behavior, update `README.md`, `AGENTS.md`, and `requirements.txt` together
