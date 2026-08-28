/* LeaveSync frontend. Vanilla React.createElement, no JSX, no build step. */
var e = React.createElement;
var useState = React.useState;
var useEffect = React.useEffect;
var useRef = React.useRef;

function Masthead(props) {
  var h = props.health || {};
  return e("div", { className: "masthead" },
    e("h1", null, "LeaveSync"),
    e("p", null,
      "QuickBooks Time leave export ",
      e("span", { className: "pipe" }, "\u2192"),
      " Humanity. Preview first, then post. Nothing writes until you say so."
    ),
    e("div", { className: "statusbar" },
      e("span", null,
        e("span", { className: "dot " + (h.humanity_token ? "on" : "off") }),
        h.humanity_token ? "Humanity token loaded" : "Humanity token missing"
      ),
      e("span", null,
        e("span", { className: "dot " + (h.database ? "on" : "warn") }),
        h.database ? "Database connected" : "No database, duplicates checked against Humanity"
      )
    )
  );
}

function Dropzone(props) {
  var over = useState(false);
  var isOver = over[0], setOver = over[1];
  var inputRef = useRef(null);

  function pick(file) {
    if (file) props.onFile(file);
  }

  return e("div", null,
    e("div", {
      className: "drop" + (isOver ? " over" : ""),
      tabIndex: 0,
      role: "button",
      onClick: function () { inputRef.current.click(); },
      onKeyDown: function (ev) {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); inputRef.current.click(); }
      },
      onDragOver: function (ev) { ev.preventDefault(); setOver(true); },
      onDragLeave: function () { setOver(false); },
      onDrop: function (ev) {
        ev.preventDefault();
        setOver(false);
        pick(ev.dataTransfer.files && ev.dataTransfer.files[0]);
      }
    },
      e("strong", null, props.fileName || "Drop the QuickBooks Time export here"),
      e("span", null, props.fileName
        ? "Click to choose a different file"
        : "Manual Time Export, CSV, one row per leave entry")
    ),
    e("input", {
      ref: inputRef,
      type: "file",
      accept: ".csv,text/csv",
      style: { display: "none" },
      onChange: function (ev) { pick(ev.target.files && ev.target.files[0]); }
    })
  );
}

function Tally(props) {
  var c = props.counts || {};
  var cells = [
    ["create", "to post"],
    ["update", "to update"],
    ["unchanged", "already synced"],
    ["skip", "needs a fix"],
    ["failed", "failed"]
  ];
  var shown = cells.filter(function (pair) { return c[pair[0]]; });
  if (!shown.length) return null;
  return e("div", { className: "tally" },
    shown.map(function (pair) {
      return e("div", { key: pair[0] },
        e("b", null, c[pair[0]]),
        e("small", null, pair[1])
      );
    })
  );
}

function Row(props) {
  var item = props.item;
  var kind = item.result || item.action;
  var fixable = item.action === "skip" && !item.employee_id && item.match_method !== null;

  var assign = useState("");
  var chosen = assign[0], setChosen = assign[1];

  return e("div", { className: "rowitem " + kind },
    e("div", { className: "rowhead" },
      e("span", { className: "who" }, item.name || item.username || "Unnamed row"),
      e("span", { className: "tag " + kind }, kind)
    ),
    e("div", { className: "meta" },
      item.local_date, "  \u00b7  ", item.jobcode || "no jobcode",
      "  \u00b7  ", item.hours, "h",
      "  \u00b7  ", item.approved_status || "no status",
      item.match_method ? "  \u00b7  matched by " + item.match_method : "",
      item.leave_id ? "  \u00b7  leave " + item.leave_id : ""
    ),
    item.reason ? e("div", { className: "reason" }, item.reason) : null,
    (item.warnings || []).map(function (w, i) {
      return e("div", { className: "warn", key: i }, "\u26a0  " + w);
    }),
    fixable ? e("div", { className: "fixrow" },
      e("select", {
        value: chosen,
        onChange: function (ev) { setChosen(ev.target.value); }
      },
        e("option", { value: "" }, "Pick the right person in Humanity"),
        (props.roster || []).map(function (p) {
          return e("option", { key: p.id, value: p.id }, p.name + " (" + p.id + ")");
        })
      ),
      e("button", {
        disabled: !chosen,
        onClick: function () { props.onMap(item, chosen); }
      }, "Save mapping")
    ) : null
  );
}


function Diagnostics(props) {
  var d = props.diag;
  return e("div", { className: "panel" },
    e("h2", null, "3. What Humanity is telling us"),
    e("div", { className: "actions", style: { marginTop: 0, marginBottom: "14px" } },
      e("button", { onClick: props.onRun, disabled: props.busy },
        props.busy ? "Checking" : "Check leave type endpoints"),
      e("button", { onClick: props.onPayloads, disabled: !props.hasFile },
        "Show what we would send"),
      e("button", { onClick: props.onDedupe, disabled: props.dedupeBusy },
        props.dedupeBusy ? "Checking" : "Inspect duplicate check")
    ),
    d ? e("div", { className: "ledger" },
      (d.results || []).map(function (r, i) {
        var kind = r.ok && r.count ? "create" : (r.status === 200 ? "skip" : "failed");
        return e("div", { className: "rowitem " + kind, key: i },
          e("div", { className: "rowhead" },
            e("span", { className: "who" }, "GET " + r.path),
            e("span", { className: "tag " + kind },
              r.status === null ? "no response" : String(r.status))
          ),
          e("div", { className: "meta" },
            r.ok ? (r.count + " records parsed") : (r.error || "nothing usable")
          ),
          r.sample && r.sample.length
            ? e("pre", { className: "raw" }, JSON.stringify(r.sample, null, 1))
            : (r.raw ? e("pre", { className: "raw" }, r.raw) : null)
        );
      })
    ) : e("div", { className: "empty" },
        "Run the check to see which path your account answers on."),
    d && d.derived && d.derived.length
      ? e("div", { style: { marginTop: "16px" } },
          e("h2", null, "Leave types found in existing leave records"),
          e("pre", { className: "raw" }, JSON.stringify(d.derived, null, 1))
        )
      : null,
    d && d.explore && d.explore.length
      ? e("div", { style: { marginTop: "16px" } },
          e("h2", null, "What else this account answers on"),
          e("div", { className: "ledger" },
            d.explore.map(function (r, i) {
              var kind = r.ok ? "create" : "failed";
              return e("div", { className: "rowitem " + kind, key: "x" + i },
                e("div", { className: "rowhead" },
                  e("span", { className: "who" }, "GET " + r.path),
                  e("span", { className: "tag " + kind },
                    r.status === null ? "no response" : String(r.status))
                ),
                r.sample && r.sample.length
                  ? e("pre", { className: "raw" }, JSON.stringify(r.sample, null, 1))
                  : (r.raw ? e("pre", { className: "raw" }, r.raw) : null)
              );
            })
          )
        )
      : null,
    d && d.winner
      ? e("div", { className: "warn", style: { marginTop: "12px" } },
          "\u2713 " + d.winner + " works. Set HUMANITY_LEAVETYPE_PATH to " + d.winner +
          " in Render to pin it.")
      : null,
    props.dedupe
      ? e("div", { style: { marginTop: "18px" } },
          e("h2", null, "What the duplicate check sees"),
          e("pre", { className: "raw" }, JSON.stringify(props.dedupe, null, 1))
        )
      : null,
    props.payloads
      ? e("div", { style: { marginTop: "18px" } },
          e("h2", null, "Exact form data we would post"),
          e("pre", { className: "raw" }, JSON.stringify(props.payloads, null, 1))
        )
      : null
  );
}


function JobcodeMapper(props) {
  if (!props.unmapped || !props.unmapped.length) return null;
  return e("div", { className: "panel" },
    e("h2", null, "Map these jobcodes"),
    e("div", { className: "meta", style: { marginBottom: "12px" } },
      "These came from the CSV and have no leave type yet. Pick one for each."),
    props.unmapped.map(function (code) {
      return e("div", { className: "fixrow", key: code },
        e("span", { className: "who", style: { minWidth: "110px" } }, code),
        (props.leaveTypes && props.leaveTypes.length)
          ? e("select", {
              value: props.overrides[code.toLowerCase()] || "",
              onChange: function (ev) { props.onPick(code, ev.target.value); }
            },
              e("option", { value: "" }, "Pick a Humanity leave type"),
              (props.leaveTypes || []).map(function (t) {
                return e("option", { key: t.id, value: t.id }, t.name + " (" + t.id + ")");
              })
            )
          : e("input", {
              type: "text",
              placeholder: "Leave type ID from Humanity",
              defaultValue: props.overrides[code.toLowerCase()] || "",
              onBlur: function (ev) {
                if (ev.target.value.trim()) props.onPick(code, ev.target.value.trim());
              }
            })
      );
    })
  );
}

function App() {
  var s0 = useState(null); var health = s0[0], setHealth = s0[1];
  var s1 = useState(null); var file = s1[0], setFile = s1[1];
  var s2 = useState([]); var items = s2[0], setItems = s2[1];
  var s3 = useState({}); var counts = s3[0], setCounts = s3[1];
  var s4 = useState([]); var roster = s4[0], setRoster = s4[1];
  var s5 = useState(""); var error = s5[0], setError = s5[1];
  var s6 = useState(false); var busy = s6[0], setBusy = s6[1];
  var s7 = useState(true); var includePending = s7[0], setIncludePending = s7[1];
  var s8 = useState(false); var previewed = s8[0], setPreviewed = s8[1];
  var s9 = useState([]); var leaveTypes = s9[0], setLeaveTypes = s9[1];
  var s10 = useState([]); var unmapped = s10[0], setUnmapped = s10[1];
  var s11 = useState({}); var overrides = s11[0], setOverrides = s11[1];
  var s12 = useState(null); var diag = s12[0], setDiag = s12[1];
  var s13 = useState(false); var diagBusy = s13[0], setDiagBusy = s13[1];
  var s14 = useState(null); var payloads = s14[0], setPayloads = s14[1];
  var s15 = useState(null); var dedupe = s15[0], setDedupe = s15[1];
  var s16 = useState(false); var dedupeBusy = s16[0], setDedupeBusy = s16[1];

  var overrideRef = useRef({});
  overrideRef.current = overrides;

  useEffect(function () {
    fetch("/api/health").then(function (r) { return r.json(); }).then(setHealth).catch(function () {});
    fetch("/api/roster").then(function (r) { return r.json(); }).then(function (d) {
      if (d.ok) setRoster(d.employees);
    }).catch(function () {});
  }, []);

  function recount(list) {
    var c = {};
    list.forEach(function (i) {
      var k = i.result || i.action;
      c[k] = (c[k] || 0) + 1;
    });
    setCounts(c);
  }

  function runPreview(theFile) {
    var target = theFile || file;
    if (!target) return;
    setBusy(true); setError(""); setItems([]);
    var form = new FormData();
    form.append("file", target);
    form.append("leavetype_overrides", JSON.stringify(overrideRef.current));
    fetch("/api/preview", { method: "POST", body: form })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { setError(d.error); return; }
        setItems(d.items);
        setCounts(d.counts);
        setLeaveTypes(d.leave_types || []);
        setUnmapped(d.unmapped_jobcodes || []);
        setPreviewed(true);
      })
      .catch(function (err) { setError(String(err)); })
      .finally(function () { setBusy(false); });
  }

  function runImport() {
    if (!file) return;
    setBusy(true); setError(""); setItems([]);
    var form = new FormData();
    form.append("file", file);
    form.append("include_pending", includePending ? "1" : "0");
    form.append("leavetype_overrides", JSON.stringify(overrideRef.current));

    fetch("/api/import", { method: "POST", body: form }).then(function (resp) {
      if (!resp.ok) {
        return resp.json().then(function (d) { throw new Error(d.error || "Import failed."); });
      }
      var reader = resp.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";
      var live = [];

      function pump() {
        return reader.read().then(function (chunk) {
          if (chunk.done) { recount(live); setBusy(false); return; }
          buffer += decoder.decode(chunk.value, { stream: true });
          var lines = buffer.split("\n");
          buffer = lines.pop();
          lines.forEach(function (line) {
            if (!line.trim()) return;
            var msg = JSON.parse(line);
            if (msg.event === "row") {
              live = live.concat([msg.row]);
              setItems(live);
              recount(live);
            }
          });
          return pump();
        });
      }
      return pump();
    }).catch(function (err) {
      setError(String(err.message || err));
      setBusy(false);
    });
  }

  function runDiagnostics() {
    setDiagBusy(true);
    fetch("/api/debug/leavetypes")
      .then(function (r) { return r.json(); })
      .then(function (d) {
        setDiag(d);
        if (d.derived && d.derived.length) setLeaveTypes(d.derived);
      })
      .catch(function (err) { setError(String(err)); })
      .finally(function () { setDiagBusy(false); });
  }

  function inspectDedupe() {
    setDedupeBusy(true);
    fetch("/api/debug/dedupe?start=2026-08-25&end=2026-08-30")
      .then(function (r) { return r.json(); })
      .then(function (d) { setDedupe(d); })
      .catch(function (err) { setError(String(err)); })
      .finally(function () { setDedupeBusy(false); });
  }

  function showPayloads() {
    if (!file) return;
    var form = new FormData();
    form.append("file", file);
    form.append("leavetype_overrides", JSON.stringify(overrideRef.current));
    fetch("/api/debug/payload", { method: "POST", body: form })
      .then(function (r) { return r.json(); })
      .then(function (d) { setPayloads(d.ok ? d.payloads : null); if (!d.ok) setError(d.error); })
      .catch(function (err) { setError(String(err)); });
  }

  function setOverride(jobcode, typeId) {
    var next = Object.assign({}, overrides);
    next[jobcode.toLowerCase()] = typeId;
    setOverrides(next);
    overrideRef.current = next;
    runPreview();
  }

  function saveMapping(item, employeeId) {
    var key = item.username || item.name;
    fetch("/api/map-employee", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_key: key, employee_id: employeeId, label: item.name })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { setError(d.error); return; }
        runPreview();
      })
      .catch(function (err) { setError(String(err)); });
  }

  var readyToPost = (counts.create || 0) + (counts.update || 0);

  return e("div", { className: "wrap" },
    e(Masthead, { health: health }),

    e("div", { className: "panel" },
      e("h2", null, "1. The file"),
      e(Dropzone, {
        fileName: file ? file.name : null,
        onFile: function (f) { setFile(f); setPreviewed(false); setItems([]); setCounts({}); runPreview(f); }
      }),
      e("div", { className: "actions" },
        e("button", { onClick: function () { runPreview(); }, disabled: !file || busy },
          busy ? "Working" : "Preview again"),
        e("button", {
          className: "primary",
          onClick: runImport,
          disabled: !file || busy || !previewed || !readyToPost
        }, "Post " + readyToPost + " to Humanity"),
        e("label", { className: "check" },
          e("input", {
            type: "checkbox",
            checked: includePending,
            onChange: function (ev) { setIncludePending(ev.target.checked); }
          }),
          "Include unapproved rows as pending"
        )
      ),
      error ? e("div", { className: "err" }, error) : null
    ),

    e(JobcodeMapper, {
      unmapped: unmapped,
      leaveTypes: leaveTypes,
      overrides: overrides,
      onPick: setOverride
    }),

    e("div", { className: "panel" },
      e("h2", null, "2. What happens to each row"),
      e(Tally, { counts: counts }),
      items.length
        ? e("div", { className: "ledger", style: { marginTop: "16px" } },
            items.map(function (item, i) {
              return e(Row, { key: i, item: item, roster: roster, onMap: saveMapping });
            })
          )
        : e("div", { className: "empty" }, "Drop a file above to see the plan.")
    ),

    e(Diagnostics, {
      diag: diag,
      busy: diagBusy,
      hasFile: !!file,
      payloads: payloads,
      onRun: runDiagnostics,
      onPayloads: showPayloads,
      onDedupe: inspectDedupe,
      dedupe: dedupe,
      dedupeBusy: dedupeBusy
    })
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(e(App));
