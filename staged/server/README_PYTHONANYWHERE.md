# Deploying the WINK help endpoint

Everything here is already written and tested. What is left needs your account
and your card, so it needs you. Roughly twenty minutes.

Nothing in WINK depends on this. If the endpoint is never deployed, WINK works
exactly as it does now — the help panel is the only thing that goes missing.

---

## Before you start

**Ask ISU IT whether they will give you a small Linux VM.** If they will, it is
free to you, inside their network, and inside their security review, which is
strictly better than paying PythonAnywhere. The steps below adapt to any Linux
host. Only pay if IT says no or the answer takes weeks.

---

## 1. The Anthropic API key

1. Go to <https://console.anthropic.com> and sign in.
2. Create an organisation (name it for the lab, not for you personally — it
   outlives any one person).
3. Add a payment method.
4. **Set a monthly spend limit before anything else.** Settings → Limits.
   Twenty dollars is generous for ten students; the limit exists to stop a loop
   bug, not to ration help.
5. Settings → API Keys → Create Key. Copy it once — it is not shown again.

Do not put this key in a file in this repository, in the WINK installer, or in
an email. It goes in one place, in step 3 below.

## 2. PythonAnywhere

1. <https://www.pythonanywhere.com> → create an account.
2. Take a paid plan (about $5/month). Two reasons, both hard requirements:
   a free account cannot reach `api.anthropic.com` (outbound access is
   whitelisted), and files on a free account do not reliably persist, which
   would erase the question ledger.
3. **Files** tab → create a directory `wink_server`.
4. Upload from `staged/server/`: `wink_assistant_server.py`.
   Upload from `staged/app/`: `assistant_context.py`, `assistant_ledger.py`,
   `method_provenance.py`.
   Put all four in `wink_server/` — the server adds its own directory to the
   path, so a flat folder is fine.
5. **Consoles** tab → Bash → install the two dependencies:

       pip3.10 install --user flask anthropic

6. **Web** tab → Add a new web app → Manual configuration → Python 3.10.
7. Edit the WSGI configuration file it offers you. Delete what is there and put:

       import sys
       path = '/home/YOURNAME/wink_server'
       if path not in sys.path:
           sys.path.insert(0, path)
       from wink_assistant_server import app as application

8. Still on the **Web** tab, find **Environment variables** and add:

       ANTHROPIC_API_KEY   = (the key from step 1)
       WINK_LEDGER_DB      = /home/YOURNAME/wink_server/wink_ledger.sqlite
       WINK_TOKENS         = /home/YOURNAME/wink_server/tokens.json

   The key lives here and nowhere else. It is not in the code, not in the
   repository, and not on any student machine.
9. Reload the web app.

## 3. Student tokens

Create `wink_server/tokens.json` on the server (Files tab → New file). One
entry per student:

```json
{
  "wink-a7f3c9d2": {"user": "kiley",  "soft_cap": 40, "hard_cap": 60},
  "wink-2b81e4a6": {"user": "ella",   "soft_cap": 40, "hard_cap": 60},
  "wink-9d05f7c1": {"user": "andres", "soft_cap": 200, "hard_cap": 300}
}
```

- The token is any hard-to-guess string. `wink-` plus a dozen random hex
  characters is plenty. Do not use names as tokens.
- `user` is what appears in the usage report. A first name is fine; this is a
  teaching tool, not an anonymised study.
- Caps are **per day**, and count only questions that reach the model.
  Questions the lab has already answered are served from the ledger, cost
  nothing, and are never charged — so a student at their cap is slowed, not
  cut off.
- To revoke access, delete the line and reload. No reinstall, no new key.

`tokens.example.json` in this folder is a template. **The real `tokens.json`
must never be committed** — it is in `.gitignore`.

## 4. Check it

Visit `https://YOURNAME.pythonanywhere.com/health` in a browser. You should see:

```json
{"ok": true, "tools": ["confidence", "cycles", "defecation", "head_tail",
 "myocyte", "rhythm"], "key_configured": true, "tokens_loaded": 3}
```

If `key_configured` is `false` the environment variable did not take — reload
the web app. If `tokens_loaded` is `0`, check the path and the JSON.

## 5. Then tell me

Send me the URL and I will wire the panel into WINK: a Help button in each
tool, the outcome buttons that feed the ledger, and the per-tool key so a
question arrives already knowing which tool it came from.

---

## What it costs

- PythonAnywhere: about **$5/month**.
- API usage: roughly **a fifth of a cent per new question**. Ten students at
  twenty questions a day is around **$2–4/month**, and it falls as the ledger
  fills, because repeats become free.

## Watching it

From a Bash console on the server:

```python
import sys; sys.path.insert(0, '/home/YOURNAME/wink_server')
import assistant_ledger as al
db = al.open_ledger('/home/YOURNAME/wink_server/wink_ledger.sqlite')
al.usage_report(db)              # who is asking, and the cache hit rate
al.promotion_candidates(db)      # what keeps coming up
```

`usage_report` — a rising cache hit rate means the ledger is working. One user
far above the rest is usually a loop or a stuck dialog, not a keen student.

`promotion_candidates` — splits repeated questions into **fix_the_tool** and
**genuine_faq**, and defaults to the first. A question fifteen students ask is
usually a tool that does not explain itself, and an FAQ entry answers it while
leaving the cause in place. Read that list as a bug queue.
