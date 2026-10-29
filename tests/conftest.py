"""Offline test bootstrap: the server modules import each other by bare name."""
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "vendor" / "iphone-use" / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))
