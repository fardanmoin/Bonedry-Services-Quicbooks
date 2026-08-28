# LeaveSync

Takes the QuickBooks Time Manual Time Export and posts leave requests into
Humanity. Preview first, post second. Nothing writes until you press the
button.

## Deploy on Render

1. Push this folder to a repo.
2. New Web Service, or point Render at `render.yaml`.
3. Build: `pip install -r requirements.txt`
4. Start: `gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 1`
5. Env vars:
   - `HUMANITY_TOKEN` your Humanity API token
   - `DATABASE_URL` your Neon connection string
   - `HUMANITY_BASE_URL` optional, defaults to the v2 base

Python is pinned to 3.12.3 via `.python-version`. The free tier wipes the
disk on every deploy, so all state lives in Neon. Uploaded files are read
in memory for the duration of the request and never written to disk.

Tables are created on boot. Nothing to run by hand.

## How a row is decided

1. **Jobcode to leave type.** `Sick` and `Vacation` map by name against the
   Humanity leave type list. Anything unmatched is parked as an exception.
   A jobcode is never defaulted, since a default drains the wrong balance.
2. **Employee.** Tried in this order: `payroll_id`, then email on
   `username`, then exact full name, then a close name match at 0.88
   similarity but only when exactly one candidate comes back. Two people
   with the same name is an exception, not a coin flip.
3. **Approval.** `approved` becomes status 1, `unapproved` becomes status 0
   which is pending in Humanity. Managers approve inside Humanity, which is
   where the decision belongs.
4. **Duration.** Blank `local_start_time` and `local_end_time` means
   `is_hourly=false` and a full day. A partial day with no times is flagged
   loudly and still posts as a full day, since the window cannot be
   reconstructed from this export.
5. **unique_id.** A stable 31 bit integer derived from employee id, date and
   jobcode, so re running the same file changes nothing.

## Why there are two writes per leave

The create form has no `unique_id` field and every new leave lands as
pending. So the app creates the leave, then immediately writes back with
`unique_id` and the real approval status. If the follow up write fails the
row is flagged, since the leave exists in Humanity but is not yet keyed for
reconcile.

## Endpoints

| Method | Path | Does |
|---|---|---|
| POST | `/api/preview` | Dry run. Never writes. |
| POST | `/api/import` | Streams NDJSON, one line per row. |
| POST | `/api/map-employee` | Pins a username or name to a Humanity id. |
| POST | `/api/map-leavetype` | Pins a jobcode to a leave type id. |
| GET | `/api/roster` | Humanity employees, `?refresh=1` to bust the cache. |
| GET | `/api/history` | Recent synced rows. |
| GET | `/api/health` | Token and database status. |

## Verify before you trust it

`fetch_leave_types` tries three known paths because Humanity has moved that
endpoint between releases. Hit `/api/preview` once against a real token and
confirm the leave type list comes back. If it does not, get the correct path
from the account and set it in `humanity.py`.
