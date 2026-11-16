# VUA-SEN305 Service Platform - Lab Session 4

Secure, server-rendered request workflow for the Enterprise Service Request and Maintenance
Platform: ModelForms, selectors, transaction-safe services, authenticated CRUD pages, staff
assignment and technician resolution.

## Run it

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt      # mysqlclient needs the MySQL client libraries
cd backend
cp .env.example .env                 # then edit: DB_ENGINE=mysql and your own credentials
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver           # 127.0.0.1 only
python manage.py test requests_app.tests -v 2
```

Leave `DB_ENGINE` unset to fall back to SQLite for a quick local run.

## Layers (the separation the lab asks you to explain)

| Layer | File | Responsibility |
| --- | --- | --- |
| Forms | `requests_app/forms.py` | Validate input; expose only safe, user-editable fields |
| Selectors | `requests_app/selectors.py` | All reads; enforce row-level visibility (requesters see own rows, staff see all) |
| Services | `requests_app/services.py` | Business rules and multi-model writes inside one `transaction.atomic`; `select_for_update` on the rows being changed |
| Views | `requests_app/views.py` | Parse HTTP, call selector/service, choose a response (render or redirect) |

## Adding Lab 4 to an existing Lab 3 project

`requests_app/models.py` and its migration here are a **reconstruction of the Lab 3 starting point**
(field names from Step A2 of the practical note) so this repository runs on its own. In your own
project keep your Lab 3 models and copy only the Lab 4 files:

- `requests_app/forms.py`, `selectors.py`, `services.py`, `views.py`, `urls.py`, `tests/`, `templates/requests_app/`
- `templates/registration/login.html`, `templates/403.html`, `templates/404.html`
- `config/urls.py` (the `accounts/` and `requests/` includes), the three `LOGIN_*` settings
- the messages/auth blocks in `core/templates/core/base.html` and the appended CSS in `core/static/core/css/site.css`

If your model names differ from the Step A2 list, adapt the code consistently.

## Changes beyond the practical note's code

The note's code is followed closely. Gaps found while building it and closed:

- **Internal comments** (`is_internal`) are hidden from requesters, and excluded from the comment count they see.
- **Edit link** is shown only to someone the server would let edit (owner while open, or staff).
- **`service_request_assign`** also rejects a technician who is not active staff (the form already limits the choices).
- **`service_request_resolve`** checks permission before revealing assignment state, refuses to resolve an already-completed request, and rejects blank work notes.
- **Assign/resolve views** check the role before loading the object, so every unauthorised caller gets the same 403.
- Custom `403.html` / `404.html` pages that name no owner or title.

## Evidence

`evidence/` holds the transcripts and screenshots for the submission package, produced by
`python evidence/run_evidence.py` (it runs the lab steps on a throw-away database).
