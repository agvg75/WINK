"""Per-user quotas, and a ledger of what students asked and whether it helped.

Two jobs. Capping and monitoring each user so one loop bug cannot spend the
lab's balance, and accumulating answered questions so the same problem is not
solved from scratch fifteen times.

THE THING THIS IS REALLY FOR, AND THE TRAP IN IT.
A question asked by fifteen students is rarely a documentation gap. It is
usually a tool that does not explain itself at the moment it matters. Turning
it into an FAQ entry answers it while leaving the cause in place, and the
better the FAQ gets the less visible the defect becomes - the tool stays
confusing and the confusion stops being reported. So `promotion_candidates`
separates two outcomes, and defaults to the uncomfortable one:

  FIX THE TOOL     a question about a failure, a setting, or why something was
                   not detected. The answer belongs in the interface, not in a
                   list students have to find.
  GENUINE FAQ      a question about the biology or the method that no interface
                   change would prevent - what a pBoc is, why ordinal grades are
                   not averaged. These are worth writing up.

A high count is evidence for the first far more often than the second, so the
count alone is reported as a defect signal and a human decides.

CACHED ANSWERS ARE FREE AND DO NOT COUNT AGAINST QUOTA. They cost nothing to
serve, and charging for them would push students away from the answers that are
already known to work.

AND A CACHED ANSWER CAN BE WRONG. An answer marked resolved once may have been
right, or the student may have given up and clicked it. Serving it forever
after makes one bad answer into a permanent one, delivered with more authority
each time. So an answer must be resolved by SEVERAL DISTINCT USERS before it is
trusted, a single `did_not_help` demotes it out of the cache, and the counts
that earned its status stay visible.
"""
from __future__ import annotations

import re
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY,
    question_key TEXT NOT NULL,
    tool TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    created_day TEXT,
    served INTEGER DEFAULT 0,
    resolved INTEGER DEFAULT 0,
    unhelpful INTEGER DEFAULT 0,
    status TEXT DEFAULT 'unproven',
    UNIQUE (question_key, tool)
);
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY,
    day TEXT, user TEXT NOT NULL, tool TEXT NOT NULL,
    question TEXT NOT NULL, question_key TEXT NOT NULL,
    answer_id INTEGER, served_from TEXT NOT NULL,
    outcome TEXT DEFAULT 'unknown'
);
CREATE TABLE IF NOT EXISTS usage (
    user TEXT NOT NULL, day TEXT NOT NULL,
    api_calls INTEGER DEFAULT 0, cached_calls INTEGER DEFAULT 0,
    PRIMARY KEY (user, day)
);
"""

# An answer is trusted only after this many DISTINCT users resolved with it.
MIN_RESOLVERS_TO_TRUST = 3
# Counts at which a repeated question is treated as evidence about the tool.
DEFECT_SIGNAL_USERS = 4

_FAILURE_WORDS = re.compile(
    r"\b(fail|failed|error|crash|wrong|not detect|didn.?t detect|no worm|"
    r"nothing happen|stuck|freeze|froze|missing|why (is|are|did|does|won)|"
    r"cannot|can.?t|doesn.?t work|broken|empty|blank|zero)\b")
_CONCEPT_WORDS = re.compile(
    r"\b(what is|what does|what are|why do we|why does the worm|meaning of|"
    r"difference between|should i|when should|how is .* defined|"
    r"interpret|means?)\b")


class LedgerError(Exception):
    """Refusals that name the consequence."""


def open_ledger(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def question_key(tool, question):
    """A lookup key that INCLUDES THE TOOL.

    "Why did it not find my worm" is a different question in the pumping tool
    and the GCaMP extractor, with different answers and different causes. Keyed
    on the words alone, the cache would confidently serve one student the other
    tool's answer - and it would look like a considered reply.
    """
    q = re.sub(r"[^a-z0-9\s]", " ", str(question).lower())
    q = re.sub(r"\b(the|a|an|is|are|my|it|to|of|in|on|i|do|does|did)\b", " ", q)
    return f"{str(tool).strip().lower()}::{' '.join(q.split())}"


def check_quota(conn, user, day, soft_cap=40, hard_cap=60):
    """Where this user stands today. Cached answers are not counted."""
    row = conn.execute("SELECT api_calls, cached_calls FROM usage "
                       "WHERE user=? AND day=?", (user, day)).fetchone()
    used = row["api_calls"] if row else 0
    cached = row["cached_calls"] if row else 0
    return {
        "user": user, "day": day, "api_calls": used, "cached_calls": cached,
        "soft_cap": soft_cap, "hard_cap": hard_cap,
        "remaining": max(hard_cap - used, 0),
        "over_soft": used >= soft_cap,
        "blocked": used >= hard_cap,
        "cached_not_counted": ("Answers served from the ledger cost nothing "
                               "and are not charged against the cap."),
        "warning": (f"{used} of {hard_cap} questions used today. The cap is "
                    f"per day and resets; it is here to stop a loop, not to "
                    f"ration help. Ask Andres to raise it if you are working."
                    if used >= soft_cap else None),
    }


def lookup(conn, tool, question):
    """A previously trusted answer, or None. Only trusted answers are served."""
    key = question_key(tool, question)
    row = conn.execute("SELECT * FROM answers WHERE question_key=? AND tool=? "
                       "AND status='trusted'", (key, tool)).fetchone()
    return dict(row) if row else None


def record(conn, user, day, tool, question, answer, served_from,
           soft_cap=40, hard_cap=60):
    """Log one interaction and update quota. Returns the interaction id.

    `served_from` is 'cache' or 'api'; only 'api' consumes quota.
    """
    if served_from not in ("cache", "api"):
        raise LedgerError(f"served_from must be 'cache' or 'api', not "
                          f"{served_from!r} - the two are billed differently "
                          f"and mislabelling one hides real spend.")
    if served_from == "api":
        q = check_quota(conn, user, day, soft_cap, hard_cap)
        if q["blocked"]:
            raise LedgerError(
                f"{user} has used {q['api_calls']} of {hard_cap} questions "
                f"today. Previously answered questions are still available and "
                f"cost nothing; only new ones are capped.")

    key = question_key(tool, question)
    conn.execute(
        "INSERT INTO answers (question_key, tool, question, answer, created_day)"
        " VALUES (?,?,?,?,?) ON CONFLICT(question_key, tool) DO NOTHING",
        (key, tool, question, answer, day))
    aid = conn.execute("SELECT id FROM answers WHERE question_key=? AND tool=?",
                       (key, tool)).fetchone()["id"]
    conn.execute("UPDATE answers SET served = served + 1 WHERE id=?", (aid,))
    cur = conn.execute(
        "INSERT INTO interactions (day, user, tool, question, question_key, "
        "answer_id, served_from) VALUES (?,?,?,?,?,?,?)",
        (day, user, tool, question, key, aid, served_from))
    col = "api_calls" if served_from == "api" else "cached_calls"
    conn.execute(f"INSERT INTO usage (user, day, {col}) VALUES (?,?,1) "
                 f"ON CONFLICT(user, day) DO UPDATE SET {col} = {col} + 1",
                 (user, day))
    conn.commit()
    return cur.lastrowid


def mark_outcome(conn, interaction_id, outcome):
    """Record whether the answer actually helped, and re-rank it.

    `did_not_help` demotes immediately and unconditionally. An answer that
    failed a student is not improved by having satisfied three others - it is
    an answer that is right sometimes, which is the worst thing to serve
    automatically.
    """
    if outcome not in ("resolved", "did_not_help"):
        raise LedgerError(
            f"outcome must be 'resolved' or 'did_not_help', not {outcome!r}. "
            f"An unrecorded outcome leaves the answer unproven, which is the "
            f"safe default - but guessing one would promote answers nobody "
            f"confirmed.")
    row = conn.execute("SELECT answer_id FROM interactions WHERE id=?",
                       (interaction_id,)).fetchone()
    if row is None:
        raise LedgerError(f"No interaction {interaction_id}.")
    aid = row["answer_id"]
    conn.execute("UPDATE interactions SET outcome=? WHERE id=?",
                 (outcome, interaction_id))
    field = "resolved" if outcome == "resolved" else "unhelpful"
    conn.execute(f"UPDATE answers SET {field} = {field} + 1 WHERE id=?", (aid,))

    unhelpful = conn.execute("SELECT unhelpful FROM answers WHERE id=?",
                             (aid,)).fetchone()["unhelpful"]
    resolvers = conn.execute(
        "SELECT COUNT(DISTINCT user) AS n FROM interactions "
        "WHERE answer_id=? AND outcome='resolved'", (aid,)).fetchone()["n"]
    if unhelpful > 0:
        status = "demoted"
    elif resolvers >= MIN_RESOLVERS_TO_TRUST:
        status = "trusted"
    else:
        status = "unproven"
    conn.execute("UPDATE answers SET status=? WHERE id=?", (status, aid))
    conn.commit()
    return {"answer_id": aid, "status": status,
            "distinct_resolvers": resolvers, "unhelpful": unhelpful,
            "why": ("Demoted: it failed at least one student. An answer that "
                    "is right sometimes is the worst thing to serve "
                    "automatically." if status == "demoted" else
                    f"Trusted: {resolvers} distinct users resolved with it."
                    if status == "trusted" else
                    f"Not yet trusted: {resolvers} of "
                    f"{MIN_RESOLVERS_TO_TRUST} distinct resolvers.")}


def classify(question):
    """Is this asking about a failure, or about a concept? A heuristic."""
    q = str(question).lower()
    if _FAILURE_WORDS.search(q):
        return "failure"
    if _CONCEPT_WORDS.search(q):
        return "concept"
    return "unclear"


def promotion_candidates(conn, min_users=3):
    """Repeated questions, split into 'fix the tool' and 'genuine FAQ'.

    The default reading of a repeated question is that the tool did not explain
    itself when it mattered. Writing an FAQ entry answers it while leaving the
    cause alone, and every student after that pays the same confusion before
    finding the entry. So the count is reported as a DEFECT SIGNAL, and only
    questions that no interface change would prevent are put forward as FAQ.
    """
    rows = conn.execute(
        "SELECT question_key, tool, MIN(question) AS question, "
        "COUNT(DISTINCT user) AS users, COUNT(*) AS asks "
        "FROM interactions GROUP BY question_key, tool "
        "HAVING users >= ? ORDER BY users DESC", (min_users,)).fetchall()

    fix_tool, faq = [], []
    for r in rows:
        kind = classify(r["question"])
        ans = conn.execute("SELECT answer, status, resolved, unhelpful FROM "
                           "answers WHERE question_key=? AND tool=?",
                           (r["question_key"], r["tool"])).fetchone()
        item = {
            "tool": r["tool"], "question": r["question"],
            "distinct_users": r["users"], "times_asked": r["asks"],
            "kind": kind,
            "answer_status": ans["status"] if ans else None,
            "resolved": ans["resolved"] if ans else 0,
            "unhelpful": ans["unhelpful"] if ans else 0,
        }
        if kind == "concept":
            faq.append(item)
        else:
            item["defect_signal"] = r["users"] >= DEFECT_SIGNAL_USERS
            item["recommendation"] = (
                f"{r['users']} different students hit this in {r['tool']}. "
                f"Treat it as a defect in the tool first: the answer belongs "
                f"where the confusion happens - in the dialog, the error text, "
                f"or the tool's stated operating envelope - not in a list they "
                f"have to go and find. Write an FAQ entry only if you conclude "
                f"no interface change would prevent it.")
            fix_tool.append(item)

    return {
        "fix_the_tool": fix_tool,
        "genuine_faq": faq,
        "n_fix": len(fix_tool), "n_faq": len(faq),
        "default_is_defect": True,
        "why": ("A question asked by many students is evidence about the tool "
                "before it is evidence about the documentation. An FAQ that "
                "grows while the interface stays confusing has hidden the "
                "problem rather than solved it - the confusion stops being "
                "reported without ever stopping."),
        "human_decides": ("Classification is by keyword and is only a prompt "
                          "for judgement. Nothing is published from here "
                          "automatically."),
    }


def usage_report(conn, day=None):
    """Per-user spend, for monitoring rather than policing."""
    if day:
        rows = conn.execute("SELECT user, api_calls, cached_calls FROM usage "
                            "WHERE day=? ORDER BY api_calls DESC",
                            (day,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT user, SUM(api_calls) AS api_calls, "
            "SUM(cached_calls) AS cached_calls FROM usage "
            "GROUP BY user ORDER BY api_calls DESC").fetchall()
    users = [dict(r) for r in rows]
    api = sum(u["api_calls"] or 0 for u in users)
    cached = sum(u["cached_calls"] or 0 for u in users)
    return {
        "day": day, "users": users,
        "total_api_calls": api, "total_cached_calls": cached,
        "cache_hit_rate": round(cached / max(api + cached, 1), 4),
        "note": ("A rising cache hit rate means the ledger is working. A "
                 "single user far above the rest is usually a loop or a stuck "
                 "dialog, not a keen student - check before raising their cap."),
    }
