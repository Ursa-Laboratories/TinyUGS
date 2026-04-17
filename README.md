# Tiny UGS

Minimal GRBL browser panel for running on a remote host and viewing locally through SSH port forwarding.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip uninstall -y serial
pip install -r requirements.txt
```

`pyserial` is required. The package named `serial` is the wrong one.

## Run

On the remote host:

```bash
source venv/bin/activate
python tiny_ugs.py --serial-port /dev/ttyUSB0 --web-port 8765 --auto-connect
```

On the local machine:

```bash
ssh -L 8765:127.0.0.1:8765 <user>@<remote-host>
```

Open:

```text
http://127.0.0.1:8765
```

## Features

- read GRBL settings with `$$`
- view raw `WPos`, `MPos`, and `WCO`
- connect and disconnect
- home, unlock, reset + unlock
- feed hold and resume
- jog and jog cancel
- send absolute moves

This tool uses raw GRBL/controller coordinates, not CubOS-translated user-space.
