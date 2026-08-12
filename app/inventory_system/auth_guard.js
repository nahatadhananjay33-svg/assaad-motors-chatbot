/* Phase 10D — shared front-end auth guard for the admin dashboards.
 *
 * Include this BEFORE a page's own script:
 *     <script src="auth_guard.js"></script>
 *
 * It runs immediately and:
 *   • redirects to login.html (remembering ?next) when there is no session;
 *   • exposes window.AUTH = {base, token, user, role, fullName};
 *   • provides AUTH.headers()/AUTH.jheaders() that send X-Session-Token
 *     (replacing the Phase 10C X-API-Key + X-Acting-User headers);
 *   • renders a "Signed in as … · Logout" bar at the top of the page;
 *   • AUTH.requireOwner() → hard page-level Owner-only gate (Owner Panel).
 *
 * The server still enforces every permission (defence in depth); this is UX.
 */
(function () {
  var token = localStorage.getItem("auth_token");
  var thisPage = location.pathname.split("/").pop() || "";

  if (!token) {
    location.replace("login.html?next=" + encodeURIComponent(thisPage));
    return;
  }

  var base = (localStorage.getItem("auth_base") || location.origin).replace(/\/+$/, "");

  var AUTH = {
    base: base,
    token: token,
    user: localStorage.getItem("auth_user") || "",
    role: localStorage.getItem("auth_role") || "",
    fullName: localStorage.getItem("auth_full_name") || "",

    headers: function (extra) {
      var h = { "X-Session-Token": this.token };
      if (extra) for (var k in extra) h[k] = extra[k];
      return h;
    },
    jheaders: function () { return this.headers({ "Content-Type": "application/json" }); },

    logout: function () {
      var b = this.base, t = this.token;
      // best-effort server-side destroy, then clear + go to login regardless
      try {
        fetch(b + "/auth/logout", { method: "POST", headers: { "X-Session-Token": t } })
          .catch(function () {}).finally(go);
      } catch (e) { go(); }
      function go() {
        ["auth_token", "auth_user", "auth_role", "auth_full_name"].forEach(function (k) {
          localStorage.removeItem(k);
        });
        location.replace("login.html");
      }
    },

    // Page-level Owner-only gate. Returns true if allowed; otherwise blanks the
    // page with an Access Denied notice and returns false.
    requireOwner: function () {
      if (this.role === "Owner") return true;
      document.body.innerHTML =
        '<div style="max-width:640px;margin:80px auto;font-family:system-ui,Arial,sans-serif;">' +
        '<div style="padding:22px 24px;border-radius:12px;background:#fde8e8;color:#842029;' +
        'font-size:18px;font-weight:700;">🚫 Access Denied — the Owner Panel is for the ' +
        'Owner account only.</div><p style="margin-top:16px;">' +
        '<a href="inventory_admin.html">Go to Inventory Dashboard</a> &nbsp;·&nbsp; ' +
        '<a href="#" id="adLogout">Logout</a></p></div>';
      var l = document.getElementById("adLogout");
      if (l) l.onclick = function (e) { e.preventDefault(); AUTH.logout(); };
      return false;
    }
  };

  // ── signed-in bar ──────────────────────────────────────────────────────────
  function renderBar() {
    if (document.getElementById("authBar")) return;
    var bar = document.createElement("div");
    bar.id = "authBar";
    bar.style.cssText =
      "display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;" +
      "background:#102a43;color:#e4ebf2;padding:10px 16px;font-family:system-ui,Arial,sans-serif;" +
      "font-size:14px;";
    var who = (AUTH.fullName || AUTH.user) + " · " + (AUTH.role || "");
    // Phase 12K (F3): only show a nav link the role can actually use. The server
    // still enforces every permission — this just hides dead links (e.g. an
    // Inventory Staff seeing "Media", or a Video Staff seeing "Inventory").
    // Mirrors permissions.py: roles holding inventory.view / media.view.
    var r = AUTH.role || "";
    var INV_ROLES = ["Owner", "Inventory Staff", "Photo Staff", "Finance Staff",
                     "Document Staff", "Read-Only Manager"];
    var MEDIA_ROLES = ["Owner", "Photo Staff", "Video Staff", "Social Media Staff",
                       "Read-Only Manager"];
    var lnk = function (href, label) {
      return '<a href="' + href + '" style="color:#9ec5fe;text-decoration:none;' +
             'margin-right:12px;">' + label + '</a>';
    };
    var links =
      (INV_ROLES.indexOf(r) !== -1 ? lnk("inventory_admin.html", "Inventory") : "") +
      (MEDIA_ROLES.indexOf(r) !== -1 ? lnk("media_admin.html", "Media") : "") +
      (r === "Owner" ? lnk("owner_panel.html", "Owner Panel") : "");
    bar.innerHTML =
      '<div><b>Assad Motors</b> &nbsp;<span style="opacity:.8;">Signed in as ' +
      who.replace(/</g, "&lt;") + '</span></div>' +
      '<div>' + links +
      '<button id="authLogoutBtn" style="background:#b42318;color:#fff;border:0;border-radius:6px;' +
      'padding:7px 14px;font-size:14px;cursor:pointer;">Logout</button></div>';
    document.body.insertBefore(bar, document.body.firstChild);
    document.getElementById("authLogoutBtn").onclick = function () { AUTH.logout(); };
  }
  if (document.body) renderBar();
  else document.addEventListener("DOMContentLoaded", renderBar);

  window.AUTH = AUTH;
})();
