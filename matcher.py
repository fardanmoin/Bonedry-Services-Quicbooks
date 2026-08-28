"""Parse the QuickBooks Time manual export and resolve rows against Humanity."""

import csv
import difflib
import hashlib
import io
import re

# QuickBooks Time ships one header with a space in it. Normalize everything.
def _norm_header(name):
    return re.sub(r"\s+", "_", (name or "").strip().lower())


def _norm_name(value):
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z\s]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_csv(raw_bytes):
    """Return (rows, headers). Rows are dicts with normalized keys."""
    text = raw_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = [_norm_header(h) for h in (reader.fieldnames or [])]
    rows = []
    for raw in reader:
        row = {}
        for key, value in raw.items():
            if key is None:
                continue
            row[_norm_header(key)] = (value or "").strip()
        if any(row.values()):
            rows.append(row)
    return rows, headers


APPROVAL_MAP = {
    "approved": 1,
    "unapproved": 0,
    "pending": 0,
    "rejected": -1,
    "denied": -1,
}


def approval_status(row):
    """Map the QuickBooks approval state onto the Humanity leave status enum."""
    raw = (row.get("approved_status") or "").strip().lower()
    return APPROVAL_MAP.get(raw, 0), raw


def make_unique_id(employee_key, local_date, jobcode):
    """Deterministic id so re running the same file is a no op.

    Humanity types unique_id as int32, so fold a digest down into a positive
    31 bit integer rather than sending a hex string.
    """
    seed = "|".join([str(employee_key), str(local_date), str(jobcode).lower()])
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 2147483647


class EmployeeIndex:
    """Resolve a CSV row to a Humanity employee id.

    Order of attempts, best key first:
      1. payroll_id on the row matched against the Humanity employee id
      2. email on username matched against the roster email
      3. exact normalized full name
      4. close name match, only when there is exactly one candidate
    Anything else is an exception the human has to look at. Never guess.
    """

    def __init__(self, roster, overrides=None):
        self.roster = roster
        self.overrides = overrides or {}
        self.by_id = {}
        self.by_email = {}
        self.by_name = {}
        for person in roster:
            self.by_id[str(person["id"])] = person
            if person.get("employee_id"):
                self.by_id.setdefault(person["employee_id"], person)
            if person.get("email"):
                self.by_email.setdefault(person["email"], person)
            key = _norm_name(person.get("name"))
            if key:
                self.by_name.setdefault(key, []).append(person)

    def resolve(self, row):
        """Return (person_or_None, method, note)."""
        email = (row.get("username") or "").strip().lower()
        full_name = _norm_name(
            " ".join([row.get("fname") or "", row.get("lname") or ""])
        )

        override_key = email or full_name
        if override_key and override_key in self.overrides:
            person = self.by_id.get(str(self.overrides[override_key]))
            if person:
                return person, "override", "Pinned by a saved mapping."

        payroll_id = (row.get("payroll_id") or "").strip()
        if payroll_id and payroll_id in self.by_id:
            return self.by_id[payroll_id], "payroll_id", "Matched on payroll_id."

        if email and email in self.by_email:
            return self.by_email[email], "email", "Matched on email."

        if full_name and full_name in self.by_name:
            candidates = self.by_name[full_name]
            if len(candidates) == 1:
                return candidates[0], "name_exact", "Matched on full name."
            return None, "ambiguous", (
                "%d people in Humanity share this name. Pick one and save a mapping."
                % len(candidates)
            )

        if full_name:
            close = difflib.get_close_matches(full_name, list(self.by_name.keys()), n=3, cutoff=0.88)
            if len(close) == 1 and len(self.by_name[close[0]]) == 1:
                person = self.by_name[close[0]][0]
                return person, "name_fuzzy", (
                    "Close name match against %s. Confirm before you rely on it." % person["name"]
                )
            if len(close) > 1:
                return None, "ambiguous", (
                    "Several similar names in Humanity: %s. Save a mapping to settle it."
                    % ", ".join(close)
                )

        return None, "unmatched", "No employee in Humanity matches this row."


def hours_to_float(value):
    try:
        return float(str(value).strip() or 0)
    except ValueError:
        return 0.0


def classify(row, index, leave_type_map, full_day_hours=8.0):
    """Turn one CSV row into a decision. No writes happen here."""
    result = {
        "username": row.get("username", ""),
        "name": " ".join([row.get("fname") or "", row.get("lname") or ""]).strip(),
        "local_date": row.get("local_date", ""),
        "jobcode": row.get("jobcode", ""),
        "hours": row.get("hours", ""),
        "approved_status": row.get("approved_status", ""),
        "action": "skip",
        "reason": "",
        "employee_id": None,
        "match_method": None,
        "leavetype_id": None,
        "status": 0,
        "is_hourly": False,
        "start_time": None,
        "end_time": None,
        "unique_id": None,
        "warnings": [],
    }

    jobcode = (row.get("jobcode") or "").strip()
    if not jobcode:
        result["reason"] = "No jobcode on this row."
        return result

    leavetype_id = leave_type_map.get(jobcode.lower())
    if not leavetype_id:
        result["reason"] = (
            "Jobcode %s has no leave type mapping. Map it before importing, "
            "since a default would drain the wrong balance." % jobcode
        )
        return result
    result["leavetype_id"] = leavetype_id

    if not row.get("local_date"):
        result["reason"] = "No local_date on this row."
        return result

    person, method, note = index.resolve(row)
    result["match_method"] = method
    if person is None:
        result["reason"] = note
        return result
    result["employee_id"] = person["id"]
    result["matched_name"] = person["name"]
    if method in ("name_fuzzy", "name_exact"):
        result["warnings"].append(note)

    status, raw_status = approval_status(row)
    result["status"] = status
    if raw_status not in APPROVAL_MAP:
        result["warnings"].append(
            "Unknown approval value %s, treating it as pending." % (raw_status or "blank")
        )

    start_time = (row.get("local_start_time") or "").strip()
    end_time = (row.get("local_end_time") or "").strip()
    hours = hours_to_float(row.get("hours"))

    if start_time and end_time:
        result["is_hourly"] = True
        result["start_time"] = start_time
        result["end_time"] = end_time
    elif hours and hours < full_day_hours:
        result["warnings"].append(
            "%.2f hours with no start or end time, so this posts as a full day. "
            "The partial day cannot be reconstructed from this export." % hours
        )

    result["unique_id"] = make_unique_id(person["id"], row["local_date"], jobcode)
    result["action"] = "create"
    result["reason"] = "Ready to post."
    return result
