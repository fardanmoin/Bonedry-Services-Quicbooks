"""LeaveSync: QuickBooks Time leave export into Humanity.

Two endpoints do the work. /api/preview never writes anything, so you can
drop any customer file in and see exactly what would post. /api/import
streams NDJSON per row, which keeps a long file from hitting the 100 second
Render request timeout.
"""

import json
import os
import traceback

from flask import Flask, Response, jsonify, request, send_from_directory

import db
import humanity
import matcher

app = Flask(__name__, static_folder="static", static_url_path="")

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "10"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

_roster_cache = {"data": None}


def get_roster(refresh=False):
    if refresh or _roster_cache["data"] is None:
        _roster_cache["data"] = humanity.fetch_employees()
    return _roster_cache["data"]


def env_leavetype_map():
    """Pinned jobcode to leave type ids from HUMANITY_LEAVETYPE_MAP.

    Format: sick=542074,vacation=542073
    Set it once in Render and the picker never appears again.
    """
    raw = os.environ.get("HUMANITY_LEAVETYPE_MAP", "").strip()
    if not raw:
        return {}
    out = {}
    for pair in raw.split(","):
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key and value:
            out[key] = value
    return out


def build_leavetype_map():
    """jobcode lowercased to Humanity leavetype id.

    Saved mappings win. Anything unmapped falls back to a case insensitive
    name match against the Humanity leave type list, which covers the common
    case where the jobcode is literally called Sick or Vacation.
    """
    saved = db.load_leavetype_map()
    try:
        types = humanity.fetch_leave_types()
    except humanity.HumanityError:
        types = []
    by_name = {t["name"].strip().lower(): t["id"] for t in types if t.get("name")}
    merged = dict(by_name)
    merged.update(saved)
    # Pinned values win over anything derived, since a derived name can be
    # ambiguous when two ids share it.
    merged.update(env_leavetype_map())
    return merged, types


def read_upload():
    upload = request.files.get("file")
    if upload is None:
        raise ValueError("No file was attached to the request.")
    raw = upload.read()
    if not raw:
        raise ValueError("That file is empty.")
    return raw


def parse_overrides():
    """Jobcode to leave type picks sent from the browser for this request."""
    raw = request.form.get("leavetype_overrides", "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return {str(k).strip().lower(): str(v) for k, v in data.items() if v}


def analyze(raw, leavetype_overrides=None):
    rows, headers = matcher.parse_csv(raw)
    roster = get_roster()
    employee_overrides = db.load_employee_overrides()
    index = matcher.EmployeeIndex(roster, employee_overrides)
    leavetype_map, leave_types = build_leavetype_map()
    if leavetype_overrides:
        leavetype_map.update(leavetype_overrides)

    items = [matcher.classify(row, index, leavetype_map) for row in rows]

    if db.available():
        _dedupe_from_db(items)
    else:
        _dedupe_from_humanity(items)
    return items, headers, leave_types


def _dedupe_from_db(items):
    unique_ids = [i["unique_id"] for i in items if i["unique_id"]]
    already = db.get_synced(unique_ids)
    for item in items:
        prior = already.get(item["unique_id"])
        if not prior:
            continue
        item["leave_id"] = prior.get("leave_id")
        if int(prior.get("status", 0)) != int(item["status"]):
            item["action"] = "update"
            item["reason"] = "Already in Humanity. Approval state changed, so this updates it."
        else:
            item["action"] = "unchanged"
            item["reason"] = "Already synced with the same approval state."


def _dedupe_from_humanity(items):
    """No database, so ask Humanity what leave already exists in this window.

    One call covers the whole file. If the lookup fails the rows are flagged
    rather than posted, since posting blind is how duplicates happen.
    """
    dates = sorted([i["local_date"] for i in items if i.get("local_date")])
    if not dates:
        return
    try:
        existing = humanity.fetch_leaves(dates[0], dates[-1])
    except humanity.HumanityError as exc:
        for item in items:
            if item["action"] == "create":
                item["action"] = "skip"
                item["reason"] = (
                    "Could not read existing leaves to check for duplicates, so nothing "
                    "posts. Add a database or fix the lookup first. Error: %s" % exc
                )
        return

    seen = {}
    for leave in existing:
        cursor = leave["start_date"]
        end = leave["end_date"] or leave["start_date"]
        # Expand multi day leaves so a single day row matches inside one.
        guard = 0
        while cursor <= end and guard < 400:
            seen[(leave["employee"], leave["leavetype"], cursor)] = leave
            cursor = _next_day(cursor)
            guard += 1

    for item in items:
        if item["action"] != "create":
            continue
        key = (str(item["employee_id"]), str(item["leavetype_id"]), item["local_date"])
        match = seen.get(key)
        if not match:
            continue
        item["leave_id"] = match["id"]
        item["action"] = "unchanged"
        item["reason"] = "Humanity already has this leave for this person and date."


def _next_day(date_string):
    from datetime import date, timedelta

    try:
        year, month, day = [int(p) for p in date_string.split("-")]
        return str(date(year, month, day) + timedelta(days=1))
    except Exception:
        return "9999-12-31"


@app.get("/")
def index_page():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    return jsonify(
        {
            "ok": True,
            "database": db.available(),
            "humanity_token": bool(humanity.TOKEN),
        }
    )


@app.get("/api/roster")
def roster():
    try:
        people = get_roster(refresh=request.args.get("refresh") == "1")
        return jsonify({"ok": True, "employees": people})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/preview")
def preview():
    """Dry run. Reads the file, resolves everything, writes nothing."""
    try:
        raw = read_upload()
        items, headers, leave_types = analyze(raw, parse_overrides())
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 502

    counts = {}
    unmapped = []
    for item in items:
        counts[item["action"]] = counts.get(item["action"], 0) + 1
        if item["action"] == "skip" and item["leavetype_id"] is None and item["jobcode"]:
            if item["jobcode"] not in unmapped:
                unmapped.append(item["jobcode"])
    return jsonify(
        {
            "ok": True,
            "headers": headers,
            "items": items,
            "counts": counts,
            "leave_types": leave_types,
            "unmapped_jobcodes": unmapped,
        }
    )


@app.post("/api/import")
def do_import():
    """Stream one NDJSON line per row as it posts."""
    try:
        raw = read_upload()
        include_pending = request.form.get("include_pending", "1") == "1"
        items, _, _ = analyze(raw, parse_overrides())
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 502

    def stream():
        posted = 0
        updated = 0
        skipped = 0
        failed = 0
        yield json.dumps({"event": "start", "total": len(items)}) + "\n"

        for item in items:
            line = dict(item)
            if item["action"] in ("skip", "unchanged"):
                skipped += 1
                line["result"] = item["action"]
                yield json.dumps({"event": "row", "row": line}) + "\n"
                continue

            if not include_pending and int(item["status"]) != 1:
                skipped += 1
                line["result"] = "skip"
                line["reason"] = "Pending rows are turned off for this run."
                yield json.dumps({"event": "row", "row": line}) + "\n"
                continue

            try:
                if item["action"] == "update" and item.get("leave_id"):
                    humanity.update_leave(
                        item["leave_id"],
                        unique_id=item["unique_id"],
                        status=item["status"],
                    )
                    db.record_sync(item, item["leave_id"])
                    updated += 1
                    line["result"] = "updated"
                else:
                    leave_id, _ = humanity.create_leave(
                        item["employee_id"],
                        item["leavetype_id"],
                        item["local_date"],
                        item["local_date"],
                        is_hourly=item["is_hourly"],
                        start_time=item["start_time"],
                        end_time=item["end_time"],
                    )
                    # The create form has no unique_id field, so stamp it on
                    # with a follow up write. That is also where the approval
                    # state gets set, since create always lands as pending.
                    if leave_id:
                        try:
                            humanity.update_leave(
                                leave_id,
                                unique_id=item["unique_id"],
                                status=item["status"],
                            )
                        except humanity.HumanityError as exc:
                            line.setdefault("warnings", []).append(
                                "Leave created but the follow up write failed: %s" % exc
                            )
                    db.record_sync(item, leave_id)
                    posted += 1
                    line["result"] = "created"
                    line["leave_id"] = leave_id
            except Exception as exc:
                failed += 1
                line["result"] = "failed"
                line["reason"] = str(exc)

            yield json.dumps({"event": "row", "row": line}) + "\n"

        yield json.dumps(
            {
                "event": "done",
                "posted": posted,
                "updated": updated,
                "skipped": skipped,
                "failed": failed,
            }
        ) + "\n"

    return Response(stream(), mimetype="application/x-ndjson")


@app.post("/api/map-employee")
def map_employee():
    payload = request.get_json(silent=True) or {}
    source_key = (payload.get("source_key") or "").strip()
    employee_id = (payload.get("employee_id") or "").strip()
    if not source_key or not employee_id:
        return jsonify({"ok": False, "error": "Both source_key and employee_id are required."}), 400
    try:
        db.save_employee_mapping(source_key, employee_id, payload.get("label"))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True})


@app.post("/api/map-leavetype")
def map_leavetype():
    payload = request.get_json(silent=True) or {}
    jobcode = (payload.get("jobcode") or "").strip()
    leavetype_id = (payload.get("leavetype_id") or "").strip()
    if not jobcode or not leavetype_id:
        return jsonify({"ok": False, "error": "Both jobcode and leavetype_id are required."}), 400
    try:
        db.save_leavetype_mapping(jobcode, leavetype_id, payload.get("label"))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502
    return jsonify({"ok": True})


@app.get("/api/debug/leavetypes")
def debug_leavetypes():
    """Probe every candidate path and report what each one actually returns."""
    results = [humanity.probe(p) for p in humanity.LEAVE_TYPE_PATHS]
    winner = None
    for r in results:
        if r["ok"] and r["count"]:
            winner = r["path"]
            break

    explore = []
    derived = []
    if not winner:
        wide = {"start_date": "2015-01-01", "end_date": "2035-12-31"}
        explore = [
            humanity.probe(p, wide if p in ("/leaves", "/leave", "/timeoff") else None)
            for p in humanity.EXPLORE_PATHS
        ]
        try:
            derived = humanity.derive_leave_types_from_leaves()
        except Exception:
            derived = []

    return jsonify(
        {
            "ok": True,
            "results": results,
            "winner": winner,
            "explore": explore,
            "derived": derived,
        }
    )


@app.get("/api/debug/leaves-params")
def debug_leaves_params():
    """Find which parameters make /leaves return pending records.

    /leaves appears to return approved records only by default, which breaks
    duplicate detection for anything still awaiting approval.
    """
    wide = {"start_date": "2015-01-01", "end_date": "2035-12-31"}
    variants = [
        ("baseline", dict(wide)),
        ("status=0", dict(wide, status="0")),
        ("status=all", dict(wide, status="all")),
        ("status=0,1", dict(wide, status="0,1")),
        ("statuses=0", dict(wide, statuses="0")),
        ("filter=pending", dict(wide, filter="pending")),
        ("include_pending=1", dict(wide, include_pending="1")),
        ("show_pending=1", dict(wide, show_pending="1")),
        ("approved=0", dict(wide, approved="0")),
        ("pending=1", dict(wide, pending="1")),
        ("mode=all", dict(wide, mode="all")),
        ("limit=200", dict(wide, limit="200")),
    ]

    results = []
    for label, params in variants:
        probe = humanity.probe("/leaves", params)
        summary = {
            "variant": label,
            "status": probe["status"],
            "count": probe["count"],
            "error": probe["error"],
            "ids": [],
            "statuses": [],
        }
        for row in (probe.get("sample") or []):
            summary["ids"].append(str(row.get("id")))
            summary["statuses"].append(str(row.get("status")))
        results.append(summary)

    return jsonify({"ok": True, "results": results})


@app.get("/api/debug/dedupe")
def debug_dedupe():
    """Show exactly what the duplicate check sees for a date window.

    Raw record count, what survives parsing, and the keys the check compares
    against. If a leave exists in Humanity but does not show here, the parse
    is dropping it.
    """
    start = request.args.get("start", "2026-08-25")
    end = request.args.get("end", "2026-08-30")

    try:
        raw = humanity._fetch_leaves_raw()
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502

    parsed = humanity.fetch_leaves(start, end)

    # Anything in the raw set that mentions this window, before filtering
    near = []
    for row in raw:
        start_ts = str(row.get("start_timestamp") or "")[:10]
        end_ts = str(row.get("end_timestamp") or "")[:10]
        if start_ts >= start and start_ts <= end:
            near.append(
                {
                    "id": row.get("id"),
                    "employee": row.get("employee"),
                    "employee_name": row.get("employee_name"),
                    "leave_type": row.get("leave_type"),
                    "leave_type_name": row.get("leave_type_name"),
                    "start_timestamp": row.get("start_timestamp"),
                    "end_timestamp": row.get("end_timestamp"),
                    "status": row.get("status"),
                    "deleted_at": row.get("deleted_at"),
                    "unique_id": row.get("unique_id"),
                }
            )

    keys = []
    for leave in parsed:
        cursor = leave["start_date"]
        stop = leave["end_date"] or leave["start_date"]
        guard = 0
        while cursor <= stop and guard < 400:
            keys.append("%s|%s|%s" % (leave["employee"], leave["leavetype"], cursor))
            cursor = _next_day(cursor)
            guard += 1

    return jsonify(
        {
            "ok": True,
            "window": {"start": start, "end": end},
            "raw_total": len(raw),
            "raw_in_window": near,
            "parsed_in_window": parsed,
            "dedupe_keys": sorted(set(keys)),
        }
    )


@app.get("/api/debug/probe")
def debug_probe():
    """Hit any path you like, so you can see the raw shape yourself."""
    path = request.args.get("path", "").strip()
    if not path.startswith("/"):
        return jsonify({"ok": False, "error": "Path must start with a slash."}), 400
    return jsonify({"ok": True, "result": humanity.probe(path)})


@app.post("/api/debug/payload")
def debug_payload():
    """Show the exact form data that would be posted for each row. Writes nothing."""
    try:
        raw = read_upload()
        items, _, _ = analyze(raw, parse_overrides())
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502

    out = []
    for item in items:
        if item["action"] not in ("create", "update"):
            out.append({"row": item["name"], "date": item["local_date"], "would_send": None,
                        "reason": item["reason"]})
            continue
        create_form = {
            "employee": item["employee_id"],
            "leavetype": item["leavetype_id"],
            "start_date": item["local_date"],
            "end_date": item["local_date"],
            "is_hourly": "true" if item["is_hourly"] else "false",
        }
        if item["is_hourly"]:
            create_form["start_time"] = item["start_time"]
            create_form["end_time"] = item["end_time"]
        out.append(
            {
                "row": item["name"],
                "date": item["local_date"],
                "method": "POST /leaves (form data)",
                "would_send": create_form,
                "then": {
                    "method": "PUT /leaves/{new_id} (form data)",
                    "body": {"unique_id": item["unique_id"], "status": item["status"]},
                },
            }
        )
    return jsonify({"ok": True, "payloads": out})


@app.get("/api/history")
def history():
    try:
        return jsonify({"ok": True, "rows": db.recent()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


if __name__ == "__main__":
    try:
        db.init()
    except Exception:
        traceback.print_exc()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
else:
    try:
        db.init()
    except Exception:
        traceback.print_exc()
