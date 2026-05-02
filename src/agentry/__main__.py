"""Allow ``python -m agentry`` invocation as a fallback when the entry-point script isn't on PATH."""

from agentry.cli import cli

if __name__ == "__main__":
    cli()
