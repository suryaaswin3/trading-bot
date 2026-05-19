#!/usr/bin/env python3
"""Fix tzinfo handling in validation.py"""
import re

with open('/opt/trading-bot/ops_api/validation.py', 'r') as f:
    content = f.read()

old = (
    '    try:\n'
    '        last_time = datetime.fromisoformat(last_order_at)\n'
    '    except (ValueError, TypeError):\n'
    '        return True, ""\n'
    '\n'
    '    now = datetime.now(timezone.utc)'
)

new = (
    '    try:\n'
    '        last_time = datetime.fromisoformat(last_order_at)\n'
    '        if last_time.tzinfo is None:\n'
    '            last_time = last_time.replace(tzinfo=timezone.utc)\n'
    '    except (ValueError, TypeError):\n'
    '        return True, ""\n'
    '\n'
    '    now = datetime.now(timezone.utc)'
)

if old in content:
    content = content.replace(old, new)
    with open('/opt/trading-bot/ops_api/validation.py', 'w') as f:
        f.write(content)
    print("FIX APPLIED")
else:
    print("OLD STRING NOT FOUND - checking actual content...")
    # Show lines 70-76
    lines = content.split('\n')
    for i in range(min(69, len(lines)-1), min(78, len(lines))):
        print(f"  {i+1}: {repr(lines[i])}")