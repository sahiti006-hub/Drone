"""WSGI Production Entry Point.

This file exposes the Flask application instance callable for production WSGI servers
such as Gunicorn (Linux/Container) or Waitress (Windows/Standalone).

Usage Examples:
  Linux / Docker (Gunicorn):
    gunicorn --bind 0.0.0.0:5000 --workers 3 --threads 2 --timeout 120 wsgi:app

  Windows (Waitress CLI):
    waitress-serve --host=127.0.0.1 --port=5000 wsgi:app

  Direct Python invocation:
    python wsgi.py
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Load environment configuration (.env file if present)
load_dotenv(BASE_DIR / ".env")

from app import create_app

# Default to production configuration unless explicitly overridden
env_name = os.getenv("FLASK_ENV", "production").lower()
app = create_app(env_name)

if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))

    print(f"[*] Starting Smart Emergency Drone Delivery System via WSGI...")
    print(f"[*] Environment : {env_name}")
    print(f"[*] Listening   : http://{host}:{port}")

    # Attempt to load a hardened production WSGI server
    try:
        from waitress import serve
        print("[+] Using Waitress production WSGI server.")
        serve(app, host=host, port=port)
    except ImportError:
        print("[!] Note: Waitress is not installed. To run production WSGI on Windows:")
        print("    pip install waitress")
        print(f"    waitress-serve --host={host} --port={port} wsgi:app")
        print("[!] Falling back to standard application server with debug disabled:")
        app.run(host=host, port=port, debug=False)
