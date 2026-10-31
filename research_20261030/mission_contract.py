"""Validate an explicit competition contract; never synthesize model commands."""
import os
import re

STAGES = ('takeoff', 'cross_frame', 'detect_aruco', 'return_cross_frame',
          'hit_balloon', 'land')

def full_mission_problems(commands):
    if os.environ.get('MISSION_REQUIRE_FULL_SEQUENCE', '0') != '1':
        return []
    lines = [s.strip() for s in (commands or '').splitlines() if s.strip()]
    normalized = ['hit_balloon' if re.fullmatch(r'hit_balloon\s*:\s*(red|purple|blue)', s)
                  else s for s in lines]
    if tuple(normalized) != STAGES:
        return ['full mission sequence mismatch: expected ' + ' -> '.join(STAGES)
                + '; got ' + ' -> '.join(normalized)]
    return []

def strict_contract_enabled():
    return os.environ.get('MISSION_REQUIRE_FULL_SEQUENCE', '0') == '1'
