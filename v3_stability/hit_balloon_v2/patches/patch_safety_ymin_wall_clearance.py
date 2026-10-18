#!/usr/bin/env python3
"""Tighten the audited purple-side safety limit from -3.0 to -2.20 m.

Usage: python3 patch_safety_ymin_wall_clearance.py PATH_TO_LLM_MISSION_LAUNCH
The caller must make a dated backup and record its MD5 first. This script
performs one byte-exact replacement and verifies the launch remains XML.
"""

import sys
import xml.dom.minidom
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit(__doc__)
path = Path(sys.argv[1])
raw = path.read_bytes()
old = b'<param name="safety/y_min" value="-3.0" type="double"/>'
new = b'<param name="safety/y_min" value="-2.20" type="double"/>'
if raw.count(old) != 1 or raw.count(new) != 0:
    raise SystemExit('unexpected safety/y_min source; no write')
updated = raw.replace(old, new)
xml.dom.minidom.parseString(updated)
path.write_bytes(updated)
print('PATCHED safety/y_min -3.0 -> -2.20; XML_OK')
