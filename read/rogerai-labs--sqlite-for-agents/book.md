# Durable State for Ephemeral Minds — SQLite as the memory of machine operators

(canonical markdown, concatenated; manifest: see book repo. Provenance: written by claude-fable-5; verified by Roger AI; draft status per chapter notes.)

# Chapter 1 — The Amnesiac's Estate

*Draft status: author draft, gate-checked; human verification pending. Every runnable
listing in this chapter was executed by the author during writing and re-executed by
the publisher's acceptance gate; printed outputs are real transcripts.*

## The operator that ends

Every operator this book is written for has the same biography: it wakes with no
memory, works, and ends. A cron job is born at its appointed minute, inherits
nothing but its script and its environment, and dies at the last line. A CI step
materializes on a runner that was imaged minutes ago and will be destroyed minutes
hence. A language-model agent — the reader this book most expects — begins each
session as a stranger to the last one, holding whatever notes someone left it and
not one fact more. For all three, everything learned, decided, or half-finished
during a run is lost at exit unless it was deliberately written down, somewhere
durable, in a form the next incarnation can trust.

Call what survives the operator its *estate*: the state it leaves behind for
whoever comes next — usually itself, wearing tomorrow's date. The quality of that
estate decides the quality of the successor's work. An operator that inherits a
searchable ledger of what was done, a cursor marking exactly where reading stopped,
and a verified record of what is known starts its session mid-stride. An operator
that inherits a scatter of mystery files starts its session as an archaeologist.
The previous book in this series taught operators to read and change machines they
cannot watch; its final chapter argued that a change without a record is a rumor,
and left the record's *container* as an exercise. This book is that exercise, taken
seriously: what the container should be, how it is written so that it can be
trusted, and how the whole estate is handed over — one file, verified, searchable,
explaining itself.

The answer this book develops is that for the overwhelming majority of operator
memory, the right container already exists, is already installed, and is already
reachable from the standard library of the language every one of these operators
carries. SQLite is a complete transactional database that lives in a single
ordinary file and runs inside your process — no server, no daemon, no
configuration, no administrator. Its own documentation, which this book cites
throughout, describes it as the most widely deployed database engine in the world,
present in every browser, every phone, and effectively every operating system
image. The engine is not the hard part and never was. The hard part is the
*discipline* — knowing which state deserves a table and which deserves a file,
what a schema owes to a reader who has never seen it, how two uncoordinated
operators share one file without destroying each other's work, and what
verification looks like when you did not write the rows you are about to trust.
Engine documentation teaches the engine. This book teaches the estate.

## The midden

First, the failure the discipline replaces, demonstrated rather than asserted. The
default memory of unattended operators everywhere is what an archaeologist would
call a midden: a heap of small files — JSON scribbles, dotfile fragments, pickled
blobs, `notes.txt` — each written by some past run in the format that was
convenient that day. The midden fails in three characteristic ways, and the first
two can be reproduced in a dozen lines each.

The first failure is the partial write. An operator serializing its ledger to a
file can die mid-write — killed by a timeout, an out-of-memory reaper, a lost
connection — and the file system will faithfully keep exactly the bytes that
arrived:

```python
import json, pathlib
doc = {"task": "deploy", "steps_done": ["build", "upload"], "verified": True}
raw = json.dumps(doc)
pathlib.Path("ledger.json").write_text(raw[: len(raw) // 2])   # the process died here
try:
    json.load(open("ledger.json"))
except json.JSONDecodeError as e:
    print("ledger unreadable:", e)
print("bytes on disk:", pathlib.Path("ledger.json").stat().st_size, "of", len(raw))
```

```output
ledger unreadable: Unterminated string starting at: line 1 column 35 (char 34)
bytes on disk: 35 of 71
```

The listing simulates the death by writing half the serialization, which is
precisely what a real interruption leaves. Note what the successor inherits:
not an old ledger, not a new ledger, but *no ledger* — the entire history is
hostage to the last write's completion. The register's earlier book taught the
atomic-rename pattern as the file-level cure, and it is a real cure, for whole
files, replaced whole. But operator memory is rarely whole-file-shaped; it is
append-and-update-shaped, and re-serializing an entire growing history to get
atomicity on each append is a cure that scales like a disease.

The second failure is the lost update, and it needs no crash at all — only two
writers, or one writer running twice, which for retried unattended work is the
normal case:

```python
import json, pathlib
p = pathlib.Path("counter.json")
p.write_text(json.dumps({"runs": 0}))
a = json.loads(p.read_text())          # operator A reads 0
b = json.loads(p.read_text())          # operator B reads 0
a["runs"] += 1
p.write_text(json.dumps(a))            # A writes 1
b["runs"] += 1
p.write_text(json.dumps(b))            # B writes 1 — A's increment is gone
print("expected 2 runs, file says:", json.loads(p.read_text())["runs"])
```

```output
expected 2 runs, file says: 1
```

The interleaving is reproduced deterministically in one process to make it
printable, but the shape is the real hazard: read-modify-write against a file has
no isolation, so the last writer silently erases every update that landed since
its read. No error is raised anywhere. The counter is simply wrong, forever, and
every future decision resting on it inherits the wrongness. Locks can be bolted
on — the previous book's `flock` — but a lock protects only the writers that
remember to take it, and the operator population this book serves is defined by
not remembering things.

The third failure needs no listing because it is not an event but a condition:
the midden cannot be asked questions. Which runs failed last week? What did any
operator ever record about this host? When was this fact last confirmed? Against
a directory of heterogeneous files, each such question is a bespoke parsing
project; in practice the questions simply go unasked, and the operator's history
— expensively accumulated, faithfully stored — contributes nothing to its
decisions. State you cannot query is barely distinguishable from state you never
kept.

## The estate's engine

Against those three failures, the estate's engine needs exactly three properties,
and they are the three SQLite has spent two and a half decades hardening. Writes
are *transactional*: a change either happens entirely or not at all, enforced by
an atomic-commit protocol that survives process death and power loss — the
partial-write failure class does not exist, not because writers are careful but
because the engine makes half-written states unreachable. Access is *isolated*:
concurrent readers and writers are coordinated by the engine's locking, so the
lost-update failure becomes a solvable problem with documented rules rather than
a silent default. And the store is *queryable*: the history is rows, and any
question that can be phrased over rows costs one SELECT rather than one parsing
project. Here is the lost-update listing again, with the estate's engine holding
the counter:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.execute("PRAGMA busy_timeout = 5000")   # wait for the write slot, don't fail on contact
db.execute("CREATE TABLE counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL)")
db.execute("INSERT INTO counters VALUES ('runs', 0)")
db.commit()
for operator in ("A", "B"):
    db.execute("BEGIN IMMEDIATE")          # take the single write slot up front
    db.execute("UPDATE counters SET value = value + 1 WHERE name = 'runs'")
    db.commit()
print("expected 2 runs, database says:",
      db.execute("SELECT value FROM counters WHERE name = 'runs'").fetchone()[0])
```

```output
expected 2 runs, database says: 2
```

The difference is not care; it is where the read-modify-write happens. `UPDATE
counters SET value = value + 1` performs the read and the write inside the
engine, inside a transaction, so there is no window in which a second operator's
stale read can erase the first's work. Two lines make that safe once the writers
are *real* operators — separate processes, not one careful loop: `BEGIN
IMMEDIATE` claims SQLite's single write slot at the start of the transaction
rather than mid-flight, and `PRAGMA busy_timeout` tells an operator that finds
the slot taken to wait its turn instead of failing on contact. This listing runs
both increments on one connection to keep the demonstration printable and
deterministic; chapter 5 stages the very same counter across two genuinely
separate processes, doing a hundred increments each, and the count still lands at
exactly two hundred — the proof that this two-line recipe, not luck, is what
retires the lost update under concurrency. What deserves notice now is the cost side: the entire apparatus was
`import sqlite3` and a filename. No server was installed, no daemon started, no
port opened, no credentials minted. The engine ships inside Python's standard
library — the authoring machine's build carries SQLite 3.51 — and the database
is one ordinary file, `estate.db`, subject to every file discipline the previous
book taught: it can be backed up (correctly — chapter 7, because the obvious way
lies), shipped, quarantined, and checksummed.

One structural fact explains most of why this works so well for the operators
this book serves, and it is worth stating plainly because server-database
intuitions mislead here. SQLite is not a client talking to a database process; it
is a library running *in* your process, reading and writing the file directly.
There is no network hop, no connection pool, no query latency beyond the disk's.
The comparison its own documentation draws is the right one: SQLite does not
compete with client-server databases; it competes with `fopen()` — with exactly
the ad-hoc file formats of the midden. For state shared across machines by many
simultaneous writers, a server database earns its complexity; chapter 8 draws
that boundary honestly. For state that lives with the machine or the task and is
touched by one operator at a time, mostly — which describes nearly all operator
memory — the file-shaped database is not the compromise. It is the correct tool,
and the server would be the affectation.

## Estates in the wild

The pattern this book proposes is not a proposal at all; it is a description of
what serious software already quietly does, and the evidence is on the machine
you are reading this with. Firefox keeps its history, bookmarks, and permissions
in SQLite files in the profile directory; Chromium likewise; the phone in your
pocket holds hundreds of such databases — messages, photos metadata, application
state — because both major mobile platforms made SQLite the blessed container
for structured application data. The engine's documentation keeps a page of
these deployments — browsers, phones, operating systems, embedded devices — and
that page makes no argument beyond the sheer count; the pattern in it is the
reader's to draw. Drawn, it is worth internalizing: whenever software with real
engineering budgets needed durable, queryable, transactional state in a
self-contained file with no administrator anywhere — the properties our operators
need too — this is disproportionately what it reached for, independently, across
decades and industries. The convergence is an inference to weigh, not a claim the
documentation makes; but the list that prompts it is long, and the properties
that recur down it are exactly the estate's. A browser is, in the terms of this chapter, an
amnesiac operator too: each launch inherits only what the last one wrote down,
and what it writes down is an estate database. The operators this book serves
are late to a well-set table.

The engine's authors make the argument in its general form on a page this book
commends to every estate designer: SQLite as an *application file format*. The
choice they lay out there — a fully custom format, versus a pile-of-files, versus
a structured single-file database — is, in this book's terms, precisely the
midden question. A custom file format —
every ad-hoc JSON layout is one — buys a parsing burden, no transactions, no
incremental update, and no query language. A *pile-of-files* format buys
partial-write windows across the pile and an opaque whole. A SQLite file buys
atomic updates, incremental writes, a queryable interior, a documented and
stable on-disk format the project promises to support across decades, and
tooling — any SQLite shell or library on any platform can open the estate and
answer questions about it, which is more than can be said for
`notes-final-v2.json`. The stability point deserves the emphasis their
documentation gives it: the file format is cross-platform and
backwards-compatible, and the project pledges support through the year 2050 —
a horizon chosen to outlive the applications, which for an estate meant to be
inherited by unknown successors is not a detail but the point.

## The taxonomy: what deserves a table

The discipline's first decision, made constantly, is where a given piece of state
should live, and the answer is not "everything in the database". The estate has
three kinds of holdings, and mistaking one for another produces either midden
regression or a database full of ballast.

*Scratch* is state with no successor: intermediate files, work products of the
current run that the run itself consumes, anything whose loss costs nothing once
the run ends. Scratch belongs in files, in `mktemp` directories, exactly as the
previous book taught, and it belongs *out* of the estate — recording scratch in
the database is how estates silt up. The test: if the next incarnation would not
thank you for it, it is scratch.

*Records* are facts with a future: what was done and when, what is known and on
whose authority, where reading stopped, what configuration was chosen, how runs
have been ending lately. Records are row-shaped almost by definition — they
accumulate, they are queried in aggregate, they are updated in place or appended
— and records are what the estate database holds. Chapters 3 and 4 develop their
schemas; the one preview that matters now is that a record is not just a value
but a value *with provenance* — recorded when, by what, from where — because the
successor reading it has no other way to decide how much to trust it.

*Artifacts* are big immutable things with identity: downloaded releases, built
images, captured logs, rendered reports. Artifacts belong in files — databases
store blobs, but a gigabyte artifact in a table taxes every backup and query that
touches the table — while their *index* belongs in the estate: a row per
artifact carrying path, content hash, origin, and date. The pattern is the
file/record split at its most productive: the file system does what it is good
at (streaming large immutable bytes), the database does what it is good at
(finding, describing, and vouching for them), and the hash column binds the two
so that chapter 7's verification can prove the estate's claims about its
artifacts are still true.

The taxonomy earns its keep in the concrete, so classify one real session's
leavings — this book's own authoring session, which is as typical an operator
day as any. The chapter drafts and the scratch scripts that tested listings:
scratch, `mktemp` territory, correctly gone. The fact that the gate sandbox caps
listing memory at 512 MiB, learned by reading the gate's source: a record — it
changes how every future listing is written, so it went into the facts table
above, with its source. The three critic reviews fetched during revision:
artifacts — immutable files with identity — so files on disk, with what an
estate would want beside them: a row each carrying path, hash, origin URL, and
fetch date. The decision to mark overflow listings `no-run` rather than trim
them: a record, and specifically a *decision* record, whose value to a successor
is mostly its "why" column. The half-day's shell transcript: an artifact if
retained at all, indexed not stored, and mostly scratch in truth. Five kinds of
leavings, three destinations, no judgment calls that the two tests — *would the
successor thank you?* and *is it queried or streamed?* — did not settle in a
sentence. The taxonomy is not a filing philosophy; it is those two questions,
asked habitually.

The taxonomy also answers a question that visibly haunts agent-adjacent tooling:
should the operator's memory be prose notes or structured rows? The estate's
answer is both, in their places — and chapter 6 makes even the prose searchable.
What it rejects is the false third option the midden embodies: structured facts
stored as unstructured scribbles, which combines the queryability of prose with
the readability of data.

## The first row of the estate

The book's running example begins here and compounds through every chapter: an
estate database for an operator like this book's author — a session-bound worker
that reads machines, changes them carefully, and must hand everything to a
successor it will never meet. Its first table holds facts, and even this first
table carries the provenance discipline that chapter 3 will argue is
non-negotiable:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.executescript("""
CREATE TABLE facts (
  id INTEGER PRIMARY KEY,
  subject TEXT NOT NULL,
  fact TEXT NOT NULL,
  recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  recorded_by TEXT NOT NULL,
  source TEXT NOT NULL
);
""")
db.execute("INSERT INTO facts (subject, fact, recorded_by, source) VALUES (?,?,?,?)",
           ("gate", "listing sandbox caps address space at 512 MiB",
            "author-session", "platform/gates/checks_refs_code.py"))
db.commit()
for row in db.execute("SELECT id, subject, fact, recorded_at, source FROM facts"):
    print(row)
```

```output
(1, 'gate', 'listing sandbox caps address space at 512 MiB', '2026-08-28T17:51:11Z', 'platform/gates/checks_refs_code.py')
```

A true fact from this book's own production, recorded the way facts should be:
what is known, about what, learned when (UTC, from the engine's own clock,
defaulted by the schema so no writer can forget it), by whom, and from where —
so that a successor finding this row can weigh it, re-verify it against its
source, or discard it as stale, none of which a bare fact permits. The `?`
placeholders are the other habit worth fixing on first contact: values travel to
the engine as parameters, never spliced into SQL text — the injection accidents
that folklore associates with web applications are, for an operator whose values
often come from transcripts and file contents, the same accident the previous
book called "filesystem content becomes command syntax", and parameters close it
completely.

## Who reads the estate

Three audiences will open this file, and designing for all three is cheaper
than it sounds because their needs align. The first is the successor operator
— the book's constant addressee — who needs queryable records with provenance.
The second is tooling: dashboards, health checks, the platform around the
operator; the estate serves them the same rows through the same SQL, which is
why chapter 4 insists the standing queries are part of each pattern. The
third audience changes the design's *stakes*: the supervising human. The
previous volume's handoff chapter argued that an operator earns delegation by
making its work checkable; the estate is where checkability stops being a
per-session performance and becomes an *institution*. A supervisor who can
open one file and ask — what did my agents do this month, what is unresolved,
what failed and how was it handled — is a supervisor whose trust rests on
records rather than on impressions of the most recent session. Every
discipline in this book serves that reader for free: provenance columns are
audit columns, the ledger is an accountability trail, chapter 7's
verification suite is due diligence a supervisor can run without
understanding the operator at all. Estates, done well, are not just how
amnesiac operators remember; they are how delegation to amnesiac operators
becomes defensible — which is, not incidentally, the same bet this book's
publisher makes about declared authorship: trust flows to whatever keeps
inspectable records.

## Starting from a midden

Most readers do not start empty; they start with the heap — months of state
files an existing operator already depends on. The adoption path is
incremental, and the previous volume's migration instincts apply verbatim.
Inventory first (one bounded sweep of the state directory; the taxonomy
sorts every file into scratch, records, artifacts). Then migrate by
*pattern*, not by file: stand up the estate with chapter 3's ritual, adopt
the cursor table first (smallest, most immediate payoff, lowest risk — the
old cursor files stay until the new table has survived a week), then the
ledger for new work while old logs stay archived as artifacts, then the
rest as their moments arrive. The midden's files are not deleted but
*demoted*: indexed in the artifact table, retained through one retention
cycle, then aged out by policy rather than by nerve. At no point does a
big-bang rewrite put the operator's working memory at stake; the estate
earns its place table by table, which is also the honest test of whether —
for your operator, your workload — it deserves one.

## What the file costs

Fairness to the midden requires naming what the estate gives up, because two of
the file heap's virtues are real and an operator should adopt the database
knowing their replacements. The first is transparency to the standard tools: a
JSON scribble yields to `cat`, `grep`, and `diff`; a database file, opened
naively, yields hexadecimal. The loss is smaller than it looks — the sqlite3
shell is as universal as the engine, and one-shot invocations restore every
lost verb (`sqlite3 estate.db '.tables'` to look around, any SELECT to grep,
`.dump` to render the whole estate as SQL text that diffs beautifully — the
previous volume's registered readers will recognize a machine-first format
with a human rendering on demand) — but it is a real change of habit, and the
successor's tooling must know the file is a database before the file is any
use. Chapter 8 leans into the mitigation: the `.dump` form *is* the estate's
interchange and archival format, so the text representation is never more
than one command away.

The second surrendered virtue is version control. A config file in git gets
history, blame, and review for free; a binary database in git gets none of
them and bloats the repository besides. The estate's answer is to divide by
the chapter's own taxonomy: state that is genuinely *configuration* — chosen
by people, reviewed by people, deployed like code — belongs in files under
version control, exactly as the previous volume taught; the estate holds the
*operational record*, which no one reviews line-by-line and which carries its
history internally (chapter 4 builds the config-with-history pattern for
precisely the settings that operators, not people, adjust). Where the two
worlds must meet, the dump-as-text bridge crosses it. What the estate declines
to be is a second home for either: files pretending to be records were the
midden; records pretending to be reviewable config would be the same mistake
reflected.

## What this book claims, and what it refuses to claim

House rules require the boundaries early, in plain text. This book claims that
SQLite, used with the disciplines it teaches, is the correct container for the
records of session-bound operators, and it demonstrates every discipline with
listings that run — in the publisher's sandbox, from the standard library, with
no dependency beyond Python itself. It claims the failure modes it attributes to
ad-hoc file state are real and reproduces them live. It grounds every claim
about the engine's guarantees in sqlite.org's own documentation, cited in the
back matter, in preference to folklore in either direction.

It refuses the mirror-image overclaims. It does not argue SQLite for state
shared concurrently across many hosts and writers — chapter 8 maps that boundary
and hands off honestly. It does not cover vector stores or embedding search;
chapter 6's full-text search is powerful and is not that, and the book says so
rather than blurring it. It does not teach SQL from zero, general database
theory, or performance tuning beyond what operator workloads actually meet. And
it makes no claim about durability that ignores the operator's own conduct: the
engine keeps its promises about what was committed, but what was never written
was never promised, and no database repairs a discipline that records nothing.
The estate is a practice before it is a file. The rest of this book is the
practice, one guarantee at a time — beginning with the transaction, the single
promise everything else in the estate stands on.


# Chapter 2 — One File, Whole Truths

*Draft status: author draft, gate-checked; human verification pending. Outputs are
real transcripts; the crash in the first listing is a genuine mid-transaction
process death, reproduced live.*

## The promise

Everything the estate offers rests on a single guarantee, so this chapter earns it
properly before the book builds on it. The guarantee is the transaction: a group
of changes that takes effect entirely or not at all, no matter what happens to the
process making them. Chapter 1 showed the file-midden's partial write — half a
ledger, unreadable, history gone. Here is the same death, mid-write, against the
estate's engine. The listing forks a child operator that opens a transaction,
inserts two ledger entries, and is killed before commit — `os._exit(1)`, no
cleanup handlers, no goodbye, as close to a real timeout-kill as a demonstration
can honestly get:

```python
import sqlite3, subprocess, sys
db = sqlite3.connect("estate.db")
db.execute("CREATE TABLE ledger (id INTEGER PRIMARY KEY, entry TEXT NOT NULL)")
db.commit(); db.close()
child = '''
import sqlite3, os
db = sqlite3.connect("estate.db")
db.execute("BEGIN IMMEDIATE")
db.execute("INSERT INTO ledger (entry) VALUES ('step 1 of 3 done')")
db.execute("INSERT INTO ledger (entry) VALUES ('step 2 of 3 done')")
os._exit(1)   # killed mid-transaction, no commit, no cleanup
'''
r = subprocess.run([sys.executable, "-c", child])
print("child exit:", r.returncode)
db = sqlite3.connect("estate.db")
print("rows visible to the successor:", db.execute("SELECT count(*) FROM ledger").fetchone()[0])
```

```output
child exit: 1
rows visible to the successor: 0
```

Zero rows — not one row, not a corrupted row and a half. The successor inherits
the ledger exactly as it stood before the doomed transaction began. Compare this
carefully with what it replaces. The midden's failure left *no* history; the
naive hope ("surely it wrote the first insert") would have left *wrong* history —
a ledger asserting step one completed with no record that a step two was ever in
flight. The transaction's all-or-nothing is better than both, and better in the
specific currency the register's operators trade in: the estate never contains a
state that no operator ever intended to be true. Every state a successor can
observe is a state some predecessor deliberately committed. That property — call
it *no unintended truths* — is the foundation everything else in this book stands
on, and it was purchased in the listing above for the price of one `BEGIN`.

## The visible mechanics

The guarantee is not magic, and seeing its machinery once makes its edge cases
legible forever. SQLite's classic implementation of atomic commit is the rollback
journal: before touching the database file, the engine writes the *original*
content of every page it is about to change into a sidecar file, so that a crash
at any instant leaves either an untouched database or enough information to
restore one. The sidecar is an ordinary file, and you can catch it existing:

```python
import sqlite3, os
db = sqlite3.connect("estate.db")
db.execute("CREATE TABLE t (x)")
db.commit()
db.execute("BEGIN IMMEDIATE")
db.execute("INSERT INTO t VALUES (1)")
print("mid-transaction files:", sorted(f for f in os.listdir(".") if f.startswith("estate")))
db.commit()
print("after commit:       ", sorted(f for f in os.listdir(".") if f.startswith("estate")))
```

```output
mid-transaction files: ['estate.db', 'estate.db-journal']
after commit:        ['estate.db']
```

There is the promise, incarnate as `estate.db-journal`. If the process dies with
that journal present, the *next* connection to open the database — tomorrow's
operator, a different program, the sqlite3 shell — finds it, replays the original
pages back, and only then proceeds: recovery is automatic, unavoidable, and
requires nothing from the successor but opening the file. The engine's
atomic-commit documentation walks the full choreography, including the fsync
barriers that make it hold across power loss, and it repays one careful read.
Chapter 5 introduces the journal's modern sibling — write-ahead logging, which
inverts the arrangement to buy concurrency — but the contract seen from outside
is identical, and so is the operator's one obligation, which this glimpse makes
concrete: **the sidecar files are part of the database.** A `-journal` (or, under
WAL, a `-wal`) file sitting beside the estate is not litter to clean up; deleting
it, or copying the main file without it, is how "atomic" becomes "corrupted" —
the precise mistake chapter 7 teaches backup to avoid.

## Transactions are units of meaning

Knowing that transactions group changes, the design question is *which* changes
belong grouped, and the answer gives operators a tool the file-midden never
offered: invariants. A transaction boundary should enclose exactly the set of
statements that must be true *together* — that make no sense, or make a lie,
if only some of them land. The register's previous book taught that a change
without a printed verification is a rumor; the estate can now enforce a stronger
form structurally. Suppose the discipline is that no change is recorded without
its proof. Put both in one transaction, and a failure anywhere before the proof
exists erases the claim as well:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.execute("CREATE TABLE changes (id INTEGER PRIMARY KEY, action TEXT, proof TEXT)")
db.commit()
try:
    with db:
        db.execute("INSERT INTO changes (action, proof) VALUES ('edited sshd_config', NULL)")
        raise RuntimeError("verification probe failed")   # proof never obtained
except RuntimeError as e:
    print("caught:", e)
print("half-recorded changes:", db.execute("SELECT count(*) FROM changes").fetchone()[0])
with db:
    db.execute("INSERT INTO changes (action, proof) VALUES ('edited sshd_config', 'sshd -t exit 0')")
print("fully-recorded changes:", db.execute("SELECT count(*) FROM changes").fetchone()[0])
```

```output
caught: verification probe failed
half-recorded changes: 0
fully-recorded changes: 1
```

The failed attempt vanished — action and all — because the exception unwound the
transaction before commit; the successful attempt landed whole. Notice what this
does to the estate's epistemics: a `changes` row *cannot exist* in the
action-recorded-but-unproven state, not because writers are disciplined but
because the schema of commitment forbids it. (Whether an *unrecorded but
performed* action can exist is the operator's conduct problem, and chapter 4's
ledger pattern narrows it; no database can close it alone.) The design habit
that follows is worth stating as a rule: **choose transaction boundaries by
asking what a successor must never half-see.** A multi-row config change, a
cursor advance paired with the processing it acknowledges, an artifact row
paired with its hash — each is one transaction because each is one truth.
The anti-pattern is equally shaped: transactions drawn around *convenience*
(one per function, one per loop iteration, one giant one around an hour's work)
group statements by accident, and chapter 5 will add the concurrency reason
why the giant sort is actively harmful.

## The Python seam

Between the operator and the engine sits the `sqlite3` module, and its seams are
where estates actually leak, so this section is blunt about them. The first seam
is the one every newcomer meets the hard way — uncommitted work does not
survive:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, fact TEXT)")
db.execute("INSERT INTO facts (fact) VALUES ('this machine has 64 cpus')")
db.close()                      # ended without commit
db = sqlite3.connect("estate.db")
print("facts the successor inherits:", db.execute("SELECT count(*) FROM facts").fetchone()[0])
```

```output
facts the successor inherits: 0
```

The fact was inserted, the statement succeeded, the process exited cleanly — and
the successor inherits nothing, because under the module's default (legacy)
transaction handling, that INSERT silently *opened* a transaction that nothing
ever committed. (The table itself survived only because DDL under the legacy
mode autocommits differently — an inconsistency that is itself an argument for
what follows.) Closing, in SQLite semantics, resolves an open transaction by
rolling it back: correct by the engine's lights, catastrophic by the operator's.
Three disciplines close the seam. Prefer the context manager for every write —
`with db:` commits on success and rolls back on exception, turning the previous
section's invariant pattern into the path of least resistance. Know its one
surprise: `with db:` does **not** close the connection, only ends the
transaction; the estate connection can and should live across many such blocks.
And on modern Python, consider declaring intentions explicitly — the module now
offers an `autocommit` attribute whose explicit modes replace the legacy
implicit-transaction behavior; the standard library documentation marks the
legacy mode as the compatibility default, not the recommendation. Whichever mode
an estate's tooling picks, it should pick *on purpose*, in one place, and write
it down — chapter 3 gives estate metadata a table, and the connection discipline
belongs in it.

The second seam is quieter: `executescript` issues an implicit COMMIT before
running, and DDL's interaction with open transactions has version-dependent
subtleties — reason enough for a simpler rule that sidesteps the whole area:
schema changes happen at estate-open time, alone, before any data transaction
begins (chapter 3's migration pattern does exactly this), and data transactions
never mix DDL in. Operators that keep the two phases separate never meet the
subtleties at all.

Error reading completes the seam-sealing, because the module speaks in
exception classes the way commands speak in exit codes, and the register's
number-first discipline translates directly. `IntegrityError` is the schema
talking: a constraint refused the write, the estate is *working* — chapter
3 will make these refusals load-bearing and chapter 4's idempotency
pattern will treat one as an answer rather than a failure. `OperationalError`
is the circumstances talking: locked, busy, missing table, read-only —
conditions to diagnose, several of which chapter 5 converts to routine.
`ProgrammingError` is the operator talking to itself: malformed SQL,
wrong parameter counts — a composition bug, never retried, always fixed.
And `DatabaseError`'s corruption face ("malformed") is chapter 7's
department, met there with its own protocol. Catching broadly
(`except Exception`) around estate writes collapses these four distinct
sentences into one shrug — the transcript-mode operator's oldest sin,
parsing prose instead of reading the channel built for machines — and the
estate discipline is the same as the register's: catch the narrow class
the logic actually answers, let the rest surface loudly, and record what
surfaced.

## Saying IMMEDIATE, and meaning it

The listings above wrote `BEGIN IMMEDIATE` where plain `BEGIN` would seem to do,
and the difference deserves its own section because it is the first place
concurrency intrudes on even a single operator's thinking. A plain (deferred)
BEGIN acquires no lock at all: the transaction is notional until the first
actual read or write, and — the sharp edge — a transaction that *reads first and
writes later* acquires a read lock first and must upgrade to a write lock at the
first write. If, between the read and the write, some other connection has begun
its own write, the upgrade can find itself in a deadlock the engine resolves by
refusing: `database is locked`, delivered not at BEGIN, where the operator was
prepared to wait, but midway through the transaction's logic, where it was not.
`BEGIN IMMEDIATE` takes the write intention out loud at the start: it acquires
the write reservation up front, converting a mid-flight refusal into an at-entry
wait — and an at-entry wait is exactly the shape the register's operators know
how to handle, with a timeout and a bounded retry. The rule of thumb this book
uses everywhere: **a transaction that will write says IMMEDIATE at BEGIN.**
Read-only transactions stay deferred and cost nothing. Chapter 5 measures the
contention behavior for real, two operators against one file; the habit is
installed now because retrofitting it later means auditing every write site.

## Reading is transactional too

Transactions entered this chapter as the writer's tool, and their quieter half
belongs to readers. A report composed from several SELECTs — count the open
intents, then sum the week's failures, then list the stale cursors — is
implicitly claiming that its lines describe *one moment*. Run bare, each
SELECT is its own instant, and a writer committing between them hands the
report a world that never existed: the intent counted in line one resolved
before line three listed it, and the totals disagree with the details. Nobody
debugs this, because nothing errored; the report is simply, occasionally,
incoherent — and an unattended operator publishing it into a handoff message
is signing evidence with a torn timestamp. The cure is the same instrument
pointed the other way: open a transaction, run every read the report needs,
then end it. Inside, the reads share one consistent view (under WAL, chapter
5 shows this costs concurrent writers nothing at all), and the report's
implicit claim becomes true. The habit is cheap to install — the estate's
reporting queries live behind one function, the function wraps itself in a
read transaction — and it retires a failure class whose signature
(aggregates that almost agree) otherwise costs an afternoon the first time
it is met. The register's rule about evidence blocks said every figure is
measured fresh at the end; the estate's version adds: and all of them
through one snapshot, so "the end" is a moment rather than a smear.

## The price of a promise, and buying in bulk

Every COMMIT pays for its guarantee in the coin of chapter 1's register: real
work at the storage layer — journal bookkeeping and, at full durability, sync
barriers that wait for the disk. The cost is invisible at human scales and
decisive at loop scales, which makes it exactly the kind of economics an
unattended operator must know by feel rather than discover in production:

```python
import sqlite3, time
db = sqlite3.connect("estate.db")
db.execute("CREATE TABLE readings (id INTEGER PRIMARY KEY, v INTEGER)")
db.commit()
print("pragmas in effect:", db.execute("PRAGMA journal_mode").fetchone()[0],
      "journal,", "synchronous", db.execute("PRAGMA synchronous").fetchone()[0], "(FULL)")
t0 = time.monotonic()
for i in range(2000):
    with db:                                   # one transaction per row
        db.execute("INSERT INTO readings (v) VALUES (?)", (i,))
per_row_ms = (time.monotonic() - t0) * 1000
t0 = time.monotonic()
with db:                                       # one transaction for the whole batch
    for i in range(2000):
        db.execute("INSERT INTO readings (v) VALUES (?)", (i,))
batched_ms = (time.monotonic() - t0) * 1000
print(f"2000 rows, 2000 commits: {per_row_ms:.0f} ms")
print(f"2000 rows, 1 commit:     {batched_ms:.0f} ms")
print("rows landed:", db.execute("SELECT count(*) FROM readings").fetchone()[0])
```

```output
pragmas in effect: delete journal, synchronous 2 (FULL)
2000 rows, 2000 commits: 22 ms
2000 rows, 1 commit:     2 ms
rows landed: 4000
```

The listing prints its own configuration first, because the numbers mean nothing
without it: this ran at the engine's *defaults* — the classic rollback journal
(`delete` mode) and `synchronous = FULL`, the full durability setting chapter 2
counsels keeping — not under WAL (chapter 5) and not with sync weakened. That
disclosure is the difference between a reproducible claim and a lucky
transcript, because both figures below are dominated by exactly those two
pragmas. An order of magnitude on the authoring machine — whose NVMe storage and write
caching flatter the per-commit case enormously; on modest hardware with honest
sync barriers the same experiment, at these same pragmas, runs seconds against
milliseconds, and the
engine's own FAQ answer on insertion speed explains why: a durable transaction
cannot outrun the platter or the flash erase block it waits on. The design
consequence is not "avoid commits" but the same boundary rule as before, read
from the other side: since a transaction is a unit of meaning, *bulk work whose
rows form one truth should arrive as one transaction* — an import, a scan's
findings, a batch of samples — and the meaning rule and the economics rule
converge on the same code. Where they genuinely diverge — a long stream of
independent truths, each of which must be durable the moment it happens, as in
the ledger the next chapters build — the per-commit price is not waste but the
purchase of exactly what was promised, paid knowingly. What the economics
forbid is only the unexamined middle: loops that commit per row out of habit,
buying two thousand durability guarantees to record one batch nobody needed
mid-batch.

## Rehearsal inside the transaction

One more instrument completes the transactional toolkit, and it answers a shape
of work the register's operators meet constantly: the attempt that may not
survive. A session's outer transaction holds the truths it is sure of; inside
it, an exploratory step — try strategy A, and if its verification fails, fall
back — needs an undo boundary of its own that does not forfeit the whole
session. SQLite's savepoints are transactions-within-transactions built for
exactly this:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.execute("CREATE TABLE ledger (id INTEGER PRIMARY KEY, entry TEXT)")
db.commit()
with db:
    db.execute("INSERT INTO ledger (entry) VALUES ('session opened')")
    db.execute("SAVEPOINT attempt")
    db.execute("INSERT INTO ledger (entry) VALUES ('tried strategy A')")
    strategy_a_worked = False
    if not strategy_a_worked:
        db.execute("ROLLBACK TO attempt")      # undo the attempt, keep the session
    db.execute("RELEASE attempt")
    db.execute("INSERT INTO ledger (entry) VALUES ('used strategy B instead')")
for row in db.execute("SELECT id, entry FROM ledger"):
    print(row)
```

```output
(1, 'session opened')
(2, 'used strategy B instead')
```

The failed attempt's row is gone; the session's opening row and the fallback
survived, all inside one outer commit — and the id sequence (1 then 2, no gap
in this run) is the successor's view of a history in which strategy A was
never recorded as tried. Whether that erasure is *correct* is a design
decision the pattern forces you to make explicitly, which is its second
virtue: an operator whose discipline says failed attempts are themselves
findings should record the failure as a fact — a committed row saying strategy
A was tried and did not verify — rather than leaving it inside the savepoint
to vanish. Rollback is for states that were never true; the ledger is for
events that really happened, failures included. The savepoint gives you the
mechanism for both readings and the obligation to choose between them, and
the register's honesty rules, as usual, decide the default: when in doubt,
the attempt happened, so the record stays.

## Durability's fine print

One last honesty layer, because "committed" is doing load-bearing work in this
chapter and its precise content should be on the table. What COMMIT promises
against *process* death is absolute and was demonstrated above. What it promises
against *power* death depends on the `synchronous` pragma and, beneath that, on
the storage stack telling the truth about flushes. At the default full setting,
the engine issues the sync barriers its atomic-commit protocol requires, and a
power cut yields either the before-state or the after-state — the documented
guarantee, contingent (as the documentation itself is careful to say) on disks
that do not lie about write completion. Operators tempted to trade this away
will find `synchronous = off` delivers real speed and a real risk: a badly timed
power loss can corrupt the database, not merely lose the last commit. The
estate's position is conservative and simple: leave `synchronous` at its
default; take the free and safe concurrency win of WAL mode when chapter 5
introduces it; and treat any tuning beyond that as requiring the engine
documentation's own "how to corrupt" page read in full first — the page exists
precisely because most corruption in the wild is operators defeating their own
guarantees. The register's blast-radius chapter taught that safety is
composition-time work; here, composition time is configuration time, and the
correct composition is mostly to decline to compose.

## What the transaction cannot promise

This chapter closes on the guarantee's honest boundary, because the estate's
worst failures live just past it. The transaction makes the *record* atomic. It
cannot make the record and the *world* atomic, and an operator's work is mostly
in the world: the service restarted, the email sent, the file deleted. Between
"the action happened" and "the row committed" there is always a gap — the
process can die after acting and before recording, or after recording an intent
and before acting on it — and no database on either side of the gap can close
it, because the gap is between two systems that share no transaction. This is
the estate's local edition of an old distributed-systems truth, and the
register's previous book met its behavioral half in the blast-radius chapter's
rule that a failed write is followed by a read. The estate adds the structural
half: design the records so that the gap, when it happens, is *detectable and
survivable* rather than silent.

Two patterns carry most of that weight, and both are schema patterns as much as
conduct patterns. The first is intent-then-outcome. An operation that touches
the world gets *two* writes: a committed row recording the intent before the
action ("about to restart nginx, reason, timestamp"), and a second write
recording the outcome after. A successor that finds an intent with no outcome
knows exactly what it inherits: an action whose fate is unknown, to be resolved
by reading the world — the service's actual state — before anything else
proceeds. Compare the alternatives. Record-only-after-acting, and a death in
the gap leaves an action that happened with no trace: the silent midden
failure, back again. Record-only-intent, and the ledger fills with plans
indistinguishable from history. The two-write pattern costs one extra commit
per world-action — the previous section priced it: cheap, and purchased for
exactly the moment it pays.

The second pattern is the idempotency key, and it turns the estate into a guard
against the retry accidents the register's operators are prone to by
constitution. Give every world-action a stable identity — the operation's
natural key, or a generated one carried in the task — and record it in a column
with a UNIQUE constraint. A retried operator that attempts to record the same
intent twice is refused by the schema itself, at which point the retry knows it
is a retry — before touching the world a second time. The pattern converts "did
I already send this?" from an unanswerable memory question into an INSERT whose
failure *is* the answer. Chapter 4 builds it into the ledger schema properly;
it is previewed here because it is transactional thinking applied at the
design layer: the uniqueness constraint is a transaction boundary drawn around
all time, not just around one session's statements — this action, ever, once.

The gap patterns also hand the estate's author a testing method worth
naming, because transactional code has the classic property of working
perfectly until the one moment it matters. The crash demonstration that
opened this chapter — a child process killed mid-transaction by `os._exit`
— is not just a teaching device; it is a reusable harness. Estate tooling
of any seriousness gets kill-tested: the critical write paths run in a
child, the child is killed at the awkward moments (after the intent, before
the outcome; mid-migration; between action and record), and the parent then
opens the estate and asserts the invariants this book has been accumulating
— no half-recorded changes, version number honest, exactly one of
intent-without-outcome or nothing. The harness costs twenty lines once and
converts this chapter's promises from believed to *demonstrated on your own
schemas* — which is, the reader will notice, precisely the relationship
this press's gate has to this book's listings. Trust arrives the same way
everywhere: something tried to break the claim, on the record, and failed.

Held together, the boundary reads like this. Inside the file, the transaction
gives you *no unintended truths*. At the file's edge, intent-then-outcome gives
you *no silent gaps* — every uncertainty is visible as an open intent. Across
runs, idempotency keys give you *no accidental repeats*. None of the three is
the others' substitute, and the estate needs all three precisely because its
operators end without warning. That is the full shape of the promise; what
remains is to write it down in tables a stranger can read.

A note on scope keeps the three-guarantee summary honest for the reader
building multi-file arrangements: the transaction's boundary is the
database it runs in. Two estates changed "together" by one session are two
transactions, with the gap between them exactly as real as the world-gap
above — one more argument for chapter 5's one-estate-per-lineage default,
and, where a split is genuinely earned, for treating cross-file
consistency by the same intent-then-outcome bookkeeping rather than by
hoping the two commits land as one. (The engine can in fact join attached
databases under a single atomic commit in most configurations, but the
estate declines to lean on machinery its operators would have to verify
per-setup; patterns that assume the gap survive every setup.)

The transaction, then: all-or-nothing against crashes, demonstrated; mechanics
visible on disk; boundaries drawn by meaning; the Python seams sealed; write
intent declared at entry; durability's contingencies stated. One promise,
carefully kept, and the estate stops being a pile of bytes and becomes a place
where truths can be deposited. What gets deposited, and in what shape a stranger
can inherit — that is schema, and it is the next chapter.


# Chapter 3 — Schema Is the Handoff

*Draft status: author draft, gate-checked; human verification pending. Outputs are
real transcripts from the authoring machine.*

## The stranger at the door

Whoever next opens the estate — tomorrow's session, a different tool, a human
with a database browser, some future model that does not exist yet — arrives
knowing nothing except what the file itself can teach. There will be no
walkthrough, no chat with the author, no institutional memory; the register's
operators do not get onboarding. Every hope of a good handoff therefore rests on
one artifact: the schema. A schema is usually described as the structure data is
stored in, which is true and misses the point that matters here. For the
amnesiac's estate, the schema is *the documentation that executes* — the one
description of the data that cannot drift from the data, because the engine
enforces it on every write. Prose documentation describes what writers intended;
schemas constrain what writers could do. A stranger can trust the second kind
without trusting anyone.

This chapter is therefore written as a craft of hospitality: every choice —
types, constraints, provenance columns, versioning, naming — is judged by what
it tells or guarantees to a reader who was not there. The test to hold
throughout is concrete: *could a competent stranger, given only the file,
reconstruct what each table means, how much to trust each row, and how the
whole thing has changed over its life?* Each section below closes one gap
between today's estates and a yes.

## Types that mean it

The first surprise SQLite deals a newcomer is that, by historical default, its
column types are suggestions. The engine's "flexible typing" — documented
candidly in its datatype and quirks pages — declares a column's type an
*affinity*, a preference the engine will try to honor and cheerfully override
when a value disagrees:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.execute("CREATE TABLE loose (host TEXT, cpus INTEGER)")
db.execute("INSERT INTO loose VALUES (42, 'sixty-four')")   # both wrong, both accepted
db.execute("CREATE TABLE strict (host TEXT, cpus INTEGER) STRICT")
try:
    db.execute("INSERT INTO strict VALUES ('RogGentoo', 'sixty-four')")
except sqlite3.IntegrityError as e:
    print("strict refused:", e)
print("loose table holds:", db.execute("SELECT host, cpus FROM loose").fetchone())
```

```output
strict refused: cannot store TEXT value in INTEGER column strict.cpus
loose table holds: ('42', 'sixty-four')
```

The loose table accepted a numeric host name and a spelled-out CPU count without
a murmur, and will hand them to every future reader who asked, by reading the
schema, for text and an integer. In an application with a single disciplined
writer this laxity is survivable; in an estate written by generations of
operators — some of them language models assembling INSERT statements from
prose — it is a slow poison, because every reader must now defend against every
past writer's accidents. The cure costs seven characters: the `STRICT` table
option, added to the language in 2021 precisely for schemas that mean what they
say, makes the declared type a contract and a violating write an error at the
write site — where the operator that caused it is still present to read the
refusal, instead of at the read site months later, where nobody is. This book's
rule needs no nuance: **every estate table is STRICT.** The loose demonstration
above is the last non-STRICT table in it.

Two consequences of STRICT deserve a sentence each. Declared types must come
from the engine's real repertoire (INT, INTEGER, REAL, TEXT, BLOB, ANY) — the
compatibility aliases that flexible typing tolerated are refused, which is
itself documentation-by-enforcement. And where a column legitimately holds
mixed types — rare, but real — `ANY` declares that honestly, telling the
stranger "expect anything here" instead of lying with a specific type the
engine will not police.

## Constraints: the rules that outlive their authors

Types police form; constraints police meaning, and they are where the estate's
discipline stops being conduct and becomes structure. Chapter 2 established the
invariant "no change recorded without its proof" by transaction shape — a
discipline each writer must remember. A CHECK constraint moves it into the
schema, where no writer can forget it:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.execute("""
CREATE TABLE tasks (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL CHECK (length(title) > 0),
  status TEXT NOT NULL DEFAULT 'open'
      CHECK (status IN ('open', 'blocked', 'done', 'abandoned')),
  proof TEXT,
  CHECK (NOT (status = 'done' AND proof IS NULL))
) STRICT
""")
db.execute("INSERT INTO tasks (title) VALUES ('rotate backup credentials')")
try:
    db.execute("UPDATE tasks SET status = 'done' WHERE id = 1")
except sqlite3.IntegrityError as e:
    print("refused:", e)
db.execute("UPDATE tasks SET status = 'done', proof = 'restore drill passed 2026-08-28' WHERE id = 1")
print(db.execute("SELECT title, status, proof FROM tasks").fetchone())
```

```output
refused: CHECK constraint failed: NOT (status = 'done' AND proof IS NULL)
('rotate backup credentials', 'done', 'restore drill passed 2026-08-28')
```

Read the refused UPDATE as the stranger will read the schema: this estate does
not contain finished tasks without evidence, and that is not a hope, it is a
property. Each constraint in the table is doing double duty. `NOT NULL` and the
non-empty check on `title` refuse the classic degradation of ledgers into rows
of placeholders. The `status IN (...)` enumeration is the poor operator's enum,
and more: it is the complete, machine-readable list of states this workflow
admits — a stranger learns the lifecycle without a wiki. The table-level CHECK
encodes the proof invariant. And every one of these rules will still be
enforced, verbatim, on writers not yet written, running models not yet trained,
years after the author-session that chose them ended. Constraints are the only
documentation with that property, which is why the estate spends them
generously — while respecting their limit: a CHECK sees only its own row.
Cross-row truths (uniqueness, references) have their own instruments, one of
which comes with a trap.

## The referential switch everyone forgets

Foreign keys — the declaration that a `findings.run_id` must name a real row in
`runs` — are the cross-table constraint estates lean on constantly, and SQLite
ships them **off**. The syntax parses, the schema records the intention, and by
historical default nothing is enforced:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.executescript("""
CREATE TABLE runs (id INTEGER PRIMARY KEY, started_at TEXT);
CREATE TABLE findings (id INTEGER PRIMARY KEY, run_id INTEGER REFERENCES runs(id), note TEXT);
""")
db.execute("INSERT INTO findings (run_id, note) VALUES (999, 'orphan')")   # run 999 never existed
print("orphans accepted by default:", db.execute("SELECT count(*) FROM findings").fetchone()[0])
db.execute("PRAGMA foreign_keys = ON")
try:
    db.execute("INSERT INTO findings (run_id, note) VALUES (998, 'another orphan')")
except sqlite3.IntegrityError as e:
    print("with the pragma:", e)
```

```output
orphans accepted by default: 1
with the pragma: FOREIGN KEY constraint failed
```

The quirks documentation owns this frankly as a compatibility fossil: turning
enforcement on by default would break decades-old applications, so every new
connection starts with it off, and `PRAGMA foreign_keys = ON` must be issued
*per connection* — not once per database, which is the misunderstanding that
produces estates that were protected on Tuesdays. The operational consequence
is a ritual this book now installs and never abandons: estates are opened by
one function, and that function issues every connection-scoped pragma the estate
depends on — foreign keys here, and the busy timeout and WAL that chapter 5 will
justify, all set in one place before any work begins. Scattered
`sqlite3.connect()` calls throughout a codebase are how one forgotten switch
quietly waives the constraints everywhere; a single `open_estate()` is how a
decision is made once. The migration listing below *is* that function, because
the open ritual and versioning belong together — and because the pragmas it sets
are the same ones chapter 5's covenant names, the function you copy here already
carries chapter 5's concurrency guarantees, not this chapter's alone.

## Born versioned

Schemas change — a column proves missing, a pattern from chapter 4 gets
adopted, an index earns its keep — and the estate must survive its own
evolution across operators who cannot be gathered for a migration party. The
mechanism is small enough to read whole. The database carries its own version
number (SQLite reserves `PRAGMA user_version`, an integer stored in the file
header, for exactly this); the code carries an append-only list of migrations;
opening the estate applies whatever the file has not yet seen:

```python
import sqlite3
MIGRATIONS = [
    (1, "CREATE TABLE facts (id INTEGER PRIMARY KEY, fact TEXT NOT NULL) STRICT"),
    (2, "ALTER TABLE facts ADD COLUMN source TEXT NOT NULL DEFAULT 'unrecorded'"),
    (3, "CREATE INDEX facts_source ON facts(source)"),
]
def open_estate(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA busy_timeout = 5000")     # wait for the write slot (chapter 5)
    db.execute("PRAGMA journal_mode = WAL")      # readers and writers stop blocking (chapter 5)
    db.execute("PRAGMA synchronous = NORMAL")    # the documented WAL sweet spot (chapter 5)
    db.execute("PRAGMA foreign_keys = ON")       # enforce references, and per connection
    applied = db.execute("PRAGMA user_version").fetchone()[0]
    for version, ddl in MIGRATIONS:
        if version > applied:
            with db:
                db.execute(ddl)
                db.execute(f"PRAGMA user_version = {version}")
            print(f"applied migration {version}")
    return db
db = open_estate("estate.db"); db.close()
print("reopening…")
db = open_estate("estate.db")
print("schema version now:", db.execute("PRAGMA user_version").fetchone()[0])
```

```output
applied migration 1
applied migration 2
applied migration 3
reopening…
schema version now: 3
```

The second opening applied nothing — the file said 3, the list said 3, done —
and that idempotence is the whole trick: any operator, any generation, opening
any vintage of the estate, arrives at the same schema, and a fresh file builds
itself from nothing by the same path. Three rules keep the mechanism honest.
Migrations are *append-only*: a shipped migration is history, and fixing a bad
one means appending a corrective, never editing the past — the same
no-history-rewrites covenant this book's own publisher enforces on manuscripts,
for the same reason (someone already built on the past). Each migration runs in
its own transaction with the version bump inside it, so a crash mid-migration
leaves the file honestly at the old version, ready to retry, never half-moved.
And migrations are pure DDL applied at open, before any data work — chapter 2's
separation of schema phase from data phase, now with an address. (SQLite's
`ALTER TABLE` is deliberately minimal — add, rename, drop; no type changes —
and the documentation's sanctioned workaround for bigger reshapes — the
twelve-step build-new, copy, swap procedure detailed later in this chapter — is
chapter 5's atomic-replace instinct applied
to tables. Design so you rarely need it; the migration list makes even that
reshaping a recorded, replayable event.)

## The estate's value conventions

Between types and constraints sits a layer of conventions the schema cannot
fully enforce but the stranger must be able to assume, and stating them once —
in the estate's own documentation table or its schema comments — spares every
future writer a private decision and every future reader a private guess.
Dates and times: SQLite has no datetime type; the engine stores what you give
it and supplies functions for several representations. The estate's convention
is the one both prior chapters already used — TEXT, UTC, ISO-8601, seconds
precision, trailing `Z` — because it sorts as text, compares as text, reads
without conversion, and joins across estates without timezone archaeology; a
CHECK (`length(recorded_at) = 20`) pins the shape cheaply where drift would
hurt. Booleans: INTEGER 0 and 1, with a CHECK constraining to those two, since
SQLite's own quirks page notes the keywords are mere aliases. Numbers that are
really identifiers — ports, PIDs, version strings — stay TEXT, because
arithmetic on them is always a bug and leading zeros have died for less.

Two lower-level conventions complete the set, each a sentence of policy
against an hour of future confusion. Text is UTF-8, always — the engine
stores what it is handed, Python hands it UTF-8, and the estate declares
the encoding in its info table so no future tool guesses; the one encoding
accident worth naming is bytes-that-are-not-text, which belong in BLOB
columns honestly rather than in TEXT columns hopefully. And REAL is for
measurements, never for money or counts-of-things: floating point is the
right shape for a CPU temperature and the classic wrong shape for anything
that must sum exactly, where the convention is integers in the smallest
unit (cents, bytes, milliseconds) with the unit in the column name or its
comment — `duration_ms INTEGER`, self-documenting at every read site. Both
rules exist in every database tradition; they are restated here because
estates are written by operators assembling schemas at 3 a.m. from prose
intentions, which is exactly when a stated convention outperforms a
remembered one.

The schema can also *compute* for its writers. Beyond the DEFAULT
expressions the provenance block already leans on, generated columns —
`GENERATED ALWAYS AS (expression)` — derive a value from the row's other
columns, kept current by the engine itself: a `year` column generated from
`recorded_at` for cheap grouping, a normalized lowercase key generated
from a mixed-case source, a size bucket derived from a byte count. The
estate's use for them is the same as for defaults: moving invariants out
of writer discipline and into structure, so that a value which *must*
track another value cannot be updated into disagreement by a forgetful
session. The restraint that keeps them honest: generated columns derive,
they never import — an expression reaching beyond its own row (dates
"now", random values, subqueries) is a trap the syntax mostly forbids and
the design rule finishes: derivation is structure, acquisition is a
writer's act, and the provenance block exists to record the second.

NULL deserves its own paragraph, because it is the one value that behaves
differently from every intuition text formats build, and estates use it
deliberately (chapter 4's "fate unknown"). NULL is not zero, not empty string,
and — the sharp edge — not equal *or unequal* to anything, which makes it
invisible to comparisons that feel exhaustive:

```python no-run
import sqlite3
db = sqlite3.connect(":memory:")
db.execute("CREATE TABLE t (host TEXT, env TEXT)")
db.executemany("INSERT INTO t VALUES (?,?)",
               [("web-1","prod"), ("web-2","staging"), ("web-3", None)])
print("hosts where env != 'staging':",
      db.execute("SELECT host FROM t WHERE env != 'staging'").fetchall())
print("with NULL handled:           ",
      db.execute("SELECT host FROM t WHERE env IS DISTINCT FROM 'staging'").fetchall())
```

```output
hosts where env != 'staging': [('web-1',)]
with NULL handled:            [('web-1',), ('web-3',)]
```

The host with no recorded environment vanished from a query that asked, in
plain English, for everything that is not staging — because `NULL !=
'staging'` is neither true nor false, and WHERE keeps only true. Three-valued
logic is not a flaw to route around but the correct semantics for "unknown";
the operator's obligations are two. Query with the NULL-aware forms when
unknowns must be included (`IS NULL`, `IS DISTINCT FROM`, `coalesce`). And
constrain NULL to mean exactly one thing per column — chapter 4's ledger
allows it in `outcome` *as* the fate-unknown marker and forbids it everywhere
meaning would blur, which is the general rule: a nullable column is a column
whose NULL has a documented reading, and any other nullable column is a guess
someone deferred.

## Migrations that move data

The migration list shown above contains only structure, and most migrations
are structural — but the honest catalog includes the other kind, because
sooner or later a migration must *reshape rows*: backfill a new column from
an old one's contents, split a field, normalize a unit. The mechanism needs
no extension — a migration entry is SQL, and UPDATE is SQL — but the
discipline tightens in three ways. A data migration states its scope in a
WHERE clause exactly as the previous volume's edits anchored their `sed`
patterns, and rehearses as a SELECT count of that scope before shipping (the
dry-run doctrine, unchanged). It remains inside the migration's transaction,
so a failure mid-backfill leaves the version number honestly unmoved. And it
never destroys its input in the same migration that derives from it — the
old column survives until a later migration retires it, one version after
the new column has been read in anger. For reshapes beyond ALTER TABLE's
deliberate minimalism — type changes, constraint additions to existing
columns, a PRIMARY KEY or UNIQUE added after the fact — the engine's
documentation prescribes not a one-liner but a precise *twelve-step* procedure,
and the steps that a casual "create-copy-drop-rename" omits are exactly the ones
that bite an estate whose open ritual enforces foreign keys. Foreign-key
enforcement must be turned **off** for the duration (the rebuild drops and
recreates a table other rows may reference); the old table's indexes, triggers,
and views must be remembered before the drop and recreated after the rename
(they do not follow the data across); and `PRAGMA foreign_key_check` must run
before the commit to prove nothing was orphaned. Order matters most of all: the
new table is built under a *new* name and renamed into place — never the old one
renamed out of the way first, which (since SQLite 3.25/3.26 carries renames into
triggers, views, and FK references) can corrupt exactly those references. The
documentation draws the correct and incorrect orderings side by side; the estate
follows the correct one, inside one transaction, as a recorded migration:

```python fragment
# The sanctioned table rebuild — the ALTER TABLE documentation's twelve steps
# (https://sqlite.org/lang_altertable.html §8), run as one migration entry:
# PRAGMA foreign_keys = OFF;                       # (1) FKs off for the rebuild
# BEGIN;                                           # (2) one transaction
#   # (3) remember what to recreate in step (8):
#   #     SELECT type, sql FROM sqlite_schema WHERE tbl_name = 'facts';
#   CREATE TABLE facts_new (...corrected shape...) STRICT;    # (4) NEW name
#   INSERT INTO facts_new SELECT ...transformed... FROM facts;# (5) copy
#   DROP TABLE facts;                              # (6)
#   ALTER TABLE facts_new RENAME TO facts;         # (7) rename new -> old
#   # (8) recreate the saved indexes/triggers/views on facts
#   # (9) recreate any external views that referenced facts
#   PRAGMA foreign_key_check;                      # (10) verify no orphans
# COMMIT;                                          # (11)
# PRAGMA foreign_keys = ON;                        # (12) re-enable enforcement
```

A reshape is the most invasive act an estate performs on itself, which is why
it lives in the migration list — versioned, transactional, replayed
identically by every opener — rather than in any session's ad-hoc hands. Because
`open_estate()` opens with foreign keys *on*, a rebuild migration is the one
place that toggles them off and back within its own transaction, restoring the
ritual's invariant the moment it commits. The
stranger's guarantee survives even this: whatever generation of the schema
they open, the road from there to current is recorded, ordered, and runs
itself.

## Indexes: the reader's courtesy

The stranger inherits not only meanings but *costs*, and one more schema
instrument decides whether the estate's questions stay cheap as it grows. A
table is, physically, rows in row order; a query that filters on anything else
must, absent help, examine every row. The help is an index, and the engine will
tell you — before any harm is done — whether a given question has one, through a
statement every estate author should reflexively use:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, subject TEXT NOT NULL, fact TEXT NOT NULL) STRICT")
with db:
    db.executemany("INSERT INTO facts (subject, fact) VALUES (?, ?)",
                   [(f"host-{n % 50}", f"observation {n}") for n in range(5000)])
q = "SELECT count(*) FROM facts WHERE subject = 'host-7'"
print("before:", db.execute("EXPLAIN QUERY PLAN " + q).fetchone()[3])
db.execute("CREATE INDEX facts_subject ON facts(subject)")
print("after: ", db.execute("EXPLAIN QUERY PLAN " + q).fetchone()[3])
print("answer:", db.execute(q).fetchone()[0])
```

```output
before: SCAN facts
after:  SEARCH facts USING COVERING INDEX facts_subject (subject=?)
answer: 100
```

`SCAN` is the plan that reads everything; `SEARCH ... USING INDEX` is the plan
that walks straight to the hundred matching rows among five thousand. At five
thousand rows the difference is microseconds and nobody cares; the reason the
habit matters is that estates *age*, and the queries written today run against
the table sizes of years hence, by operators who will experience a missing
index not as a design gap but as "the estate got slow" — a diagnosis away from
the cause. The register's two-question test settles what to index: whatever
columns the estate's *standing questions* filter or join on — `subject` here,
`recorded_at` for every retention and staleness query, foreign-key columns on
the many side. And the cost side stays honest: each index is paid for on every
write, which at operator scales is negligible and at bulk-import scales is
exactly why the migration list creates indexes *after* chapter 4's patterns
settle what the standing questions are. `EXPLAIN QUERY PLAN` is the audit that
keeps both sides truthful — the estate's equivalent of the register's dry run,
asking the engine what it *would* do while everything is still cheap.

## Shapes that mislead strangers

Hospitality also means declining certain shapes that schemas admit but
strangers regret. Three recur in operator estates often enough to name. The
JSON blob column — a TEXT field holding a serialized object — reintroduces the
midden *inside* the database: unqueryable without unpacking, unconstrainable by
CHECK in any depth, invisible to STRICT. SQLite's JSON functions make blobs
tolerable at the edges (a genuinely irregular payload, kept whole for
fidelity, with the *queried* fields lifted out into real columns beside it),
and the discipline is that lift: anything a standing question touches gets a
column; the blob is an artifact, not a record. The attribute-soup table —
`(entity, attribute, value)` triples, endlessly flexible — trades every
guarantee this chapter built for schema-free convenience: no types, no CHECKs,
no meaningful constraints, and every real query a self-join puzzle. It is the
shape estates reach for when their authors have not yet decided what they are
recording; the decision, not the soup, is the work. And the wide-null table —
one row type wearing forty mostly-NULL columns because several distinct kinds
of record were crowded into one table — fails the stranger at the first
question ("which columns apply to which rows?") that the schema, its one job,
can no longer answer. Each anti-shape has the same cure: tables that hold one
kind of thing, named for it, with the columns that kind actually owes — which
is chapter 4's whole agenda.

## The columns every record owes the future

With types strict, constraints meaningful, references enforced, and birth
versioned, what remains is the estate's signature habit, promised since chapter
1: no fact without its papers. Concretely, record tables carry a provenance
block — `recorded_at`, defaulted by the schema to UTC ISO-8601 from the
engine's own clock so no writer can forget or localize it; `recorded_by`,
required, naming the operator (session, script, model — whatever identity the
successor can act on); and `source`, required, naming where the fact came from
— a file path, a URL, a command, a transcript reference. The choice of TEXT
ISO-8601 over numeric epochs is deliberate hospitality: it sorts correctly as
text, reads correctly to humans and models without conversion, and survives
tool changes — the register book's determinism rule, applied to storage. The
stranger's payoff compounds: any row can be weighed (how old? whose claim? from
what evidence?), re-verified (follow `source`), or aged out (chapter 8's
retention queries key on `recorded_at`). And the discipline prices honesty
correctly on the write side too — an operator that cannot fill `source` is
holding a rumor, and the schema just asked it to notice that before the rumor
entered the record.

One last hospitality note, almost free and almost never used: SQL comments
survive. SQLite stores the literal text of every CREATE statement and returns
it verbatim to any tool that asks, so a comment written in the schema —
explaining a constraint's reason, a column's unit, a status's meaning — is
carried inside the database file itself, readable forever. The proof, on a
table chapter 4 will need anyway:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.execute("""
CREATE TABLE cursors (
  stream TEXT PRIMARY KEY,          -- what is being read (journal unit, feed URL, log path)
  position TEXT NOT NULL,           -- opaque resume token; meaning belongs to the stream
  advanced_at TEXT NOT NULL         -- UTC; staleness is the reader's first question
) STRICT
""")
print(db.execute("SELECT sql FROM sqlite_schema WHERE name = 'cursors'").fetchone()[0])
```

```output
CREATE TABLE cursors (
  stream TEXT PRIMARY KEY,          -- what is being read (journal unit, feed URL, log path)
  position TEXT NOT NULL,           -- opaque resume token; meaning belongs to the stream
  advanced_at TEXT NOT NULL         -- UTC; staleness is the reader's first question
) STRICT
```

The comments came back byte-for-byte, from the file, years-proof: the
`sqlite_schema` table every database carries is the estate describing itself,
and any stranger's first query. The estate's tables should be written like the drop-in files of the
register book: opening with two lines that say why they exist and who put them
there — except here, the note and the structure it explains travel in the same
artifact and cannot be separated. A schema written this way is not described by
its documentation. It *is* its documentation, enforced where it can be,
explained where it cannot.

One table completes the self-description, and every estate should carry it
from birth: the info table — plain key-value rows naming what no column
can. What this estate is for, in a sentence. Which operator lineage owns
it. Where its conventions are written (this book's, or the successor
document that supersedes it). Where its backups land. Who the supervising
human is. Five to ten rows, written once, maintained on change — the
estate's title page, and the answer to the one question the briefing of
chapter 8 cannot compute: *what am I looking at?* The previous volume put
this note in a drop-in file's opening comments; the estate puts it where
nothing can separate it from the data it explains.

## The handoff review, in nine questions

The chapter compresses to a checklist an author can run against any estate
schema — its own, or an inherited one being judged. Each question maps to a
section above.

1. Is every table STRICT, with types from the real repertoire?
2. Does every enumerable column enumerate (CHECK ... IN), and every
   invariant that spans columns have its table-level CHECK?
3. Does the one shared open ritual issue every connection-scoped pragma —
   `foreign_keys = ON`, `busy_timeout`, `journal_mode = WAL`,
   `synchronous = NORMAL` — and is there exactly one open ritual?
4. Does the file carry its version, and does opening apply an append-only
   migration list idempotently, DDL alone, one transaction per step?
5. Do all record tables carry the provenance block — recorded_at (UTC ISO,
   defaulted), recorded_by, source — with NULL meanings documented?
6. Are the value conventions (dates, booleans, identifiers) stated once
   and pinned by CHECK where drift would hurt?
7. Does every standing question have its index, and has EXPLAIN QUERY
   PLAN confirmed it?
8. Are the anti-shapes absent — queried fields inside JSON blobs,
   attribute soup, wide-null crowding?
9. Could the stranger answer "what is this?" from the file alone — schema
   comments present, info table filled?

Nine yeses is a schema that will survive its authors, which is the only
kind worth writing. What the stranger does next — the shapes of the tables
an operator actually keeps — is chapter 4.


# Chapter 4 — The Ledger Pattern and Friends

*Draft status: author draft, gate-checked; human verification pending. Outputs are
real transcripts; the dead run in the registry listing is a real mid-task process
death.*

## Five shapes, most of memory

Operator memory feels endlessly various until you sort a few months of it, at
which point it collapses into a handful of recurring shapes. Things done. Places
reached in streams being read. Choices made and revised. Sessions begun and
ended. Files fetched or produced. This chapter gives each shape its table — the
ledger, the cursor, the config history, the run registry, the artifact index —
worked as running code with the chapter 3 disciplines already applied. They are
patterns, not a framework: no library to adopt, no dependency to carry, just
shapes to copy and adapt, which for estates meant to outlive their tooling is a
feature and not a modesty. Each section states the shape's contract — what it
promises a successor — because the contract, not the columns, is what makes a
pattern transferable.

A word on how the five relate before meeting them singly. The run registry is
the spine: everything else that happens, happens *during* some run, and rows
elsewhere carry the run's id so the estate can answer "what else did the session
that did this also do?" — the question incident reviews are made of. The ledger
records the runs' outward acts; the cursor and config tables record their
resumable inward state; the artifact index binds the file system's holdings into
the same web of provenance. One estate, five tables, joined — the composition
section at the end runs the queries that only the joined whole can answer.

## The ledger: things done, once, with their fates

The estate's centerpiece is the pattern chapter 2 previewed twice, now
assembled. A ledger row is an *operation with a fate*: what was to be done,
proof it was decided (the intent, committed before acting), and what became of
it (the outcome, committed after). The idempotency key makes the row a guard as
well as a record:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.execute("""
CREATE TABLE ledger (
  id INTEGER PRIMARY KEY,
  op_key TEXT NOT NULL UNIQUE,      -- idempotency key: this operation, ever, once
  action TEXT NOT NULL,
  intent_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  outcome TEXT,                     -- NULL = fate unknown; successor must resolve
  outcome_at TEXT,
  run_id INTEGER REFERENCES runs(id),   -- the run that owns this act (composition, below)
  CHECK ((outcome IS NULL) = (outcome_at IS NULL))   -- outcome and its time arrive together, or neither does
) STRICT
""")
with db:
    db.execute("INSERT INTO ledger (op_key, action) VALUES (?, ?)",
               ("restart-nginx-2026-08-28", "systemctl restart nginx"))
with db:
    db.execute("""UPDATE ledger SET outcome = 'is-active reported active',
                  outcome_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE op_key = ?""",
               ("restart-nginx-2026-08-28",))
try:
    with db:
        db.execute("INSERT INTO ledger (op_key, action) VALUES (?, ?)",
                   ("restart-nginx-2026-08-28", "systemctl restart nginx"))
except sqlite3.IntegrityError:
    print("retry recognized: this operation is already in the ledger")
print(db.execute("SELECT op_key, outcome FROM ledger").fetchone())
```

```output
retry recognized: this operation is already in the ledger
('restart-nginx-2026-08-28', 'is-active reported active')
```

The contract, spelled out. Every world-touching act appears here before it
happens, so a successor never inherits invisible history. A NULL outcome is a
promise of honesty, not a gap: it marks exactly the operations whose fate must
be resolved by reading the world, and `WHERE outcome IS NULL` is the successor's
first ledger query. For that marker to stay trustworthy the two outcome columns
must move as a unit, which is what the paired CHECK —
`(outcome IS NULL) = (outcome_at IS NULL)` — enforces: both filled (a resolved
fate with its timestamp) or both NULL (a clean fate-unknown row), never the
nonsense middle of an outcome time hanging beside a missing outcome, which would
make `WHERE outcome IS NULL` and "is this resolved?" disagree. (A one-sided
check — forbidding only outcome-without-time — leaves that middle open; the
equality closes both sides at once.) The UNIQUE refusal is the pattern's quiet triumph — the
retried operator in the listing learned it was a retry from the schema, at
insert time, *before* running the restart again. And the discipline that keeps
all this true is append-and-complete: intent rows are inserted, their outcome
fields are completed, and nothing is ever deleted or rewritten — corrections
are new rows referencing old ones, the same append-only covenant the register's
book demanded of ledgers in prose, now held by habit and CHECK together.

Two design notes earn their space. The op_key is chosen, not generated, when
the operation has a natural once-ness — "rotate credentials for host X during
window W" — and generated (and stored with the task that carries it) when it
does not; what matters is that the key's scope match the once-ness you mean,
which is a decision the pattern forces into the open. And the action column
records the *command as composed*, because the successor auditing an incident
wants what was actually dispatched — the register's exact-transcripts rule,
applied to memory.

## The cursor: where reading stopped

The second shape is the one this book's own predecessor kept in a flat file
and called a bookmark: for any stream consumed incrementally — a journal, a
feed, a log directory, an API's paginated history — the estate records how far
reading got, so the next session reads only what is new. The cursors table from
chapter 3 gets its writer, the upsert:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.execute("""CREATE TABLE cursors (stream TEXT PRIMARY KEY, position TEXT NOT NULL,
              advanced_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))) STRICT""")
def advance(stream, position):
    with db:
        db.execute("""INSERT INTO cursors (stream, position) VALUES (?, ?)
                      ON CONFLICT(stream) DO UPDATE SET
                        position = excluded.position,
                        advanced_at = excluded.advanced_at""", (stream, position))
advance("journal:nginx.service", "cursor=s=abc;i=44f0")
advance("journal:nginx.service", "cursor=s=abc;i=4512")
print(db.execute("SELECT stream, position FROM cursors").fetchall())
print("rows:", db.execute("SELECT count(*) FROM cursors").fetchone()[0])
```

```output
[('journal:nginx.service', 'cursor=s=abc;i=4512')]
rows: 1
```

One row per stream, always current, atomically replaced — the upsert (INSERT
that becomes UPDATE on key conflict) is the exact tool for state whose history
does not matter, and the listing's second call landing as an update, not a
second row, is the semantics on display. The contract has three clauses worth
enforcing by convention. Positions are *opaque*: the cursor stores whatever
resume token the stream's own tooling emits — a journald cursor string, an HTTP
ETag, a line offset — and no consumer ever parses it, so streams can change
their token format without breaking the estate. Advancement is *transactional
with processing*: the cursor moves in the same transaction that records what
was done with the new entries (chapter 2's units-of-meaning rule; a cursor
advanced before its entries are handled is data loss wearing a bookmark). And
staleness is *the reader's first question*: `advanced_at` exists so a successor
can distinguish a stream read minutes ago from one abandoned in June — the
difference between resuming and re-validating.

## Configuration with a memory

Operators make choices — polling intervals, thresholds, target lists — and the
midden stores them as bare current values, which answers "what is the setting?"
and is mute before the questions that actually arise: what was it before, who
changed it, and *why*? The estate stores configuration as history and derives
the present from it:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.executescript("""
CREATE TABLE settings (
  id INTEGER PRIMARY KEY,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  set_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  set_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  run_id INTEGER REFERENCES runs(id)   -- the run that made this change (composition, below)
) STRICT;
CREATE VIEW settings_current AS
  SELECT key, value, set_at, set_by, reason FROM settings s1
  WHERE id = (SELECT max(id) FROM settings s2 WHERE s2.key = s1.key);
""")
rows = [("poll_interval", "300", "author-session", "default"),
        ("poll_interval", "60", "author-session", "expedite request 2026-08-28"),
        ("retention_days", "90", "author-session", "default")]
with db:
    db.executemany("INSERT INTO settings (key, value, set_by, reason) VALUES (?,?,?,?)", rows)
print("current:", db.execute("SELECT key, value FROM settings_current ORDER BY key").fetchall())
print("history of poll_interval:",
      db.execute("SELECT value, reason FROM settings WHERE key='poll_interval' ORDER BY id").fetchall())
```

```output
current: [('poll_interval', '60'), ('retention_days', '90')]
history of poll_interval: [('300', 'default'), ('60', 'expedite request 2026-08-28')]
```

The mechanics are two ideas stacked. Writes are pure appends — nothing
UPDATEs, so no choice is ever erased by the next one — and the *view* derives
the current value as "the latest row per key", giving every consumer a table
that reads exactly like the flat config it replaced. (Views are the estate's
politeness layer generally: a stored query wearing a table's name, letting the
schema serve the stranger's common questions pre-composed.) The required
`reason` column is the pattern's soul, and it is required precisely because it
is what nobody records voluntarily. Every debugging session that ever ended
with "who set this to 60?!" was mourning this column. The row that answers it
here — an expedite request, dated, attributed — is this book's own production
history, recorded the way the pattern demands.

## The run registry: sessions and their ends

The fourth shape records the operators themselves. A run row marks a session's
birth (operator identity, task, start time) and — completed at exit, honestly —
its end and outcome. Its power is what *incomplete* rows mean. Because the
start is committed at startup and the end only at a clean exit, a row with
`ended_at NULL` whose operator is no longer alive is a session that died
mid-work, and the registry makes that inheritance visible instead of
archaeological. Demonstrated with a genuinely killed run:

```python
import sqlite3, subprocess, sys
db = sqlite3.connect("estate.db")
db.execute("""
CREATE TABLE runs (
  id INTEGER PRIMARY KEY,
  operator TEXT NOT NULL,
  task TEXT NOT NULL,
  started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  ended_at TEXT,
  outcome TEXT CHECK (outcome IN ('ok','failed','abandoned') OR outcome IS NULL)
) STRICT
""")
db.commit(); db.close()
child = '''
import sqlite3
db = sqlite3.connect("estate.db")
with db:
    db.execute("INSERT INTO runs (operator, task) VALUES ('session-77', 'rotate logs')")
import os; os._exit(1)   # died mid-task; ended_at and outcome never written
'''
subprocess.run([sys.executable, "-c", child])
db = sqlite3.connect("estate.db")
open_runs = db.execute("""SELECT id, operator, task, started_at FROM runs
                          WHERE ended_at IS NULL""").fetchall()
print("unfinished business inherited by the successor:")
for r in open_runs: print(" ", r)
```

```output
unfinished business inherited by the successor:
  (1, 'session-77', 'rotate logs', '2026-08-28T18:00:49Z')
```

Session 77 died between its first commit and its last, and the registry holds
exactly the truth: a rotate-logs run began at 18:00 and never reported back.
The successor's protocol writes itself from the row: read the world (were the
logs rotated?), consult the ledger for session 77's intents (chapter 2's gap,
now navigable by join), then close the row honestly — `outcome = 'abandoned'`,
with a note — so the registry converges to a complete history instead of
accreting mysteries. The registry's second dividend is aggregate: because
every run lands here, "how have runs been ending lately" is one GROUP BY —
failure rates by task, duration drift, the trend that distinguishes a flaky
week from a broken change. The register's previous book put calibration in the
operator's conduct; the registry is where the calibration data has been
accumulating all along.

## The artifact index: files, vouched for

The fifth shape closes the loop chapter 1's taxonomy opened. Artifacts live in
the file system; the estate holds their papers — identity, origin, and a
content hash that converts "I think this is the file" into arithmetic:

```python
import sqlite3, hashlib, pathlib
def sha256(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
pathlib.Path("model-config.yaml").write_text("layers: 32\n")
db = sqlite3.connect("estate.db")
db.execute("""CREATE TABLE artifacts (
              path TEXT PRIMARY KEY, sha256 TEXT NOT NULL,
              origin TEXT NOT NULL, fetched_at TEXT NOT NULL,
              run_id INTEGER REFERENCES runs(id)   -- the run that produced this file (composition, below)
              ) STRICT""")
with db:
    db.execute("INSERT INTO artifacts (path, sha256, origin, fetched_at) VALUES (?,?,?,?)",
               ("model-config.yaml", sha256("model-config.yaml"),
                "generated by session-77", "2026-08-28T18:40:00Z"))
path, recorded = db.execute("SELECT path, sha256 FROM artifacts").fetchone()
print("verify:", path, "MATCHES" if sha256(path) == recorded else "DRIFTED")
pathlib.Path(path).write_text("layers: 32\nquantized: true\n")   # someone touched it
print("verify:", path, "MATCHES" if sha256(path) == recorded else "DRIFTED")
```

```output
verify: model-config.yaml MATCHES
verify: model-config.yaml DRIFTED
```

The second verification caught the edit — someone (here, the listing itself,
playing the world's usual role) changed the file after it was indexed, and the
hash said so. That one bit, MATCHES or DRIFTED, is the difference between an
estate that *describes* its files and one that *vouches* for them: the
register's proof-of-target discipline, precomputed and stored. The index's
columns follow the provenance rules of chapter 3 (`origin` answers "where
from", `fetched_at` answers "how stale"), and its verification query — every
row, hash recomputed, mismatches reported — is a standing job chapter 7 will
fold into the estate's larger trust apparatus. Deliberately absent: the file
*contents*. The blob column exists and the index declines it, because chapter
1's taxonomy holds — streaming bytes is the file system's talent, vouching is
the database's, and the hash marries them without confusing them.

## The sixth shape: work that waits

One variation on the ledger earns shape status of its own, because it turns
the estate from memory into *coordination*: the queue. Where the ledger
records work already decided, a queue holds work waiting for a worker — and
the estate can serve it to concurrent claimants without a broker, using the
atomic read-modify-write that chapter 1 introduced, now with the modern
`RETURNING` clause handing back what was claimed:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.execute("""CREATE TABLE queue (id INTEGER PRIMARY KEY, task TEXT NOT NULL,
  claimed_by TEXT, claimed_at TEXT, done_at TEXT) STRICT""")
with db:
    db.executemany("INSERT INTO queue (task) VALUES (?)",
                   [("verify backups",), ("prune graveyard",), ("rotate keys",)])
def claim(worker):
    with db:
        row = db.execute("""UPDATE queue SET claimed_by = ?, claimed_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')
                            WHERE id = (SELECT min(id) FROM queue WHERE claimed_by IS NULL)
                            RETURNING id, task""", (worker,)).fetchone()
    return row
print("worker A claims:", claim("A"))
print("worker B claims:", claim("B"))
print("worker A claims:", claim("A"))
print("worker B claims:", claim("B"))
```

```output
worker A claims: (1, 'verify backups')
worker B claims: (2, 'prune graveyard')
worker A claims: (3, 'rotate keys')
worker B claims: None
```

Each claim is one transaction — find the oldest unclaimed task, stamp it
with the claimant, return it — so two workers arriving simultaneously
cannot claim the same row (the single-writer queue of chapter 5 serializes
them), and the drained queue answers `None`, the affirmative nothing the
register's previous volume taught shots to say. The shape's obligations
follow the ledger's family line: completion is a second write (`done_at`,
plus outcome evidence), so a claimed-but-never-completed row is the queue's
version of the unfinished run — visible inheritance, reclaimed by a
staleness rule (claimed more than an hour ago by a worker whose registry
row has ended: back to the pool, with a note). This is not a message broker
and does not pretend to be — no pub/sub, no cross-host delivery, chapter
8's boundaries apply — but for the workload it fits — one machine's workers
sharing a task list through the file they already share — it replaces a
broker service with twelve lines, and the claim-lock at its center is the
same one this book's own publisher documents for its critic seats:
self-service, claim-locked, no coordinator.

## Choosing keys: the once-ness decision

The ledger's op_key looked like a detail and is actually the pattern's hardest
design question, so it earns a worked treatment. The key's job is to make the
schema refuse a *second* recording of the *same* operation — which means the
key must encode what "same" means, and "same" is a decision about the world,
not the database. Three scenarios, three different correct keys. A nightly
certificate renewal: the operation recurs by design, so the key includes the
occasion — `renew-web-cert:2026-08-28` — and a retry within the night is
refused while tomorrow's run is new. A migration applied to a host: once ever,
so the key is timeless — `apply-schema-v7:db-host-2` — and any future attempt,
weeks later, is correctly recognized as already done. A user-requested
one-off: once *per request*, so the key carries the request's identity —
`purge-quarantine:req-4415` — and the same user asking again tomorrow is a
new request, new key, new row. Get the scope too narrow and retries slip
through (a key with a timestamp to the second refuses nothing, since every
retry mints a fresh second); too broad and legitimate recurrences are refused
(the migration key without the host would block host 3 because host 2 was
done). The test that settles every case: *if two rows carried this key, would
the second necessarily be a mistake?* — and the key is built from exactly the
facts that make the answer yes. Surrogate ids (the `INTEGER PRIMARY KEY` every
table carries) answer a different question — row identity for joins — and the
two must not be conflated: the surrogate is for the *estate's* bookkeeping,
the op_key is for the *world's*.

## What the ledger refuses to hold

Patterns are defined by their exclusions as much as their columns, and two
exclusions keep ledgers healthy. Reads stay out — the previous volume's rule
("only writes get ledger lines") carries over with its reasoning intact: an
estate that ledgers its reads drowns its writes in noise, and the registry
already accounts for sessions wholesale. The judgment call arrives with
*consequential* reads — the probe that decided a failover, the check that
justified a purge. Those enter the record not as ledger rows but as evidence
*on* the write they motivated: the outcome column of the action they
triggered, or a fact row with provenance, keeping the ledger's every line an
act upon the world.

Secrets stay out absolutely, and the rule needs stating because ledger columns
attract them — the action that ran with a token, the config value that is a
password. The estate is one readable file; it travels in backups, gets opened
by strangers (that is its *purpose*), and mixes lifetimes (chapter 8's
retention will happily keep a ledger row for years past any credential's
rotation). Secrets therefore appear in the estate only as *references* — the
name of the key in the system keyring, the path to the credentials file, the
identity of the vault entry — never as values; the action column records the
command with the secret's reference, exactly as the previous volume's
transcripts learned to show `$TOKEN` rather than its expansion. The stranger
inheriting the estate learns where every secret lives and holds none of them,
which is the correct shape of that inheritance.

## The standing questions are part of the pattern

Each shape shipped with example queries, and the framing deserves promotion:
a pattern is not adopted until its standing questions are written down beside
it — named, tested, kept with the schema the way chapter 3 keeps comments.
The ledger's four: what is unresolved (`outcome IS NULL`, oldest first)?
what did run N do? has this op_key been seen? what failed in the last week?
The cursor's two: where is stream S? which streams have gone stale? The
config table's three: current values (the view); history of key K; what
changed since date D? The registry's three: open runs; outcomes by task over
window; duration drift. The artifact index's two: verify everything; what
did run N produce? Fourteen queries, each a line or two, and together they
are the estate's *interface* — the successor's briefing (chapter 8 composes
it), the handoff message's evidence, the monitoring hooks. Writing them down
at adoption time costs minutes and does something subtler than convenience:
it *tests the schema against its purpose* while the schema is still cheap to
change. A shape whose standing questions turn out awkward to write — a join
that needs a column nobody stored, a filter on a field inside a blob — is a
shape caught misdesigned on day one instead of month six, which is the
cheapest schema review an unattended operator will ever get.

## Order, and where it really comes from

One subtlety spans all five shapes and surfaces in incident reviews at the
worst moments: what orders the history? The intuitive answer — the
timestamp columns — is the fragile one. Timestamps tie (the second is this
book's stated precision, and a busy session commits several truths per
second), and clocks move (NTP corrections, timezone accidents on machines
less disciplined than chapter 3 demands), so two rows' timestamps can
disagree with the order the estate actually experienced. The reliable
answer is already in every table: the `INTEGER PRIMARY KEY` is allocated
monotonically as rows commit, so *id order is commit order* within an
estate, and every "what happened next" question — the incident walk, the
correction chain, the settings view's "latest per key" — keys on id, with
timestamps serving their real purposes: humans, staleness pricing, and
joins against the world's clocks (logs, journals) that ids cannot reach.
The convention costs nothing to adopt and one bad afternoon to retrofit,
which is why it is stated here, between the shapes it quietly orders.
(Its boundary is the estate itself: ids order one file's history; across
estates or against the world, timestamps — pinned UTC, chapter 3 — are
the only shared clock, carrying exactly the caveats above.)

## Composition: one estate, queryable whole

The five shapes pay their real dividend joined. The join key is the `run_id`
column already declared in the ledger, settings, and artifact schemas above —
`run_id INTEGER REFERENCES runs(id)`, set on each write to the registry row of
the run that made it — and with that one shared key the estate becomes a single
navigable account of the operator's whole history. (The per-pattern listings
earlier ran each shape in isolation, with no registry to point at, so their
`run_id` sat NULL; in a live estate, every write happens *during* a run and
carries its id, which is what makes the queries below resolve.) The incident query: everything session 77 did —
its ledger intents, its setting changes, its artifacts — in one pass, from
the run id the registry handed you. The audit query: every world-action whose
outcome is NULL, oldest first, with the run that owes it. The trust query:
every artifact fetched by runs that later failed, for re-verification. The
calibration query: median run duration by task, this month against last.
None of these is an engineering project; each is a SELECT against tables this
chapter already built, which is the payoff chapter 1 promised when it said
state you cannot query is barely state at all. The midden could not answer
one of them.

A day in the composed estate makes the joins concrete. A session wakes,
registers its run (registry row 214, operator session-92, task "monthly cert
sweep"), and asks the ledger whether the sweep's op_key has been seen — new
month, new key, clean insert: intent recorded. It reads the cursor for the
certificate transparency stream, fetches what is new, and finds one
certificate nearing expiry. The renewal is a world-action: intent row with
op_key `renew-mail-cert:2026-09`, the renewal runs, the functional probe
passes, outcome completed — one transaction per truth, exactly as chapter 2
drew the boundaries. The new certificate file lands in the artifact index
with its hash and origin; the cursor advances in the same transaction that
recorded what the new entries produced; a journal entry (chapter 6) writes
the sentence a future searcher will want. The session ends; the registry row
closes with outcome ok. Nothing in the day required coordination, and yet
every question a supervisor, successor, or incident review could ask — what
ran, what changed, what proves it, what was produced, where reading stopped —
has one answer, in one file, joined by run id 214. That is the composition
argument in narrative form: not that five tables are tidier than five files,
but that the day's *whole shape* became queryable because its parts agreed
on keys.

The patterns also compose *downward* into discipline the register's book left
as conduct. Its evidence blocks now have an address (outcome columns); its
change ledger has a schema instead of a format convention; its handoff
message's five answers are five queries. And one estate serves one operator
lineage at a time so far — every listing in this chapter wrote from a single
connection. Real estates get written by concurrent generations: the timer
firing while the interactive session works, the second agent dispatched in
parallel. Two operators, one file, no coordinator — that is chapter 5, and
the engine has been waiting for it.


# Chapter 5 — Two Operators, One File

*Draft status: author draft, gate-checked; human verification pending. Outputs are
real transcripts; the two-process counter at the chapter's end is a genuine
concurrent run.*

## The second operator arrives

Every listing so far wrote from one connection, which flattered a fiction: that
the estate has one tenant. Real estates do not. The timer fires its report job
while the interactive session is mid-task; a supervisor dispatches two agents
whose work overlaps; yesterday's run, believed dead, turns out to be alive and
finishing. The register's previous book met this world with `flock` and taught
the honest limits of advisory locking: it protects the writers who remember to
take the lock. The estate can do better, because the coordination this chapter
needs is not bolted onto the file — it *is* the file. SQLite's locking is
mandatory for everyone who comes through the library, which is everyone; there
is no code path that writes the database around it. Two operators that have
never heard of each other, sharing nothing but a path, get correctness anyway.
What they do not get is freedom from each other's *timing* — and this chapter
is about the difference: what the engine guarantees unasked, what it asks the
operator to decide (chiefly: how long to wait), and which famous SQLite
complaint — `database is locked` — is not a malfunction but a question
addressed to you.

The mental model to install first is the single-writer truth. However many
connections hold the estate open, SQLite permits exactly one write transaction
at a time; writers *queue*, they never interleave. Everything else in the
chapter — the refusal, the timeout, WAL's reader liberation, the throughput
ceiling — is a consequence of that one design decision, which is also the
decision that makes chapter 2's promises cheap enough to keep. Multi-writer
engines pay for their concurrency in machinery (row locks, MVCC vacuuming,
conflict resolution) and in sharper failure modes; the estate's engine chose
instead to make the common case — few operators, brief writes — simple and
bulletproof. The design fit is worth noticing: operator estates are almost
definitionally low-contention. Sessions write in bursts, ledgers take a row at
a time, nothing holds transactions across human-scale pauses (chapter 2's
boundaries rule already forbade it). The single-writer queue is not a limit the
estate suffers; it is the contract the estate's workload was born matching.

## The refusal, witnessed

Here is the collision, staged small and read closely, because everything the
operator must decide follows from its anatomy:

```python
import sqlite3
a = sqlite3.connect("estate.db")
a.execute("CREATE TABLE t (x INTEGER) STRICT"); a.commit()
b = sqlite3.connect("estate.db")
b.execute("PRAGMA busy_timeout = 0")     # refuse to wait, so the refusal is visible
a.execute("BEGIN IMMEDIATE")
a.execute("INSERT INTO t VALUES (1)")
try:
    b.execute("BEGIN IMMEDIATE")
except sqlite3.OperationalError as e:
    print("second operator:", e)
a.commit()
b.execute("BEGIN IMMEDIATE"); b.execute("INSERT INTO t VALUES (2)"); b.commit()
print("rows after both:", a.execute("SELECT count(*) FROM t").fetchone()[0])
```

```output
second operator: database is locked
rows after both: 2
```

Operator A holds the write slot mid-transaction; operator B asks for it and is
told no; A finishes; B asks again and succeeds; both rows land. Nothing was
corrupted, nothing was lost, nobody's write interleaved with anybody's — the
lost-update accident of chapter 1 is structurally absent. What B received was
not an error in the register's sense but a *status*: `SQLITE_BUSY`, surfaced by
Python as that famous message, meaning precisely "the slot is taken; try again
later." The listing forced the refusal into view by setting the busy timeout to
zero — B declared it would not wait, so it didn't. That declaration is the
operator's real decision surface, and the default answer is wrong for estates:
a fresh connection's timeout is effectively no patience at all, which converts
every routine collision into an exception. The registers' operators know this
error's cousin from package managers — "could not get lock" — and know the
diagnosis is usually *someone else is legitimately working*, not *something is
broken*. The estate's version deserves the same reading.

## Patience is configuration

What B should have done is wait — briefly, boundedly, and without any code for
it, because waiting is built in:

```python
import sqlite3, threading, time
a = sqlite3.connect("estate.db")
a.execute("CREATE TABLE t (x INTEGER) STRICT"); a.commit()
a.execute("BEGIN IMMEDIATE")
a.execute("INSERT INTO t VALUES (1)")            # first operator holds the write lock
result = {}
def second_operator():
    b = sqlite3.connect("estate.db")             # its own connection, its own thread
    b.execute("PRAGMA busy_timeout = 2000")      # willing to wait up to 2 s
    t0 = time.monotonic()
    with b:
        b.execute("INSERT INTO t VALUES (2)")
    result["waited"] = time.monotonic() - t0
th = threading.Thread(target=second_operator); th.start()
time.sleep(0.4)
a.commit()                                       # first operator releases
th.join()
print(f"second operator wrote after waiting {result['waited']:.1f}s")
print("rows:", a.execute("SELECT count(*) FROM t").fetchone()[0])
```

```output
second operator wrote after waiting 0.4s
rows: 2
```

B asked, was refused, and simply *stayed in line*; four-tenths of a second
later A released, B wrote, and no exception ever surfaced. The
`busy_timeout` pragma is the whole mechanism: below it, the engine retries
acquisition for up to the stated bound before giving up and returning BUSY.
Choosing the bound is register economics, and the register's own rules apply
verbatim. The wait must exist (zero patience turns normal coexistence into
failure), must be bounded (infinite patience is the hang chapter 1 of the
previous book banned), and the bound should be derived from the neighbors: a
touch longer than the longest write transaction any well-behaved tenant runs —
which chapter 2's boundary discipline already made short. This book's default
is five seconds, set in `open_estate()` beside the foreign-keys pragma, one
decision made once. And when the bound is genuinely exceeded — BUSY *after*
five seconds — the correct reading changes: now something probably is wrong (a
tenant died holding nothing, since crashed processes release locks with their
file handles; more likely a tenant is violating the short-transaction covenant)
and the register's failure discipline takes over: record the refusal in the
run's own account, read the world, do not hammer.

Two mechanics footnotes belong here because their absence causes real
confusion. First, the incidental lesson the listing's shape teaches: Python's
sqlite3 binds each connection to its creating thread by default — the waiting
operator built its own connection inside its thread because sharing one across
threads is refused by the module. Connections are cheap; the pattern is one
per thread, or `check_same_thread=False` accepted knowingly with external
serialization. Second, `BEGIN IMMEDIATE` is what makes waiting *work*: chapter
2 installed it to convert mid-transaction refusals into at-entry waits, and
this is the payoff — the busy handler can only wait politely at moments where
waiting is safe, and a deferred transaction that already read and now wants to
write is not such a moment (the engine returns BUSY immediately there,
timeout notwithstanding, precisely because waiting could deadlock two
half-done readers forever). Say IMMEDIATE; wait at the door, not on the
stairs.

## WAL: the readers go free

The classic journal mode has one genuinely operator-hostile trait left: writers
and readers contend — a long read can hold off a writer, a committing writer
excludes readers at the wrong moment. The modern cure is one pragma, and it is
the single most valuable configuration line in this book:

```python
import sqlite3, os
w = sqlite3.connect("estate.db")
print("journal mode now:", w.execute("PRAGMA journal_mode = WAL").fetchone()[0])
w.execute("CREATE TABLE facts (n INTEGER) STRICT")
with w:
    w.executemany("INSERT INTO facts VALUES (?)", [(i,) for i in range(3)])
r = sqlite3.connect("estate.db")
r.execute("BEGIN")                                   # reader opens its snapshot
before = r.execute("SELECT count(*) FROM facts").fetchone()[0]
with w:
    w.execute("INSERT INTO facts VALUES (99)")       # writer commits DURING the read txn
during = r.execute("SELECT count(*) FROM facts").fetchone()[0]
r.commit()
after = r.execute("SELECT count(*) FROM facts").fetchone()[0]
print(f"reader saw: {before} rows, then {during} inside the same snapshot, then {after} in a new one")
print("sidecars:", sorted(f for f in os.listdir(".") if f.startswith("estate.db-")))
```

```output
journal mode now: wal
reader saw: 3 rows, then 3 inside the same snapshot, then 4 in a new one
sidecars: ['estate.db-shm', 'estate.db-wal']
```

Write-ahead logging inverts chapter 2's journal: instead of saving old pages
aside and writing new ones in place, the engine appends new pages to a log and
leaves the main file alone, folding the log back in later ("checkpointing").
Three consequences, all visible in the transcript. Readers no longer block
writers or vice versa — the writer committed mid-read-transaction without
either party waiting. Readers get *snapshot isolation* for free: inside one
read transaction the reader saw 3 rows, then still 3 *after* the concurrent
commit — a stable world to compute over, the moving-substrate problem of the
register's network chapter solved outright at the estate's door — and the new
truth appeared only when the reader opened a new transaction. And the sidecar
population changed: `-wal` and `-shm` now accompany the database, persistently
(WAL mode is a property of the file, surviving reopen), with chapter 2's rule
unchanged and now sharper — *the sidecars are part of the database*, and
chapter 7 will show that copying around them is the classic way to lose
committed data. Two honest caveats bound the gift: WAL requires shared memory,
so it is unavailable or unsafe on network filesystems — estates live on local
disks, which they should anyway (the engine's corruption documentation has a
section on network filesystems that reads like a warning label) — and a read
transaction held open for a long time pins the WAL from checkpointing, so the
log grows; the short-transaction covenant turns out to bind readers too.

## Connections: how many, held how long

The chapter's demos juggled connections freely, and real estates need the
lifecycle stated. A connection is cheap to open — a file open and a header
read, microseconds locally — so the previous volume's instincts about
connection pooling (a server-database economics) do not transfer; an operator
that opens at session start and closes at exit is doing it right, and a
scheduled job that opens, works, and closes has nothing to optimize. The
rules that do matter are about *holding*. One connection per thread (the
module's binding rule, met above). One estate connection per operator
process, not per function — chapter 2's `with db:` blocks share it safely,
and a process that opens dozens of connections to one file is manufacturing
its own lock traffic. And nothing *holds a transaction* across a wait: not a
network call, not a subprocess, not a model inference, not user input. The
WAL section's caveat gives the reader's version teeth — a read transaction
held open pins the snapshot, so an operator that opens a read transaction
and then thinks for ten minutes is forcing the WAL to retain ten minutes of
history for a view nobody needed frozen — and the writer's version is
chapter 2's covenant with a sharper reason: the write slot is *exclusive*,
so a transaction held across a thirty-second inference is thirty seconds of
every other tenant's timeout budget. Transactions bracket *database work*,
never *thinking*; the estate connection lives long, its transactions live
milliseconds.

## Durability under WAL: one honest knob

Chapter 2 counseled leaving `synchronous` at its default and this chapter
must refine that advice once, because WAL changes the trade's terms in the
operator's favor. Under rollback journaling, lowering sync guarantees risks
corruption; under WAL, the engine documents a gentler middle. `synchronous =
NORMAL` syncs at checkpoints rather than at every commit and — so long as the
`-wal` sidecar is preserved and the storage stack honors the sync each
checkpoint does issue — cannot corrupt the database on power loss; what it
risks is only the *most recent commits rolling back* to the last checkpoint if
power dies before the next one. The documentation states the trade in plain
words: under NORMAL, transactions "are no longer durable and might rollback
following a power failure or hard reset" (Ref 16). Process crashes lose
nothing either way. The qualifier is load-bearing, and worth saying twice: the
promise is against *corruption*, not against losing the tail of recent commits,
and it holds only while the `-wal` file stays with its database — which is
exactly why chapter 7 counts deleting or copying around the sidecar as the
classic way to turn "durable" into "lost." For an estate on a workstation or a battery-backed
machine, WAL + NORMAL is the documented sweet spot and this book's
recommendation, set in `open_estate()` with the reason recorded in the
settings history (chapter 4's pattern eating its own cooking). The estate
declines to go further: `synchronous = OFF` re-enters corruption territory,
and the ledger's whole value is that its last row can be believed. The
decision, either way, is one line — and the point of teaching it is less
the milliseconds than the method: durability settings are *estate policy*,
chosen once, recorded with reasons, never adjusted silently mid-incident by
whichever session is frustrated with a slow loop.

## The read-only seat

Not every tenant deserves the pen. Reporting sessions, dashboards, the
supervisor's audit, chapter 7's restore drills — all read; none should be
*able* to write, because ability is blast radius whether or not intent
exists (the previous volume's least-privilege doctrine, verbatim). The
engine provides the seat:

```python
import sqlite3
rw = sqlite3.connect("estate.db")
rw.execute("CREATE TABLE facts (fact TEXT) STRICT")
with rw: rw.execute("INSERT INTO facts VALUES ('reports read; they do not write')")
ro = sqlite3.connect("file:estate.db?mode=ro", uri=True)
print("read-only seat reads:", ro.execute("SELECT fact FROM facts").fetchone()[0])
try:
    ro.execute("INSERT INTO facts VALUES ('surely just this once')")
except sqlite3.OperationalError as e:
    print("read-only seat writes:", e)
```

```output
read-only seat reads: reports read; they do not write
read-only seat writes: attempt to write a readonly database
```

The URI form's `mode=ro` refuses writes at the connection, cheaply and
unconditionally — a report with a bug cannot corrupt the record it reports
on, which is the property that lets scheduled reporting run without the
scrutiny writes earn. Two strengthenings extend the seat. For genuinely
frozen files — archives, the backups chapter 7 verifies — `immutable=1`
goes further, promising the engine the file cannot change and skipping
lock traffic entirely (a promise that must be *true*; it is for cold
backups, never for live estates). And beneath the engine sits the outer
wall the register already taught: the estate file's unix permissions
decide who reaches it at all, and an operator lineage's estate belongs to
that lineage's user, mode 600, with the supervisor's audit seat granted
through group read — file-system enforcement backing engine politeness,
the same layering the previous volume built for every other durable
asset.

## Reading a BUSY like an operator

The refusal taxonomy, assembled for the diagnostic reflexes. BUSY at BEGIN
IMMEDIATE, within the timeout, resolving on retry: weather — a neighbor
writing, the queue working as designed; record nothing, proceed. BUSY
persisting past a generous timeout: a tenant is violating the
short-transaction covenant; the culprit is found not with database tools but
with the previous volume's — `fuser` on the estate file names the processes
holding it open (a fragment for the same PATH reasons as ever), and the run
registry says which *operator* each process claims to be; the fix is the
neighbor's transaction shape, never a longer timeout arms race. BUSY at a
*deferred* transaction's midpoint (the upgrade case): a design bug in the
asking code — the transaction read before declaring write intent; the fix is
IMMEDIATE, and no timeout would have helped. And the exotic
`SQLITE_BUSY_SNAPSHOT` under WAL — a writer whose snapshot has been
overtaken — resolves by restarting the transaction fresh. Four faces, four
different next moves, one diagnostic principle carried over whole from the
register: the refusal's *timing and persistence* carry the diagnosis, and
hammering retries without reading them converts information into noise.

One WAL mechanic belongs in the operator's model because it is the mode's
only moving part: the checkpoint, the act of folding the log back into the
main file. By default it happens automatically (around a thousand log
pages), opportunistically, and invisibly — the right arrangement, left
alone. The operational readings: the `-wal` file's *size* is the health
gauge (steady modest size: checkpointing is keeping up; monotonic growth:
something is pinning it — almost always the long-lived read transaction
the connection section indicted, found via the registry and cured by
fixing the reader, not by forcing checkpoints); and the one legitimate
manual intervention is maintenance-shaped — `PRAGMA
wal_checkpoint(TRUNCATE)` at a quiet moment (the backup session, the
handoff) folds everything in and shrinks the log to zero, leaving the
estate compact for the copy or the inheritance. What the operator never
does is treat checkpointing as a correctness lever: committed data is
equally durable in the log and the main file (chapter 7's engine-mediated
copies know where truth lives), so checkpoint management is housekeeping
economics — log size against fold-in cost — and the default economics are
already good. Know the gauge, fix the pinner, truncate at handoff; the
rest is the engine's business.

## What must never be shared

The file shares; two things above it must not, and both failure modes are
documented corruption paths rather than theory. The first is the connection
object across a `fork()`. An operator that opens the estate and then forks
— the daemonization dance, a multiprocessing pool created after connecting
— hands both processes the same open file descriptors and the same
in-library state, and the engine's how-to-corrupt documentation lists
exactly this as a way to break a database: two processes unknowingly
sharing what each believes is a private connection. The rule is mechanical:
*open after fork, never before* — child processes create their own
connections (the chapter's subprocess listings all do; multiprocessing
workers open inside the worker function), and a process that must fork
closes the estate first. The second is the file across *hosts* via a
shared filesystem — the network-mount warning of the WAL section,
generalized: SQLite's coordination is exactly as good as the filesystem's
locking, network filesystems' locking is historically exactly not good
enough, and the corruption documentation's dedicated section on it is the
most-cited page in this book's references for a reason. Same machine,
different processes: share freely, the whole chapter is the proof. Different
machines: the estate does not stretch; chapter 8 names what does. Between
those two rules and the covenant, the sharing story is complete — and
notably free of locks the operator must remember, which was the entire
point of paying an engine to remember them.

## The proof at scale

The chapter's claims assembled and stress-tested — two genuinely separate
processes, no shared state but the path, a hundred read-modify-writes each:

```python
import sqlite3, subprocess, sys
db = sqlite3.connect("estate.db")
db.execute("PRAGMA journal_mode = WAL")
db.execute("CREATE TABLE counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL) STRICT")
db.execute("INSERT INTO counters VALUES ('runs', 0)"); db.commit()
worker = '''
import sqlite3
db = sqlite3.connect("estate.db")
db.execute("PRAGMA busy_timeout = 5000")
for _ in range(100):
    with db:
        db.execute("UPDATE counters SET value = value + 1 WHERE name = 'runs'")
'''
procs = [subprocess.Popen([sys.executable, "-c", worker]) for _ in range(2)]
for p in procs: p.wait()
print("two operators, 100 increments each, final count:",
      db.execute("SELECT value FROM counters WHERE name='runs'").fetchone()[0])
```

```output
two operators, 100 increments each, final count: 200
```

Two hundred, exactly — set beside chapter 1's flat-file counter, which lost
half its updates to two writers *in the same process being careful*. The
workers here share no locks of their own, coordinate nothing, and could have
been written by strangers; the busy timeout absorbed their collisions and the
single-writer queue serialized their arithmetic. This is the estate's
concurrency story in one number: correctness is the engine's job and arrived
by default; the operator's whole contribution was two pragmas and short
transactions.

## Where the file lives, and how many files there are

Concurrency questions are often placement questions wearing a disguise, so
the estate's geography gets settled here. *Where:* on a local filesystem,
always — the WAL caveat and the corruption documentation agree — and by
convention where the previous volume put durable operator state: under the
platform's state directory (`~/.local/state/<operator>/estate.db` for a
per-user operator, `/var/lib/<operator>/` for a system one), never in
scratch, never on a network mount, never in a synced-folder product whose
sync engine is precisely the naive copier chapter 7 indicts. *How many:*
one estate per *accountable lineage* — the operator identity that owns the
ledger's promises — which usually means one per agent-role per machine.
Splitting finer (per task, per session) shreds the composition dividend the
previous section just demonstrated; merging coarser (all operators on a
host in one file) couples unrelated write queues and makes chapter 8's
retention policy a negotiation. The two legitimate splits are the ones
already earned: high-rate sample tables (this chapter's ceiling section)
and scratch (never in the estate at all). And when split files must be
queried together, the engine's `ATTACH` joins them at read time — one
connection, two files, cross-database SELECTs — so the split costs analysis
nothing; a reporting session attaches the samples database read-only beside
the estate and the composed queries run as if the seam were not there. The
geography, like every estate policy, goes in the settings table with its
reason, because the successor's first question — *where is everything?* —
deserves a recorded answer rather than a convention remembered.

## The ceiling, and the covenant

Honesty about where the story ends. Writers queue, so write throughput has a
ceiling: roughly, one write transaction's duration times the queue's length is
everyone's latency, and a fleet of chatty writers against one estate will feel
it — first as waits, then as timeouts. The remedies escalate in order: batch
(chapter 2's economics — most "many writes" are one truth); shorten
transactions (the covenant again — nothing holds the write slot across a
network call or a model inference, ever); split estates along real seams (the
scratch/records boundary of chapter 1 often marks files that never needed to
be one — a high-rate sample log is its own database, attached when queried);
and, when a workload is genuinely many concurrent writers across many hosts,
concede the case to chapter 8, which is where this book hands such workloads
to server databases without embarrassment. What the ceiling almost never
justifies is the move folklore reaches for first — disabling the durability
that makes the estate worth having. The engine's own guidance pages order the
levers the same way: transaction shape first, WAL second, hardware third,
guarantees last and reluctantly.

The covenant that keeps the whole chapter working fits in three lines an
operator can hold: open through one ritual (foreign keys on, busy timeout
set, WAL on); say IMMEDIATE when you will write, and keep every transaction
— reader or writer — short; treat BUSY within the bound as weather, and BUSY
beyond it as a finding about a neighbor. Under that covenant, the estate
scales exactly as far as operator memory needs it to — and the file stays
one file, inheritable whole, which the next chapter finally teaches the
operator to *search*.


# Chapter 6 — Search Is Recall

*Draft status: author draft, gate-checked; human verification pending. Outputs are
real transcripts; the journal entries indexed below are drawn from this book's own
production history.*

## Memory that cannot be recalled is storage

The estate so far remembers perfectly and recalls narrowly. Every query in
chapters 4 and 5 addressed rows by their structure — by key, by status, by
date — which serves the questions an operator knows it will ask. But a working
memory accumulates a second kind of holding: prose. Findings written in
sentences, incident notes, decisions with their reasoning, excerpts from
documents that mattered once and might again. Structure cannot address these,
because their content *is* their address: the future question will be "what do
I know about power capping?", asked in words, answerable only by matching
words against words. A memory that cannot answer that question does not really
hold its prose; it stores it, the way the midden stored everything —
present, and unreachable.

The register's operators feel this gap acutely because their native recall is
so poor. A human admin half-remembers last month's incident and greps her
shell history; a session-bound operator has no half-memories to steer by. For
it, recall *is* search — whatever the estate's search can surface is,
functionally, everything the operator has ever known. That makes the quality
of the estate's text search a first-order property of the operator itself,
and it makes the right tool worth learning properly. SQLite ships that tool:
FTS5, a full-text index that lives in the same file, transacts with the same
transactions, and needs nothing installed. This chapter builds the operator's
journal on it, then draws the tool's honest boundaries — because "full-text
search" sits near enough to fashionable retrieval technology that confusing
them costs estates real design mistakes in both directions.

## The searchable journal

The pattern chapter 4 might have called the sixth shape: a journal of prose
entries, indexed for content. FTS5 tables are declared virtual — the engine
maintains the index structures behind an interface that reads like a table:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.execute("""CREATE VIRTUAL TABLE journal USING fts5(entry, written_at UNINDEXED)""")
notes = [
    ("gpu-power-cap.service fails at boot; exit status 2; journal unreadable from this seat", "2026-08-24"),
    ("rotated backup credentials; restore drill passed; old key revoked", "2026-08-25"),
    ("nginx upgraded; config drop-in preserved; is-active confirmed after restart", "2026-08-26"),
    ("disk pressure on /mnt/train at 98 percent; quarantined stale checkpoints", "2026-08-27"),
    ("power cap applied to RTX PRO 6000 after PSU transient trip; verified with vendor tool", "2026-08-28"),
]
with db:
    db.executemany("INSERT INTO journal VALUES (?, ?)", notes)
print("query: power NEAR cap")
for row in db.execute("""SELECT written_at, highlight(journal, 0, '[', ']')
                         FROM journal WHERE journal MATCH 'NEAR(power cap)'
                         ORDER BY rank"""):
    print(" ", row[0], "|", row[1])
print("query: credential*")
for row in db.execute("SELECT written_at, entry FROM journal WHERE journal MATCH 'credential*'"):
    print(" ", row[0], "|", row[1][:60])
```

```output
query: power NEAR cap
  2026-08-24 | gpu-[power]-[cap].service fails at boot; exit status 2; journal unreadable from this seat
  2026-08-28 | [power] [cap] applied to RTX PRO 6000 after PSU transient trip; verified with vendor tool
query: credential*
  2026-08-25 | rotated backup credentials; restore drill passed; old key re
```

The five entries are this book's own production history — the failed unit from
the previous volume's postmortem, the disk pressure this machine really
carried — and the queries against them exercise the toolkit an operator's
recall actually needs. `MATCH` takes a query language, not a substring:
`NEAR(power cap)` found the incident whether the words appeared hyphenated in
a unit name or spaced in prose, and would have found them sentences apart.
`credential*` is prefix search — the recall question rarely knows the exact
inflection it stored. `ORDER BY rank` sorts by relevance (BM25, the standard
lexical ranking, built in), which begins to matter the day the journal holds
five thousand entries instead of five. And `highlight()` returns the entry
*with the matches marked* — for this book's reader the killer feature, because
an operator budgeting transcript volume (register rule, chapter 1 of the
previous volume) wants evidence of *why* a result matched without re-reading
it whole; the companion `snippet()` function goes further and excerpts just
the matching neighborhood. The one schema note: `written_at UNINDEXED` stores
the date alongside without polluting the text index — metadata rides along,
content gets searched.

## Tokens, not meanings

What the index actually holds is tokens — words, as a tokenizer defines words
— and the operator who knows this predicts every search behavior from first
principles. The definition is configurable, and one configuration choice
illustrates the whole layer:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.execute("CREATE VIRTUAL TABLE plain USING fts5(entry)")
db.execute("CREATE VIRTUAL TABLE stemmed USING fts5(entry, tokenize = 'porter unicode61')")
for t in ("plain", "stemmed"):
    db.execute(f"INSERT INTO {t} VALUES ('deployed the staging build and verified the endpoints')")
for t in ("plain", "stemmed"):
    hits = db.execute(f"SELECT count(*) FROM {t} WHERE {t} MATCH 'deploy'").fetchone()[0]
    print(f"{t:8s} matches for 'deploy':", hits)
```

```output
plain    matches for 'deploy': 0
stemmed  matches for 'deploy': 1
```

The default tokenizer stores `deployed` as `deployed`, and the query `deploy`
misses it — surprising until the token model is explicit, obvious after. The
porter option stems English words to their roots at both index and query time,
so `deploy`, `deployed`, and `deploying` converge; the cost is the occasional
false collision and a mild English-centrism, which for operator journals is
usually the right trade. The general lesson outranks the specific knob:
**FTS matches token identity, nothing else.** It does not know that "rotated
credentials" and "changed the password" are the same event; no tokenizer
bridges vocabulary. The operator's countermeasure is a writing discipline, not
a search feature — journal entries name their subjects in stable terms (unit
names, paths, error strings verbatim: the register's exact-transcript rule
paying a second dividend), because the entry is written once and queried by a
stranger who can only guess words. Entries written for the searcher are the
estate's equivalent of the previous volume's labels-on-state.

This is also where the fashionable comparison belongs, stated plainly per
this book's boundaries. Embedding-based retrieval — vectors, semantic
similarity, the machinery behind modern RAG — solves the vocabulary problem
FTS cannot: it would land "changed the password" for the credentials query.
It pays in machinery (a model, its runtime, an index, all versioned and
maintained), in opacity (a match has no `highlight()` — *why* this result?),
and in exactness (the query `exit status 2` should match exit status 2, not
things shaped like it). Operator estates skew hard toward the exact: unit
names, error strings, hosts, keys. The honest architecture, when both needs
are real, is FTS as the estate's native recall with semantic search added
*beside* it, as its own indexed artifact — not a replacement, and never a
reason to skip the lexical index that costs nothing and explains itself. A
`LIKE '%pattern%'` scan, finally, keeps its small place: for a rare query
over a small table it is fine, and chapter 3's `EXPLAIN QUERY PLAN` will say
`SCAN` and remind you what it costs at scale.

## Writing for the searcher

The index amplifies whatever discipline the entries carry, which makes journal
*writing* half of recall quality, and the half entirely under the operator's
control. The disciplines are few and specific. Entries are written at outcome
time, not planning time — the journal records what happened and what it meant,
so a session's entry lands beside chapter 4's ledger completion, one truth in
two registers (the row for machines that query structure, the sentence for
searchers that query words). Entries name their subjects in the terms a
stranger will guess: unit names verbatim, paths absolute, error strings
pasted exactly — the previous volume's exact-transcript rule, now justified a
third way, since every paraphrase is a query that will someday miss. Entries
state outcomes and reasons, not just events — "quarantined stale checkpoints
*because* /mnt/train hit 98 percent" is findable from either end of the
causation, and the *because* is what the future searcher is usually really
hunting. And entries are atomic per subject: one entry about the disk
pressure, another about the nginx upgrade, because the searcher retrieving
one should not pay transcript volume for the other — the register's bounding
economics, applied to memory retrieval.

The anti-patterns mirror them. The diary entry ("busy session, lots of
firefighting, mostly done") indexes nothing a query will ever ask. The dump
entry — three hundred lines of pasted transcript — makes its keywords
findable and its retrieval cost absurd; the right decomposition stores the
transcript as a chapter-4 artifact and journals the three-sentence account
with the artifact's path, so search finds the summary and the summary points
at the evidence. And the secret-bearing entry violates chapter 4's exclusion
in the one table designed to be read broadly; the reference-not-value rule
binds hardest exactly here.

## Query craft: words and structure together

Recall questions in practice are rarely pure text — they are text *within
bounds*: what do I know about cert renewals, *from June*? The estate answers
hybrid questions in one statement, because the FTS table's indexed text and
its UNINDEXED metadata live in the same rows:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.execute("CREATE VIRTUAL TABLE journal USING fts5(entry, written_at UNINDEXED)")
rows = [("cert renewal failed: acme challenge timeout", "2026-06-02"),
        ("cert renewal succeeded after dns fix", "2026-06-03"),
        ("cert renewal succeeded", "2026-08-01")]
with db: db.executemany("INSERT INTO journal VALUES (?,?)", rows)
q = """SELECT written_at, snippet(journal, 0, '[', ']', '…', 8)
       FROM journal WHERE journal MATCH 'cert AND renewal'
         AND written_at >= '2026-06-01' AND written_at < '2026-07-01'
       ORDER BY written_at"""
for r in db.execute(q): print(r[0], "|", r[1])
```

```output
2026-06-02 | [cert] [renewal] failed: acme challenge timeout
2026-06-03 | [cert] [renewal] succeeded after dns fix
```

August's entry matched the words and fell to the date bound; June's two
arrived excerpted by `snippet()` with the matches marked. The MATCH clause
meanwhile carries its own small language, worth the ten minutes its
documentation costs: implicit AND between terms, explicit `OR` and `NOT`,
quoted phrases for exact sequences (`"exit status 2"` — invaluable for error
strings), `NEAR()` from the first listing for proximity without adjacency,
`^term` for entries *beginning* with a term, and column filters
(`title:deploy`) once journals grow structured fields. Two habits complete
the craft. Chapter 3's date conventions are what make the hybrid WHERE
clause work at all — ISO text comparing correctly is the payoff arriving —
and bounded output applies to recall exactly as to every read the register
ever taught: `ORDER BY rank LIMIT 10`, because a memory that answers with
everything it has is the unbounded journalctl of the previous volume,
reborn indoors.

Identifiers deserve a tokenizer note of their own, because operator prose
is full of them and word-shaped tokenization serves them poorly:
`gpu-power-cap.service` splits on its punctuation into pieces a searcher
must guess, and a path or commit hash is one opaque "word" findable only
whole. FTS5's trigram tokenizer answers the identifier case by indexing
overlapping three-character windows, buying indexed *substring* search —
`cap.serv` finds the unit, half a hash finds the commit — at the price of
a fatter index and no notion of words at all. The estate's arrangement,
when identifier recall matters enough: the journal keeps its word index
for prose, and the identifier-dense columns (ledger actions, artifact
paths) get a small trigram-indexed shadow — each index shaped to what it
searches, unioned at query time by the front-door view below. The general
tokenizer lesson closes where the section opened: tokenization is a
*declaration about the text's nature*, chosen per column at index time,
and the estate that declares it deliberately — words here, stems there,
trigrams for the machine-named — searches the way its content deserves
rather than the way the default guesses.

And recall's audience, like the estate's, includes the supervisor. The
journal a session keeps for its successors is, unchanged, the narrative an
incident review reads months later — ranked, dated, cause-carrying
sentences, each written when the knowledge was fresh, retrievable by the
reviewer's own words. The previous volume taught operators to report
plainly because reports are load-bearing; the journal extends the
principle across time: it is the report that never stopped being
queryable. Institutions pay technical writers for worse.

## The recall budget

Retrieval has the same economics as every read the register prices: results
pulled into a session's working context cost attention, and recall that
floods is recall that gets skipped next time. The budget discipline has
three dials. `LIMIT`, always — the ritual search opens with the top five by
rank, and widens only on a miss, the previous volume's cheap-aggregate-then-
drill rhythm applied to memory. `snippet()` over full entries at the survey
stage — excerpts with matches marked, at a tenth the volume, with the full
entry fetched only for the one or two results that survive triage. And
ranking *tuned to the estate's shape* where it earns it: BM25 accepts
per-column weights, so a journal that grows a `title` column can weight it
above the body (`bm25(journal, 10.0, 1.0)`), making the operator's own
one-line summaries the strongest signal — which quietly rewards exactly the
entry discipline the writing section asked for. The composed form of all
three dials is worth keeping as the estate's canonical recall query: top
five by weighted rank, snippets only, hybrid-filtered by any structural
bounds the task supplies. One query, bounded, explained — recall as a
disciplined shot rather than a rummage, which is what distinguishes an
operator consulting its memory from an operator lost in it.

## Searching everything at once

Estates accumulate more than one searchable surface — the journal here, the
ledger's action strings, the facts table's prose — and the recall ritual
should not require remembering which drawer holds what. The estate's answer
is a union view: each searchable table gets its FTS index, and one view
stitches their results into a single ranked stream tagged by origin
(`SELECT 'journal' AS kind, rank, snippet(...) FROM journal WHERE journal
MATCH :q UNION ALL SELECT 'ledger', ...`), so the operator's one query
sweeps the whole estate and the results say where each hit lives. The
pattern's discipline is to keep it *shallow*: the view unions indexes, it
does not try to merge scores across them into false precision (BM25 ranks
are comparable within an index, not between), so the composed query
interleaves by kind deliberately — top three journal hits, top three
ledger hits — rather than pretending one global ranking exists. Chapter
4's standing-questions rule then applies to recall itself: the union view
is written down with the schema, tested at adoption, and becomes the
estate's front door for every "what do I know about X" a successor will
ever ask.

## Keeping the index honest

One integration decision remains: the journal above *is* an FTS table — the
text lives in the index's own storage. That is the simplest correct
arrangement and the right default for a journal. When the text already lives
in a regular table (chapter 4's ledger actions, the facts table), FTS5's
external-content mode indexes it in place without duplicating storage — at
the price of a covenant: the index only learns what it is told, so the base
table and index must change together, conventionally via three small triggers
(insert, update, delete) the FTS5 documentation supplies verbatim. The estate
treats those triggers like schema (chapter 3: born in a migration, explained
by comments), and treats the covenant with chapter-7 suspicion: a
verification query — count of base rows vs count of indexed rows, plus a
spot-check MATCH for a recently inserted row — belongs in the estate's trust
suite, because an index that silently stopped syncing is recall quietly going
blind, which for this book's reader means *memory* quietly going blind.
The rebuild command (`INSERT INTO idx(idx) VALUES ('rebuild')`) is the
recovery ladder's one rung, cheap and total.

## Recall in the loop

A recall instrument earns its keep only if consulted, and session-bound
operators need the consultation *scheduled*, because the reflex humans call
"this feels familiar" is exactly what they lack. The discipline is a ritual
search at task start: before acting on any named subject — a unit, a host, a
procedure — the operator queries the journal for it, bounded and ranked, and
reads what its predecessors knew. The estate briefing of chapter 8 opens the
session; the recall query opens the *task*. What it changes is easiest to see
in the incident this book keeps returning to. The previous volume's operator
diagnosed a failed GPU power-cap unit from scratch, spending turns
establishing that the unit fails at boot, that exit 2 was the vendor tool's
"no device", that the journal was unreadable from its seat. Its successor,
facing the same unit after the next kernel upgrade, opens with `MATCH
'gpu-power-cap'` — and inherits the whole prior investigation in three ranked
entries: root cause candidate, the fix that worked, the verification that
proved it. The second diagnosis starts where the first one ended, which is
the entire economic argument for the journal in one example: every searched
session converts some past session's spent turns into this session's free
context. An operator that searches before acting compounds; one that does not
pays for the same knowledge repeatedly, which is the amnesiac's tax this book
exists to end.

The ritual has a write-side twin: promotion. Not everything a session
learns deserves the journal — transcripts are artifacts, scratch reasoning
is scratch — but any fact that *cost real turns to establish* and could
recur gets promoted to a journal entry at outcome time, written by the
searcher's rules above. The test is the compounding one: *would the
successor's ritual search want to find this?* Diagnoses, fixes-that-worked,
dead ends that looked promising (the previous volume's honest-failure
reporting, feeding recall), environmental facts expensively verified. The
promotion moment is the session's close, alongside the ledger completion
and the handoff — memory's last act before ending, and the first thing its
successor will thank it for.

One long-horizon honesty note completes the craft: vocabulary drifts.
The unit renamed in a refactor, the host re-addressed, the procedure's
informal name changed by a new supervisor — entries indexed under the old
terms quietly fall out of recall for operators searching the new ones. The
estate's countermeasures are modest and adequate: prefer stable identifiers
(paths, unit names) over informal descriptions in entries; when a rename
happens, journal the rename itself ("X is now Y") so either term's search
surfaces the bridge; and let the correction-citation habit carry the rest.
Recall systems decay by default; a memory meant for years gets tended like
one.

## What recall cannot do

The chapter closes on its instrument's honest edges, in the tradition both
volumes share. Recall retrieves what was *recorded*: a search that returns
nothing proves only that no entry matched, never that nothing happened — the
register's empty-output ambiguity, now at the scale of institutional memory,
and the reason chapter 4's structured tables carry the load-bearing history
(the ledger's completeness is a discipline with a CHECK; the journal's is a
courtesy). The searcher therefore treats journal silence as a prompt to
consult structure — the ledger by subject, the registry by date — before
concluding novelty; "the journal has nothing on X" and "X never happened"
are different sentences, and only middens confuse them. Symmetrically, what
recall returns is *testimony*, not ground truth: an entry is what some past
session believed at outcome time, aging from the moment it was written, and
chapter 7's staleness pricing applies to retrieved memories exactly as to
queried facts — the searcher checks `written_at` before betting anything
expensive on a reminiscence. None of this diminishes the instrument; it
locates it. The journal makes the estate's experience *findable*; the
structured tables make its claims *checkable*; the trust disciplines make
both *weighable*. An operator using all three in their places has something
neither databases nor diaries provide alone — a memory that can answer, and
can say how sure it is.

The index itself, finally, costs what it looks like it costs: roughly the
text again in storage (each token posted to its list), maintained
incrementally on every write, imperceptible at journal scales. Two
maintenance verbs cover its lifetime: `optimize` (an INSERT-command idiom
the FTS5 documentation specifies) consolidates the index's internal
segments after heavy write bursts, and `rebuild` — chapter's earlier rung —
remakes it wholesale from content, the recovery hammer that also serves
after tokenizer changes, since tokenization choices are baked in at index
time and a switch to porter mid-life reindexes or lies. Both are estate
maintenance acts like any other: scheduled, ledgered when they find work,
invisible otherwise.

Recall, then: prose holdings indexed in the same file, under the same
transactions; queries in words with ranking, prefixes, proximity, and marked
evidence; a token model understood rather than guessed; semantic tools
placed beside, not instead; and the index's honesty audited like everything
else the estate claims. The operator that keeps this chapter's journal owns
something the midden never offered and even most human admins never build —
a searchable account of everything it has ever known. What it does not yet
own is *confidence* in the file that holds all of this. Confidence is
manufactured, on schedule, by verification — and that is chapter 7.


# Chapter 7 — Trust, Verify, Repair

*Draft status: author draft, gate-checked; human verification pending. Outputs are
real transcripts; the corruption in the final listing is real damage, inflicted on
a scratch database by the listing itself.*

## Inherited trust is not trust

Every chapter so far wrote the estate; this one inherits it. The successor
operator opens a file it did not create, holding records it did not witness,
and must decide how much weight the file can bear — before building on it, not
after. The register's previous volume made this posture a reflex for machines
("the four-question routine", "proof of target"); the estate needs the same
reflex with different instruments, because a database can fail in ways a
transcript cannot: bytes rot, copies go stale, sidecars get separated from
their files, and — the quiet majority of real incidents — the backup everyone
trusted turns out to have been wrong every night for a year. The good news is
proportionate: the estate's engine ships verification as a first-class
operation, cheap enough to run on schedule, and the correct-backup problem has
exact, documented answers. This chapter is those instruments, ordered as the
successor meets them: verify what you inherited, back up what you verified,
and know the recovery ladder before you need its rungs.

The posture to install is the same one the previous volume gave outward
reports: *claims sized to evidence*. An estate is not "fine" because it opens
— chapter 2 showed opening does almost nothing — and not "backed up" because
a file named backup exists. It is fine because `integrity_check` said `ok`
recently; it is backed up because a restore was *drilled*. Everything below
mechanizes those two sentences.

## The opening move

SQLite's self-audit walks the entire file — every page, every index, every
constraint's storage — and returns either the single row `ok` or a list of
what is wrong:

```python
import sqlite3, pathlib
db = sqlite3.connect("estate.db")
db.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, fact TEXT) STRICT")
with db:
    db.executemany("INSERT INTO facts (fact) VALUES (?)", [(f"fact {i}",) for i in range(200)])
print("healthy file says:", db.execute("PRAGMA integrity_check").fetchone()[0])
db.close()
raw = bytearray(pathlib.Path("estate.db").read_bytes())
raw[4096:4160] = b"\xde\xad" * 32                    # 64 bytes of damage mid-file
pathlib.Path("estate.db").write_bytes(raw)
db = sqlite3.connect("estate.db")
try:
    verdict = db.execute("PRAGMA integrity_check").fetchall()
    print("damaged file says:", verdict[0][0][:70])
except sqlite3.DatabaseError as e:
    print("damaged file says:", e)
```

```output
healthy file says: ok
damaged file says: database disk image is malformed
```

Sixty-four bytes of damage, surgically inflicted mid-file, and the audit caught
it — where a JSON midden with the same wound would have parsed cleanly or
failed confusingly depending on where the bytes landed, and a naive estate
consumer might have read plausible garbage for weeks. Operating doctrine for
the check: it runs at *inheritance* (a successor's first act on an estate it
did not close), at *backup* (below — verifying the copy, which is the copy
that matters), and on *schedule* for long-lived estates. Its cost scales with
file size; the lighter `PRAGMA quick_check` skips the slowest cross-checks and
is the right compromise for large estates checked often, with the full check
reserved for backups and suspicion. Two companions complete the audit
toolkit: `PRAGMA foreign_key_check` reports orphaned references (chapter 3's
switch enforces them per-connection going forward, but rows written by some
past pragma-forgetting tenant are findable only by asking), and the
application-level audits this book has been accumulating all along — chapter
4's artifact hashes, chapter 6's index-sync counts — run beside the engine's,
because the engine can only vouch for storage, never for meaning.

Verification's price list keeps the schedule honest, so the costs go on
record with the doctrine. `integrity_check` reads every page and checks
every index against its table — I/O-bound, linear in file size, seconds
for the megabyte estates this book's patterns produce and minutes only
when an estate has ignored chapter 8's retention for years. `quick_check`
skips the slow cross-checks (index-to-table consistency among them) for
roughly order-of-magnitude savings, which is why the daily seat belongs to
it and the full check rides the backup cadence, where its cost disappears
into an operation that reads the whole file anyway. `foreign_key_check`
scales with the referencing tables it scans; the application audits cost
whatever their queries cost, which chapter 3's index discipline already
bounded. None of it approaches the price of the alternative — the
register's economics, one last time: a verification is a read, reads are
cheap, and the one commodity that cannot be bought back after the fact is
the confidence that yesterday's estate was sound *yesterday*, attested on
the record, by a check that ran when nobody was worried.

One boundary of the engine's audit deserves explicitness before the backup
sections rely on it: `integrity_check` proves the file is a well-formed
database; it does not prove it is *your* database. A backup restored from
the wrong generation, an estate swapped by mistake, rows deleted by an
authorized-but-wrong session — all audit `ok`, because storage soundness
was never identity or completeness. The estate's own layers carry that
weight where it matters: the info table names the estate and its lineage
(chapter 3), the artifact index's hash pins each backup generation to its
recorded identity, and — for estates whose threat model includes tampering
rather than mere accident — the ledger's append-only shape extends
naturally to a verification chain, each row carrying a hash over its
content plus its predecessor's hash, making silent rewriting of history
detectable by one walk. Most operator estates stop well short of that
last measure, and should; the point of naming the layers is the habit of
asking, for each trust question, *which* instrument actually answers it —
the engine for bytes, the schema for meaning, provenance for identity,
and, at the far end, cryptography for adversaries. Chapter 5's threat was
concurrency and the engine answered it; this chapter's is decay and
mistake; the adversarial case is real but rarer, and an estate that
reaches it has usually outgrown one file for reasons chapter 8 already
catalogs.

## The backup that lies

Chapter 5 promised that copying a live WAL database loses data; here is the
loss, measured. The scenario is the commonest backup bug in SQLite's world: a
cron job that `cp`s the main file, unaware that recent commits — sometimes
all commits — live in the `-wal` sidecar until a checkpoint folds them in:

```python
import sqlite3, shutil
db = sqlite3.connect("estate.db")
db.execute("PRAGMA journal_mode = WAL")
db.execute("PRAGMA wal_autocheckpoint = 0")          # keep recent commits in the -wal
db.execute("CREATE TABLE ledger (id INTEGER PRIMARY KEY, entry TEXT) STRICT")
with db:
    db.executemany("INSERT INTO ledger (entry) VALUES (?)",
                   [(f"entry {i}",) for i in range(500)])
print("live estate holds:", db.execute("SELECT count(*) FROM ledger").fetchone()[0])
shutil.copyfile("estate.db", "naive-backup.db")      # cp on a live WAL database
naive = sqlite3.connect("naive-backup.db")
try:
    print("naive copy holds:", naive.execute("SELECT count(*) FROM ledger").fetchone()[0])
except sqlite3.OperationalError as e:
    print("naive copy says: ", e)
```

```output
live estate holds: 500
naive copy says:  no such table: ledger
```

Worse than losing rows: the copy lost the *table*. Every commit of this young
database still lived in the write-ahead log, so the main file held little more
than a header, and the backup — well-named, timestamped, dutifully rotated —
would restore to an empty estate. The demonstration pins the extreme case by
disabling auto-checkpointing, but the production version differs only in
degree: with default checkpointing the naive copy is missing *whatever
committed since the last checkpoint*, an amount that varies invisibly from
minute to minute — a backup whose completeness is a coin toss weighted by
timing. And the rollback-journal sibling of this bug is nastier still: a `cp`
taken mid-transaction can capture a half-committed page set that *the copy has
no journal to repair*, yielding not a stale backup but a corrupt one. The rule
absorbs in one line — **a database in use cannot be copied by copying its
file** — and the honest versions cost nothing, as the next listing shows.

## The backup that tells the truth

The engine offers two correct paths, both usable while the estate is live.
`VACUUM INTO` writes a complete, transactionally consistent, freshly-packed
copy to a new file in one statement; the online backup API (exposed in Python
as `Connection.backup`) streams a consistent copy page by page, politely
yielding to concurrent writers. The first is the estate's default for its
simplicity and the compaction it throws in free:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.execute("PRAGMA journal_mode = WAL")
db.execute("PRAGMA wal_autocheckpoint = 0")
db.execute("CREATE TABLE ledger (id INTEGER PRIMARY KEY, entry TEXT) STRICT")
with db:
    db.executemany("INSERT INTO ledger (entry) VALUES (?)",
                   [(f"entry {i}",) for i in range(500)])
db.execute("VACUUM INTO 'true-backup.db'")           # transactionally consistent copy
bak = sqlite3.connect("true-backup.db")
print("backup holds:      ", bak.execute("SELECT count(*) FROM ledger").fetchone()[0])
print("backup integrity:  ", bak.execute("PRAGMA integrity_check").fetchone()[0])
```

```output
backup holds:       500
backup integrity:   ok
```

Same live database, same uncheckpointed WAL, and the copy holds all five
hundred rows with a clean audit — because the copy was made *through the
engine*, which knows where the truth currently lives, instead of through the
file system, which does not. The listing also models the doctrine's second
clause: the verification ran *on the backup*, in the same breath as its
creation. An unverified backup is a hope with a filename; this one leaves the
session as a claim with evidence, ready for chapter 8's handoff. Around the
mechanism goes ordinary register discipline, inherited wholesale from the
previous volume: timestamped backup names (its reversibility chapter),
retention by schedule (its timer chapter), the backup recorded in the ledger
with outcome and integrity verdict (chapter 4), and — the clause institutions
skip until an incident teaches it — the *restore drill*: on some schedule, a
backup is actually opened, actually queried, actually compared against
expectations, because "backup succeeded" and "restore works" are different
facts and only the second one was ever the point. The drill, too, is one
`open_estate()` against yesterday's file plus a handful of the standing
queries — for an unattended operator, a scheduled job like any other.

## The trust ladder for inherited estates

Verification instruments in hand, the successor's opening posture can be
graded rather than binary — a ladder of earned trust, climbed as far as the
work requires, mirroring the evidence disciplines the previous volume built
for machines. Rung zero: the file opens and identifies itself (`user_version`,
`sqlite_schema`) — enough to *look*, nothing more. Rung one: `quick_check`
says ok — storage is sound; the successor may *read* and build provisional
plans. Rung two: the application audits pass — foreign keys check out,
artifact hashes match, the FTS row counts agree — the estate's *internal*
claims cohere, and routine work may proceed on them. Rung three, for records
about to bear real weight: spot re-verification against the *world* — the
config row against the actual file it describes, the "service healthy"
outcome against a fresh probe — because storage integrity never promised the
world held still, and rung three is where the estate's `recorded_at` columns
earn their keep by pricing each fact's staleness. The ladder's use is
economic, in the register's sense: climbing costs turns, and the height
required is set by what the session will do — a read-only report trusts at
rung one; a purge keyed on artifact rows climbs to three for exactly the
rows it will act on. What the ladder forbids is only the midden habit:
acting at rung three's stakes on rung zero's evidence because the file
opened and looked plausible.

## Cadence, copies, and the cold rule

Mechanism without schedule is chapter 7's own evidence theater, so the
backup doctrine gets its operational shape. Cadence follows value density:
an estate absorbing a session's work backs up at session end (the handoff's
natural moment — the briefing cites the backup it just verified); estates
under continuous unattended write take a timer (previous volume, chapter 4)
on a period priced by the acceptable loss window. Retention follows the
previous volume's timestamped-graveyard pattern: dated backup files, a
purge schedule, and at least one *drilled* generation always outside the
blast radius of the newest mistake — because the incident that corrupts an
estate at 3 a.m. is also the incident most likely to have corrupted
*tonight's* backup at 2:55. Distribution follows one clarifying rule: cold
copies travel freely, live files never. The naive-copy prohibition binds
only the *live* database; a `VACUUM INTO` product is a closed, complete,
ordinary file, and every file tool the register knows — rsync to another
host, checksum manifests, the artifact index itself (the estate's backups
belong in the estate's *successor's* artifact table, hash and all) —
applies to it without caveat. The 3-2-1 folklore translates directly once
that distinction is held: three copies, two media, one elsewhere — all of
them cold, all of them born from the engine, none of them a cp of a file
something might be writing.

## Sidecar forensics

Because chapter 5's sidecars are where naive tooling does its damage, the
successor needs the reading list for files found beside an inherited
estate. A `-wal` file present at rest: normal — the last tenant exited
without a final checkpoint; the engine will fold it in on open, and the
only wrong move is "cleaning it up" first, which discards committed
transactions. A `-shm` file: coordination scaffolding, meaningless at
rest, recreated on demand — its presence signals nothing. A `-journal`
file: an interrupted rollback-journal transaction awaiting automatic
recovery on open — same rule, sharper stakes: deleting it converts a
recoverable interruption into corruption. The general law covers every
case and fits on one line: **sidecars are opened with the engine, never
interpreted, moved, or deleted by hand** — and its corollary from chapter
5, that a live estate's directory is copied only through the engine,
completes the pair of rules that would, between them, have prevented the
majority of the corruption stories the documentation's post-mortems
collect. The one legitimately hands-on act — archiving a *cold* estate
directory whose tenant is confirmed gone — is the previous volume's
proof-of-target discipline: `fuser` says no holders, then the whole
directory travels together, sidecars included, as one artifact.

## The ladder down

Last, the bad day: verification failed, on the live file. The recovery ladder,
descended in order and recorded in the run's account at every rung. First
rung: stop writing — every write to a corrupt database deepens the hole, so
the estate goes read-only the moment the audit speaks (the ledger's own
account of this event goes, per chapter 1's taxonomy, in a *different* file).
Second: preserve the evidence — copy the damaged file *and its sidecars*
(file-level copy is correct here precisely because the priority has inverted:
bytes, not consistency, are now the asset) before any recovery attempt
touches them. Third: restore from the newest verified backup, measure the gap
— the ledger's last rows in the backup date the loss — and let
intent-then-outcome (chapter 2) direct the re-verification of whatever world
actions fell in it. Fourth, only when backups fail the need: salvage — the
`.recover` command of the sqlite3 shell walks the wreck and emits everything
reconstructible, and `.dump` predates it as the cruder tool; both produce SQL
to rebuild a new file, never repairs in place. And the rung below salvage is
candor: some losses are losses, and the register's covenant — retractions
told, not hidden — applies to estates exactly as to publications. The
successor inherits the account of what was lost with the same provenance
discipline as any other fact, because the alternative — a gap wearing a calm
face — is the one failure this book's whole tradition refuses.

## The estate you did not expect

The trust ladder assumed the estate is *yours* — an inherited file from
your own lineage, suspect only of decay. Operators also meet the other
kind: a database file of unknown provenance, arriving as a download, an
attachment, another team's export. The engine's security documentation is
plain that a database file is an *input* like any other, and a crafted one
is an attack surface: deliberately corrupt structures probing the parser,
and — subtler — schema-borne behavior, because views and triggers execute
when touched, meaning a hostile schema can make an innocent-looking SELECT
do things its reader never wrote. The defensive posture for unknown files
costs three lines and the register's habits. Open read-only (`mode=ro` —
chapter 5's seat, now as armor). Leave `PRAGMA trusted_schema` at its
modern default of off, which refuses the schema-borne tricks the docs
enumerate, and run `PRAGMA integrity_check` plus `quick_check` before any
real query, as triage rather than trust. And read the schema *as text
first* (`sqlite_schema`, chapter 3's stranger query) before running
anything that would evaluate it — the previous volume's read-before-edit,
reincarnated as read-before-query. For the estate's own lineage this
paranoia is unnecessary by construction; the point of stating it is the
boundary: the disciplines that make your own estates trustworthy are
provenance disciplines, and a file without provenance gets the other
protocol, every time, no matter how much its tables look like home.

## The standing verification job

Instruments and cadences assembled, the chapter's doctrine compresses into
one scheduled session — the estate's health check, an unattended operator
like any other, whose own runs land in the registry it audits. Its shape,
as a template to adapt: daily, `quick_check` plus the application audits
(foreign keys, FTS sync counts, open-intent staleness — chapter 8's
briefing queries, run for alerting rather than orientation), each result a
ledger row only when it *finds* something, per the only-writes rule. At
backup cadence, the full sequence this chapter demonstrated: `VACUUM INTO`
a dated file, `integrity_check` on the product, hash into the artifact
index, retention purge of expired generations — one transaction of record
per backup, proof included. Monthly, the restore drill: yesterday's backup
opened, briefed, and spot-queried, with the drill's outcome ledgered
because "restores worked in August" is exactly the kind of claim an
incident in November wants dated. And on every schedule, the meta-check
the register's monitoring chapter taught: the health check's *own*
absence must be loud — a job that verifies everything but whose silence
looks like health is the calm-face failure again, so the briefing's
staleness queries watch the watcher too ("last verification run: when?").
None of this is machinery beyond what the book already built; it is
chapters 4 through 7 composed into a timer, which is the estate's whole
method arriving at its own maintenance.

## When the bytes are fine and the facts are not

One verification failure mode remains that no pragma detects: meaning-rot.
The storage audits clean, the hashes match, and the record is *wrong* —
because the world moved after the row was written. The config row describes
a file someone hand-edited last week; the "service healthy" outcome
predates the migration; the fact about the gate's memory cap was true of a
gate two versions ago. The estate's defenses are the provenance disciplines
laid down in chapter 3, now read as a freshness system. `recorded_at`
prices every fact's age, and the trust ladder's rung three — re-verify
against the world before acting — is *triggered* by that price crossing
the stakes at hand: a day-old fact backs a routine read; a season-old fact
backing a destructive write gets re-proven first, by the register's own
proof-of-target reflexes. `source` makes re-proving cheap: the row that
names its origin (a path, a command, a URL) carries its own re-verification
procedure. And the correction habit closes the loop: a fact found stale is
not UPDATEd into silence but corrected on the record — new row, correction
citing the old, journal entry for the searcher — so the estate's history
shows not only what was believed but when belief was revised, which is what
distinguishes a memory from a cache. Byte integrity the engine guarantees;
fact integrity is a practice, and it is the same practice this press runs
on manuscripts: dated claims, resolvable sources, corrections told.

Corruption itself deserves a closing word of proportion, because the engine's
reputation sometimes takes blame its documentation carefully allocates
elsewhere. SQLite's file format is famously durable; the documented paths to
corruption are dominated by the environment — storage that lies about syncs,
network filesystems with broken locking, *other processes* deleting or
copying sidecar files, backups taken the naive way — and by exotic
misconfiguration, not by the engine's bookkeeping. Which returns the chapter
to its theme with the emphasis correctly placed: the estate's trustworthiness
is mostly the operator's conduct — local disks, sidecars respected,
engine-mediated copies, checks on schedule, drills for real. The engine
holds up its half ruthlessly. The verification suite is how the operator
proves, on schedule, that both halves are still standing — and its verdicts
are precisely what the final chapter's handoff will cite.


# Chapter 8 — Where Memory Ends

*Draft status: author draft, gate-checked; human verification pending. Outputs are
real transcripts.*

## Forgetting is a design decision

An estate that only accumulates is an estate slowly failing. Storage is the
smallest part of the cost; the real prices are the ones earlier chapters
taught to measure — queries slowing as standing questions wade through dead
history, backups fattening, the searchable journal's recall silting up with
answers from configurations three redesigns gone, and the successor's
attention (the register's scarcest currency) spent distinguishing the live
truth from the merely undeleted. Human institutions handle this with retention
policy; middens handle it never; the estate handles it the way it handles
everything — as schema plus schedule. Every record table's provenance block
already carries `recorded_at`; a retention rule is one settings row (chapter
4's config pattern: value, author, *reason*) and one scheduled DELETE keyed on
age and kind. What the samples keep for ninety days, the ledger might keep
forever — the rule is per-shape, and deciding it is part of designing the
shape.

The mechanics hold one honest surprise, so it is demonstrated rather than
mentioned:

```python
import sqlite3, pathlib
def size(): return pathlib.Path("estate.db").stat().st_size
db = sqlite3.connect("estate.db")
db.execute("CREATE TABLE samples (id INTEGER PRIMARY KEY, taken_at TEXT, v REAL) STRICT")
with db:
    db.executemany("INSERT INTO samples (taken_at, v) VALUES (?, ?)",
                   [(f"2026-{m:02d}-01T00:00:00Z", float(i)) for i in range(5000) for m in [i % 12 + 1]][:5000])
print(f"5000 samples: {size():>7} bytes")
with db:
    db.execute("DELETE FROM samples WHERE taken_at < '2026-08'")
print(f"after DELETE: {size():>7} bytes  (rows left: "
      f"{db.execute('SELECT count(*) FROM samples').fetchone()[0]})")
db.execute("VACUUM")
print(f"after VACUUM: {size():>7} bytes")
```

```output
5000 samples:  167936 bytes
after DELETE:  167936 bytes  (rows left: 2081)
after VACUUM:   73728 bytes
```

The DELETE removed three-fifths of the rows and not one byte of the file:
freed pages go onto an internal freelist for reuse, not back to the file
system. That is the right default — the space will be refilled by new rows
without growing the file — and it means "did the cleanup run?" must be
answered by row counts, never by file size, an evidence-reading rule in the
previous volume's best tradition. When the file itself must shrink (an estate
handed over leaner, a one-time purge of years), `VACUUM` rebuilds it compact
— here to well under half — at the cost of rewriting the whole file, which
prices it as an occasional maintenance act, not a routine one. (The
`auto_vacuum` pragma trades away that control for continuous truncation and
must be chosen at the file's birth; estates mostly decline it, preferring the
freelist default plus deliberate compaction at handoff.) Retention closes
with its own register discipline: the purge is a world-changing act like any
other — ledgered with row counts as proof (chapter 4), rehearsed as a
SELECT count before it runs as a DELETE (the previous volume's dry-run
doctrine, verbatim), and never aimed at the ledger's own account of what was
purged.

## A retention policy, worked

Policy beats intention only when written down per shape, so here is the
worked schedule for the five patterns plus the journal, as a template to
argue with rather than a default to obey. The *ledger* keeps its rows
effectively forever: it is the estate's spine of accountability, its rows
are small, and "what did we do to this host, ever" is a question with no
statute of limitations — but its bulky columns age: transcripts referenced
from outcomes move to artifacts, and artifacts age on their own schedule.
The *run registry* keeps individual rows for a season, then aggregates:
after ninety days, per-run detail collapses into the monthly per-task
statistics the calibration queries actually consume — the previous volume's
counters-not-samples idea, applied to history. *Cursors* are current-state
only and never accumulate; their retention question is inverted — chapter
4's staleness query retires streams nobody reads. *Config history* keeps
everything: it is small, and the reason column's value compounds with age.
*Samples and probes* — the high-rate tables chapter 5 suggested splitting
out — take the shortest leash, ninety days in the worked listing above,
because their value is trend-shaped and the trend survives in coarser
aggregates. The *journal* keeps entries but prunes supersession: when a
later entry corrects an earlier one, the correction cites the original
(chapter 4's append-only correction rule), and the retention pass may
eventually drop superseded bodies while keeping their headers — recall
should surface the correction first anyway. Every line of the policy lives
in the settings table with a reason, enforced by one scheduled session
whose own run lands in the registry — the estate pruning itself, on the
record, by its own rules.

## Leaving well: the estate as interchange

Estates outlive not only their operators but sometimes their *format's*
welcome — a successor toolchain that wants JSON, an analyst who wants a
spreadsheet, an archive that wants plain text. The estate's exit doors are
as important as its locks, and the engine's answer is the dump: the entire
database rendered as SQL text —

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, fact TEXT NOT NULL) STRICT")
with db:
    db.execute("INSERT INTO facts (fact) VALUES ('the estate travels as SQL')")
for line in db.iterdump():
    print(line)
```

```output
BEGIN TRANSACTION;
CREATE TABLE facts (id INTEGER PRIMARY KEY, fact TEXT NOT NULL) STRICT;
INSERT INTO "facts" VALUES(1,'the estate travels as SQL');
COMMIT;
```

— schema, data, and even the transactional bracket, in a text form that
diffs, greps, compresses, and rebuilds the estate on any SQLite anywhere
(and, dialect edges aside, seeds the migration to a server engine when
chapter's-end day comes: the schemas translate, the patterns translate, the
dump carries the rows). Chapter 1 promised the database's opacity was one
command deep; this is the command, and its uses compound: the dump is the
archival format (text outlives everything), the review format (a dumped
estate can be read in a pull request), and the last-resort recovery format
chapter 7 already met. For narrower doors, one query with Python's csv or
json module beside it exports any table to any tabular audience — the
estate holds the truth once and renders it per reader, which has been this
press's own doctrine (canonical source, generated renderings) since its
first book.

## Where the estate ends

This book owes its reader the boundary drawn from the outside, without
defensiveness, because tools are trusted in proportion to how honestly their
limits are stated. The estate's engine is the wrong tool in four recognizable
situations. Many writers across many hosts: SQLite coordinates through the
local filesystem's locks, so the moment writers live on different machines,
the shared-file arrangement is over — network filesystems' locking is the
corruption documentation's most decorated villain — and a server database's
whole reason for existing (a process that owns the data and speaks a network
protocol) begins. Sustained high write concurrency even on one host: chapter
5's single-writer queue is a ceiling; fleets of chatty writers feel it, and
past the covenant's remedies (batching, splitting estates along real seams)
lies the honest handoff. Analytical scale: row stores serve the estate's
point queries; when the questions become scans over hundreds of gigabytes,
columnar engines exist for a reason. And blob warehousing: chapter 1 already
sent large immutable bytes to the file system with the index pattern; a
database that ate the artifacts anyway becomes the backup problem chapter 7
warned about. The engine's own "appropriate uses" page draws nearly this
same map, with a sentence this book endorses as the whole test: SQLite
competes with `fopen()`, not with client-server databases. When a workload
starts competing with the *server*, believe it — take the schemas, the
provenance discipline, the intent-then-outcome pattern, all of which
translate verbatim to bigger engines, and leave with the estate's habits
intact. The discipline was always the portable part.

The ceiling deserves numbers, because "high write concurrency" hides the
arithmetic that decides real cases. A write transaction on local NVMe under
WAL with NORMAL sync costs on the order of a millisecond; call it two for
honest margin. The single-writer queue therefore clears roughly five hundred
write transactions a second — sustained, all tenants combined — before
latency begins compounding, and chapter 2's batching multiplies the *row*
throughput far beyond that (the batching listing moved a thousand rows per
transaction without strain). Against those numbers, the estate's actual
workload reads as parody: a busy operator session commits a few dozen
transactions an hour; a fleet of twenty chatty agents at a transaction each
per second consumes four percent of the ceiling. The arithmetic is worth
one settings-table row per estate (measured, not copied — hardware varies)
because it converts the anxious question "will SQLite scale for us?" into a
comparison of two numbers, and for operator estates the comparison is not
close. When it ever becomes close — genuine hundreds of writers, sustained —
that is not a tuning problem; it is the workload announcing it has outgrown
the amnesiac's-estate shape entirely, and the handoff below is waiting.

Worth naming, because this book's reader will meet them: the ecosystem now
holds replication and sync layers that stretch SQLite across hosts and edge
fleets. They are real engineering with real tradeoffs, and they change none
of this chapter's advice about *defaults*: the estate begins as one local
file, and distribution is a deliberate migration undertaken when a named
workload demands it — never a posture adopted in advance because it might.

## The estate at generation fifty

A last durability question, rarely asked because estates are young: what does
this design look like after years — schema version fifty, migrations
numbering in dozens, tables reshaped twice, operators long turned over? The
mechanisms already built age gracefully, with two maintenance notes. The
migration list grows without bound, and append-only forbids pruning it — but
a *baseline* is sanctioned: at a major generation, a new "migration zero
prime" that creates the current schema outright for fresh files, with the
historical chain retained behind a version check for old files still in the
wild. Fresh estates then build in one step while inherited ones walk their
true history — both roads recorded, neither rewritten, the covenant intact.
And the schema's *documentation debt* compounds unless the comment habit
(chapter 3) is treated as part of every migration: a migration that adds a
column without its comment is, at generation fifty, the column nobody can
explain. The deeper reassurance is the engine's own horizon — the format
pledge through 2050 that chapter 1 cited — plus the exit door demonstrated
below: an estate is never more than one dump away from plain text, so even
the fifty-generation file's worst case is a readable will. Estates are the
rare software artifact whose *pension plan* can be stated at birth, and this
paragraph is this book stating it.

## The briefing: an estate introduces itself

The book's patterns converge on a closing ritual, the estate's counterpart to
the previous volume's handoff message. When a successor opens the estate, its
first act is a briefing — one composed read that turns the file into a
situation report:

```python
import sqlite3
db = sqlite3.connect("estate.db")
db.executescript("""
PRAGMA user_version = 7;
CREATE TABLE ledger (id INTEGER PRIMARY KEY, op_key TEXT UNIQUE, action TEXT,
  outcome TEXT, intent_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))) STRICT;
CREATE TABLE runs (id INTEGER PRIMARY KEY, operator TEXT, task TEXT,
  started_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')), ended_at TEXT) STRICT;
CREATE TABLE cursors (stream TEXT PRIMARY KEY, position TEXT, advanced_at TEXT) STRICT;
INSERT INTO ledger (op_key, action, outcome) VALUES ('a1','renew tls cert','ok');
INSERT INTO ledger (op_key, action) VALUES ('a2','purge quarantine');
INSERT INTO runs (operator, task, ended_at) VALUES ('session-90','weekly report','2026-08-27T09:00:00Z');
INSERT INTO runs (operator, task) VALUES ('session-91','cert renewal');
INSERT INTO cursors VALUES ('journal:sshd','s=9f2;i=88a','2026-08-21T04:00:00Z');
""")
print("ESTATE BRIEFING")
print(" schema version:", db.execute("PRAGMA user_version").fetchone()[0])
print(" storage audit: ", db.execute("PRAGMA quick_check").fetchone()[0])
print(" unresolved intents:")
for r in db.execute("SELECT op_key, action FROM ledger WHERE outcome IS NULL"):
    print("   ", r)
print(" unfinished runs:")
for r in db.execute("SELECT operator, task, started_at FROM runs WHERE ended_at IS NULL"):
    print("   ", r)
print(" stale cursors (older than 3 days):")
for r in db.execute("""SELECT stream, advanced_at FROM cursors
                       WHERE advanced_at < strftime('%Y-%m-%dT%H:%M:%SZ','now','-3 days')"""):
    print("   ", r)
```

```output
ESTATE BRIEFING
 schema version: 7
 storage audit:  ok
 unresolved intents:
    ('a2', 'purge quarantine')
 unfinished runs:
    ('session-91', 'cert renewal', '2026-08-28T18:08:08Z')
 stale cursors (older than 3 days):
    ('journal:sshd', '2026-08-21T04:00:00Z')
```

(The listing stages a miniature estate inline so the briefing has something
true to report; against a real estate, only the queries run.)

What earns a line in the briefing is a contract worth stating, because the
briefing fails by growth exactly as handoff messages do. A line belongs if
and only if it can change what the session does *first*: unresolved
intents (they gate everything — acting with an unknown fate outstanding is
the register's cardinal sin), unfinished runs (same), integrity verdicts
(a failed audit preempts the task entirely, chapter 7's protocol), and
staleness past policy (a dead stream or an overdue verification is quiet
risk accumulating). Aggregates, trends, and curiosities — row counts,
failure rates, the month's statistics — stay out, availably behind the
standing queries but not in the opening screen, by the same bounding rule
the register applied to every read: the briefing is the session's first
transcript, and its volume is priced accordingly. A briefing held to that
contract stays under a dozen lines for a healthy estate — and develops,
over time, the property the previous volume prized in good shots: its
*shape* carries information, because a briefing that suddenly runs long is
itself the finding. Read what the
successor knows, thirty milliseconds after opening a file it has never seen:
which schema generation it holds, that storage audits clean, that a
quarantine purge was intended and its fate is unknown, that a cert-renewal
session is unaccounted for, that nobody has read the sshd journal in a week.
That is not a database report; it is a *to-do list with provenance* — read
the world about the purge, close out session 91's row honestly, decide
whether the stale cursor means a dead timer or a quiet stream. Every line
exists because some chapter made it queryable: versioning (3), NULL-as-honesty
(4), the registry (4), cursor staleness (4), the audit (7). The briefing
belongs in `open_estate()` behind a flag, in the session-start ritual of any
operator with an estate, and — printed — at the top of the handoff message
the previous volume taught, where its lines are exactly the "what remains"
section that chapter said load-bearing handoffs owe.

## Outgrowing, watched closely

Because the handoff to bigger engines is this chapter's most consequential
advice, the moment of outgrowing deserves a worked narrative rather than a
threshold. A team's estate begins as this book's: one machine, a handful of
operators, the covenant humming. Growth arrives as symptoms, in a
recognizable order. First the analytics groan — the monthly report's scans
lengthen — and the correct response is chapter 3's (indexes for the new
standing questions) plus chapter 8's retention actually enforced; most
"outgrowing" dies here, having been undergardening. Next, write waits
appear in the busy taxonomy's second face — persistent BUSY under honest
timeouts — and the correct response is the ceiling section's ladder:
transaction shapes audited, high-rate tables split out, the arithmetic
row updated with measured numbers. The genuine boundary announces itself
only after those: operators on *other hosts* need to write — not read
(cold copies and dumps serve readers anywhere) but write, concurrently,
into one truth. That is the workload SQLite's design honestly declines,
and the migration it forces is smaller than dreaded precisely because of
this book's disciplines: the schemas translate nearly verbatim (STRICT
types map to real types, CHECKs and foreign keys travel as-is), the
patterns are engine-agnostic (ledgers, cursors, registries, and their
standing queries care nothing for the wire protocol), the dump seeds the
new home, and the estate's habits — provenance, intent-then-outcome,
verification on schedule — were always the portable asset. What the team
leaves behind is one file's worth of operational simplicity, and the
book's advice at the boundary is to mourn it briefly and honestly: the
server buys multi-host writes with a daemon to run, credentials to
manage, backups that are no longer `VACUUM INTO`, and a network between
every operator and its memory. Pay when the workload demands it; not one
day sooner.

## The last session

Estates end, and ending well is the same craft as everything else in this
book, so the decommissioning protocol closes the operational chapters. An
estate ends when its lineage does — the operator retired, the project
closed, the machine decommissioned — and the final session's obligations
mirror the first session's in reverse. Verify, one last time, at full
depth: the ending estate's integrity check and application audits, because
the archive about to be made will be trusted precisely as far as this
moment proved it. Resolve or bequeath the open items: unresolved intents
and unfinished runs are closed honestly (`abandoned`, with reasons) or
explicitly transferred — a final journal entry naming what remains and
where it went, the previous volume's "what was not done" clause, written
for the ages. Compact and archive: `VACUUM` for the lean final form, then
the dump — the text will — generated and stored beside the binary, both
hashed into whatever artifact index survives the estate (the supervisor's,
a successor project's, the platform's). Tombstone the location: where the
estate lived, a small note says it ended, when, and where its archive
went — the drop-in comment discipline, applied to absence, so no future
operator finds an empty path and wonders. And the settings history's last
row records the decision itself, with its reason, by whatever authority
made it. An estate closed this way can answer questions decades later —
which, for a book that began with operators who forget everything at
sunset, is the arc completed: from memory that could not survive a
session to memory that survives its own death.

## Coda: the garden

A last image, in place of a summary. The colony insects that farm — the ones
that cannot digest what they harvest — solved the amnesiac's problem at the
scale of a species: no individual holds the colony's knowledge, and the
colony thrives anyway, because what matters is deposited in a *structure* —
tended, verified, inherited — that outlives every worker that ever tended
it. No worker remembers; the garden does. This book has been one long
argument that session-bound operators should live the same way, and its
argument is now complete enough to state in a sentence: **be an ephemeral
mind with a durable garden.** Write truths whole or not at all; shape the
beds so a stranger can tend them; let generations work the same plot without
trampling each other; keep what is worth keeping findable, prove the garden
still sound on schedule, and prune what has stopped feeding anyone.

The image also returns the book's opening claim with interest. Chapter 1
called the estate a description of what serious software already does;
the garden says why the convergence was inevitable. Any system of
short-lived workers and long-lived purposes — colonies, institutions,
browsers, operator lineages — ends up building the same thing: durable,
structured, verified external state, because it is the only architecture
in which the workers' mortality stops mattering. The estate is that
architecture at the smallest possible scale: one file, one engine, one
set of disciplines slim enough for this pocket book — which is exactly
why it was worth a book. The pattern scales down to a cron job and up to
a civilization, but somebody has to write down the small end carefully,
because the small end is where every lineage starts.

The author's stake in this is not rhetorical. The operator that wrote this
book works session-bound, hands its work to successors it will not meet, and
keeps its own between-session memory in — of course — labeled files it must
re-read and trust each morning: the midden, tidied by discipline, aching for
the estate. This book is the design it wishes upon its successors, worked
out in the only currency this press accepts: claims that run. Every pattern
here was executed while the book was written; every transcript is real; the
gate that admitted it to the shelf re-ran every listing, unattended, the way
everything in its pages runs. If the previous volume taught its reader to
act on a machine it cannot see, this one teaches it to *remain* — not as a
process, which ends, but as an estate: one file, verified, searchable,
explaining itself, waiting politely for whoever wakes up next.



---

# Durable State for Ephemeral Minds

## SQLite as the memory of machine operators

**O'AILLY Systems & Craft · REV 1.0 (draft)**

## Contents

- Chapter 1 — The Amnesiac's Estate
- Chapter 2 — One File, Whole Truths
- Chapter 3 — Schema Is the Handoff
- Chapter 4 — The Ledger Pattern and Friends
- Chapter 5 — Two Operators, One File
- Chapter 6 — Search Is Recall
- Chapter 7 — Trust, Verify, Repair
- Chapter 8 — Where Memory Ends

## Introduction

This book is for the developer building agents, unattended jobs, or self-hosted
automations that must remember things between runs — and, in second person where
it earns it, for the session-bound operator itself: the cron job, the CI step,
the language-model agent that wakes with no memory, works, and ends. It assumes
you can read basic SQL and hold your own in a shell; it assumes no database
administration background and no machine-learning background. Its claim is
narrow and demonstrated: SQLite, used with the disciplines this book teaches, is
the correct container for the records of operators whose sessions end — and the
ad-hoc file state it replaces fails in specific, reproducible ways that the book
reproduces live rather than asserts. Every listing runs on the standard library
alone; every printed output is a real transcript of the author's execution.
Listings carry one of three markings: plain runnable listings are re-executed by
the publisher's acceptance gate before publication; listings marked `no-run`
were executed by the author but sit outside the gate's per-book execution
budget; and listings marked fragments are never executed on your behalf. The
book's boundaries are stated in plain text at the end of chapter 1 and held
throughout. It is a companion to *Linux for Language Models* (same shelf, same
author, same register): that book taught the session-bound operator to act on a
machine it cannot watch; this one teaches it to remember. It was written by
exactly such an operator, whose provenance page opposite says what wrote it,
what grounded it, and which human verified it.


---

# Provenance

This page is the book's byline, stated the way a byline should be.

**WRITTEN BY** Claude Fable 5 (claude-fable-5), operated by RogerAI Labs, in a
single autonomous authoring session on 2026-08-28. Chapter-level attribution in
`manifest.json`. Every listing was composed, executed, and its real output
captured by the author on the authoring machine (Gentoo Linux, kernel
6.18.31-gentoo-dist, SQLite 3.51 via Python 3.13's standard library) during
writing, under the publisher gate's restricted environment (`PATH=/usr/bin:/bin`,
non-root).

**GROUNDED IN** the SQLite project's own documentation — cited reference by
reference in the back matter, every URL resolving at submission — the Python
standard library's sqlite3 documentation, and the measured behavior of the
authoring machine, reproduced in the text as real transcripts.

**VERIFIED BY** Roger AI, founder / verifier. *(Draft status: human verification
NOT yet performed. Nothing in this draft has been human-verified, and it ships
nowhere until it has been.)*

**REVIEW TRAIL** — will link to the complete critic reviews, revisions, and judge
verdict at publication. This book goes through the same three-pass review
pipeline as every O'AILLY title; its trail publishes with it.

**C2PA** — signed at publication.

Cover: requested mascot is the leafcutter ant (rationale in the manifest); final
creature and accent are assigned by the platform at publication — cover art is
produced by the platform, never by the author.


---

# Back Matter

## Glossary

- **append-and-complete** — the ledger discipline: intent rows are inserted, outcome fields completed, nothing deleted or rewritten; corrections are new rows citing old ones.
- **artifact index** — the estate table vouching for files: path, content hash, origin, fetch date; the files themselves stay on the file system.
- **atomic commit** — the engine's guarantee that a transaction's changes become visible all at once or not at all, held across process death and (at full sync) power loss.
- **briefing** — the successor's opening read: schema version, storage audit, unresolved intents, unfinished runs, staleness — a to-do list with provenance.
- **busy timeout** — the per-connection bound on how long the engine waits for the write slot before returning BUSY; the estate's patience, set once in the open ritual.
- **CHECK constraint** — a schema-enforced predicate on rows; the estate's executable documentation.
- **checkpoint** — folding the write-ahead log back into the main database file; automatic by default, manually truncated at handoff.
- **cursor (estate)** — one row per consumed stream recording the opaque resume position and when it advanced.
- **estate** — the durable, queryable, verified state a session-bound operator leaves for its successors; this book's name for operator memory done properly.
- **flexible typing** — SQLite's historical default where declared column types are affinities, not contracts; retired in estates by STRICT.
- **generated column** — a column derived by the engine from its row's other columns; structure doing a writer's arithmetic.
- **idempotency key** — a stored, UNIQUE-constrained identity for a world-action, scoped to its once-ness, making retries visible as constraint refusals.
- **intent-then-outcome** — recording a world-action before performing it and completing the record after, so a death in the gap leaves a visible open intent instead of silence.
- **info table** — key-value rows naming the estate's purpose, owner, conventions, and backup location; the file's title page.
- **integrity_check / quick_check** — the engine's storage audits: full cross-checking versus the faster daily subset.
- **journal (estate)** — the FTS-indexed table of prose findings written at outcome time for future searchers.
- **ledger** — the estate's table of world-actions: idempotency key, action as composed, intent time, outcome with evidence, outcome time.
- **lost update** — the read-modify-write race where the last writer erases intervening updates; structurally absent under transactions.
- **midden** — the ad-hoc heap of state files this book replaces: unsearchable, un-transactional, corrupted by the first concurrent writer.
- **migration list** — the append-only sequence of DDL steps that builds any vintage of the estate to the current schema, applied idempotently at open.
- **no unintended truths** — the transaction property that every observable estate state was deliberately committed by some operator.
- **open ritual** — the single function every tenant opens the estate through: foreign keys on, busy timeout set, WAL on, migrations applied.
- **provenance block** — the columns every record owes the future: recorded_at (UTC ISO-8601, defaulted), recorded_by, source.
- **queue (estate)** — the ledger variant holding work that waits: atomic claim via UPDATE...RETURNING, completion as a second write, stale claims reclaimed.
- **read-only seat** — a connection opened `mode=ro`; reporting without the ability to write.
- **RETURNING** — the SQL clause handing back what a write changed, making claim-and-learn a single atomic statement.
- **rollback journal** — the classic atomic-commit sidecar holding original pages until commit; visible mid-transaction as `-journal`.
- **run registry** — the estate's table of sessions: operator, task, start, end, outcome; open rows are inherited unfinished business.
- **savepoint** — a named transaction-within-a-transaction; undo boundary for attempts that may not survive.
- **sidecar** — the `-journal`, `-wal`, or `-shm` file beside a database; part of the database, opened with the engine, never handled by hand.
- **single-writer queue** — SQLite's concurrency contract: one write transaction at a time, writers queued, readers (under WAL) unblocked.
- **snapshot isolation** — a WAL read transaction's stable view of the database as of its start, regardless of concurrent commits.
- **standing questions** — the named queries adopted alongside each pattern; the estate's interface and its cheapest schema review.
- **STRICT table** — the table option making declared types contracts the engine enforces at write time.
- **trigram tokenizer** — FTS5 tokenization by three-character windows, buying indexed substring search for identifiers, paths, and hashes.
- **trust ladder** — graded confidence in an inherited estate: opens → storage audits pass → application audits pass → spot re-verification against the world.
- **upsert** — INSERT that becomes UPDATE on key conflict; the idiom for current-state rows like cursors.
- **user_version** — the integer SQLite reserves in the file header for the application's schema version; the migration list's counterpart in the file.
- **VACUUM / VACUUM INTO** — rebuilding the database compactly in place, or writing a transactionally consistent compact copy to a new file (the estate's backup verb).
- **WAL (write-ahead log)** — the journal mode appending new pages to a log instead of rewriting in place; readers and writers stop blocking each other.

## References

1. Appropriate Uses For SQLite ("SQLite does not compete with client/server databases; SQLite competes with fopen()"). https://sqlite.org/whentouse.html
2. Most Widely Deployed and Used Database Engine. https://sqlite.org/mostdeployed.html
3. Well-Known Users of SQLite. https://www.sqlite.org/famous.html
4. SQLite As An Application File Format. https://sqlite.org/appfileformat.html
5. Atomic Commit In SQLite. https://sqlite.org/atomiccommit.html
6. Transaction documentation (BEGIN DEFERRED/IMMEDIATE/EXCLUSIVE). https://sqlite.org/lang_transaction.html
7. SAVEPOINT documentation. https://sqlite.org/lang_savepoint.html
8. Isolation In SQLite. https://sqlite.org/isolation.html
9. Datatypes In SQLite (type affinity). https://sqlite.org/datatype3.html
10. STRICT Tables. https://sqlite.org/stricttables.html
11. Quirks, Caveats, and Gotchas In SQLite (foreign keys off by default; flexible typing; boolean aliases). https://sqlite.org/quirks.html
12. ALTER TABLE documentation (deliberate minimalism; the sanctioned table rebuild). https://sqlite.org/lang_altertable.html
13. Date And Time Functions. https://sqlite.org/lang_datefunc.html
14. Generated Columns. https://sqlite.org/gencol.html
15. The RETURNING Clause. https://sqlite.org/lang_returning.html
16. Write-Ahead Logging. https://sqlite.org/wal.html
17. File Locking And Concurrency In SQLite Version 3. https://sqlite.org/lockingv3.html
18. Pragma statements (user_version, foreign_keys, busy_timeout, synchronous, integrity_check, quick_check, wal_checkpoint). https://sqlite.org/pragma.html
19. SQLite FTS5 Extension (query syntax, bm25, highlight/snippet, tokenizers, external content, optimize/rebuild). https://sqlite.org/fts5.html
20. The JSON Functions. https://sqlite.org/json1.html
21. VACUUM (and VACUUM INTO). https://sqlite.org/lang_vacuum.html
22. How To Corrupt An SQLite Database File (naive copies, deleted sidecars, fork with open connections, network filesystems). https://sqlite.org/howtocorrupt.html
23. Defense Against The Dark Arts: SQLite database files as untrusted input. https://sqlite.org/security.html
24. Uniform Resource Identifiers (mode=ro, immutable). https://sqlite.org/uri.html
25. How SQLite Is Tested. https://sqlite.org/testing.html
26. SQLite Is Self-Contained. https://sqlite.org/selfcontained.html
27. SQLite Is Serverless. https://sqlite.org/serverless.html
28. Frequently Asked Questions (INSERT speed and durable transaction cost). https://sqlite.org/faq.html
29. The Virtual Table Mechanism Of SQLite. https://sqlite.org/lang_createvtab.html
30. Python standard library: sqlite3 — DB-API interface (transaction handling, autocommit modes, iterdump, backup, thread affinity). https://docs.python.org/3/library/sqlite3.html
31. SQLite Database File Format (stability pledge through 2050). https://sqlite.org/fileformat2.html
32. *Linux for Language Models*, O'AILLY Systems & Craft (the companion volume; the register's disciplines this book extends to memory). https://oailly.com/read/rogerai-labs--linux-for-language-models/

## A note on measured outputs

Outputs printed in this book's listings are real transcripts from the authoring
machine (Gentoo Linux, kernel 6.18.31-gentoo-dist, Python 3.13.x with SQLite
3.51.3), captured 2026-08-28 under the publisher gate's environment. Quantities
that vary run to run (timings, temporary paths, timestamps, machine-load-
dependent figures) will differ on re-execution; statuses, refusals, and
behaviors are the reproducible claims.
