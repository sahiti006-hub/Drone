import os
from dotenv import load_dotenv
from app import create_app

# Load environment configuration from .env file
load_dotenv()

# Determine environment and instantiate application
env_name = os.getenv("FLASK_ENV", "development")
app = create_app(env_name)

if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "1") == "1"

    print(f"[*] Starting Smart Emergency Drone Delivery System in {env_name} mode...")
    print(f"[*] Listening on http://{host}:{port}")
    print(f"[*] Health check available at http://{host}:{port}/api/health")

    app.run(host=host, port=port, debug=debug)
