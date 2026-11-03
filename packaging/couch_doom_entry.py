import sys

# The apply helper is this same executable. Importing the UI first pulls in pygame and the
# launchers, and on an Intel build under Rosetta that translation is the long pause before
# the updated app opens. Handle the swap before any of that loads.
if len(sys.argv) > 1 and sys.argv[1] == "--apply-update":
    from couch_doom.self_update import apply_from_argv

    sys.exit(apply_from_argv(sys.argv[1:]))

from couch_doom.__main__ import _entry

sys.exit(_entry())
