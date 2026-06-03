"""Filesystem paths used across the overlay."""
import os

# This file is at: cs2_overlay/paths.py
# BASE should resolve to the CS2Toolkit root (parent of cs2_overlay/).
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))   # cs2_overlay/
BASE = os.path.dirname(_THIS_DIR)                         # CS2Toolkit/

DATA_DIR = os.path.join(BASE, "data")
OFFSET_FILE = os.path.join(DATA_DIR, "offsets.json")
PIC_DIR = os.path.join(BASE, "pic")
