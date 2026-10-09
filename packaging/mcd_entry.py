"""PyInstaller entry point for the standalone `mcd` binary."""
from mcd_terminal.cli import app

if __name__ == "__main__":
    app(prog_name="mcd")
