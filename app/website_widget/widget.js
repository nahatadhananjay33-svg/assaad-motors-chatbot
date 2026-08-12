/* ============================================================================
 * Vasant Oasis Cars — Website Chatbot Widget  (Phase 4B, Website Pilot)
 * ----------------------------------------------------------------------------
 * Frontend integration ONLY. Talks to the existing, validated backend `/chat`
 * API exactly as-is. No backend changes, no LLM, no analytics SDK, no lead DB.
 *
 * Embed with ONE script tag:
 *   <script src="https://your-cdn/website_widget/widget.js"
 *           data-api-url="https://api.yourdealership.com"
 *           data-title="Vasant Oasis Cars"
 *           data-greeting="Namaste! Ask me about our cars 🚗"
 *           data-accent="#0b5cab"
 *           data-position="right"></script>
 *
 * Backend contract consumed (unchanged):
 *   POST {api-url}/chat   body: {"message": str, "session_id": str}
 *   ->   {intent, response, vehicles[], status, count, filters, guardrails,
 *         request_id, meta}
 *   GET  {api-url}/health -> {status, inventory_count, ...}
 *
 * Media: the widget renders media if the response provides it (per-vehicle
 * `vehicle.media` OR a top-level `media` object shaped like MediaService output:
 * {photos[], videos[], instagram[], youtube[]}). It degrades silently when the
 * backend does not include media. See frontend_api_contract.md §Media.
 * ========================================================================== */
(function () {
  "use strict";
  if (window.__vocWidgetLoaded) return;          // idempotent: never double-mount
  window.__vocWidgetLoaded = true;

  // ── resolve config from this script tag ──────────────────────────────────
  var script = document.currentScript ||
    (function () { var s = document.getElementsByTagName("script");
                   return s[s.length - 1]; })();
  var ds = (script && script.dataset) || {};
  var SRC = (script && script.src) || "";
  var BASE = SRC ? SRC.slice(0, SRC.lastIndexOf("/") + 1) : "";

  var CFG = {
    apiUrl: (ds.apiUrl || "http://localhost:8000").replace(/\/+$/, ""),
    title: ds.title || "Vasant Oasis Cars",
    subtitle: ds.subtitle || "Andheri East, Mumbai",
    greeting: ds.greeting ||
      "Namaste! 🙏 Ask me about our used cars — by budget, model, fuel or seats. " +
      "Aap Hindi, English ya Marathi mein pooch sakte hain.",
    accent: ds.accent || "",
    position: (ds.position === "left") ? "left" : "right",
    placeholder: ds.placeholder || "Type your message…",
    injectCss: ds.noCss !== "true"
  };

  var SESSION_KEY = "voasis_chat_session";
  var MAX_LEN = 500;                              // mirrors backend MAX_MESSAGE_LEN

  // ── persistent session id (enables backend lead-capture + analytics) ─────
  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }
  function getSessionId() {
    var id;
    try { id = localStorage.getItem(SESSION_KEY); } catch (e) { id = null; }
    if (!id) { id = "web-" + uuid();
      try { localStorage.setItem(SESSION_KEY, id); } catch (e) {} }
    return id;
  }
  var SESSION_ID = getSessionId();

  // ── tiny DOM helpers (textContent only → XSS-safe) ───────────────────────
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function svg(path, vb) {
    var s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", vb || "0 0 24 24");
    var p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", path); s.appendChild(p); return s;
  }
  function isHttp(u) { return typeof u === "string" && /^https?:\/\//i.test(u); }

  // ── stylesheet (one tag → auto-inject sibling widget.css) ────────────────
  function injectCss() {
    if (!CFG.injectCss) return;
    if (document.getElementById("voc-css")) return;
    var link = el("link"); link.id = "voc-css"; link.rel = "stylesheet";
    link.href = BASE + "widget.css?v=20260612";
    document.head.appendChild(link);
  }

  // ── build the UI ─────────────────────────────────────────────────────────
  var root, panel, log, input, sendBtn, launcher, typingNode = null, busy = false;

  function build() {
    root = el("div"); root.id = "voc-root";
    root.classList.add(CFG.position === "left" ? "voc-pos-left" : "voc-pos-right");
    if (CFG.accent) root.style.setProperty("--voc-accent", CFG.accent);

    // launcher bubble
    launcher = el("button"); launcher.id = "voc-launcher";
    launcher.setAttribute("aria-label", "Open chat");
    launcher.appendChild(svg("M12 3C6.48 3 2 6.92 2 11.5c0 2.4 1.23 4.56 3.2 6.06" +
      "L4 21l3.66-1.2c1.32.45 2.78.7 4.34.7 5.52 0 10-3.92 10-8.5S17.52 3 12 3z"));
    launcher.addEventListener("click", toggle);

    // panel
    panel = el("div"); panel.id = "voc-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", CFG.title + " chat");

    var header = el("div"); header.id = "voc-header";
    header.appendChild(el("span", "voc-h-dot"));
    var htxt = el("div");
    htxt.appendChild(el("div", "voc-h-title", CFG.title));
    htxt.appendChild(el("div", "voc-h-sub", CFG.subtitle));
    header.appendChild(htxt);
    var close = el("button"); close.id = "voc-close"; close.innerHTML = "&times;";
    close.setAttribute("aria-label", "Close chat");
    close.addEventListener("click", closePanel);
    header.appendChild(close);

    log = el("div"); log.id = "voc-log";
    log.setAttribute("role", "log"); log.setAttribute("aria-live", "polite");

    var composer = el("div"); composer.id = "voc-composer";
    input = el("textarea"); input.id = "voc-input"; input.rows = 1;
    input.placeholder = CFG.placeholder; input.maxLength = MAX_LEN;
    input.setAttribute("aria-label", "Message");
    input.addEventListener("input", autoGrow);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
    });
    sendBtn = el("button"); sendBtn.id = "voc-send";
    sendBtn.setAttribute("aria-label", "Send");
    sendBtn.appendChild(svg("M2 21l21-9L2 3v7l15 2-15 2v7z"));
    sendBtn.addEventListener("click", submit);
    composer.appendChild(input); composer.appendChild(sendBtn);

    var footer = el("div"); footer.id = "voc-footer";
    footer.textContent = "Powered by Vasant Oasis Cars • replies may be in your language";

    panel.appendChild(header); panel.appendChild(log);
    panel.appendChild(composer); panel.appendChild(footer);
    root.appendChild(panel); root.appendChild(launcher);
    document.body.appendChild(root);

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && root.classList.contains("voc-open")) closePanel();
    });
  }

  // ── panel open/close ─────────────────────────────────────────────────────
  var greeted = false;
  function toggle() { root.classList.contains("voc-open") ? closePanel() : openPanel(); }
  function openPanel() {
    root.classList.add("voc-open");
    launcher.setAttribute("aria-label", "Close chat");
    if (!greeted) { greeted = true; addBot(CFG.greeting); }
    setTimeout(function () { input.focus(); }, 60);
  }
  function closePanel() {
    root.classList.remove("voc-open");
    launcher.setAttribute("aria-label", "Open chat");
  }
  function autoGrow() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  }
  function scrollDown() { log.scrollTop = log.scrollHeight; }

  // ── render: messages ─────────────────────────────────────────────────────
  function addUser(text) { var m = el("div", "voc-msg voc-msg-user", text);
    log.appendChild(m); scrollDown(); }
  // Bot text: URLs become real clickable links (new tab). Still XSS-safe —
  // everything is added via textContent/createTextNode; only strings matching
  // ^https?:// are ever used as an href.
  var URL_RE = /(https?:\/\/[^\s]+)/g;
  function addBot(text) {
    var m = el("div", "voc-msg voc-msg-bot");
    String(text == null ? "" : text).split(URL_RE).forEach(function (part) {
      if (/^https?:\/\//i.test(part)) {
        var url = part, trail = "";
        while (/[).,;!]$/.test(url)) { trail = url.slice(-1) + trail; url = url.slice(0, -1); }
        var a = el("a", "voc-msg-link", url);
        a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer";
        m.appendChild(a);
        if (trail) m.appendChild(document.createTextNode(trail));
      } else if (part) {
        m.appendChild(document.createTextNode(part));
      }
    });
    log.appendChild(m); scrollDown();
  }
  function addError(text, retryText) {
    var box = el("div", "voc-msg voc-msg-error");
    box.appendChild(el("div", null, text));
    if (retryText) {
      var b = el("button", null, "Retry");
      b.addEventListener("click", function () { box.remove(); doSend(retryText); });
      box.appendChild(b);
    }
    log.appendChild(box); scrollDown();
  }

  // ── render: typing indicator ─────────────────────────────────────────────
  function showTyping() {
    hideTyping();
    typingNode = el("div", "voc-typing");
    typingNode.appendChild(el("span")); typingNode.appendChild(el("span"));
    typingNode.appendChild(el("span"));
    typingNode.setAttribute("aria-label", "Assistant is typing");
    log.appendChild(typingNode); scrollDown();
  }
  function hideTyping() { if (typingNode) { typingNode.remove(); typingNode = null; } }

  // ── render: vehicle cards ────────────────────────────────────────────────
  function fmtPrice(v) {
    if (v && v.price_quotable && typeof v.price_lakh === "number")
      return { text: "₹ " + v.price_lakh.toFixed(2) + " L", onVisit: false };
    return { text: "Price on visit", onVisit: true };
  }
  function vehicleTitle(v) {
    var bits = [];
    if (v.year) bits.push(v.year);
    if (v.color) bits.push(v.color);
    if (v.make) bits.push(v.make);
    if (v.model) bits.push(v.model);
    if (v.registration_no) bits.push("· " + v.registration_no);
    return bits.join(" ") || "Vehicle";
  }
  function addVehicles(vehicles) {
    if (!vehicles || !vehicles.length) return;
    var wrap = el("div", "voc-cards");
    vehicles.forEach(function (v) {
      var card = el("div", "voc-card");
      var head = el("div");
      var price = fmtPrice(v);
      var pEl = el("span", "voc-card-price" + (price.onVisit ? " voc-onvisit" : ""), price.text);
      head.appendChild(pEl);
      head.appendChild(el("span", "voc-card-title", vehicleTitle(v)));
      card.appendChild(head);

      var specs = el("div", "voc-card-specs");
      var chips = [];
      if (v.fuel && v.fuel !== "Unknown") chips.push(v.fuel);
      if (v.transmission && v.transmission !== "Unknown") chips.push(v.transmission);
      if (v.body_type && v.body_type !== "Unknown") chips.push(v.body_type);
      if (typeof v.km === "number") chips.push(v.km.toLocaleString("en-IN") + " km");
      if (typeof v.owners === "number") chips.push(v.owners + " owner" + (v.owners > 1 ? "s" : ""));
      if (typeof v.seats === "number") chips.push(v.seats + " seater");
      chips.forEach(function (c) { specs.appendChild(el("span", "voc-chip", c)); });
      card.appendChild(specs);

      // media (forward-compatible: rendered only if the backend supplies it)
      if (v.media) card.appendChild(renderMedia(v.media));
      wrap.appendChild(card);
    });
    log.appendChild(wrap); scrollDown();
  }

  // ── render: media (MediaService-shaped: photos/videos/instagram/youtube) ──
  function renderMedia(media) {
    var box = el("div", "voc-media");
    var photos = (media.photos || media.exterior_photos || []).filter(isHttp);
    if (media.interior_photos) photos = photos.concat(media.interior_photos.filter(isHttp));
    var videos = (media.videos || []).filter(isHttp);
    var insta = (media.instagram || []).filter(isHttp);
    var yt = (media.youtube || []).filter(isHttp);

    if (photos.length) {
      box.appendChild(el("div", "voc-media-label", "Photos"));
      var row = el("div", "voc-media-row");
      photos.slice(0, 8).forEach(function (u) {
        var img = el("img", "voc-media-thumb"); img.src = u;
        img.alt = "Vehicle photo";
        // retry once with a cache-buster if the browser cached a failed load
        img.addEventListener("error", function () {
          if (!img.dataset.retried) {
            img.dataset.retried = "1";
            img.src = u + (u.indexOf("?") >= 0 ? "&" : "?") + "r=" + Date.now();
          }
        });
        img.addEventListener("click", function () { window.open(u, "_blank", "noopener"); });
        row.appendChild(img);
      });
      box.appendChild(row);
    }
    var links = el("div", "voc-media-links");
    function addLinks(arr, label) {
      arr.forEach(function (u, i) {
        var a = el("a", "voc-media-link", label + (arr.length > 1 ? " " + (i + 1) : ""));
        a.href = u; a.target = "_blank"; a.rel = "noopener noreferrer";
        links.appendChild(a);
      });
    }
    addLinks(videos, "▶ Video");
    addLinks(insta, "Instagram");
    addLinks(yt, "YouTube");
    if (links.childNodes.length) box.appendChild(links);
    return box;
  }

  // ── send / receive ───────────────────────────────────────────────────────
  function submit() {
    var text = (input.value || "").trim();
    if (!text || busy) return;
    input.value = ""; autoGrow();
    doSend(text);
  }

  function doSend(text) {
    addUser(text);
    busy = true; sendBtn.disabled = true; showTyping();

    var controller = (typeof AbortController !== "undefined") ? new AbortController() : null;
    var timer = setTimeout(function () { controller && controller.abort(); }, 20000);

    fetch(CFG.apiUrl + "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text.slice(0, MAX_LEN), session_id: SESSION_ID }),
      signal: controller ? controller.signal : undefined
    }).then(function (res) {
      clearTimeout(timer);
      return res.json().catch(function () { return {}; })
        .then(function (data) { return { ok: res.ok, status: res.status, data: data }; });
    }).then(function (r) {
      hideTyping();
      if (!r.ok) {
        var detail = (r.data && (r.data.detail || r.data.error)) || ("HTTP " + r.status);
        addError("Sorry — " + detail + ". Please try rephrasing.", null);
        return;
      }
      var d = r.data || {};
      if (d.response) addBot(d.response);
      addVehicles(d.vehicles);
      if (d.media) { var box = renderMedia(d.media);     // top-level media (if present)
        if (box.childNodes.length) { var w = el("div", "voc-cards");
          var c = el("div", "voc-card"); c.appendChild(box); w.appendChild(c);
          log.appendChild(w); scrollDown(); } }
    }).catch(function (err) {
      clearTimeout(timer); hideTyping();
      var msg = (err && err.name === "AbortError")
        ? "The server took too long to respond."
        : "I couldn't reach the server. Please check your connection.";
      addError(msg, text);
    }).then(function () {
      busy = false; sendBtn.disabled = false; input.focus();
    });
  }

  // ── boot ─────────────────────────────────────────────────────────────────
  function boot() { injectCss(); build(); }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", boot);
  else boot();

  // small public hook for host pages / testing (no analytics, no PII)
  window.VOCWidget = {
    open: function () { root && openPanel(); },
    close: function () { root && closePanel(); },
    sessionId: function () { return SESSION_ID; },
    send: function (t) { if (root) { openPanel(); doSend(String(t || "")); } }
  };
})();
