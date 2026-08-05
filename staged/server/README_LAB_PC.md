# Running the WINK assistant on a lab PC

No account, no hosting fee, no IT ticket. One machine in the lab answers
questions for students on the campus network. The only thing you have to obtain
is an Anthropic API key.

Closing the window stops it. Nothing is exposed off campus.

---

## Step 1 — Get an API key (about 5 minutes)

1. Go to **<https://console.anthropic.com>** and sign in (or create an account
   with your ISU email).
2. It will ask you to create an **organisation**. Name it for the lab —
   *Vidal-Gadea Lab* — not for yourself. It outlives any one person and a
   student can later be added without rebuilding anything.
3. Left sidebar → **Billing** → add a payment method. This is a usage account,
   not a subscription: you are charged for what is used and nothing if it sits
   idle.
4. **Do this before anything else:** Billing → **Set a monthly spend limit**.
   Twenty dollars is generous for a handful of students. The limit exists to
   stop a loop bug, not to ration help — if it is ever reached, that is a
   signal to look at what happened, not to raise it reflexively.
5. Left sidebar → **API keys** → **Create key**. Name it *WINK lab PC*.
6. **Copy it now.** It is shown once and never again. If you lose it, delete
   that key and make another; nothing else breaks.

A key looks like `sk-ant-api03-` followed by a long string. Treat it like a
credit card number: anyone holding it can spend against your account.

## Step 2 — Put the key on the lab PC

Create this file:

    %LOCALAPPDATA%\LabTools\assistant_key.txt

(Paste that path straight into the File Explorer address bar; it expands.)

Paste the key into it as a **single line, nothing else** — no quotes, no label,
no trailing blank line. Save.

That location is deliberate: it is outside the WINK repository, so the key
cannot be committed by accident, and it does not travel when the app is
installed on a student machine.

## Step 3 — Make student tokens

Run **`Start_WINK_Assistant.bat`** (in this folder). The first time, it will
copy a template to `%LOCALAPPDATA%\LabTools\tokens.json` and open it in Notepad.

Replace the examples with one line per student:

```json
{
  "wink-7f3a9c21d8e4": {"user": "kiley",  "soft_cap": 40, "hard_cap": 60},
  "wink-b2e81a06c5f7": {"user": "ella",   "soft_cap": 40, "hard_cap": 60},
  "wink-4d90e7c1a3b6": {"user": "andres", "soft_cap": 200, "hard_cap": 300}
}
```

- The token is any hard-to-guess string. **Do not use names as tokens** — the
  token is the password, the `user` field is the label.
- Caps are **per day**, and count only questions that reach the model.
  Questions the lab has already answered are served from the ledger, cost
  nothing, and are never charged — so a student at their cap is slowed, not cut
  off.
- To revoke someone: delete their line and restart. No reinstall.

Save, close Notepad, and run the batch file again.

## Step 4 — It's running

You will see something like:

```
==============================================================
  WINK assistant - running on this PC
==============================================================
  Students point WINK at:  http://10.20.30.40:5000
  Check it works:          http://10.20.30.40:5000/health
  Students with a token:   3
  Question ledger:         C:\Users\...\LabTools\wink_ledger.sqlite
```

Open the `/health` address in a browser on the same PC. You should see
`"ok": true`, `"key_configured": true`, and the number of tokens loaded.

Then try it from a **different** machine on the campus network. If it works
there, students can use it. If it works locally but not remotely, Windows
Firewall is blocking the port — see below.

**Leave the window open.** Closing it stops the assistant. Minimise it.

## Step 5 — Point WINK at it

Tell me the address it printed and I will wire the Help button into the tools.
Each student needs their own token, given to them once.

---

## If it will not work from another machine

Windows Firewall blocks the port by default. From an **Administrator**
PowerShell on the lab PC:

```powershell
New-NetFirewallRule -DisplayName "WINK assistant" -Direction Inbound `
  -Protocol TCP -LocalPort 5000 -Action Allow -Profile Domain,Private
```

`-Profile Domain,Private` deliberately excludes public networks.

If ISU blocks PC-to-PC connections between subnets, students on a different
part of the network will not reach it. That is a real limit of this approach
and the reason a hosted VM is the eventual answer — but it costs nothing to
find out.

## What this tells you

After a couple of weeks, from a WINK console:

```python
import sys; sys.path.insert(0, r"<repo>\staged\app")
import assistant_ledger as al, os
db = al.open_ledger(os.path.expandvars(r"%LOCALAPPDATA%\LabTools\wink_ledger.sqlite"))
al.usage_report(db)            # who is asking; the cache hit rate
al.promotion_candidates(db)    # what keeps coming up
```

`usage_report` — a rising cache hit rate means the ledger is doing its job. One
user far above the rest is usually a loop or a stuck dialog, not a keen student.

`promotion_candidates` — repeated questions, split into **fix_the_tool** and
**genuine_faq**, defaulting to the first. A question fifteen students ask is
usually a tool that does not explain itself, and an FAQ entry answers it while
leaving the cause in place. Read that list as a bug queue.

That is the number that decides whether this is worth a VM or a subscription:
if the assistant is used and the questions are real, it has earned it. If it is
not, you have spent nothing finding out.

## Cost

Roughly **a fifth of a cent per new question**. Ten students asking twenty
questions a day is about **$2-4 a month**, and it falls as the ledger fills,
because repeats become free. The spend limit protects you from a bug, not from
normal use.

## Moving it later

Only the address changes. The same files run unchanged on a departmental VM or
on PythonAnywhere — see `README_PYTHONANYWHERE.md`. Copy the ledger across and
no history is lost.
