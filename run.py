#!/usr/bin/env python3
"""Collect then build. Always builds, so the site shows honest stale-data status even if sources fail."""
from pathlib import Path

import build
import collect

if __name__ == "__main__":
    root = Path(__file__).parent
    collect.run(root)
    build.run(root)
