"""Vercel Serverless Function entry point with WSGI path normalization."""

import os
import sys
import json
from pathlib import Path

# Ensure the repository root is always in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Ensure VERCEL environment flag is recognized
os.environ.setdefault("VERCEL", "1")

from wsgi import app


class VercelPathNormalizer:
    """WSGI middleware ensuring proper PATH_INFO under Vercel serverless rewrites."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        # Diagnostic debug endpoint
        if environ.get("PATH_INFO") == "/debug-vercel" or environ.get("HTTP_X_MATCHED_PATH") == "/debug-vercel":
            debug_info = {
                k: v for k, v in environ.items()
                if k.startswith(("HTTP_", "PATH_", "REQUEST_", "RAW_", "VERCEL", "SCRIPT_"))
            }
            body = json.dumps(debug_info, indent=2).encode("utf-8")
            start_response("200 OK", [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
            ])
            return [body]

        # In Vercel Python runtime with rewrites to /api/index.py:
        # Vercel provides the true client request path in HTTP_X_MATCHED_PATH or REQUEST_URI.
        # If PATH_INFO is overwritten with /api/index.py or /api, restore the real path.
        matched_path = environ.get("HTTP_X_MATCHED_PATH")
        if matched_path and not matched_path.startswith("/api/index"):
            # Strip query parameters if present in matched_path
            real_path = matched_path.split("?")[0]
            environ["PATH_INFO"] = real_path
        elif environ.get("PATH_INFO") in ("/api/index.py", "/api/index", "/api"):
            req_uri = environ.get("REQUEST_URI", "").split("?")[0]
            if req_uri and not req_uri.startswith("/api/index"):
                environ["PATH_INFO"] = req_uri
            else:
                environ["PATH_INFO"] = "/"

        return self.wsgi_app(environ, start_response)


# Expose normalized handler
handler = VercelPathNormalizer(app)
