"""python -m promo: see promo/run.py."""
import sys

from .llm import ModelError
from .run import main

if __name__ == "__main__":
    try:
        main()
    except (ModelError, ValueError, OSError) as exc:
        sys.exit(f"Stopped: {exc}\nFinished model answers are cached; run the same command again to resume.")
