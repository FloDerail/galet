import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from .application import GaletApplication  # noqa: E402


def main():
    return GaletApplication().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
