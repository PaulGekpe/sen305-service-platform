"""Re-runs the Lab 4 verification steps against a fresh database and writes the transcripts.

    cd sen305-service-platform && python evidence/run_evidence.py

Everything in evidence/*.txt and evidence/screenshots/ is produced by this script.
"""

import os
import platform
import re
import secrets
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import shell_parts as S  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
EVID = ROOT / "evidence"
DB = BACKEND / "evidence_db.sqlite3"
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"

ENV = os.environ.copy()
ENV.update(
    DJANGO_DEBUG="False",          # so the real 403/404 pages are what the screenshots show
    SQLITE_PATH=str(DB),
    NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost",
    PYTHONDONTWRITEBYTECODE="1",
)
ENV.pop("DB_ENGINE", None)


def manage(*args, stdin=None, env=None):
    proc = subprocess.run(
        [sys.executable, "manage.py", *args], cwd=BACKEND, env=env or ENV,
        input=stdin, capture_output=True, text=True,
    )
    text = "\n".join(
        line for line in (proc.stdout + proc.stderr).splitlines()
        if not re.match(r"^\d+ objects? imported automatically", line)
    ).strip("\n")
    return text.rstrip(), proc.returncode


class Transcript:
    def __init__(self, name, title):
        self.path = EVID / name
        self.lines = [f"# {title}", f"# generated {time.strftime('%Y-%m-%d %H:%M:%S %z')}", ""]

    def cmd(self, text, output=""):
        self.lines.append(f"$ {text}")
        if output:
            self.lines.append(output)
        self.lines.append("")

    def snippet(self, command, code, output):
        self.lines.append(f"$ {command}")
        self.lines.append("# --- statements typed/pasted into the shell ---")
        self.lines.extend(code.rstrip().splitlines())
        self.lines.append("# --- output ---")
        self.lines.append(output)
        self.lines.append("")

    def save(self):
        self.path.write_text("\n".join(self.lines).rstrip() + "\n")


def main():
    EVID.mkdir(exist_ok=True)
    if DB.exists():
        DB.unlink()

    # ---- environment ---------------------------------------------------------------------------
    import django
    out, _ = manage("shell", "-c", "from django.db import connection as c; print(c.vendor, c.Database.sqlite_version)")
    env_t = Transcript("00_environment.txt", "Environment used to produce this evidence")
    env_t.cmd("python --version", platform.python_version())
    env_t.cmd("python -m django --version", django.get_version())
    env_t.cmd("database backend / version used for this run", out)
    env_t.cmd("uname -sr", f"{platform.system()} {platform.release()}")
    env_t.lines.append(
        "NOTE: this run used SQLite because no MySQL server was available in the sandbox. The code is\n"
        "backend-neutral (ORM only); re-run the same commands against MySQL 8 on your own machine."
    )
    env_t.save()

    manage("migrate", "--noinput")  # Lab 3 starting point: migrations already applied

    # ---- Part A ---------------------------------------------------------------------------------
    t = Transcript("01_part_a_verify_starting_point.txt", "Part A - Verify the Lab Session 3 starting point")
    t.cmd("git branch --show-current", subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, capture_output=True, text=True).stdout.strip())
    t.cmd("python manage.py check", manage("check")[0])
    t.cmd("python manage.py showmigrations requests_app", manage("showmigrations", "requests_app")[0])
    a2 = ('from requests_app.models import *; print([f.name for f in ServiceRequest._meta.fields]); '
          'print([f.name for f in WorkOrder._meta.fields]); print([f.name for f in Comment._meta.fields])')
    t.cmd(f'python manage.py shell -c "{a2}"', manage("shell", "-c", a2)[0])
    su_env = dict(ENV, DJANGO_SUPERUSER_PASSWORD=secrets.token_urlsafe(16))
    t.cmd("python manage.py createsuperuser --noinput --username admin --email admin@example.com",
          manage("createsuperuser", "--noinput", "--username", "admin", "--email", "admin@example.com", env=su_env)[0])
    out, _ = manage("shell", stdin=S.A3_ACCOUNTS)
    t.snippet("python manage.py shell", S.A3_ACCOUNTS, out or "(accounts created)")
    t.save()

    # ---- Part B2 --------------------------------------------------------------------------------
    t = Transcript("02_part_b2_form_validation.txt", "Part B2 - Exercise validation")
    out, _ = manage("shell", stdin=S.B2_VALIDATION)
    t.snippet("python manage.py shell", S.B2_VALIDATION, out)
    rows, _ = manage("shell", "-c", "from requests_app.models import ServiceRequest; print(ServiceRequest.objects.count())")
    t.cmd('python manage.py shell -c "...print(ServiceRequest.objects.count())"   # validation must not save a row', rows)
    t.save()

    # ---- Part C2 --------------------------------------------------------------------------------
    t = Transcript("03_part_c2_row_level_visibility.txt", "Part C2 - Prove row-level visibility")
    out, _ = manage("shell", stdin=S.C2_VISIBILITY)
    t.snippet("python manage.py shell", S.C2_VISIBILITY, out)
    t.lines.append("# Expected: owner True, other requester False, staff True")
    t.save()

    manage("shell", stdin=S.SEED_PRINTER_REQUESTS)  # data for the Task 3 pagination screenshot

    # ---- Part J (browser) -----------------------------------------------------------------------
    server_log = open(EVID / "_server.log", "w")
    server = subprocess.Popen(
        [sys.executable, "manage.py", "runserver", f"127.0.0.1:{PORT}", "--noreload", "--insecure"],
        cwd=BACKEND, env=ENV, stdout=server_log, stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"{BASE}/accounts/login/", timeout=2)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise SystemExit("server did not start")
        proc = subprocess.run(
            [sys.executable, str(EVID / "browser_walkthrough.py"), BASE, str(DB), str(EVID)],
            env=ENV, capture_output=True, text=True,
        )
    finally:
        server.terminate()
        server.wait(timeout=10)
        server_log.close()
    t = Transcript("04_part_j_manual_crud_script.txt", "Part J - Manual CRUD test script (real Chrome browser against runserver)")
    t.cmd(f"python manage.py runserver 127.0.0.1:{PORT}   # DEBUG=False so the real 403/404 pages are shown")
    t.cmd("python evidence/browser_walkthrough.py", (proc.stdout + proc.stderr).rstrip())
    out, _ = manage("shell", stdin=S.J_DB_VERIFICATION)
    t.snippet("python manage.py shell   # database verification", S.J_DB_VERIFICATION, out)
    t.save()
    print((proc.stdout + proc.stderr)[-3500:])
    if proc.returncode:
        raise SystemExit("browser walkthrough reported failures")

    # ---- Part K ---------------------------------------------------------------------------------
    t = Transcript("05_part_k_transaction_rollback.txt", "Part K - Prove transaction rollback")
    out, _ = manage("shell", stdin=S.K_ROLLBACK)
    t.snippet("python manage.py shell", S.K_ROLLBACK, out)
    t.save()

    # ---- Part M DB verification -----------------------------------------------------------------
    t = Transcript("07_part_m_task2_resolution_db_check.txt", "Part M Task 2 - Verify status, resolved_at, work_notes, completed_at")
    out, _ = manage("shell", stdin=S.TASK_DB_VERIFICATION)
    t.snippet("python manage.py shell", S.TASK_DB_VERIFICATION, out)
    t.save()

    # ---- Part L: tests --------------------------------------------------------------------------
    t = Transcript("06_part_l_automated_tests.txt", "Part L and Part M Task 5 - Automated tests")
    t.cmd("python manage.py check", manage("check")[0])
    test_env = dict(ENV)
    test_out, code = manage("test", "requests_app.tests", "-v", "2", env=test_env)
    t.cmd("python manage.py test requests_app.tests -v 2", test_out)
    t.save()
    print(test_out[-600:])
    DB.unlink(missing_ok=True)
    (EVID / "_server.log").unlink(missing_ok=True)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
