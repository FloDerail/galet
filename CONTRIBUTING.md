# Contributing to Galet

Galet is maintained by **Florian Dérail** ([florianderail.fr](https://florianderail.fr), GitHub
[@FloDerail](https://github.com/FloDerail)).

Galet was largely written with the help of an AI assistant (Claude, by Anthropic); see the
"How Galet is made" section of the README. Human reviews of the code and translations are especially
welcome.

Thanks for helping! Galet is plain Python + PyGObject (GTK 4, libadwaita), so there is
no build step: clone the repository and run `./bin/galet`.

## Code

- Keep the code readable for newcomers: small functions, docstrings on classes.
- All user-visible strings must be wrapped in `_()` (from `galet/i18n.py`).
- Follow the GNOME Human Interface Guidelines for UI. When in doubt, ask how Finder
  does it and how that fits GNOME.
- Before opening a pull request, run `python3 -m py_compile galet/*.py` and test the
  three views (icons, list, columns).

## Translations

Available: English, French (fr), Spanish (es), German (de), Italian (it), Portuguese (pt).
Native speakers are very welcome to review and improve them.

1. Regenerate the template: `python3 tools/update-pot.py`
2. Copy `po/galet.pot` to `po/<lang>.po` (e.g. `po/de.po`) and fill in the `msgstr` lines,
   or update an existing file.
3. Check coverage: `python3 tools/update-pot.py --check`
4. Test with `LANGUAGE=<lang> ./bin/galet`.

## Reporting bugs

Please include your distribution, GTK and libadwaita versions, and the terminal output
of `./bin/galet`.
