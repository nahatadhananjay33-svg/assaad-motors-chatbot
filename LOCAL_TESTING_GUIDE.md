# Local Testing Guide (for Staff)

This guide explains, in very simple steps, how to test the car chatbot on this
laptop **before** it goes on the internet (VPS). You do **not** need to know any
coding. Just follow each step exactly.

**Two things you will use again and again:**
- The **address** of the system: `http://localhost:8000`
- The **admin key** (a password for the management pages): `testadmin`

> Tip: anything written `like this` is something you type or click exactly.
> If a step does not look right, **stop** and tell the technical person — do not
> guess.

---

## STEP 1 — Start the chatbot on the laptop

**Do this:**

1. Click the Windows **Start** button, type `PowerShell`, and open
   **Windows PowerShell** (the blue window).
2. Click in the blue window and type these **three** lines, pressing **Enter**
   after each one:

```
cd C:\Users\ASUS\Desktop\Assad_Papa_Mumbai_work\Assad_Bhaiya_work\app\inventory_system
$env:CHAT_ADMIN_API_KEYS = "testadmin"
python -X utf8 chat_api.py
```

3. **Leave this blue window open** the whole time you are testing. The system is
   running inside it.

**What success looks like:**
- You see some lines of text, including one with `"server_start"` and
  `"inventory_count": 44` (the number may differ).
- You may see a yellow `SECURITY` warning block — this is **normal** on a laptop
  and is fine for testing.
- The window **stays open** and does not return to a normal `PS C:\>` prompt.

**What an error looks like (STOP and report it):**
- `python is not recognized…` → Python is not installed correctly.
- `ModuleNotFoundError…` → a part is missing.
- `Address already in use` / `port 8000` → it is already running in another
  window (close the other one).
- A long red block of text (a "traceback"), or the window closes by itself.

**To stop the system later:** click the blue window and press `Ctrl` + `C`.

---

## STEP 2 — Check that the chatbot is running

**Do this:**
1. Open any web browser (Chrome / Edge).
2. In the address bar type: `http://localhost:8000/health` and press **Enter**.

**What success looks like:**
- You see a short line of text like:
  `{"status": "ok", "inventory_count": 44, ...}`
- This means the server is alive (a "200 OK" response).

**What failure looks like:**
- "This site can't be reached" / "connection refused" → the system is not
  running. Go back to **STEP 1**.

---

## STEP 3 — Test Inventory Management (adding cars)

> Goal: prove that updating the Excel file updates the chatbot, and that a backup
> is made automatically. **We use a COPY so the real list is always safe.**

**3.1 — Open the inventory page**
- Go to the folder
  `C:\Users\ASUS\Desktop\Assad_Papa_Mumbai_work\Assad_Bhaiya_work\app\inventory_system`
- Double-click **`inventory_admin.html`** (it opens in your browser).

**3.2 — Connect the page**
- In **Server address** type `http://localhost:8000`
- In **Admin key** type `testadmin`
- Click **Check status**.
- ✅ Expected: it shows **Cars live** (a number), **Last updated**, and
  **Current file**. (If it says error → check STEP 1/2.)

**3.3 — Note the current count**
- Write down the **Cars live** number (example: `44`).

**3.4 — Make a safe copy of the Excel file**
- Go to `C:\Users\ASUS\Desktop\Assad_Papa_Mumbai_work\Assad_Bhaiya_work\app`
- Right-click **`IVR_Sheet.xlsx`** → **Copy**, then **Paste**.
- Rename the new file to **`IVR_Sheet_TEST.xlsx`**.

**3.5 — Add ONE temporary test car to the copy**
- Open **`IVR_Sheet_TEST.xlsx`** in Excel.
- Click the sheet tab named **`DNJ`** at the bottom.
- Scroll to the **first empty row** at the very bottom of the list.
- Fill in just these boxes on that empty row (use the column **titles** to find
  them):
  - **Company Name** → `MARU`
  - **MODEL** → `Swift`
  - the year column (next to MODEL) → `2021`
  - **RATE** → `550000`
  - **CAR NUMB** → `TEST0001`
- Press **Save** (Ctrl + S). Close Excel.

**3.6 — Upload the copy**
- Back on the **inventory_admin.html** page, click **Choose file** and pick
  **`IVR_Sheet_TEST.xlsx`**.
- Click **Upload & Update**.
- ✅ Expected: a green message like
  **"✓ Inventory updated — 45 cars are now live."** (one more than before).

**3.7 — Verify the count changed**
- Click **Check status** again.
- ✅ Expected: **Cars live** is now **one higher** than what you wrote in 3.3.

**3.8 — Verify a backup was created**
- Open the folder
  `C:\Users\ASUS\Desktop\Assad_Papa_Mumbai_work\Assad_Bhaiya_work\app\inventory_backups`
- ✅ Expected: there is a new file named like **`IVR_Sheet_20260623_…​.xlsx`**
  with today's date/time. (This is the automatic safety copy.)

**3.9 — Verify the chatbot can find the new car**
- Do **STEP 6** first to open the chat page, then ask: `TEST0001`
- ✅ Expected: the chatbot mentions a 2021 Swift / shows the test car.

**3.10 — Put the real list back (cleanup)**
- On **inventory_admin.html**, click **Choose file**, pick the **original**
  **`IVR_Sheet.xlsx`**, and click **Upload & Update**.
- ✅ Expected: count goes back to the original number; the test car is gone.
- You can now delete `IVR_Sheet_TEST.xlsx`.

---

## STEP 4 — Test Media Management (photos / videos / links)

> Goal: prove the owner can add photos, videos, Instagram and YouTube without
> ever touching Supabase or copying any links.

**4.1 — Open the media page**
- In the `inventory_system` folder, double-click **`media_admin.html`**.

**4.2 — Connect the page**
- **Server address** → `http://localhost:8000`
- **Admin key** → `testadmin`
- Click **Load vehicles**.
- ✅ Expected: a table of cars appears (Car Number, Model, Status).

**4.3 — Pick a test car**
- Click any **one** car row (it highlights and an "Actions" box appears).
  (If you still have `TEST0001` live, use that.)

**4.4 — Upload 3 photos**
- Click **📷 Upload Photos** → choose **3** picture files (`.jpg`/`.png`) → Open.
- ✅ Expected: green message **"✓ 3 photos uploaded and saved to Excel."**

**4.5 — Upload 1 video**
- Click **🎥 Upload Videos** → choose **1** video file (`.mp4`) → Open.
- ✅ Expected: green message **"✓ 1 videos uploaded and saved to Excel."**

**4.6 — Add an Instagram reel**
- Click **Add Instagram URL** → paste an Instagram link → OK.
- ✅ Expected: **"✓ instagram link saved."**

**4.7 — Add a YouTube link**
- Click **Add YouTube URL** → paste a YouTube link → OK.
- ✅ Expected: **"✓ youtube link saved."**

**4.8 — Verify the links are written into Excel**
- Open **`IVR_Sheet.xlsx`** → sheet **`DNJ`** → find the car's row (match the
  **CAR NUMB**).
- Scroll **far right** to the columns named **`PHOTO_URLS`**, **`VIDEO_URLS`**,
  **`INSTAGRAM_URL`**, **`YOUTUBE_URL`**, **`LAST_UPDATED`**.
- ✅ Expected: these boxes now contain web links, and **LAST_UPDATED** shows
  today's date/time.

**4.9 — Verify the chatbot sends photos and videos**
- On the chat page (STEP 6), type (use the car's model, e.g. Swift):
  - `Swift ke photos dikhao` → ✅ chatbot replies with photo links.
  - `Swift ka video bhejo` → ✅ chatbot replies with the video link.
  - (If two cars share a model, the chatbot will ask which one — that is correct.)

---

## STEP 5 — Test the Sold Workflow

> Goal: prove that marking a car sold removes it everywhere.

**5.1 — Select the test car**
- On **media_admin.html**, click the **same test car** row.

**5.2 — Mark it sold**
- Click **Mark Sold**.
- A warning box appears → click **OK** to confirm.
- ✅ Expected: green message **"✓ Sold. N media files deleted. Vehicle removed
  from chatbot."** and the car **disappears from the list**.

**5.3 — Verify the row MOVED (not lost)**
- Open **`IVR_Sheet.xlsx`**. At the bottom you should now see a sheet tab named
  **`SOLD_CARS`**.
- ✅ Expected: the test car's row is in **SOLD_CARS**, and it is **no longer** in
  the **DNJ** sheet.

**5.4 — Verify the car is hidden from customers**
- On the chat page, ask: `TEST0001 dikhao` (or the car's number).
- ✅ Expected: the chatbot says it is **not available** and does not show it.

**5.5 — Verify the media was deleted**
- The "Sold" message already said how many files were deleted.
- ✅ Expected: the photo/video columns for that car are now empty (you can check
  in Excel as in 4.8 — but the row is in SOLD_CARS now, with media cleared).

---

## STEP 6 — Test the chatbot by talking to it

**Open the chat page:**
- Go to
  `C:\Users\ASUS\Desktop\Assad_Papa_Mumbai_work\Assad_Bhaiya_work\app\website_widget`
- Double-click **`demo.html`**.
- In the **Backend API URL** box type `http://localhost:8000`, then reload the
  widget (the page has a button to apply it).

**Ask these one by one** and compare to the expected answer:

| You type | ✅ Good answer looks like | ❌ Bad answer looks like |
|----------|--------------------------|--------------------------|
| `family car batao` | Suggests 6–7 seater / family cars from stock | Empty, error, or "I don't understand" |
| `6 lakh budget` | Shows cars around ₹6 lakh | Shows cars far outside budget, or nothing |
| `photo bhejo` (after naming a car) | Sends photo links for that car | "no media" for a car that has photos, or wrong car |
| `video bhejo` (after naming a car) | Sends the video link | Sends photos instead, or error |
| `price kya hai` (after naming a car) | Gives that car's price in ₹/lakh | Wrong price, or no price |
| A Marathi question, e.g. `gaadi kuठे आहे?` / `किती किंमत आहे?` | Replies in Marathi, on-topic | Replies in English only, or nonsense |

> General rule: a **good** answer is polite, in the customer's language, and
> about cars actually in stock. A **bad** answer is an error, a blank reply, the
> wrong car, or a made-up car.

---

## STEP 7 — Verify logging (that questions are being recorded)

**Where the log is:**
- File: `C:\Users\ASUS\Desktop\Assad_Papa_Mumbai_work\Assad_Bhaiya_work\data\pilot_query_log.db`

**How to open it (no coding):**
1. Download and install the free tool **"DB Browser for SQLite"**
   (https://sqlitebrowser.org).
2. Open it → **Open Database** → choose the `pilot_query_log.db` file above.
3. Click the **Browse Data** tab → choose the table **`query_log`**.

**What you should see (the columns):**
- `timestamp` — when the question was asked
- `user_query` — what the customer typed
- `detected_language` — e.g. hindi / english / marathi
- `detected_intent` — what they wanted (availability / photo / price …)
- `route` — how it was answered
- `bot_response` — what the chatbot replied
- `matched_inventory`, `lead_level`, `visit_ready`, `vehicle_selected`

**What confirms logging works:**
- Ask 2–3 new questions on the chat page (STEP 6).
- Re-open `query_log` (or click refresh).
- ✅ Expected: **new rows** appear at the bottom with your latest questions and
  today's time. That confirms logging is working.

---

## You are done

Now fill in **`LOCAL_TESTING_CHECKLIST.md`** (tick each box you saw working),
then read **`GO_LIVE_DECISION.md`** to decide if it is ready for the VPS.
