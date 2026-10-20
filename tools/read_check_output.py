import json
import os
import re
import sys

name = sys.argv[1]
path = os.path.join(os.environ["TEMP"], name)
text = open(path, encoding="utf-8", errors="replace").read()
match = re.search(r"DIAGNOSTICS (\{.*)$", text, re.S)
if not match:
    print(text[:3000])
    raise SystemExit
raw = match.group(1).strip()
decoder = json.JSONDecoder()
obj, end = decoder.raw_decode(raw)
obj.pop("probes", None)
print(json.dumps(obj, indent=1))
