"""Vercel Serverless Function entry point.

Exposes the WSGI `app` callable for the @vercel/python runtime.
All incoming HTTP requests rewritten by `vercel.json` are routed here.
"""

import os
import sys
from pathlib import Path

# Ensure the repository root is always in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Ensure VERCEL environment flag is recognized
os.environ.setdefault("VERCEL", "1")

from wsgi import app

# Vercel's Python runtime checks for `app` or `handler`
handler = app
