"""Run project services with a separate, loopback-only PostgreSQL database."""
import os
from pathlib import Path
import subprocess
import sys

from dotenv import dotenv_values
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "outputs" / "local-runtime"
os.environ.update({k: v for k, v in dotenv_values(ROOT / ".env").items() if v is not None})
user = os.environ.get("POSTGRES_USER", "dispatch")
password = os.environ.get("POSTGRES_PASSWORD", "dispatch")
database = os.environ.get("POSTGRES_DB", "dispatch_intelligence")
port = int(os.environ.get("LOCAL_POSTGRES_PORT", "5433"))
os.environ["DATABASE_URL"] = URL.create("postgresql+psycopg", username=user, password=password,
    host="127.0.0.1", port=port, database=database).render_as_string(hide_password=False)
os.environ["PYTHONPATH"] = os.pathsep.join([str(ROOT / "apps/api"), str(ROOT / "services")])
os.environ["EXAMPLE_DATA_DIR"] = str(ROOT / "example data")
os.environ["IMPORT_UPLOAD_DIR"] = str(ROOT / "import_uploads")
os.environ["ML_ARTIFACT_DIR"] = str(ROOT / "ml_artifacts")
os.environ["NUMBA_CPU_NAME"] = "generic"

def run(args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)

mode = sys.argv[1]
if mode in ("database", "stop-database"):
    pg = RUNTIME / "pgsql/bin"
    data = RUNTIME / "pgdata"
    if mode == "stop-database":
        run([pg / "pg_ctl.exe", "-D", data, "-m", "fast", "-w", "stop"])
    else:
        if not (data / "PG_VERSION").exists():
            pwfile = RUNTIME / "init-password.txt"
            pwfile.write_text(password, encoding="utf-8")
            try:
                run([pg / "initdb.exe", "-D", data, "-U", user, "-E", "UTF8",
                     "--locale=C", "--auth=scram-sha-256", f"--pwfile={pwfile}"])
            finally:
                pwfile.unlink(missing_ok=True)
        status = subprocess.run([str(pg / "pg_ctl.exe"), "-D", str(data), "status"], capture_output=True)
        if status.returncode:
            run([pg / "pg_ctl.exe", "-D", data, "-l", RUNTIME / "postgres.log",
                 "-o", f"-h 127.0.0.1 -p {port} -c timezone=Asia/Jakarta", "-w", "start"])
        import psycopg
        from psycopg import sql
        with psycopg.connect(host="127.0.0.1", port=port, user=user, password=password,
                             dbname="postgres", autocommit=True) as conn:
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone():
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
elif mode == "migrate":
    run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT / "apps/api")
elif mode == "api":
    run([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"], cwd=ROOT / "apps/api")
elif mode in ("phase6_worker", "import_worker"):
    run([sys.executable, "-m", f"app.{mode}"], cwd=ROOT / "apps/api")
else:
    raise SystemExit(f"Unknown service: {mode}")
