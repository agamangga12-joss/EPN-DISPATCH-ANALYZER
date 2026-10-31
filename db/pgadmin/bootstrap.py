"""Prepare the application's server definition and password file for pgAdmin."""

import json
import os
from pathlib import Path


def prepare() -> None:
    database = os.environ["APP_DB_NAME"]
    username = os.environ["APP_DB_USER"]
    password = os.environ["APP_DB_PASSWORD"]
    server = {
        "Name": "Dispatch Intelligence",
        "Group": "Aplikasi",
        "Host": "db",
        "Port": 5432,
        "MaintenanceDB": database,
        "Username": username,
        "ConnectionParameters": {"sslmode": "prefer", "passfile": ".pgpass"},
    }
    Path(os.environ["PGADMIN_SERVER_JSON_FILE"]).write_text(
        json.dumps({"Servers": {"1": server}}), encoding="utf-8"
    )

    fields = ["db", "5432", "*", username, password]
    if any("\n" in value or "\r" in value for value in fields):
        raise ValueError("Database credentials must not contain newlines")
    escaped = [value.replace("\\", "\\\\").replace(":", "\\:") for value in fields]
    passfile = Path(os.environ["PGPASS_FILE"])
    descriptor = os.open(passfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(":".join(escaped) + "\n")
    passfile.chmod(0o600)


if __name__ == "__main__":
    prepare()
