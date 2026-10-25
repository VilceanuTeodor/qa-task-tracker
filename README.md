# Task Tracker

A basic Jira-like task tracker built with FastAPI and SQLite, made for practicing QA.

- Sign up / sign in; every page and API call requires an account
- Create, view, edit and delete tasks (title, description, status, creator, assignee)
- Comment section on every task
- Change history per task, starting with "Ticket created on ..."
- Admin role: an Admin page (task stats, user management) and the right to delete tasks
- Web UI plus a JSON API, with interactive Swagger docs at `/docs`

## Run locally

Requires Python 3.10+.

```powershell
python -m venv .venv
.\.venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Then open http://127.0.0.1:8000. Data is stored in `tracker.db` (set `TRACKER_DB` to use a different file).

### Admin account

On first start the app creates an `admin` account with a random password and prints it in the terminal once.
To choose (or reset) the password, set `ADMIN_PASSWORD` before starting:

```powershell
$env:ADMIN_PASSWORD = "your-password-here"   # macOS/Linux: export ADMIN_PASSWORD=...
python run.py
```

Accounts created through Sign up are regular users. An admin can promote them on the Admin page.

| | User | Admin |
|---|---|---|
| View, create, edit tasks; comment | ✓ | ✓ |
| Delete tasks | | ✓ |
| Admin page (stats, users, roles, delete users) | | ✓ |

## API

Every endpoint except signup/login needs `Authorization: Bearer <token>`.
Get a token from `POST /api/auth/login`; in Swagger (`/docs`) paste it into the **Authorize** button.

| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/signup` | Create an account `{username, password}` |
| POST | `/api/auth/login` | Get a token `{username, password}` |
| POST | `/api/auth/logout` | Invalidate the current token |
| GET | `/api/auth/me` | The signed-in user |
| GET | `/api/users` | List usernames (for picking assignees) |
| GET | `/api/tasks?status=&assignee=` | List tasks (optional filters) |
| POST | `/api/tasks` | Create a task (creator = you) |
| GET | `/api/tasks/{id}` | Get a task with its comments and history |
| PATCH | `/api/tasks/{id}` | Update any of title, description, status, assignee |
| DELETE | `/api/tasks/{id}` | Delete a task (admin) |
| GET | `/api/tasks/{id}/comments` | List comments |
| POST | `/api/tasks/{id}/comments` | Add a comment `{body}` |
| GET | `/api/tasks/{id}/history` | Get the change history |
| GET | `/api/admin/users` | All users with roles (admin) |
| PATCH | `/api/admin/users/{id}` | Change a user's role `{role}` (admin) |
| DELETE | `/api/admin/users/{id}` | Delete a user (admin) |
| GET | `/api/admin/stats` | Task and user counts (admin) |

Statuses: `To Do`, `In Progress`, `In Review`, `Done`.

## Automated tests

API tests (`tests/api/`) use pytest + requests; UI tests (`tests/ui/`) use Playwright to drive a real Chromium browser.
Each run starts its own copy of the app with an empty temporary database, so your `tracker.db` is never touched.

```powershell
pip install -r requirements-dev.txt
python -m playwright install chromium

python -m pytest                    # everything, browser hidden (headless)
python -m pytest tests/api          # API tests only
python -m pytest tests/ui --headed  # watch the browser, with a short pause after each step
python -m pytest -k comment         # only tests with "comment" in their name
```

## API collection (Postman)

The `postman/` folder has a ready-made collection of 50 requests with test assertions, covering every
endpoint plus error and permission cases.

1. In Postman, **Import** both files from `postman/`.
2. Select the **Task Tracker - local** environment (top right) and set `adminPassword` to your admin password.
3. With the app running, send the requests top to bottom, or run the whole collection with **Run collection**.

The folders build on each other: sign up, then log in, then create a task, and so on. The scripts save tokens and ids
into variables automatically, and each run creates its own test user and deletes it at the end.

From the command line, with [Newman](https://www.npmjs.com/package/newman):

```
npx newman run postman/task-tracker.postman_collection.json -e postman/local.postman_environment.json --env-var adminPassword=YOUR_ADMIN_PASSWORD
```
