/* Inventory Excel Editor — lightweight client.
   Renders the real workbook as an Excel-like grid (true column letters + row
   numbers) so the Name Box maps 1:1 to Excel coordinates. No frameworks. */
(function () {
  "use strict";

  var COL_W = 110, ROW_H = 22, HEAD_H = 22, ROWHEAD_W = 56;

  var state = {
    key: null, editable: true,
    usedRows: 0, usedCols: 0, gridRows: 0, gridCols: 0,
    rows: [],                 // dense strings for used range
    dirty: {},                // "r,c" -> string (per sheet)
    cellRefs: {},             // "r,c" -> <td>
    active: { r: 1, c: 1 },
    freezeRows: 0, freezeCols: 0,
    editing: false
  };

  var els = {};
  function $(id) { return document.getElementById(id); }

  // ── column-letter helpers ────────────────────────────────
  function colLetter(n) {          // 1-based -> A, B, ... AA
    var s = "";
    while (n > 0) { var m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); }
    return s;
  }
  function letterToCol(s) {         // "AS" -> number
    var n = 0;
    for (var i = 0; i < s.length; i++) n = n * 26 + (s.charCodeAt(i) - 64);
    return n;
  }
  function addr(r, c) { return colLetter(c) + r; }
  function parseAddr(txt) {
    var m = /^\s*([A-Za-z]+)\s*(\d+)\s*$/.exec(txt || "");
    if (!m) return null;
    var c = letterToCol(m[1].toUpperCase()), r = parseInt(m[2], 10);
    if (!c || !r) return null;
    return { r: r, c: c };
  }

  // ── value access ─────────────────────────────────────────
  function baseVal(r, c) {
    if (r <= state.usedRows && c <= state.usedCols) {
      var row = state.rows[r - 1];
      return row ? (row[c - 1] || "") : "";
    }
    return "";
  }
  function cellVal(r, c) {
    var k = r + "," + c;
    return (k in state.dirty) ? state.dirty[k] : baseVal(r, c);
  }

  // ── grid rendering ───────────────────────────────────────
  function renderGrid() {
    var gr = state.gridRows, gc = state.gridCols;
    var html = [];
    // header row
    html.push("<tr><th class='corner'></th>");
    for (var c = 1; c <= gc; c++) html.push("<th class='colhead' data-c='" + c + "'>" + colLetter(c) + "</th>");
    html.push("</tr>");
    // data rows
    for (var r = 1; r <= gr; r++) {
      html.push("<tr data-r='" + r + "'><th class='rowhead'>" + r + "</th>");
      for (c = 1; c <= gc; c++) {
        var v = cellVal(r, c);
        html.push("<td data-r='" + r + "' data-c='" + c + "'>" + escapeHtml(v) + "</td>");
      }
      html.push("</tr>");
    }
    els.grid.innerHTML = html.join("");
    // cache td references
    state.cellRefs = {};
    var tds = els.grid.getElementsByTagName("td");
    for (var i = 0; i < tds.length; i++) {
      var td = tds[i];
      state.cellRefs[td.getAttribute("data-r") + "," + td.getAttribute("data-c")] = td;
      if (!state.editable) td.classList.add("readonly-cell");
    }
    applyFreeze();
    selectCell(state.active.r, state.active.c, false);
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // ── freeze panes ─────────────────────────────────────────
  function applyFreeze() {
    var fr = state.freezeRows, fc = state.freezeCols;
    // clear previous freeze classes/offsets
    var prev = els.grid.querySelectorAll(".frzcol, .frzrow, .frzcell");
    prev.forEach(function (e) {
      e.classList.remove("frzcol", "frzcell");
      e.style.left = ""; e.style.top = "";
    });
    els.grid.querySelectorAll("tr.frzrow").forEach(function (tr) {
      tr.classList.remove("frzrow");
      Array.prototype.forEach.call(tr.children, function (cell) { cell.style.top = ""; });
    });

    // frozen columns: for every row, cols 1..fc sticky-left
    if (fc > 0) {
      var rows = els.grid.rows;
      for (var ri = 0; ri < rows.length; ri++) {
        var cells = rows[ri].children; // [th, td, td, ...] or [corner, colhead...]
        for (var c = 1; c <= fc; c++) {
          var cell = cells[c]; // index c because index0 is the row/corner header
          if (!cell) continue;
          cell.classList.add("frzcol");
          cell.style.left = (ROWHEAD_W + (c - 1) * COL_W) + "px";
        }
      }
    }
    // frozen rows: data rows 1..fr sticky-top
    if (fr > 0) {
      for (var r = 1; r <= fr; r++) {
        var tr = els.grid.querySelector("tr[data-r='" + r + "']");
        if (!tr) continue;
        tr.classList.add("frzrow");
        var top = HEAD_H + (r - 1) * ROW_H;
        Array.prototype.forEach.call(tr.children, function (cell) { cell.style.top = top + "px"; });
        // intersection cells
        for (var c2 = 1; c2 <= fc; c2++) {
          if (tr.children[c2]) tr.children[c2].classList.add("frzcell");
        }
      }
    }
  }

  // ── selection ────────────────────────────────────────────
  function selectCell(r, c, doScroll) {
    r = Math.max(1, Math.min(state.gridRows, r));
    c = Math.max(1, Math.min(state.gridCols, c));
    var old = state.cellRefs[state.active.r + "," + state.active.c];
    if (old) old.classList.remove("active");
    state.active = { r: r, c: c };
    var td = state.cellRefs[r + "," + c];
    if (td) td.classList.add("active");
    els.nameBox.value = addr(r, c);
    els.valueBar.value = cellVal(r, c);
    if (doScroll !== false) ensureVisible(r, c);
  }

  function ensureVisible(r, c) {
    var sc = els.gridScroll;
    var frozenLeft = ROWHEAD_W + state.freezeCols * COL_W;
    var frozenTop = HEAD_H + state.freezeRows * ROW_H;
    var cellLeft = ROWHEAD_W + (c - 1) * COL_W;
    var cellRight = cellLeft + COL_W;
    var cellTop = HEAD_H + (r - 1) * ROW_H;
    var cellBottom = cellTop + ROW_H;

    if (c > state.freezeCols) {
      var visL = sc.scrollLeft + frozenLeft, visR = sc.scrollLeft + sc.clientWidth;
      if (cellLeft < visL) sc.scrollLeft = cellLeft - frozenLeft;
      else if (cellRight > visR) sc.scrollLeft = cellRight - sc.clientWidth;
    }
    if (r > state.freezeRows) {
      var visT = sc.scrollTop + frozenTop, visB = sc.scrollTop + sc.clientHeight;
      if (cellTop < visT) sc.scrollTop = cellTop - frozenTop;
      else if (cellBottom > visB) sc.scrollTop = cellBottom - sc.clientHeight;
    }
  }

  // ── editing ──────────────────────────────────────────────
  function startEdit(initial) {
    if (!state.editable) return;
    var r = state.active.r, c = state.active.c;
    var td = state.cellRefs[r + "," + c];
    if (!td) return;
    var rect = td.getBoundingClientRect();
    var wrapRect = els.gridWrap.getBoundingClientRect();
    var ed = els.cellEditor;
    ed.style.left = (rect.left - wrapRect.left) + "px";
    ed.style.top = (rect.top - wrapRect.top) + "px";
    ed.style.width = rect.width + "px";
    ed.style.height = rect.height + "px";
    ed.style.display = "block";
    ed.value = (initial != null) ? initial : cellVal(r, c);
    state.editing = true;
    ed.focus();
    if (initial == null) ed.select();
  }

  function commitEdit(move) {
    if (!state.editing) return;
    var ed = els.cellEditor;
    var r = state.active.r, c = state.active.c;
    setCell(r, c, ed.value);
    ed.style.display = "none";
    state.editing = false;
    els.grid.focus && els.grid.focus();
    if (move) selectCell(r + 1, c);
  }

  function cancelEdit() {
    els.cellEditor.style.display = "none";
    state.editing = false;
  }

  function setCell(r, c, value) {
    if (!state.editable) return;
    var k = r + "," + c;
    state.dirty[k] = value;
    var td = state.cellRefs[k];
    if (td) td.textContent = value;
    if (state.active.r === r && state.active.c === c) els.valueBar.value = value;
    markDirtyStatus();
  }

  function markDirtyStatus() {
    var n = Object.keys(state.dirty).length;
    els.status.textContent = n ? (n + " unsaved change" + (n > 1 ? "s" : "")) : "";
    els.saveBtn.disabled = !state.editable || n === 0;
  }

  // ── clipboard ────────────────────────────────────────────
  function onCopy(e) {
    if (state.editing) return;
    var v = cellVal(state.active.r, state.active.c);
    if (e.clipboardData) { e.clipboardData.setData("text/plain", v); e.preventDefault(); }
  }
  function onPaste(e) {
    if (state.editing || !state.editable) return;
    var txt = e.clipboardData && e.clipboardData.getData("text/plain");
    if (txt == null) return;
    e.preventDefault();
    var r0 = state.active.r, c0 = state.active.c;
    var lines = txt.replace(/\r/g, "").split("\n");
    if (lines.length && lines[lines.length - 1] === "") lines.pop();
    for (var i = 0; i < lines.length; i++) {
      var cols = lines[i].split("\t");
      for (var j = 0; j < cols.length; j++) {
        var rr = r0 + i, cc = c0 + j;
        if (rr <= state.gridRows && cc <= state.gridCols) setCell(rr, cc, cols[j]);
      }
    }
    selectCell(r0, c0);
  }

  // keys while the floating editor is focused (it is NOT inside #grid, so the
  // grid keydown handler never sees these — handle them here).
  function onEditorKey(e) {
    if (!state.editing) return;
    if (e.key === "Enter") { e.preventDefault(); commitEdit(true); }
    else if (e.key === "Escape") { e.preventDefault(); cancelEdit(); }
    else if (e.key === "Tab") { e.preventDefault(); var a = state.active; commitEdit(false); selectCell(a.r, a.c + (e.shiftKey ? -1 : 1)); }
  }

  // ── keyboard nav ─────────────────────────────────────────
  function onKeyDown(e) {
    if (state.editing) return;   // editor handles its own keys
    var r = state.active.r, c = state.active.c;
    switch (e.key) {
      case "ArrowUp": selectCell(r - 1, c); e.preventDefault(); break;
      case "ArrowDown": case "Enter": selectCell(r + 1, c); e.preventDefault(); break;
      case "ArrowLeft": selectCell(r, c - 1); e.preventDefault(); break;
      case "ArrowRight": selectCell(r, c + 1); e.preventDefault(); break;
      case "Tab": selectCell(r, c + (e.shiftKey ? -1 : 1)); e.preventDefault(); break;
      case "PageUp": selectCell(r - 20, c); e.preventDefault(); break;
      case "PageDown": selectCell(r + 20, c); e.preventDefault(); break;
      case "Home": selectCell(r, 1); e.preventDefault(); break;
      case "F2": startEdit(null); e.preventDefault(); break;
      case "Delete": case "Backspace": setCell(r, c, ""); e.preventDefault(); break;
      default:
        if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
          startEdit(e.key); e.preventDefault();
        }
    }
  }

  // ── data loading ─────────────────────────────────────────
  function loadSheet(key) {
    els.status.textContent = "loading…";
    fetch("/api/data?sheet=" + encodeURIComponent(key))
      .then(function (res) { return res.json(); })
      .then(function (d) {
        if (d.error) { els.status.textContent = "error: " + d.error; return; }
        state.key = key;
        state.editable = d.editable;
        state.usedRows = d.usedRows; state.usedCols = d.usedCols;
        state.gridRows = d.gridRows; state.gridCols = d.gridCols;
        state.rows = d.rows;
        state.dirty = {};
        state.active = { r: 1, c: 1 };
        els.roLabel.style.display = d.editable ? "none" : "inline-block";
        renderGrid();
        markDirtyStatus();
        els.status.textContent = d.usedRows + " rows × " + d.usedCols + " cols";
      })
      .catch(function (err) { els.status.textContent = "load failed: " + err; });
  }

  function save() {
    var keys = Object.keys(state.dirty);
    if (!keys.length) return;
    var edits = keys.map(function (k) {
      var p = k.split(","); return { r: +p[0], c: +p[1], v: state.dirty[k] };
    });
    els.saveBtn.disabled = true;
    els.status.textContent = "saving…";
    fetch("/api/save", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sheet: state.key, edits: edits })
    }).then(function (r) { return r.json(); })
      .then(function (res) {
        if (res.ok) {
          // fold saved values into the base so they persist without reload
          keys.forEach(function (k) {
            var p = k.split(","), rr = +p[0], cc = +p[1];
            while (state.rows.length < rr) state.rows.push([]);
            var row = state.rows[rr - 1];
            while (row.length < cc) row.push("");
            row[cc - 1] = state.dirty[k];
          });
          state.usedRows = Math.max(state.usedRows, Math.max.apply(null, keys.map(function (k) { return +k.split(",")[0]; })));
          state.usedCols = Math.max(state.usedCols, Math.max.apply(null, keys.map(function (k) { return +k.split(",")[1]; })));
          state.dirty = {};
          markDirtyStatus();
          els.status.textContent = "saved " + res.applied + " cell(s) → backup " + res.backup;
        } else {
          els.status.textContent = "save error: " + (res.error || "unknown");
          els.saveBtn.disabled = false;
        }
      })
      .catch(function (err) { els.status.textContent = "save failed: " + err; els.saveBtn.disabled = false; });
  }

  // ── wiring ───────────────────────────────────────────────
  function init() {
    els.grid = $("grid"); els.gridScroll = $("gridScroll"); els.gridWrap = $("gridWrap");
    els.nameBox = $("nameBox"); els.valueBar = $("valueBar");
    els.sheetSelect = $("sheetSelect"); els.roLabel = $("roLabel");
    els.freezeRows = $("freezeRows"); els.freezeCols = $("freezeCols");
    els.saveBtn = $("saveBtn"); els.status = $("status");
    els.cellEditor = $("cellEditor");

    // grid focusable for key handling
    els.grid.tabIndex = 0;

    // cell click -> select
    els.grid.addEventListener("mousedown", function (e) {
      var td = e.target.closest ? e.target.closest("td") : null;
      if (!td || !td.hasAttribute("data-c")) return;
      if (state.editing) commitEdit(false);
      selectCell(+td.getAttribute("data-r"), +td.getAttribute("data-c"), false);
      els.grid.focus();
    });
    els.grid.addEventListener("dblclick", function (e) {
      var td = e.target.closest ? e.target.closest("td") : null;
      if (td && td.hasAttribute("data-c")) startEdit(null);
    });

    els.grid.addEventListener("keydown", onKeyDown);
    els.cellEditor.addEventListener("keydown", onEditorKey);
    els.cellEditor.addEventListener("blur", function () { if (state.editing) commitEdit(false); });
    document.addEventListener("copy", onCopy);
    document.addEventListener("paste", onPaste);

    // name box jump
    els.nameBox.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        var p = parseAddr(els.nameBox.value);
        if (p) { selectCell(p.r, p.c); els.grid.focus(); }
        else els.nameBox.value = addr(state.active.r, state.active.c);
        e.preventDefault();
      }
    });

    // value bar edit
    els.valueBar.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && state.editable) {
        setCell(state.active.r, state.active.c, els.valueBar.value);
        selectCell(state.active.r + 1, state.active.c);
        els.grid.focus();
        e.preventDefault();
      }
    });

    els.freezeRows.addEventListener("change", function () { state.freezeRows = +this.value; applyFreeze(); });
    els.freezeCols.addEventListener("change", function () { state.freezeCols = +this.value; applyFreeze(); });

    els.sheetSelect.addEventListener("change", function () { loadSheet(this.value); });
    els.saveBtn.addEventListener("click", save);
    els.saveBtn.disabled = true;

    // load sheet list, then first sheet
    fetch("/api/sheets").then(function (r) { return r.json(); }).then(function (d) {
      (d.sheets || []).forEach(function (s) {
        var o = document.createElement("option");
        o.value = s.key; o.textContent = s.label + (s.editable ? "" : " (view)");
        els.sheetSelect.appendChild(o);
      });
      if (d.sheets && d.sheets.length) { els.sheetSelect.value = d.sheets[0].key; loadSheet(d.sheets[0].key); }
      document.title = "Editor — " + (d.workbook || "IVR_Sheet.xlsx");
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
