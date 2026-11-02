"""Prepare the application's server definition and password file for pgAdmin."""

import json
import os
import sqlite3
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
        "ConnectionParameters": {"sslmode": "prefer", "passfile": os.environ["PGPASS_FILE"]},
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

    # Imported server definitions are retained in existing pgAdmin volumes.
    # Update only this application's connection, preserving other servers.
    config_db = Path("/var/lib/pgadmin/pgadmin4.db")
    if config_db.exists():
        with sqlite3.connect(config_db) as connection:
            rows = connection.execute(
                "SELECT id, connection_params FROM server WHERE name = ? AND host = ?",
                (server["Name"], server["Host"]),
            ).fetchall()
            for server_id, raw_parameters in rows:
                parameters = json.loads(raw_parameters or "{}")
                parameters["passfile"] = str(passfile)
                connection.execute(
                    "UPDATE server SET connection_params = ? WHERE id = ?",
                    (json.dumps(parameters), server_id),
                )


if __name__ == "__main__":
    prepare()
