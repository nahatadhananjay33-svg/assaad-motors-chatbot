/* Phase 11A — Assad Motors standalone chat app.
   Frontend only: talks to the existing backend POST /chat
   (body {message, session_id} → {response, vehicles[], media{}}).
   No frameworks. Conversations persist in localStorage. */

(function () {
  "use strict";
  var CFG = window.DEALER_CONFIG || {};
  var API = (CFG.apiUrl || "").replace(/\/+$/, "") || location.origin;
  var STORE_KEY = "assad_chats_v1";
  var MAX_LEN = 500;

  var $ = function (id) { return document.getElementById(id); };
  var chatScroll = $("chatScroll"), conversation = $("conversation");
  var input = $("input"), sendBtn = $("sendBtn"), composer = $("composer");
  var sidebar = $("sidebar"), scrim = $("scrim");

  /* ── branding from config ── */
  document.title = CFG.name + " — Chat";
  $("brandName").textContent = CFG.name;
  $("brandTag").textContent = CFG.tagline || "";
  $("welcomeTitle").textContent = CFG.greeting || ("Welcome to " + CFG.name);
  $("welcomeSub").textContent = CFG.subGreeting || "How can I help you today?";
  $("footerNote").textContent = CFG.footer || "";
  $("sidebarFooter").textContent = CFG.footer || "";
  $("igLink").href = CFG.instagram || "#";
  $("waLink").href = CFG.whatsapp || "#";
  $("callLink").href = CFG.phone || "#";
  input.placeholder = CFG.inputPlaceholder || "Ask anything...";
  (CFG.suggestions || []).forEach(function (s) {
    var b = document.createElement("button");
    b.type = "button"; b.className = "chip"; b.textContent = s;
    b.addEventListener("click", function () { sendMessage(s); });
    $("chips").appendChild(b);
  });
  function paintLogo(node) {
    if (CFG.logo) { node.style.backgroundImage = "url('" + CFG.logo + "')"; node.textContent = ""; }
    else { node.textContent = (CFG.name || "A").trim().charAt(0).toUpperCase(); }
  }
  paintLogo($("logo"));

  /* ── conversation store (localStorage) ── */
  function loadStore() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY)) || { convos: [] }; }
    catch (e) { return { convos: [] }; }
  }
  function saveStore() { try { localStorage.setItem(STORE_KEY, JSON.stringify(store)); } catch (e) {} }
  function uuid() {
    return (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
      : "s-" + Date.now() + "-" + Math.random().toString(36).slice(2, 10);
  }
  var store = loadStore();
  var current = null;                    // active conversation object

  function newConversation() {
    current = { id: uuid(), title: "", messages: [], created: Date.now() };
    renderConversation(); renderRecents();
  }
  function persistCurrent() {
    if (!current || !current.messages.length) return;
    var i = store.convos.findIndex(function (c) { return c.id === current.id; });
    if (i === -1) store.convos.unshift(current); else store.convos[i] = current;
    store.convos = store.convos.slice(0, 30);          // keep last 30
    saveStore(); renderRecents();
  }
  function openConversation(id) {
    var c = store.convos.find(function (x) { return x.id === id; });
    if (!c) return;
    current = c; renderConversation(); renderRecents(); closeDrawer();
  }
  function deleteConversation(id, ev) {
    ev.stopPropagation();
    store.convos = store.convos.filter(function (c) { return c.id !== id; });
    saveStore();
    if (current && current.id === id) newConversation(); else renderRecents();
  }

  function renderRecents() {
    var list = $("recentList"); list.innerHTML = "";
    store.convos.forEach(function (c) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "recent-item" + (current && current.id === c.id ? " active" : "");
      var t = document.createElement("span");
      t.textContent = c.title || "New chat";
      var x = document.createElement("button");
      x.type = "button"; x.className = "recent-del"; x.textContent = "×";
      x.setAttribute("aria-label", "Delete conversation");
      x.addEventListener("click", function (ev) { deleteConversation(c.id, ev); });
      b.appendChild(t); b.appendChild(x);
      b.addEventListener("click", function () { openConversation(c.id); });
      list.appendChild(b);
    });
    $("recentLabel").style.display = store.convos.length ? "" : "none";
  }

  /* ── safe mini-markdown renderer ──
     Escapes all HTML first, then applies: **bold**, `code`, bullet lists,
     bare-URL links, newlines. XSS-safe: only regex-matched http(s) URLs
     ever become hrefs. */
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function renderMarkdown(text) {
    var esc = escapeHtml(text);
    esc = esc.replace(/(https?:\/\/[^\s<]+[^\s<).,;!])/g,
      '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
    esc = esc.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    esc = esc.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    var lines = esc.split("\n"), out = [], inList = false;
    lines.forEach(function (ln) {
      var m = ln.match(/^\s*[-•]\s+(.*)$/);
      if (m) { if (!inList) { out.push("<ul>"); inList = true; } out.push("<li>" + m[1] + "</li>"); }
      else {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push(ln === "" ? "<br>" : ln + "<br>");
      }
    });
    if (inList) out.push("</ul>");
    return out.join("").replace(/(<br>)+$/, "");
  }

  /* ── message rendering ── */
  function hideWelcome() { var w = $("welcome"); if (w) w.remove(); }
  function scrollDown(instant) {
    try {
      chatScroll.scrollTo({ top: chatScroll.scrollHeight, behavior: instant ? "auto" : "smooth" });
    } catch (e) { chatScroll.scrollTop = chatScroll.scrollHeight; }
  }

  function addUserMsg(text) {
    var row = document.createElement("div"); row.className = "msg user";
    var b = document.createElement("div"); b.className = "bubble"; b.textContent = text;
    row.appendChild(b); conversation.appendChild(row); scrollDown();
  }
  function botRow() {
    var row = document.createElement("div"); row.className = "msg bot";
    var av = document.createElement("div"); av.className = "avatar"; paintLogo(av);
    var b = document.createElement("div"); b.className = "bubble";
    row.appendChild(av); row.appendChild(b);
    conversation.appendChild(row); scrollDown();
    return b;
  }
  function addBotMsg(text) { botRow().innerHTML = renderMarkdown(text); scrollDown(); }
  function addTyping() {
    var b = botRow(); b.classList.add("is-typing");
    b.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
    return b;
  }

  function fmtPrice(v) {
    return (v && v.price_quotable && typeof v.price_lakh === "number")
      ? "₹ " + v.price_lakh.toFixed(2) + " L" : "";
  }
  function addVehicles(vehicles) {
    if (!vehicles || !vehicles.length) return;
    var wrap = document.createElement("div"); wrap.className = "cars";
    vehicles.forEach(function (v) {          // show every car the backend sends
      var card = document.createElement("div"); card.className = "car-card";
      var title = document.createElement("div"); title.className = "car-title";
      title.textContent = [v.year, v.make, v.model].filter(Boolean).join(" ");
      if (v.registration_no) {
        var reg = document.createElement("span"); reg.className = "car-reg";
        reg.textContent = v.registration_no;
        title.appendChild(reg);
      }
      card.appendChild(title);
      var price = fmtPrice(v);
      if (price) { var p = document.createElement("div"); p.className = "car-price"; p.textContent = price; card.appendChild(p); }
      var chips = document.createElement("div"); chips.className = "car-chips";
      [v.fuel, v.transmission, v.color,
       (typeof v.km === "number" ? v.km.toLocaleString("en-IN") + " km" : null),
       (v.owners ? v.owners + " owner" + (v.owners > 1 ? "s" : "") : null),
       (v.seats ? v.seats + " seater" : null), v.body_type]
        .filter(function (x) { return x && x !== "Unknown"; })
        .forEach(function (x) {
          var c = document.createElement("span"); c.className = "car-chip"; c.textContent = x;
          chips.appendChild(c);
        });
      card.appendChild(chips);
      wrap.appendChild(card);
    });
    conversation.appendChild(wrap); scrollDown();
  }
  function isHttp(u) { return typeof u === "string" && /^https?:\/\//i.test(u); }
  function addMedia(media) {
    if (!media) return;
    var photos = (media.photos || []).filter(isHttp);
    var videos = (media.videos || []).filter(isHttp);
    var insta = (media.instagram || []).filter(isHttp);
    var yt = (media.youtube || []).filter(isHttp);
    if (photos.length) {
      var row = document.createElement("div"); row.className = "media-row";
      photos.slice(0, 8).forEach(function (u) {
        var img = document.createElement("img");
        img.className = "media-thumb"; img.src = u; img.alt = "Vehicle photo";
        // if the browser cached a FAILED load (e.g. while storage was paused),
        // retry once with a cache-buster so the thumbnail heals itself
        img.addEventListener("error", function () {
          if (!img.dataset.retried) {
            img.dataset.retried = "1";
            img.src = u + (u.indexOf("?") >= 0 ? "&" : "?") + "r=" + Date.now();
          }
        });
        img.addEventListener("click", function () { window.open(u, "_blank", "noopener"); });
        row.appendChild(img);
      });
      conversation.appendChild(row);
    }
    var links = [];
    videos.forEach(function (u, i) { links.push(["▶ Video" + (videos.length > 1 ? " " + (i + 1) : ""), u]); });
    insta.forEach(function (u, i) { links.push(["Instagram" + (insta.length > 1 ? " " + (i + 1) : ""), u]); });
    yt.forEach(function (u, i) { links.push(["YouTube" + (yt.length > 1 ? " " + (i + 1) : ""), u]); });
    if (links.length) {
      var lr = document.createElement("div"); lr.className = "media-row";
      links.forEach(function (pair) {
        var a = document.createElement("a");
        a.className = "media-link"; a.textContent = pair[0];
        a.href = pair[1]; a.target = "_blank"; a.rel = "noopener noreferrer";
        lr.appendChild(a);
      });
      conversation.appendChild(lr);
    }
    scrollDown();
  }

  /* re-render a stored conversation into the DOM */
  function renderConversation() {
    conversation.innerHTML = "";
    if (!current || !current.messages.length) {
      conversation.innerHTML = document.getElementById("welcomeTpl").innerHTML;
      bindWelcome();
      return;
    }
    current.messages.forEach(function (m) {
      if (m.role === "user") addUserMsg(m.text);
      else { addBotMsg(m.text); addVehicles(m.vehicles); addMedia(m.media); }
    });
    // instant scroll after layout settles (cards/images change height post-append)
    requestAnimationFrame(function () { scrollDown(true); });
    setTimeout(function () { scrollDown(true); }, 120);
  }

  /* keep a template copy of the welcome section so New Chat can restore it */
  var tpl = document.createElement("script");
  tpl.type = "text/template"; tpl.id = "welcomeTpl";
  tpl.innerHTML = document.getElementById("welcome").outerHTML;
  document.body.appendChild(tpl);
  function bindWelcome() {
    var w = $("welcome");
    if (!w) return;
    $("welcomeTitle").textContent = CFG.greeting || "";
    $("welcomeSub").textContent = CFG.subGreeting || "";
    var chips = $("chips"); chips.innerHTML = "";
    (CFG.suggestions || []).forEach(function (s) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "chip"; b.textContent = s;
      b.addEventListener("click", function () { sendMessage(s); });
      chips.appendChild(b);
    });
  }

  /* ── send / receive ── */
  var busy = false;
  function setBusy(v) { busy = v; sendBtn.disabled = v || !input.value.trim(); }

  function sendMessage(text) {
    text = (text || "").trim().slice(0, MAX_LEN);
    if (!text || busy) return;
    hideWelcome();
    if (!current) newConversation();
    if (!current.title) { current.title = text.slice(0, 42); }
    addUserMsg(text);
    current.messages.push({ role: "user", text: text });
    persistCurrent();
    input.value = ""; autoGrow(); setBusy(true);
    var typing = addTyping();

    fetch(API + "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: current.id })
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        typing.parentNode.remove();
        var reply = d && d.response ? d.response : "Sorry, something went wrong. Please try again.";
        addBotMsg(reply);
        addVehicles(d && d.vehicles);
        if (d && d.media) addMedia(d.media);
        current.messages.push({ role: "bot", text: reply, vehicles: (d && d.vehicles) || [], media: (d && d.media) || null });
        persistCurrent();
      })
      .catch(function () {
        typing.parentNode.remove();
        addBotMsg("I couldn't reach the server. Please check your connection and try again.");
      })
      .finally(function () { setBusy(false); input.focus(); });
  }

  /* ── composer behaviour ── */
  function autoGrow() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 132) + "px";
  }
  input.addEventListener("input", function () { autoGrow(); sendBtn.disabled = busy || !input.value.trim(); });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(input.value); }
  });
  composer.addEventListener("submit", function (e) { e.preventDefault(); sendMessage(input.value); });

  /* ── sidebar / drawer ── */
  function openDrawer() { sidebar.classList.add("open"); scrim.hidden = false; }
  function closeDrawer() { sidebar.classList.remove("open"); scrim.hidden = true; }
  $("menuBtn").addEventListener("click", function () {
    sidebar.classList.contains("open") ? closeDrawer() : openDrawer();
  });
  scrim.addEventListener("click", closeDrawer);
  $("newChatBtn").addEventListener("click", function () { newConversation(); closeDrawer(); input.focus(); });

  /* ── boot ── */
  renderRecents();
  newConversation();
  input.focus();
})();
