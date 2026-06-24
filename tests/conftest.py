import sys, os
# 确保能 import core.* / backend.*
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "core"), os.path.join(ROOT, "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)
