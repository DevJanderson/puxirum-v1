import os
import sys
from pathlib import Path

# Run the tests against src/ without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# The suite may run inside a tuios pane. Nothing in it may reach that real session.
for _name in [n for n in os.environ if n.startswith("TUIOS_")]:
    del os.environ[_name]
