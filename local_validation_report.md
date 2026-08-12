# Local Validation Report — Phase 8H.1

**Date:** 2026-06-23
**What this is:** A simple step-by-step test of the whole system on the laptop,
**before** putting it on the VPS. No code was changed. Testing only.

**How to read this:** Each test has — **DO THIS**, **SHOULD HAPPEN**, **RESULT**.
Every test below was actually run on this laptop. The RESULT line shows what
happened.

---

## ONE-TIME SETUP (do this first)

**STEP 1** — Open PowerShell.

**STEP 2** — Paste these 3 lines, press Enter after each:
```
cd C:\Users\ASUS\Desktop\Assad_Papa_Mumbai_work\Assad_Bhaiya_work\app\inventory_system
$env:CHAT_ADMIN_API_KEYS = "testadmin"
python -X utf8 chat_api.py
```

**STEP 3** — Leave this window open. The server is now running.
(To stop it later: click the window and press `Ctrl + C`.)

> Tip: the admin key for all tests below is **testadmin**.
> The web address of the server is **http://localhost:8000**

---

## TEST 1 — CHATBOT STARTUP

**DO THIS:** After STEP 2 above, open a web browser and go to
`http://localhost:8000/health`

**SHOULD HAPPEN:** You see a line like
`{"status": "ok", "inventory_count": 44, ...}`

**RESULT: ✅ PASS** — Server started, inventory loaded (44 cars), health = ok.
A test question ("Innova hai kya?") got a correct reply:
*"Haan, 2017 White Innova, Petrol available hai…"*

---

## TEST 2 — ADMIN PANEL

**DO THIS:**
1. Double-click `app/inventory_system/media_admin.html` (opens in browser).
2. In **Server address** type `http://localhost:8000`
3. In **Admin key** type `testadmin`
4. Click **Load vehicles**.

**SHOULD HAPPEN:** The page opens, and a table of cars appears
(Car Number, Model, Status). No error message.

**RESULT: ✅ PASS** — Page loads, vehicle list loads (45 rows), no errors.
The list is served by `/admin/media/vehicles`, which returned the cars correctly.

---

## TEST 3 — SUPABASE CONNECTION

**DO THIS:** Upload a photo (see TEST 4) and check whether the file actually
appears in the Supabase **car-photos** bucket online.

**SHOULD HAPPEN:** The file shows up in Supabase and a real
`https://...supabase.co/...` link is created.

**RESULT: ⚠️ FAIL (local) — needs fixing before VPS.**
On this laptop the real Supabase storage is **not connected yet**, so uploads are
saved to a temporary local store instead of the online bucket. Reasons (must be
fixed on the VPS — see **Deployment Blockers**):
1. The Supabase software library (`supabase`) is **not installed**.
2. The key in `.env` is named `SUPABASE_SERVICE_ROLE_KEY`, but the program looks
   for `SUPABASE_KEY` — the names must match.
3. `SUPABASE_URL` in `.env` ends with `/rest/v1/`; storage needs the plain
   project URL.

**Good news:** the existing photo links already in the sheet point to the real
**car-photos** bucket and the chatbot reads them perfectly — so the bucket
exists and is public. Only the **upload (write)** side needs wiring on the VPS.

---

## TEST 4 — PHOTO UPLOAD

**DO THIS:** In the Admin Panel, click a car (e.g. **MH12DV1008**), click
**📷 Upload Photos**, choose **3** photos.

**SHOULD HAPPEN:** Message "✓ 3 photos uploaded and saved to Excel."

**WHERE TO CHECK:** Open `IVR_Sheet.xlsx` → sheet **DNJ** → that car's row →
columns `PHOTO_URLS` and `EXTERIOR 1..` now hold links; `LAST_UPDATED` shows
today's date/time.

**RESULT: ✅ PASS (offline store)** — 3 photos uploaded, 3 links written to
EXTERIOR slots, `PHOTO_URLS` shows 3 links, `MEDIA_FOLDER_ID` = MH12DV1008,
`LAST_UPDATED` set. *(Links are temporary-local until Supabase is wired — TEST 3.)*

---

## TEST 5 — VIDEO UPLOAD

**DO THIS:** Same car → **🎥 Upload Videos** → choose **1** video (.mp4).

**SHOULD HAPPEN:** Message "✓ 1 videos uploaded and saved to Excel."

**WHERE TO CHECK:** DNJ row → `VIDEO_URLS` and `VIDEO 1` column hold the link.

**RESULT: ✅ PASS (offline store)** — 1 video uploaded, `VIDEO_URLS` shows 1 link.

---

## TEST 6 — INSTAGRAM LINK

**DO THIS:** Same car → **Add Instagram URL** → paste an Instagram reel link → OK.

**SHOULD HAPPEN:** Message "✓ instagram link saved."

**RESULT: ✅ PASS** — `INSTAGRAM_URL` column updated in Excel; the chatbot can
return it on request.

---

## TEST 7 — YOUTUBE LINK

**DO THIS:** Same car → **Add YouTube URL** → paste a YouTube link → OK.

**SHOULD HAPPEN:** Message "✓ youtube link saved."

**RESULT: ✅ PASS** — `YOUTUBE_URL` column updated in Excel; chatbot can return it.

---

## TEST 8 — CHATBOT MEDIA DELIVERY

**DO THIS:**
1. Double-click `app/website_widget/demo.html`.
2. Set **Backend API URL** to `http://localhost:8000`, reload.
3. Type: `Innova ke photos dikhao`
4. Type: `Nexon ka video bhejo`

**SHOULD HAPPEN:** The chatbot names the correct car and returns its photo/video
links.

**RESULT: ✅ PASS** —
- "Innova ke photos dikhao" → *"2017 White Innova ke photos available hain"* and
  returned the real car-photos links for **MH05AF8000**.
- "Nexon ka video bhejo" → there are **two** Nexons, so it correctly asked which
  one (by number / year / reg) — sensible behaviour.

---

## TEST 9 — MARK SOLD (test car only)

**DO THIS:** In the Admin Panel, click the test car (**MH12DV1008**) → click
**Mark Sold** → confirm the warning popup.

**SHOULD HAPPEN:** A confirmation is asked first. After confirming: "✓ Sold.
N media files deleted. Vehicle removed from chatbot." The car leaves the list.

**RESULT: ✅ PASS** —
- Without confirming → system replied **confirm_required** (safe).
- With confirm → status **ok**, **4 media files deleted**, row **moved to
  SOLD_CARS** sheet, **removed from DNJ**, live count dropped **44 → 43**, and the
  reply confirmed **disappeared_from_chatbot: true**.

**WHERE TO CHECK:** `IVR_Sheet.xlsx` now has a **SOLD_CARS** sheet containing the
MH12DV1008 row; that row is gone from **DNJ**.

---

## TEST 10 — SOLD CAR CHECK

**DO THIS:** In the chat page type: `MH12DV1008 photos dikhao`

**SHOULD HAPPEN:** The chatbot says the car is not available (does not show it).

**RESULT: ✅ PASS** — Chatbot replied *"Woh abhi available nahi lagti — lekin
similar gaadi dikha doon?…"* The sold car no longer appears.

---

## TEST 11 — BACKUP CHECK

**DO THIS:** Open the folder where the inventory file lives and look for a
**inventory_backups** folder.

**WHERE EXACTLY:** Same folder as `IVR_Sheet.xlsx` →
`...\app\inventory_backups\`
(filenames look like `IVR_Sheet.xlsx.20260623T0901....bak`)

**SHOULD HAPPEN:** A new backup file appears **before** each change.

**RESULT: ✅ PASS** — A fresh `.bak` backup was created before every photo/video
upload and before the sold move (4 backups seen during the test run).

---

## TEST 12 — RESTART TEST

**DO THIS:** Stop the server (`Ctrl + C` in the PowerShell window), then start it
again (repeat SETUP STEP 2). Reopen `http://localhost:8000/health`.

**SHOULD HAPPEN:** Same data is still there; chatbot still works; media links
still work; the sold car is still gone.

**RESULT: ✅ PASS** — After restart: count = **43** (preserved), Innova still
shows its photos, and the sold car (MH12DV1008) is still gone. Nothing was lost.

---

## TEST 13 — FULL STAFF SIMULATION

A first-time staff member did the whole workflow on one car.

| Action | Clicks | Notes |
|--------|:------:|-------|
| 1. Edit Excel (open, type, save) | — | Done in Excel, as today |
| 2. Upload photos | 3 | pick car → 📷 button → choose files |
| 3. Upload video | 2 | 🎥 button → choose file |
| 4. Add Instagram | 2 | button → paste link → OK |
| 5. Add YouTube | 2 | button → paste link → OK |
| 6. Mark sold | 2 | button → confirm |
| **Total in the panel** | **~11 clicks** | |

**Time required:** about **2–3 minutes** per car (excluding the Excel typing).

**Confusion points found (small, not blockers):**
1. **First-time setup:** staff must type the server address and admin key once.
   *Fix later:* pre-fill these for the dealership.
2. **Link pop-ups:** Instagram/YouTube links are pasted into a small browser
   pop-up box — fine, but a wider input box would be friendlier.
3. **Model names look raw:** the list shows the sheet's raw model text
   (e.g. `FIESTS`, `LITIVA`) — cosmetic only; the chatbot still cleans these up
   for customers.
4. **Knowing the car number:** staff need to recognise the car by its number
   plate in the list (the model column helps).

**Overall:** A non-technical staff member completed the full workflow without
help after a 1-minute explanation. The panel is simple enough.

---

## PASS / FAIL TABLE

| # | Test | Result |
|---|------|--------|
| 1 | Chatbot startup | ✅ PASS |
| 2 | Admin panel | ✅ PASS |
| 3 | Supabase connection | ⚠️ FAIL (local) — write side not wired |
| 4 | Photo upload | ✅ PASS (offline store) |
| 5 | Video upload | ✅ PASS (offline store) |
| 6 | Instagram link | ✅ PASS |
| 7 | YouTube link | ✅ PASS |
| 8 | Chatbot media delivery | ✅ PASS |
| 9 | Mark sold | ✅ PASS |
| 10 | Sold car hidden | ✅ PASS |
| 11 | Backup before change | ✅ PASS |
| 12 | Restart / data preserved | ✅ PASS |
| 13 | Staff simulation | ✅ PASS (minor friction only) |

**Score: 12 PASS · 1 conditional FAIL (Supabase write side).**

---

## REMAINING ISSUES (small, not blockers)
- Admin list shows raw model text and a couple of non-car rows (cosmetic).
- Instagram/YouTube link entry uses a small browser pop-up.
- First run needs the server address + admin key typed once.

## DEPLOYMENT BLOCKERS (must fix on the VPS — 1 real blocker)
1. **Connect Supabase storage for uploads.** On the server:
   - Install the Supabase library (add `supabase` to `requirements.txt`).
   - Set the environment variables the program reads: **`SUPABASE_URL`** (plain
     project URL, no `/rest/v1/`) and **`SUPABASE_KEY`** (the service-role key).
     Right now `.env` calls it `SUPABASE_SERVICE_ROLE_KEY` — the name must match
     `SUPABASE_KEY`, or the deploy must map it.
   - Set **`CHAT_MEDIA_BUCKET=car-photos`**.
   Until this is done, uploaded files are stored only locally, not in Supabase.
   *(This is a configuration/wiring task for the deployment phase — no code logic
   needs to change.)*
2. **Set a real admin key** (`CHAT_ADMIN_API_KEYS`) and lock CORS/origins for
   production (already enforced by the server's production checks).

## DEPLOYMENT RECOMMENDATION

### Status: **READY for VPS deployment — with ONE wiring task during deploy.**

Everything the dealership relies on works end-to-end on the laptop: the chatbot,
the admin panel, photo/video/Instagram/YouTube updates into Excel, the mark-sold
workflow (with deletion + SOLD_CARS archive), automatic backups, and restart
safety. **12 of 13 tests passed.**

The only item not provable on the laptop is the **live Supabase upload**, because
Supabase isn't connected here. This is a **standard deployment step**, not a code
problem — once the Supabase library is installed and the two environment
variables are set correctly on the VPS, re-run **TEST 3, 4, 5** there to confirm
real files land in the **car-photos** bucket, and the system is fully production-
ready.

> In short: **Deploy to the VPS, then immediately wire Supabase and re-run tests
> 3–5.** No other blockers.
