"""Console progress log: one timestamped line per step, written to stderr."""

from datetime import datetime
import sys

QUIET = False


def log(message: str, doc: str | None = None) -> None:
    if QUIET:
        return
    stamp = datetime.now().strftime("%H:%M:%S")
    prefix = f"{stamp}  {doc:<26}" if doc else f"{stamp}  "
    print(prefix + message, file=sys.stderr, flush=True)


def short(text, limit: int = 160) -> str:
    """One line, cut to `limit` characters, for problem messages."""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"
