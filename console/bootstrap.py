"""One-shot Docker secret initialization; no credentials are printed."""

import os
from pathlib import Path
import secrets


def main():
    for name in ("/secrets/mysql/password", "/secrets/root/password"):
        path = Path(name)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(48))
    print("Database credentials initialized.")


if __name__ == "__main__":
    main()
