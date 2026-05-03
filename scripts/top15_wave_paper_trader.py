#!/usr/bin/env python3
from __future__ import annotations

import runpy
from pathlib import Path


def main():
    target = Path(__file__).with_name("top15_wave_proto_balanced_paper_trader.py")
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
