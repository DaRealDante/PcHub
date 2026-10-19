import sys

import updater_boot

updater_boot.prepare()

from pchub.app import main  # noqa: E402  (must come after the updater)

if __name__ == "__main__":
    sys.exit(main(sys.argv))
