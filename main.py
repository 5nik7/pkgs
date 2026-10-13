#!/usr/bin/env python3
import sys
if sys.version_info < (3, 9):
    sys.exit('pkgs: Python 3.9+ is required')
from pkgs_lib.cli import main
if __name__ == '__main__':
    sys.exit(main())
