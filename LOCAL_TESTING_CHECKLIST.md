# Local Testing Checklist

Tick a box **only after you saw the ✅ expected result** for that test in
`LOCAL_TESTING_GUIDE.md`. If anything was wrong, leave it unticked and write a
note next to it.

**Tester name:** ________________   **Date:** ____________

---

## Core checks

- [ ] **Chatbot starts** — PowerShell shows `server_start` and stays open (Guide STEP 1)
- [ ] **Health page OK** — `http://localhost:8000/health` shows `"status": "ok"` (STEP 2)

## Inventory

- [ ] **Inventory upload works** — count went up by 1 after uploading the test copy (STEP 3.6–3.7)
- [ ] **Backup created** — a new file appeared in `app\inventory_backups\` (STEP 3.8)
- [ ] **Chatbot finds new vehicle** — `TEST0001` was found (STEP 3.9)
- [ ] **Real list restored** — original `IVR_Sheet.xlsx` re-uploaded, test car gone (STEP 3.10)

## Media

- [ ] **Media upload works** — "3 photos uploaded" and "1 video uploaded" messages (STEP 4.4–4.5)
- [ ] **Instagram + YouTube saved** — both green confirmations (STEP 4.6–4.7)
- [ ] **URLs appear in Excel** — `PHOTO_URLS` / `VIDEO_URLS` / `INSTAGRAM_URL` / `YOUTUBE_URL` filled, `LAST_UPDATED` set (STEP 4.8)
- [ ] **Photos visible** — chatbot replied to `photos dikhao` with photo links (STEP 4.9)
- [ ] **Videos visible** — chatbot replied to `video bhejo` with the video link (STEP 4.9)

## Sold workflow

- [ ] **Sold workflow works** — "Sold… removed from chatbot" message; car left the list (STEP 5.2)
- [ ] **Row moved** — car is now in the `SOLD_CARS` sheet, not in `DNJ` (STEP 5.3)
- [ ] **Vehicle hidden** — chatbot says the sold car is not available (STEP 5.4)
- [ ] **Media deleted** — sold message reported files deleted; columns cleared (STEP 5.5)

## Chatbot conversation

- [ ] **Chatbot works** — all STEP 6 questions gave good answers (family car / budget / photo / video / price / Marathi)

## Logging

- [ ] **Logging works** — new rows appeared in `query_log` after asking questions (STEP 7)

---

## Summary line (copy your result into GO_LIVE_DECISION.md)

- Total boxes: **18**
- Boxes ticked: ______
- Any box unticked? **YES / NO**
