"""Start the project command-line interface with python -m options_lab.

Pass command-line parsing and execution to options_lab.cli.main and expose its return code
to the shell. This is the terminal entry point for collecting data, initializing databases,
valuing saved captures and replaying the synthetic fixture. The notebooks call the parser
and dispatcher directly inside their kernels.
"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
