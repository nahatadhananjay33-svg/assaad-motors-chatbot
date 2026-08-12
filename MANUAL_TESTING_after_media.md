# Manual Testing Guide — after Media/YouTube (Modules 21+)

**Before you start**
- Servers running: API `:8000`, pages `:8080`, chatbot widget `:8090`.
- Use an **Incognito/Private window** (avoids stale cache).
- After any server restart, sessions reset → **log in again**.
- Login: open `http://localhost:8080/login.html` → username **owner**, password **owner123**.
  (Click the 👁 to reveal the password if you want to check it.)

---

## 1) User Management  — `http://localhost:8080/owner_panel.html` → scroll to **User Management**

| Step | Do this | ✅ Expected |
|---|---|---|
| List | Look at the users table | The **owner** account is shown |
| Create | Name = `Test Staff`, Username = `teststaff`, Password = `test123`, Role = **Inventory Staff** → **Add/Create** | `teststaff` appears in the list |
| Edit role | Edit `teststaff` → change Role to **Photo Staff** → Save | Role updates to Photo Staff |
| Reset password | `teststaff` → **Reset Password** → set `test456` (min 6 chars) | Success message |
| Disable | `teststaff` → **Disable** | Row shows inactive/disabled |
| Enable | `teststaff` → **Enable** | Row active again |
| Owner is protected | Try to **Delete** or **Disable** the **owner** row | Blocked — owner can't be deleted/disabled |
| Delete | `teststaff` → **Delete** | Removed from the list |

> Tip: recreate `teststaff` (Inventory Staff, pwd `test456`) before section 2.

## 2) Roles & Permissions  — log in as the staff user

| Step | Do this | ✅ Expected |
|---|---|---|
| Staff login | Logout, then log in as `teststaff` / `test456` | Login works |
| Restricted view | Open the owner panel | User Management / Activity Logs are **hidden or blocked** (Inventory Staff can't manage users or see audit) |
| Allowed view | Open the inventory dashboard | Inventory **is** visible (Inventory Staff has inventory.view) |
| Back to owner | Logout → log in as `owner` again | Full panel returns |

## 3) Activity Logs (Audit)  — owner panel → **Activity Logs**

| Step | Do this | ✅ Expected |
|---|---|---|
| View | Scroll to Activity Logs → **Refresh** | Recent actions listed (logins, user create/edit/delete, etc.) |
| Search | Type `teststaff` in the search box | Rows filter to that user |
| Filter | Use the category/filter control (e.g. Users / Media) | Rows filter by category |
| Denied actions logged | Note rows with status **failed / Access Denied** | Blocked attempts are recorded too |

## 4) Chatbot languages  — `http://localhost:8090`

Type each and check the reply language:

| Type | ✅ Expected |
|---|---|
| `Do you have a Creta?` | English reply |
| `Creta hai kya?` | Hinglish reply |
| `क्या आपके पास Creta hai` | Hindi reply |
| `Creta आहे का?` | **Marathi** reply (Devanagari, e.g. "हो … उपलब्ध आहे") |

Bonus (new Phase 11 behaviour to see live):
- `RC?` → "RC / documents kis gaadi ke chahiye?" (asks which car)
- Pick a car first (e.g. `Swift`), then `RC?` / `owner?` / `km?` → answers **that** car
- `petrol diesel` → "Petrol ya Diesel — kaunsa fuel chahiye?" (asks instead of guessing)

## 5) Security & Logout

| Step | Do this | ✅ Expected |
|---|---|---|
| Bad login | Try `owner` / `wrongpass` | Rejected, no access |
| Logout | Click **Logout** in the panel | Returns to login page |
| Session ends | Press browser Back after logout | Panel does **not** work — must log in again |

---

**All of the above was already verified at the backend level (36/36 checks passed).**
This guide is for you to confirm the same in the actual UI. If any screen behaves
differently from the ✅ column, tell me the step and what you saw and I'll fix it.
