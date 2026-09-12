"""Windows frozen entrypoint, preserving the native binary's CLI and -c modes."""

import multiprocessing
import sys

from mnemosyne import cli


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == "-c":
        code = sys.argv[2] if len(sys.argv) > 2 else ""
        sys.argv = ["mnemosyne-c", *sys.argv[3:]]
        exec(compile(code, "<command>", "exec"), {"__name__": "__main__"})
    else:
        cli.main()
