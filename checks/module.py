"""Test the module's actual registration masks against real ELF files."""

import codecs
import json
import sys
from pathlib import Path

rules = json.loads(Path(sys.argv[1]).read_text())
samples = [Path(name).read_bytes()[:128] for name in sys.argv[2:]]
for name, rule in rules.items():
    assert rule["preserveArgvZero"]
    assert not any(
        rule[key]
        for key in ("openBinary", "fixBinary", "matchCredentials", "wrapInterpreterInShell")
    )
    magic = codecs.decode(rule["magicOrExtension"], "unicode_escape").encode("latin1")
    mask = codecs.decode(rule["mask"], "unicode_escape").encode("latin1")
    matches = [
        all((byte & mask[i]) == (sample[i] & mask[i]) for i, byte in enumerate(magic))
        for sample in samples
    ]
    assert matches == ([True, False, False] if name.endswith("x86_64") else [False, True, False]), (
        name,
        matches,
    )
print("Module: default x86 ELF handlers, preserved argv0, correct ABI masks")
