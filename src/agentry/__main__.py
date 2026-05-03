"""Allow ``python -m agentry`` invocation.

This is a fallback for when the entry-point script isn't on PATH.
"""

from agentry.cli import cli

if __name__ == "__main__":
    cli()
