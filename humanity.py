"""Humanity API v2 client.

Everything goes out as form data, never JSON. Read endpoints treat a plain
HTTP 200 as success. The status==1 body check that shifts needs does not
apply here, since on a leave record "status" is the approval state.
"""

import os
import requests

BASE_URL = os.environ.get("HUMANITY_BASE_URL", "https://www.humanity.com/api/v2")
TOKEN = os.environ.get("HUMANITY_TOKEN", "")
TIMEOUT = 30


class HumanityError(Exception):
    pass


def _headers():
    if not TOKEN:
        raise HumanityError("HUMANITY_TOKEN is not set on this service.")
    return {"Authorization": "Bearer " + TOKEN}


def _params():
    # Token as a query param is the documented fallback when the header is
    # stripped by a proxy. Harmless to send both.
    return {"access_token": TOKEN}


def _normalize(payload):
    """Humanity returns data as a list, a dict keyed by id, or {"items": [...]}.

    Flatten all three into a list of dicts.
    """
    if payload is None:
        return []
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("items"), list):
            return [d for d in data["items"] if isinstance(d, dict)]
        out = []
        for key, value in data.items():
            if isinstance(value, dict):
                value.setdefault("id", key)
                out.append(value)
        return out
    return []


def get(path, params=None):
    merged = _params()
    if params:
        merged.update(params)
    resp = requests.get(BASE_URL + path, headers=_headers(), params=merged, timeout=TIMEOUT)
    if resp.status_code != 200:
        raise HumanityError("GET %s returned %s: %s" % (path, resp.status_code, resp.text[:300]))
    try:
        return _normalize(resp.json())
    except ValueError:
        raise HumanityError("GET %s returned a non JSON body." % path)


def post_form(path, form):
    """POST as x-www-form-urlencoded. Booleans go over the wire lowercased."""
    body = {}
    for key, value in form.items():
        if value is None:
            continue
        if isinstance(value, bool):
            body[key] = "true" if value else "false"
        else:
            body[key] = str(value)
    resp = requests.post(
        BASE_URL + path, headers=_headers(), params=_params(), data=body, timeout=TIMEOUT
    )
    if resp.status_code not in (200, 201):
        raise HumanityError("POST %s returned %s: %s" % (path, resp.status_code, resp.text[:300]))
    try:
        return resp.json()
    except ValueError:
        return {}


def put_form(path, form):
    body = {}
    for key, value in form.items():
        if value is None:
            continue
        if isinstance(value, bool):
            body[key] = "true" if value else "false"
        else:
            body[key] = str(value)
    resp = requests.put(
        BASE_URL + path, headers=_headers(), params=_params(), data=body, timeout=TIMEOUT
    )
    if resp.status_code not in (200, 201):
        raise HumanityError("PUT %s returned %s: %s" % (path, resp.status_code, resp.text[:300]))
    try:
        return resp.json()
    except ValueError:
        return {}


def fetch_employees():
    """Return the roster as a list of {id, name, email, employee_id}."""
    rows = get("/employees")
    out = []
    for row in rows:
        emp_id = row.get("id") or row.get("employee_id")
        if emp_id is None:
            continue
        name = row.get("name") or " ".join(
            [str(row.get("first_name") or ""), str(row.get("last_name") or "")]
        ).strip()
        out.append(
            {
                "id": str(emp_id),
                "name": name,
                "email": (row.get("email") or row.get("username") or "").strip().lower(),
                "employee_id": str(row.get("employee_id") or "").strip(),
            }
        )
    return out


LEAVE_TYPE_PATHS = [
    "/leavetypes",
    "/leaves/types",
    "/leave/types",
    "/leaves/leavetypes",
    "/company/leavetypes",
    "/settings/leavetypes",
    "/leaves/types/list",
]


def probe(path, params=None):
    """Raw call used by the diagnostics panel. Never raises, always reports."""
    result = {"path": path, "status": None, "ok": False, "error": None,
              "count": None, "sample": None, "raw": None}
    try:
        merged = _params()
        if params:
            merged.update(params)
        resp = requests.get(
            BASE_URL + path, headers=_headers(), params=merged, timeout=TIMEOUT
        )
    except Exception as exc:
        result["error"] = str(exc)
        return result

    result["status"] = resp.status_code
    body = resp.text or ""
    result["raw"] = body[:1200]
    if resp.status_code != 200:
        return result
    try:
        payload = resp.json()
    except ValueError:
        result["error"] = "Body was not JSON."
        return result

    rows = _normalize(payload)
    result["ok"] = True
    result["count"] = len(rows)
    result["sample"] = rows[:3]
    return result



LEAVE_TYPE_PATH_OVERRIDE = os.environ.get("HUMANITY_LEAVETYPE_PATH", "").strip()


def fetch_leave_types():
    """Humanity has moved this path between releases, so try the known ones.

    Set HUMANITY_LEAVETYPE_PATH to pin the one your account actually uses.
    Returns a list of {id, name}. Raises only if every path fails.
    """
    last_error = None
    paths = ([LEAVE_TYPE_PATH_OVERRIDE] if LEAVE_TYPE_PATH_OVERRIDE else []) + LEAVE_TYPE_PATHS
    for path in paths:
        try:
            rows = get(path)
        except HumanityError as exc:
            last_error = exc
            continue
        out = []
        for row in rows:
            type_id = (row.get("id") or row.get("leavetype") or row.get("leavetype_id")
                       or row.get("type_id"))
            if type_id is None:
                continue
            name = (row.get("name") or row.get("title") or row.get("leavetype_name")
                    or row.get("label") or "")
            out.append({"id": str(type_id), "name": str(name)})
        if out:
            return out
    raise HumanityError(
        "Could not read leave types from any known path. Last error: %s" % last_error
    )


def fetch_leaves(start_date, end_date):
    """Existing leaves in a date window, used to dedupe when there is no database.

    Humanity has a habit of ignoring query filters on list endpoints, so the
    window is filtered again in Python rather than trusted.
    """
    rows = get("/leaves", {"start_date": start_date, "end_date": end_date})
    out = []
    for row in rows:
        employee = row.get("employee") or row.get("employee_id") or row.get("user")
        if isinstance(employee, dict):
            employee = employee.get("id")
        leavetype = row.get("leavetype") or row.get("leave_type") or row.get("type")
        if isinstance(leavetype, dict):
            leavetype = leavetype.get("id")
        start = str(row.get("start_date") or row.get("start") or "")[:10]
        end = str(row.get("end_date") or row.get("end") or start)[:10]
        if not start:
            continue
        if end < start_date or start > end_date:
            continue
        out.append(
            {
                "id": str(row.get("id") or ""),
                "employee": str(employee or ""),
                "leavetype": str(leavetype or ""),
                "start_date": start,
                "end_date": end,
                "status": row.get("status"),
            }
        )
    return out


def create_leave(employee_id, leavetype_id, start_date, end_date, is_hourly=False,
                 start_time=None, end_time=None):
    form = {
        "employee": employee_id,
        "leavetype": leavetype_id,
        "start_date": start_date,
        "end_date": end_date,
        "is_hourly": is_hourly,
    }
    if is_hourly:
        form["start_time"] = start_time
        form["end_time"] = end_time
    payload = create_leave_response = post_form("/leaves", form)
    return _extract_leave_id(payload), create_leave_response


def update_leave(leave_id, unique_id=None, status=None, notes=None, comments=None,
                 start_date=None, end_date=None, start_time=None, end_time=None):
    form = {
        "unique_id": unique_id,
        "status": status,
        "notes": notes,
        "comments": comments,
        "start_date": start_date,
        "end_date": end_date,
        "start_time": start_time,
        "end_time": end_time,
    }
    return put_form("/leaves/" + str(leave_id), form)


def _extract_leave_id(payload):
    """Dig the new leave id out of whatever shape came back."""
    if not isinstance(payload, dict):
        return None
    for key in ("id", "leave_id"):
        if payload.get(key) is not None:
            return str(payload[key])
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("id", "leave_id"):
            if data.get(key) is not None:
                return str(data[key])
    if isinstance(data, list) and data and isinstance(data[0], dict):
        if data[0].get("id") is not None:
            return str(data[0]["id"])
    return None
