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
    fetch("/api/preview", { method: "POST", body: form })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { setError(d.error); return; }
        setItems(d.items);
        setCounts(d.counts);
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
    )
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(e(App));
