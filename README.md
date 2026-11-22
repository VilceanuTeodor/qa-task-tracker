# Task Tracker

A basic Jira-like task tracker built with FastAPI and SQLite, made for practicing QA.

- Sign up / sign in; every page and API call requires an account
- Create, view, edit and delete tasks (title, description, status, creator, assignee)
- Comment section on every task
- Change history per task, starting with "Ticket created on ..."
- Admin role: an Admin page (task stats, user management) and the right to delete tasks
- Web UI plus a JSON API, with interactive Swagger docs at `/docs`

## Run with Docker

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine with the Compose plugin).

```powershell
docker compose up --build
```

Then open http://127.0.0.1:8000. On the very first start the admin password is printed in the output
(find it again later with `docker compose logs app`). To choose it yourself, create a `.env` file next to
`compose.yaml` (it's git-ignored):

```
ADMIN_PASSWORD=your-password-here
```

The app runs in one container (`app`). Its SQLite database is stored in a Docker volume (`tracker-data`, mounted
at `/data/tracker.db`), so your data survives restarts and rebuilds. It is separate from the `tracker.db` file
used when you run the app without Docker.

| Command | What it does |
|---|---|
| `docker compose up --build` | Build the image and start the app (add `-d` to run it in the background) |
| `docker compose logs -f app` | Follow the app's logs |
| `docker compose ps` | Show whether the container is running and healthy |
| `docker compose down` | Stop and remove the container (data is kept) |
| `docker compose down -v` | Stop and **delete the database** too (fresh start) |
| `docker compose cp app:/data/tracker.db ./tracker-docker.db` | Copy the database out, e.g. to open it in DBeaver |
| `docker compose cp ./tracker.db app:/data/tracker.db` | Replace the container's database with your local one (then `docker compose restart app`) |

Code changes are not picked up live: run `docker compose up --build` again after editing.

## Run locally (without Docker)

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
