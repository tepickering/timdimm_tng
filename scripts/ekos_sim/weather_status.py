#!/usr/bin/env python

import sys
from pathlib import Path
import json


with open(Path.home() / "roof_status.json", 'r') as fp:
    status = json.load(fp)

print(json.dumps(status, indent=4))

sys.exit(0)
