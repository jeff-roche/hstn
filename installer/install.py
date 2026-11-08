#!/usr/bin/env python3
"""HSTN standalone installation / per-user native-package setup entry point."""
import os
from pathlib import Path
import sys

if __name__ == '__main__':
    script = Path(__file__).resolve().parent/'install-hstn.py'
    os.execv(sys.executable, [sys.executable, '-B', str(script), *sys.argv[1:]])
