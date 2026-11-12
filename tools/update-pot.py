#!/usr/bin/env python3
"""Extract translatable strings into po/galet.pot and report missing translations.

Usage:  python3 tools/update-pot.py          # regenerate po/galet.pot
        python3 tools/update-pot.py --check  # list untranslated strings per language
"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CALL = re.compile(r'''(?:\b_|\bN_|\bngettext)\(\s*((?:"(?:[^"\\]|\\.)*"\s*,?\s*)+)''')
LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"(\s*,)?')
CHOICE = re.compile(r'\("[a-z_]+", "([^"]+)"\)')  # (key, "Label") tuples in preferences.py


def extract():
    strings = {}
    for path in sorted((ROOT / "galet").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for match in CALL.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            # Adjacent literals ("a" "b") form one string; a comma starts a new one.
            current = ""
            for literal, comma in LITERAL.findall(match.group(1)):
                current += ast.literal_eval(f'"{literal}"')
                if comma:
                    strings.setdefault(current, f"galet/{path.name}:{line}")
                    current = ""
            if current:
                strings.setdefault(current, f"galet/{path.name}:{line}")
        if path.name == "preferences.py":
            for literal in CHOICE.findall(source):
                strings.setdefault(literal, f"galet/{path.name}")
    return strings


def main():
    strings = extract()
    if "--check" in sys.argv:
        from galet.i18n import _parse_po

        for po in sorted((ROOT / "po").glob("*.po")):
            catalog = _parse_po(po.read_text(encoding="utf-8"))
            missing = [s for s in strings if s not in catalog]
            print(f"{po.stem}: {len(strings) - len(missing)}/{len(strings)} translated")
            for s in missing:
                print(f"   missing: {s}")
        return
    out = ['msgid ""', 'msgstr ""', '"Content-Type: text/plain; charset=UTF-8\\n"', ""]
    for text, where in strings.items():
        escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        out += [f"#: {where}", f'msgid "{escaped}"', 'msgstr ""', ""]
    (ROOT / "po" / "galet.pot").write_text("\n".join(out), encoding="utf-8")
    print(f"{len(strings)} strings written to po/galet.pot")


if __name__ == "__main__":
    main()
