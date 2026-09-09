"""Private entrypoint for the transient user service."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from x86_on_arm.vm import VirtualMachine

if __name__ == "__main__":
    config_path = sys.argv[1]
    VirtualMachine(json.loads(Path(config_path).read_text()), config_path, dict(os.environ)).serve()
