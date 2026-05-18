"""
ASGI wrapper for Chanakya v5 Flask trading platform.
Mounts the Flask app under uvicorn (supervisor-managed at port 8001).
"""
import os
import sys
import logging
from pathlib import Path

# Add chanakya project root to sys.path
CHANAKYA_ROOT = Path("/app/chanakya")
sys.path.insert(0, str(CHANAKYA_ROOT))

# Load env from chanakya/.env
from dotenv import load_dotenv
load_dotenv(CHANAKYA_ROOT / ".env")

# Change CWD so relative paths (data/, frontend/templates) resolve correctly
os.chdir(CHANAKYA_ROOT)

# Ensure data directory exists for log file
(CHANAKYA_ROOT / "data").mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("chanakya.wrapper")
logging.basicConfig(level=logging.INFO)

# Import the Flask app from main.py
try:
    from main import app as flask_app  # noqa: E402
    logger.info("Loaded Chanakya Flask app successfully")
except Exception as e:
    logger.exception("Failed to import chanakya main.py: %s", e)
    # Provide a fallback minimal Flask app that exposes the error
    from flask import Flask, jsonify
    flask_app = Flask(__name__)
    _err = repr(e)

    @flask_app.route("/health")
    def _h():
        return jsonify({"status": "error", "error": _err}), 500

    @flask_app.route("/")
    def _r():
        return jsonify({"status": "error", "error": _err, "hint": "Check backend logs"}), 500

# Wrap Flask (WSGI) into ASGI so uvicorn can serve it
from asgiref.wsgi import WsgiToAsgi  # noqa: E402

app = WsgiToAsgi(flask_app)
