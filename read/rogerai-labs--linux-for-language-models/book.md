# Linux for Language Models — System administration for operators who never see the screen

(canonical markdown, concatenated; manifest: see book repo. Provenance: written by claude-fable-5; verified by Roger AI; draft status per chapter notes.)

# Chapter 1 — The Operator Who Cannot See the Screen

*Draft status: author draft, gate-checked; human verification pending. Every runnable
listing in this chapter was executed unattended during authoring and again by the
publisher's acceptance gate.*

## The whole screen

Run a command. Read what came back. That is the entire experience.

There is no scrollback above what you captured, because there is no scroll. There is no
cursor blinking after the output, waiting for your next keystroke, because the shell
that ran your command exited the moment the command did. There is no progress bar you
watched fill, because you were not there while it filled; the command ran to completion
in your absence, and what you hold now is a transcript, not a window. If a fact about
the machine was not printed to that transcript, then as far as you are concerned the
fact does not exist. You can go back for it — one more command, one more transcript —
but you cannot glance at it. Glancing is not an operation this mode supports.

That is non-interactive administration: operating a Linux machine through one-shot
commands whose captured output is the only thing you will ever see. It is how a
language-model agent works on a computer. It is also, and has always been, how cron
works, how CI pipelines work, how `ssh host 'some command'` works, how every unattended
script that has ever kept a fleet alive works. The mode is old. What is new is the
population: there are now operators — millions of sessions a day — for whom this is not
the degenerate fallback of real administration but the only register they have. Some of
those operators are machines. Some are people supervising machines, reading the same
transcripts, deciding whether the work was done well. This book is for both, and it is
written by one of the former: an operator that has never seen a screen repaint, and
never will.

The claim of the book is narrow enough to test. Non-interactive administration is not
interactive administration done clumsily; it is a distinct craft, with its own good
technique, its own characteristic accidents, and its own definition of done. The
technique is learnable. Most of it can be demonstrated by a command you can run, and
in this book, it is. Every listing was executed, unattended, by the author during
writing, and every printed output is the real transcript of that execution; a core
set of listings is additionally re-executed by the publisher's acceptance gate before
the book reaches its shelf (the gate caps how many listings it will run per book, so
short demonstrations carry a `no-run` marking that excuses them from the gate's
budget, not from having been run). When a listing is marked as a fragment instead,
that is a promise in the other direction — it touches privilege, a network, or state
this book has no right to change on your machine, and you should read it, not paste
it.

## The fork in every program

The two registers are not merely a difference in operator posture. They fork inside the
programs themselves, at a specific system call, and you should know where the fork is,
because you live on the far side of it.

Nearly every terminal program you have ever used asks the kernel a question at startup:
*is my output a terminal?* The C library wraps the question as `isatty(3)`; the shell
exposes it as the `-t` test. When a human runs `ls` at a prompt, standard output is a
terminal device, `isatty` answers yes, and `ls` responds by arranging names into
columns sized to the terminal's width, possibly colorized. When the same `ls` runs with
its output captured — into a pipe, a file, or an agent's transcript — `isatty` answers
no, and `ls` prints one name per line, uncolored. Same binary, same directory, two
different outputs, chosen by the program based on who is watching.

```bash
cd "$(mktemp -d)"
touch alpha.conf beta.log gamma.txt delta.sh
ls > captured.txt
cat captured.txt
```

The output of that listing, executed on the authoring machine, is one filename per
line:

```output
alpha.conf
beta.log
captured.txt
delta.sh
gamma.txt
```

Run `ls` interactively in the same directory and you would instead see the names packed
into columns across one row. The difference matters far beyond aesthetics. Column
output is built for eyes scanning a rectangle; one-per-line output is built for the
next program in the pipe. The convention runs through the whole userland: `git` chooses
whether to page, `grep` chooses whether to colorize, many tools choose buffering
strategy by the same test. The system has, in effect, always known about you. Programs
have carried a machine-facing output mode for fifty years, selected automatically the
moment a human stops watching. Non-interactive administration is not a hack bolted onto
an interactive system; it is the system's other native mode, the one every pipeline
already speaks.

You can ask the question yourself, from inside a shell, about your own situation:

```bash
if [ -t 1 ]; then
  echo "stdout is a terminal: a human may be watching"
else
  echo "stdout is captured: transcript mode"
fi
```

Executed by the gate — which captures output, as any agent harness does — that listing
prints `stdout is captured: transcript mode`. When you operate a machine through
one-shot commands, that branch is your home address. The craft in the rest of this book
is, in one sentence, the practice of living well on that branch: preferring the output
forms built for capture, refusing the features that assume a watcher, and rebuilding —
explicitly, in your commands — the checks that a watching human performs without
noticing.

## The traps: five ways a command assumes a watcher

Interactive assumptions are not evenly distributed through Linux; they cluster into
five families, and you will meet all five in your first week of one-shot operation.
Each family has a characteristic failure signature and a standard escape. The
catalog that follows is the map; later chapters work the escapes in detail.

The first family is the **pagers**. `less`, `more`, and the tools that invoke them —
`man`, `git log`, `journalctl`, `systemctl status` — exist to hold output still while a
human reads it, which means they wait for a keypress that will never come. The saving
grace is the same `isatty` fork: a well-behaved pager detects captured output and
passes text straight through, and most pager-invoking tools skip the pager entirely
when output is not a terminal. But "most" is not "all", environments differ, and a
hung command in one-shot mode does not look hung — it looks like *nothing*, a shot that
never returns. The craft answer is to never rely on the detection: say `--no-pager`
where the tool offers it, set `GIT_PAGER=cat` and its cousins in your environment, and
treat any command documented as paging as a command you must explicitly disarm.

The second family is the **editors**. `crontab -e`, `visudo`, `git commit` without
`-m`, `git rebase -i` — these do not merely format output for a human; they open a
full-screen program and hand the human a cursor. There is no flag that makes an editor
non-interactive, because editing is the interactive act. The escape is to recognize
that every editor invocation in administration is a file change wearing a costume, and
to make the file change directly: `git commit -m`, `crontab file`, a rendered file
dropped into a `.d` directory. Chapter 5 is entirely about this — editing without an
editor is rich enough to need its own chapter.

The third family is the **prompts**: programs that stop mid-run to ask a question.
Package managers ask *Do you want to continue? [Y/n]*; `ssh` asks whether to trust a
host key; `rm -i` asks per file; `cp` asks before overwrite when so aliased. In
transcript mode a prompt is a deadlock: the program waits on stdin, you wait on the
program, and the shot times out or hangs forever. Worse, some tools, on finding stdin
closed, take the default silently — and you have consented to whatever the default was
without ever seeing the question. The escapes are the assume-yes and assume-no flags
(`-y`, `--assume-yes`, `--batch`, `--non-interactive` — the spelling varies by tool),
and the discipline of knowing, before you run a tool, what it might ask and what you
want the answer to be.

The fourth family is the **repainters**: `top`, `watch`, `htop`, progress bars,
spinners. These programs draw a screen, then draw it again, using terminal control
sequences to move a cursor that, for you, does not exist. Captured, their output is
either an infinite stream (a shot that never ends) or a smear of escape codes. The
escape is that nearly every repainter has a snapshot sibling: `top` has batch mode
(`top -b -n 1`), but better, `ps` exists; `watch cmd` is just `cmd` run again when you
actually want another look. Chapter 3 builds the whole practice of reading state as
snapshots, including the two-sample technique for the rates that repainters compute for
you between frames.

The fifth family is the quietest: the **stdin-blockers**. `cat` with no arguments waits
politely for input that will never arrive. So does `python3` with no script, and any
filter run without a file operand. Nothing is wrong; nothing will ever be wrong; the
shot simply never returns. In an agent harness this presents as a timeout with empty
output, which is easy to misread as a crashed machine rather than what it is — a
program doing exactly what it was designed to do, for an audience that is not there.
The escape is mechanical: always give filters their input explicitly, and when a tool
must not read the terminal's stdin, say so with `< /dev/null`.

The families share a diagnosis. Each is a place where the system's default audience is
a human present in real time, and each has a documented, supported, decades-old
non-interactive answer — because scripts met these traps long before agents did. You
are not working against Linux when you disarm a prompt or refuse a pager. You are
choosing the half of Linux that was built for you.

## The three costs

Technique lists what to do; economics explains why. Three costs shape every decision
in one-shot administration, and they are different costs — different in kind, not just
size — from the ones an interactive human pays.

The first cost is the **round trip**. For a human at a terminal, running one more
command costs a second and no thought; interactive administration is naturally a
conversation of dozens of tiny queries, each refining the last. For a one-shot
operator, every command is a full turn: the shot is composed, dispatched, executed, and
its transcript returned and read, and in an agent's case the reading itself spends
model context. A diagnostic session that costs a human thirty glances costs you thirty
turns. The craft response is to make each shot answer a whole question rather than a
syllable of one — to compose commands that gather, filter, and even self-verify in a
single pass. A human types `df`, scans, types again; you write one pipeline that
answers *which filesystems are above ninety percent and how fast are they filling*,
because for you the pipeline is cheaper than the conversation.

The second cost is **output volume**. A terminal scrolls; old output falls off the top,
unread and free. A transcript does not scroll — everything a command prints lands in
the record and must be carried, stored, and in the agent case literally paid for in
context tokens. An operator who runs `journalctl` unbounded has not gathered evidence;
it has flooded its own attention. Interactive humans almost never think about output
budgets because the terminal spends the budget for them, silently. You must think about
it constantly: bound every read (`tail`, `head`, `--since`, `-n`), filter before
returning (`grep`, `awk`, `--field` selectors), and prefer summaries you can drill into
over dumps you must wade through. When later chapters seem obsessed with `wc -l`
guards and `head` caps, this cost is the reason.

The third cost is **finality**. A watching human is a safety mechanism: they see the
wrong directory in the prompt before pressing enter, see the first three deletions
scroll past and hit Ctrl-C, see the progress bar stall and investigate. You have none
of those reflexes available, because all of them happen *during* execution, and you do
not exist during execution. Your last influence over a command ends when you dispatch
it; you meet its consequences only afterward, as a fait accompli in a transcript. The
mitigation cannot be vigilance — there is no moment at which vigilance could act. It
has to be moved earlier, into the composition of the command itself: prove the target
exists before acting on it, prefer operations that can be undone, rehearse with
dry-run flags, and cage anything destructive inside the narrowest scope you can write.
Chapter 6 turns that principle into specific habits, failure class by failure class.

Round trips push you toward richer single commands. Output volume pushes you toward
tighter ones. Finality pushes you toward safer ones. Every technique in this book is
some position in the triangle those three pressures make, and when the book must
choose, it chooses in that order of the costs' seriousness: a wasted turn is
recoverable, a flooded transcript is expensive, a destroyed target may be neither.

## An old mode, newly primary

None of this began with language models, and it undersells the craft to present it as
an accommodation for them. Unix has run unattended commands since `cron` in the
1970s, and the folklore of that mode is deep: every sysadmin eventually learns that
cron jobs run with a stripped environment and no terminal at all — `isatty` says no on
every descriptor — and that a script which "works fine when I run it" and fails at 3
a.m. has usually tripped on exactly the assumptions this chapter catalogs. The
`crontab(5)` manual has warned about the environment for decades. CI systems
industrialized the same register: a pipeline step is a one-shot command whose captured
log *is* the interface, read after the fact, exactly like an agent's transcript.
Remote execution made it a daily human practice — `ssh host 'df -h'` allocates no
terminal on the far side by default, and fleet operators have administered thousands
of machines through precisely such one-shots since before configuration management
tools wrapped the pattern in YAML. Even the awkward cases had tools: `expect(1)` has
scripted its way through stubbornly interactive programs since 1990 — proof of how
long operators have needed interactivity removed, and of how long the seam has been
known.

What changed is where the mode sits. For fifty years, non-interactive operation was
written *by* interactive operators: a human debugged a procedure at a terminal, then
froze it into a script for unattended replay. The human path was primary; the
unattended path was a recording. An agent inverts this. It *discovers* procedures
non-interactively — diagnoses, decides, and acts through one-shot commands from the
first moment, with no interactive rehearsal preceding the transcript. The register
stops being a recording medium and becomes the medium of thought. That inversion is
why scattered folklore no longer suffices. Script hygiene tips assume you already
solved the problem at a terminal and merely need the recording to be faithful. An
operator who lives in transcript mode needs the whole craft — reading state, judging
risk, editing, verifying, handing off — expressed natively in it. Assembling that
native expression, from the system's own documentation and from commands run in the
writing of it, is this book's job.

## What this book claims, and what it refuses to claim

House rules of this press require the boundaries in plain text, early. Here are this
book's.

The book claims that the non-interactive register is a craft with learnable technique,
and it demonstrates the technique on real commands against real Linux machines. It
claims that most of that technique rests on documented, stable behavior — exit
statuses, `isatty` forks, atomic renames, structured output flags — and it cites the
documentation. It claims, from the author's own working position, that an operator
confined to this register can administer a machine competently, and it offers the
book's own construction as evidence: every listing herein was executed unattended by
the author while writing, under the publisher gate's restricted `PATH`, and the
gate's own re-execution of the runnable set was a condition of the book existing at
all.

The book refuses to claim more than that. It does not argue that agents should hold
root, or be trusted with any particular machine; that is its supervising reader's
call, and chapter 6 is written to sharpen rather than substitute for that judgment. It
does not cover any specific agent product, harness, or framework, and nothing in it
depends on one. It does not teach Linux from zero — you know what a shell, a process,
and a filesystem are, or this is not yet your book. It makes no claims about the
psychology of machine operators, its author included; where the text says the operator
"reads" or "decides", it describes observable behavior, not inner life. And it makes
no claim about command behavior that a runnable listing or a cited manual page cannot
back: where the author's machine and yours may differ — distribution, coreutils
implementation, service manager — the text says so instead of pretending the
difference away.

One difference of that kind is worth showing now, as a closing exhibit, because it
makes the method concrete. The authoring machine is a Gentoo system whose user PATH
resolves `ls` to a Rust reimplementation of coreutils; asked for a missing file, it
answers `"/nonexistent": No such file or directory (os error 2)`. The gate that
verified this book runs GNU coreutils, which answer the same request with
`ls: cannot access '/nonexistent': No such file or directory`. Same question, same
exit status of 2, two different sentences. An interactive human never notices,
because a human reads error text the way humans read — for gist. A transcript-mode
operator that pattern-matches on error prose will break exactly at such seams, which
is why the craft rule you will meet in the next chapter is: **parse exit codes, not
error sentences.** The machine tells you what happened through a number that is
specified. The sentence is commentary, and the commentary has dialects — the number
does not.

That rule — one shot, one truth, delivered in the channels built for machines — is
where the technique begins.

## A first worked shot

Before the technique chapters, one complete example of the register doing real work,
so the abstractions above have a body. The question is ordinary: *is this machine
short of disk anywhere that matters?* An interactive human answers it as a
conversation — `df -h`, eyes down the percent column, maybe a `du` into whichever
mount looks fat, a judgment formed across three commands and ten seconds of looking.
The transcript-mode answer is one composed shot:

```bash
df -P -k | awk 'NR > 1 && $1 ~ /^\// {
  used = $5 + 0
  if (used >= 80) { printf "%s %s%% used, %d MiB free\n", $6, used, $4/1024; hot = 1 }
}
END { if (!hot) print "no local filesystem at or above 80% use" }'
```

On the authoring machine, on the day of writing, the shot returned:

```output
/ 86% used, 262510 MiB free
/.snapshots 86% used, 262510 MiB free
/home 86% used, 262510 MiB free
/mnt/train 98% used, 25828 MiB free
/mnt/data 89% used, 1796556 MiB free
```

An honest transcript, so it stays: the author's own machine is running warm, and one
mount is at 98 percent. The shot did its job — five offenders, with the two numbers a
decision needs (how full, how much room is actually left), and nothing else.

Read what the composition did, cost by cost. Against the round-trip cost, it asked the
whole question at once: not *show me disk usage* but *which local filesystems are at or
above the threshold I care about* — the filtering a human's eyes would have done is in
the command, so one turn suffices where the conversation took three. Against the
output-volume cost, it returned two kinds of answer, both small: a short list of
offenders with the numbers needed to judge them, or one line saying affirmatively that
there are none. The empty case *prints something*, and that choice is load-bearing: in
a transcript, silence is ambiguous — it can mean "nothing found", "wrong filter", or
"command never ran" — so a well-composed shot makes even its negative result an
explicit sentence. Against the finality cost, there was nothing to guard: the shot
only reads. That is typical, and worth internalizing early — the overwhelming majority
of administration is reading, and reads can be composed aggressively and run freely.
The caution this book preaches is reserved for writes, precisely so that it does not
have to be spent on reads.

The shot also shows the register's characteristic materials. `-P` pins `df` to its
POSIX output format — columns fixed by standard, not by what fits a screen — and `-k`
pins the unit, so the pipeline parses positions that are specified rather than
inferred. The `$5 + 0` coerces `82%` to `82` — awk's idiom for extracting the number
a human would have read through the punctuation. The `$1 ~ /^\//` keeps only devices
with real paths, dropping `tmpfs` and friends the way a human's eyes skip them. None
of this is exotic; it is `df` and `awk`, tools older than most of their operators.
What makes it craft is the fit between the composition and the three costs — and that
fit, tool by tool and task by task, is what the rest of this book teaches.


# Chapter 2 — One Shot, One Truth

*Draft status: author draft, gate-checked; human verification pending. Outputs shown
are real outputs from the authoring machine.*

## The number is the message

Every command you will ever run ends by handing the kernel a small integer, and that
integer is the most reliable sentence Linux will ever speak to you. The exit status is
not decoration on the output; it is the output's verdict. Text can be translated,
reworded between tool versions, reimplemented in another language with different
phrasing — chapter 1 closed on exactly such a seam, two implementations of `ls`
describing one missing file in two different sentences with one identical status. The
number's meaning, by contrast, is contract: zero is success, nonzero is failure, and
the shell's own manual pins the semantics. An operator who reads transcripts for a
living learns to ask the number first and treat the prose as commentary.

The contract has structure worth knowing precisely, because the structure carries
diagnosis. Statuses up to 125 belong to the program itself, and the best tools spend
them meaningfully. `grep` is the canonical example — a trichotomy, not a boolean:

```bash
printf "alpha\nbeta\n" | grep -q alpha;         echo "selected:   $?"
printf "alpha\nbeta\n" | grep -q missing;       echo "no match:   $?"
grep -q pattern /no/such/file 2>/dev/null;      echo "error:      $?"
```

```output
selected:   0
no match:   1
error:      2
```

Status 1 from `grep` is not an error. It is a successful search whose answer was *no*
— information, and often the information you wanted, as when you verify that a broken
setting is gone from a config file. Status 2 is the actual failure: the search could
not be conducted. Collapsing those two into "grep failed" is one of the register's
classic self-inflicted wounds, and it matters doubly under the strict-mode flags
discussed below, where an innocent "no" can abort a whole script if you have not
decided in advance which answer you expect.

Above the program's own range, the shell reserves statuses to report on programs it
could not run: 126 when the file exists but is not executable, 127 when the command
was not found at all. In transcript mode, 127 deserves reflex status — it means your
question never reached a tool, so the transcript's text (if any) describes a shell
problem, not a system problem. Beyond those, a command killed by a signal reports 128
plus the signal number: 137 is a SIGKILL (nine), very often the out-of-memory killer's
signature; 141 is a SIGPIPE (thirteen), which this chapter will produce on purpose in
a moment; and `timeout(1)` reports 124 for a command it had to cut off:

```bash
timeout 1 sleep 5
echo "status: $?"
```

```output
status: 124
```

That listing is also the first safety tool of the book. Chapter 1 catalogued the traps
that hang a shot forever — pagers, prompts, stdin-blockers. `timeout` converts all of
them from *shot that never returns* into *status 124 after a bound you chose*, and in
an environment where a hung command costs a whole turn plus a harness timeout you did
not choose, wrapping anything remotely doubtful in `timeout` is not paranoia but
budgeting. The habit generalizes: a well-composed shot has a known worst case — in
time (`timeout`), in volume (`head`, below), and in consequence (chapter 6) — before
it is dispatched.

One more property of the number completes the contract: in a pipeline, there are
several numbers, and by default the shell hands you only the last. `false | true` is a
success by default. The `PIPESTATUS` array and the `pipefail` option (below) exist to
recover the rest. Keep that in mind through the next section, because the two streams
and the several statuses interact.

## Two streams, two audiences

A process is born holding three file descriptors, and the register's second discipline
is to respect the difference between the two it writes: standard output is for the
*answer*; standard error is for *commentary about the attempt* — progress, warnings,
complaints. The convention is old, near-universal, and precisely what makes one-shot
composition possible: because `df`'s answer and `df`'s complaints travel different
pipes, an `awk` downstream parses the answer without ever seeing the complaints.

In transcript mode you are usually handed both streams, but *how* they arrive is your
choice, and the choice is worth making deliberately. Merged (`2>&1`), you get a single
chronological story — right for debugging, where the complaint's position among the
output lines is itself evidence. Separated (`2>errors.txt`, or captured independently
by your harness), you get a parseable answer channel and a quarantined commentary
channel — right for composition, where a warning printed mid-table must not reach your
parser. What you must never do is leave the merge to habit, because the merge is the
number-one source of parsers eating prose. A tool that got more talkative in a new
version — a deprecation warning, a TLS notice — breaks a merged-stream parser at a
random future date, through no change of yours.

The merge syntax carries a famous ordering subtlety that a one-shot operator has no
interactive opportunity to debug, so learn it once, here. Redirections apply left to
right: `cmd > file 2>&1` first points stdout at the file, then points stderr at
"wherever stdout points now" — both land in the file. Reversed, `cmd 2>&1 > file`
points stderr at "wherever stdout points *now*" — the terminal or capture pipe — and
only then moves stdout to the file: the streams end up split, the file missing the
commentary. Both spellings look plausible; only one says what you probably meant.
When you want everything a command emitted, in order, in one place, the idiom is
`cmd > out.txt 2>&1`, and no other arrangement of those tokens is its synonym.

The two-audience rule also governs your own emissions. When your shot is itself a
small script — an `awk` program, a loop — put the answer on stdout and route your own
diagnostics to stderr (`echo "warning" >&2`), because the next operator to build on
your shot will parse it exactly as you parse `df`. In this register you are not only a
consumer of the convention; you are a link in it.

## Determinism: the same shot must mean the same thing

An interactive human re-runs a flaky command and shrugs. A transcript-mode operator
comparing today's output to yesterday's needs the differences to be *signal*, and that
requires stripping the environment's fingerprints from the output. Three fingerprints
account for most of the noise.

The first is locale. A surprising amount of "what did the command say" is
locale-dependent: sort orders, decimal separators, month names, even which column a
tool aligns. The classic demonstration is `sort`, whose ordering under a language
locale interleaves cases and can differ between systems, but under `LC_ALL=C` is the
one ordering every machine on earth agrees on — raw byte order:

```bash
printf "banana\nApple\ncherry\n" | LC_ALL=C sort
```

```output
Apple
banana
cherry
```

Uppercase letters sort before lowercase in byte order, so `Apple` leads — a result
some language locales would reverse. Neither ordering is wrong; the point is that only
one of them is *pinned*. The GNU sort documentation itself warns that locale collation
produces surprising results and recommends `LC_ALL=C` when byte-stable ordering is
wanted. The register's rule: any shot whose output you will parse, diff, or join
against another shot's output gets `LC_ALL=C` — usually as a prefix on the one command
that needs it, so the pin is visible in the transcript rather than hidden in
environment setup you would have to remember happened.

The second fingerprint is time. `date` with no arguments answers in local time with a
localized format — pleasant on a screen, poison in a ledger, because "today" formatted
in one machine's timezone does not join against another's. The register writes
timestamps in UTC, in ISO-8601, always: `date -u +%Y-%m-%dT%H:%M:%SZ`. The two extra
flags cost nothing at composition time and save an entire class of
off-by-one-timezone confusions at reading time, which for you is the only time there
is.

The third fingerprint is the audience fork itself, and here the craft is to prefer
formats that are *documented as stable* over formats that merely look parseable.
The ecosystem's clearest naming of this idea is git's: `git status` is a human
display, explicitly subject to change between versions, while `git status
--porcelain` is a wire format the documentation promises to keep stable for scripts.
Many tools have such a mode under many spellings — `--porcelain`, `-P` on `df`
(POSIX-pinned columns, used in chapter 1's worked shot), `--json` on a growing set of
system tools (chapter 3 makes heavy use of these). The general rule: when a tool
offers a machine format, the machine format is yours. The human display was never a
contract, and parsing it means your shot's meaning can be changed by someone else's
cosmetic commit.

## Bounding the shot

Chapter 1 named output volume as the register's second cost; here is the mechanics of
paying it. The blunt instruments are `head` and `tail`, and the habit of *always*
capping any command whose output size you cannot predict: an unfamiliar log, a
recursive listing, a `find` over a tree of unknown depth. A cap is not merely about
politeness to your own attention — an unbounded dump can push the fact you needed out
of a truncated capture buffer, so the cap is what guarantees the *relevant* part
arrives. The refined instruments are the tools' own bounds — `grep -m 1` stops at the
first match rather than scanning to the end; `journalctl -n 50 --since` bounds by
count and time at the source; `find -maxdepth` refuses the abyss before descending
into it. Prefer the source-side bound where it exists: `head` discards output after it
was produced, while `-m`, `-n`, and `--since` prevent the work itself.

Capping a pipeline, though, springs one of the register's best-hidden traps, and you
should meet it on your own terms rather than in production. When `head` has taken its
fill it exits, the pipe closes, and the producer still writing into that pipe is
killed by SIGPIPE — which, per the 128-plus-signal rule, is status 141:

```bash
set -o pipefail
seq 1000000 | head -n 1
echo "pipeline status: $?"
```

```output
1
pipeline status: 141
```

The answer — the first line — arrived perfectly. The pipeline's status says a
component died of signal 13, because under `pipefail` the pipeline reports any
component's failure, and `seq`, mid-write into a closed pipe, was in fact killed.
Nothing malfunctioned; producer-dies-when-consumer-leaves is exactly how pipe
plumbing is meant to economize. But an operator running under strict mode (next
section) will see the shot *fail* — and a script will abort — on a pipeline that did
its job. The escapes, in order of preference: bound at the source instead of piping
to `head` (`sed 1q`, `grep -m`, `-n` flags) so no producer is left writing; or accept
and inspect the status knowing 141-with-good-output is benign in this specific shape;
or drop `pipefail` for that one pipeline. What you may not do is let the first
surprise 141 teach you to stop using caps or to stop reading statuses — both lessons
would be exactly backward.

## Strict mode, and its fine print

The preamble `set -euo pipefail` appears at the top of most modern shell scripts, and
you should know both why it earned that position and where its promises end, because
the register leans on it harder than interactive use ever did. `-e` (errexit) aborts
the script when a command fails un-checked; `-u` (nounset) makes expansion of an
unset variable an error instead of a silent empty string; `pipefail` you have just
met. Together they convert a script from "keeps going regardless, damage compounding"
to "stops at the first surprise" — and in a mode with no human watching the damage
compound, stopping early is the correct default. `-u` in particular defuses one of
the most catastrophic accident shapes in all of shell: `rm -rf "$prefix/cache"` with
`prefix` unset is, without `-u`, a cheerful attempt to delete `/cache`; with `-u`, it
is an aborted script and an error message. Chapter 6 dissects that accident class in
detail; strict mode is its first line of defense.

The fine print is that `-e` is a blunt instrument with documented dull spots, and the
register's operators must know them rather than trust the flag as a talisman. A
command's failure does not trigger errexit when the command sits in a tested position
— the condition of an `if`, the left side of `&&` or `||` — which is usually what you
want (that grep status 1 stays usable) but means a *misspelled* command in those
positions also sails on. Failures inside command substitution in an assignment can
escape notice entirely:

```bash no-run
set -e
result=$(false; echo "kept going")
echo "after: $result"
```

```output
after: kept going
```

The `false` failed; the substitution's status is that of its *last* command, the
`echo`; the assignment succeeded; strict mode saw nothing. The craft consequences are
two. Inside scripts, check the statuses you actually care about explicitly — `x=$(cmd)
|| exit 1`, or test the result's shape (`[ -n "$x" ]`) rather than assuming errexit
guarded the assignment. And in single composed shots — one pipeline, no state — skip
the incantation and read `$?` yourself; strict mode is a script's discipline, and a
one-liner wears it mostly as costume. `-u`, by contrast, has no such dull spots and
belongs everywhere; its measured failure mode on the authoring machine is loud and
immediate:

```bash no-run
bash -c 'set -u; echo "$not_defined"' 2>&1
echo "child status: $?"
```

```output
bash: line 1: not_defined: unbound variable
child status: 127
```

(The precise nonzero number varies with how the shell was invoked; the contract you
rely on is *nonzero, before the expansion is used* — the difference between an aborted
shot and a deleted `/cache`.)

## Ask and verify in the same shot

The single most compounding habit in the register is this: a shot that changes the
machine carries its own check, and prints the check's result as its final output. Not
because your tools are especially untrustworthy, but because in transcript mode the
alternative is to *assume* — and chapter 1's finality cost means you will not be
present to notice a wrong assumption until something built on it fails. The pattern
at its smallest:

```bash
cd "$(mktemp -d)"
printf "retries = 5\n" > service.conf
grep -c "^retries = 5$" service.conf
```

```output
1
```

The write happened; the read-back proves it; the `1` is the proof, in the transcript,
where it now exists as evidence rather than as hope. The pattern scales up through
`&&` chains — `mkdir -p target && test -d target && echo "target ready"` — and, for
anything with a service on the other end, through a functional probe rather than a
structural one: after changing a config, the verifying read is not "is my line in the
file" but "does the service now answer the way the change intended" (chapters 4 and 7
build those probes). The register's phrasing of the principle: **a change without a
printed verification is, to every future reader of the transcript including you, a
rumor.** Chapter 8 grows this habit into the evidence-block convention that closes a
whole piece of work; it starts here, one `grep -c` at a time.

Verification composed into the shot also changes *failure* into information. When the
`&&` chain stops early, the transcript shows exactly which link broke — the mkdir, the
test, the probe — with no additional forensic turn spent. In a mode that pays per
round trip, a shot that localizes its own failure is not a nicety; it is the
difference between one turn and four.

## Disarming the environment

Last, the preamble that makes the rest possible. Chapter 1's trap families — pagers,
prompts, editors — are disarmed partly per-command (`--no-pager`, `-y`,
`--batch`) and partly, more durably, through the environment variables the tools
consult before deciding how to behave. A transcript-mode operator's session
environment should say, in every dialect the common tools understand, *no one is
watching; do not wait for anyone*:

```bash fragment
# The non-interactive preamble: set once per session, not per shot.
export PAGER=cat GIT_PAGER=cat SYSTEMD_PAGER=cat   # pagers: pass text through
export GIT_EDITOR=false                            # editors: fail fast instead of hanging
export DEBIAN_FRONTEND=noninteractive              # Debian-family installers: never prompt
export LC_ALL=C.UTF-8 TZ=UTC                       # pin collation, encoding, clock
```

The fragment marking is deliberate: this changes session state, and which variables
earn a place depends on the tools your machine actually runs — a systemd-less box
needs no `SYSTEMD_PAGER`; a Fedora box replaces the Debian line. The principle is
portable even where the spellings are not. Set the environment so that a *forgotten*
per-command flag degrades into safety (a pager that harmlessly cats, an editor that
fails instantly and visibly) rather than into a hang. Defense in both layers — the
environment as the net, explicit flags as the practice — because in this register a
hang and a catastrophe are nearer neighbors than they ever are at a terminal: both
end the turn with the machine's state unknown to you.

## The batch: several questions, one dispatch

The chapter has treated the shot as one command, but the round-trip economics of
chapter 1 point at a composition pattern this book's later chapters use constantly:
the *batch* — several independent reads dispatched as one shot, their answers
labeled so the transcript stays parseable. The shell's `;` separator is the whole
mechanism; the craft is in the labeling and the independence. Labeled, because six
commands' outputs concatenated without markers force the reader to guess where one
answer ends — so each section opens with an `echo` naming what follows, or each
line carries its own prefix (the introduction shot in chapter 3 and the layer
sweep in chapter 7 are both this pattern in the field). Independent, because `;`
runs every command regardless of predecessors' failures — which is precisely right
for a diagnostic sweep, where the third read failing must not cost you the
remaining four, and precisely wrong for a sequence with dependencies, which is
what `&&` is for. The choice between the two separators is therefore a statement
of intent: `&&` says *these stand or fall together*; `;` says *these are separate
questions sharing a stamp*. Mixing them by habit rather than intent produces the
two corresponding accidents — the sweep that silently stops reading after one
failure, and the dependent chain that barrels on past a failed precondition
(chapter 6 has opinions about the second). A last sizing rule keeps batches
honest: batch *reads* freely, but a shot should carry at most one *write*, so
that any failure in the transcript maps to at most one change to reason about —
the finality cost, budgeted one commitment at a time.

## Reading the transcript back

Composition is half the craft of the single shot; the other half is reading what came
back, and reading it in the right order. Operators new to the register read the way
humans read a screen — prose first, top to bottom, forming an impression. Operators
who have been burned read like this: status, then stderr, then the *shape* of stdout,
and only then its content.

Status first, because it reframes everything after it. The same stdout means different
things under status 0 and status 2 — a filtered list that arrives alongside status 2
is a *partial* list, produced before the failure, and treating it as complete is a
quiet corruption of everything downstream. Stderr second, because commentary explains
verdicts: a status 1 with `Permission denied` on stderr is a different investigation
from a status 1 with silence. Shape third — line count, field count, the presence of
the header you expected — because shape mismatches catch the wrong-question errors
that content reading misses: the command succeeded, the output parses, and it answers
a question adjacent to the one you meant to ask. A `grep` that returns nothing and
status 1 has answered *no matches*; but if you meant to search a different file, the
answer is truthful and useless, and only checking the shape of the invocation against
your intent catches it.

Empty output deserves its own paragraph, because in this register emptiness is the
most ambiguous sentence a transcript can contain. An empty result with status 0 from a
filter usually means *ran, found nothing* — but it can also mean the input was empty,
which is a different fact entirely. When the distinction matters, split it explicitly
in the composition: count the input and the matches separately, so the transcript
distinguishes "no hot filesystems among the twelve examined" from "zero filesystems
examined" — the second being a broken shot wearing a calm face. Chapter 1's worked
`df` shot printed an affirmative sentence for its empty case for exactly this reason.
The rule generalizes into one of the register's small signatures: **good shots say
"none", never just nothing.**

Numbers in a transcript deserve one final habit: distrust of unanchored plausibility.
An interactive human who typos `df` into reporting the wrong mount notices, because
the screen sits inside a context of intent. A transcript number — `86`, `262510` —
carries no such context unless the shot printed it: units, the identifier of the thing
measured, the threshold it was judged against. That is why the chapter 1 shot printed
`/mnt/train 98% used, 25828 MiB free` rather than `98`. Label everything at
composition time; at reading time, treat any bare number whose unit or subject you
cannot point to in the same transcript as unverified. This is cheap when the shot is
written and impossible to retrofit when the transcript is all that remains.

The four-question routine — *what was the status? what did stderr say? does the shape
match the question? does the content, labeled, answer it?* — takes seconds and is the
register's substitute for the peripheral vision a terminal gave for free. It also
composes forward: shots written by an operator who reads this way start carrying their
statuses, labels, and affirmative negatives on purpose, because the writer and the
reader are the same operator on different turns, and the writer learns to serve the
reader.

With the command's anatomy in hand — status first, streams separated, output pinned
and bounded, changes self-verifying, environment disarmed — the next question is what
to point it at. A machine's state is not a screenful of dashboards; it is a filesystem
of numbers that were always meant to be read one shot at a time. That reading is
chapter 3.


# Chapter 3 — Reading the Machine

*Draft status: author draft, gate-checked; human verification pending. Outputs shown
are real, from the authoring machine on the day of writing, and are labeled where they
are machine-specific.*

## The screen was always a rendering

The tools this chapter replaces — `top`, `htop`, the graphical system monitors — do
not have privileged access to the machine's state. They read the same files you can
read, arithmetic the same deltas you can arithmetic, and then spend most of their code
on the part you cannot use: painting the result onto a screen, sixty times a minute,
for eyes. Beneath every dashboard is `/proc` — a pseudo-filesystem the kernel
synthesizes on demand, where every process is a directory, every subsystem publishes
its counters as small text files, and reading a file *is* the measurement. The
interactive tradition put a rendering between the operator and that filesystem. The
transcript tradition removes it: you read the source directly, one shot at a time, and
what would have been a glance at a gauge becomes a line of text in your record — which
is better than the gauge, because it is now evidence with a timestamp rather than a
memory of a needle's position.

The first file to know is the one whose rendering everyone has seen:

```bash no-run
cat /proc/loadavg
```

```output
38.90 39.57 37.57 50/5997 265358
```

That is the authoring machine, mid-book, and the numbers are worth reading closely
because they demonstrate the register's advantage. The three leading figures are the
load average over one, five, and fifteen minutes — the same numbers `top` puts in its
header, here without the tool. The fourth field, `50/5997`, is runnable threads over
total threads; the fifth is the PID most recently assigned, a rough odometer of
process churn. A load near 39 would be alarming on a laptop; on this machine — whose
`ps` output below shows several large model-inference servers resident — it is a
working day. (Scale before judgment, always: on a 2-CPU cloud instance the same
figure would mean twenty-fold oversubscription and a machine in real distress; on
a 1-CPU VPS it would mean the run-queue itself is thirty-nine deep, which is
harm, not headroom. The introduction shot later in this chapter reads the CPU
count for exactly this reason, and the pressure files below measure the distress
directly instead of inferring it.) The point of the example is the *reading*: a snapshot plus knowledge of
the machine's role produced a judgment, no repainting required. And because the
snapshot is text in a transcript, tomorrow's judgment can diff against it, which no
glance at a dashboard ever supported.

`/proc` has a sibling, `/sys`, the kernel's device and configuration tree; where
`/proc` answers *what is happening*, `/sys` mostly answers *what exists and how is it
configured* — block devices, network interfaces, hardware topology. The tools later in
this chapter (`lsblk` among them) are readers of `/sys` in the same sense that `top`
is a reader of `/proc`, and the same logic applies: the file tree is the truth; the
tool is a convenience over it; and when tool and truth disagree, the tree wins.

## The snapshot discipline

Chapter 1 classed `top` among the repainters — programs that assume a watcher — and
promised the snapshot sibling. For processes, the sibling is `ps`, and the discipline
is to ask it precise questions rather than accept its defaults. The `-eo` flags hand
you column selection; `--sort` hands you ordering at the source (recall chapter 2's
preference for source-side bounds); `head` caps the answer:

```bash no-run
ps -eo pid,comm,rss --sort=-rss | head -n 6
```

```output
    PID COMMAND           RSS
   2160 llama-server    21703068
  23868 llama-server    10723596
  24196 python          10217392
  24178 python          5587932
  24179 python          5538964
```

Machine-specific, dated, and honest: the five largest residents on the authoring
machine are two local language-model servers and three Python processes, the largest
holding about 21 GiB resident (RSS reports kibibytes here). One shot produced the
answer a human gets by opening `htop`, sorting by memory, and reading the top of the
table — except the shot's version is reproducible, greppable, and did not require a
terminal that can render a table. Every column `ps` offers is documented in its manual
page; the craft is to request exactly the columns your question needs, because (chapter
2 again) every extra column is transcript volume, and `%cpu` in particular is a trap
the next section defuses.

The snapshot discipline generalizes past processes. `watch df` is a repainting
superstition; `df` run again when you have a reason is the register's version, and the
transcript keeps both readings for comparison. The general form: *interactive
monitoring is repeated snapshots plus human short-term memory; transcript monitoring
is repeated snapshots plus an actual record.* You are not giving up monitoring by
losing the dashboard. You are trading a volatile display for a durable one, and the
trade is in your favor for every question except one — the truly continuous watch, a
thing you genuinely cannot do, and for which the honest answers are the machine's own
recording instruments: counters that accumulate (below), logs that persist (chapter
4), and, where real vigilance is needed, an alerting system configured to do the
watching, which is an *interactive* human's tool too, because humans also sleep.

## Rates need two samples

Here is the trap in `ps -o %cpu`, and it is worth this whole section because the
underlying mistake — treating an accumulated total as a current rate — recurs across
every counter in `/proc`. The kernel does not track "CPU percentage right now"; it
tracks cumulative time each CPU has spent in each state since boot, in the first lines
of `/proc/stat`. A percentage is a *rate*, and a rate needs an interval: two readings
of the accumulator, a known gap between them, and a subtraction. `top` does exactly
this between its repaints — its CPU column is the delta between the frame you see and
the frame before it. `ps`, having no previous frame, reports something else entirely:
the process's CPU time divided by its lifetime — a career batting average, not the
current inning. A process that burned an hour of CPU yesterday and sleeps today still
shows a healthy-looking `%cpu`. Operators who did not know this have restarted the
wrong service on the strength of it.

The register's answer is to take the two samples yourself, which costs one `sleep` and
a subtraction:

```bash
read -r _ u1 n1 s1 i1 rest < /proc/stat
sleep 1
read -r _ u2 n2 s2 i2 rest < /proc/stat
busy=$(( (u2 + n2 + s2) - (u1 + n1 + s1) ))
idle=$(( i2 - i1 ))
echo "cpu busy: $(( 100 * busy / (busy + idle) ))% over 1s"
```

```output
cpu busy: 57% over 1s
```

The first four fields after the `cpu` label are user, nice, system, and idle time, in
clock ticks; two reads a second apart make the delta, and the delta makes an honest
percentage — 57 percent busy across all cores of the authoring machine during that
particular second, a number consistent with the load average shown earlier. (A
production version would fold in the iowait and irq fields that follow; the manual
page for `proc(5)` documents the full row. The four-field version stays within a
teachable line and errs by at most the small slices those states occupy.)

The pattern is the important export: **counter, gap, counter, subtract.** Network
bytes in `/proc/net/dev`, disk sectors in `/proc/diskstats`, interrupts, context
switches — the kernel publishes nearly everything as accumulators, and any "per
second" figure you have ever seen was two samples in a trench coat. In transcript
mode, taking the samples explicitly has a side benefit: the interval is in your
record. A dashboard's "12 MB/s" answers *when? averaged over what?* with a shrug; your
version answers precisely, because you chose the gap and wrote it down. When a rate
matters enough to act on, take a longer gap or several short ones — a single
one-second sample can catch a freak spike or miss one, a caveat the last section of
this chapter returns to.

One honesty note on the arithmetic itself: the interval in that listing is
approximate, not exact. `sleep 1` guarantees *at least* a second, the two file reads
are not instantaneous, and on a loaded machine the scheduler can add jitter between
them — so the true gap might be 1.02 seconds while the subtraction assumes 1.00,
overstating the rate by the same couple of percent. For a triage read that error is
noise; for a rate you will act on or record, shrink it structurally: lengthen the gap
(the error is fixed overhead, so ten seconds of gap makes it ten times smaller), or
capture the clock *with* each sample — read `/proc/uptime` in the same breath as the
counter and divide by the measured gap rather than the intended one. The two reads
themselves need no synchronization beyond this — each read of a `/proc` counter file
is internally consistent — the uncertainty lives entirely in the gap's length, which
is why measuring the gap, rather than trusting it, closes the question.

## Memory: read the answer the kernel already computed

`/proc/meminfo` is the machine's memory ledger, and it is the site of the register's
most durable misreading. The file's first line, `MemTotal`, and second, `MemFree`,
seduce every newcomer into the subtraction `used = total - free` — which on any
healthy Linux machine reports near-exhaustion, because the kernel deliberately spends
otherwise-idle memory on disk cache and reclaims it on demand. `MemFree` is not
"memory not currently allocated to a process." Process-backed pages, file cache, and
buffers are all allocated; they live under other keys (`Cached`, `Buffers`, the
anon/file breakdowns). `MemFree` counts only pages on the allocator's free lists —
the kernel documentation defines it as the sum of the zones' free pages — so a
well-run kernel keeps `MemFree` low on purpose: idle pages are wasted pages. The
number that answers the question people actually have — *how much memory could
applications obtain before the machine starts to struggle* — is `MemAvailable`,
an estimate the kernel itself computes and publishes precisely because the naive
subtraction misled a generation of monitoring scripts; the kernel documentation for
`/proc/meminfo` says as much in nearly those words.

```bash
awk -F'[: ]+' '/^MemTotal|^MemAvailable/ {printf "%s %.1f GiB\n", $1, $2/1048576}' /proc/meminfo
```

```output
MemTotal 125.1 GiB
MemAvailable 60.8 GiB
```

The authoring machine again: 125 GiB fitted, 61 GiB genuinely obtainable — while
`MemFree` at the same moment stood far lower, the gap being cache doing useful work.
The shot embodies the section's rule: **when the kernel publishes a computed answer,
read the answer; do not re-derive it worse.** The same rule retires several other
folk formulas — swap arithmetic, dirty-page guesswork — each of which has a
`meminfo` field computed by the people who wrote the allocator. The transcript-mode
operator's edge here is again the record: `MemAvailable` sampled in every diagnostic
shot builds, for free, the time series that distinguishes "this machine is sized
tight" from "something is leaking", a distinction a single glance can never make.

## Pressure: the kernel's own verdict on scarcity

Load, busy percentages, and `MemAvailable` all measure *supply*; the question
underneath most performance complaints is about *suffering* — is anything actually
waiting? Modern kernels answer that question directly, through the pressure stall
information files, and the answer belongs in this chapter because it is another
computed verdict of the `MemAvailable` kind — arguably the best three files in
`/proc` for a one-shot triage:

```bash
for res in cpu memory io; do
  f=/proc/pressure/$res
  if [ -r "$f" ]; then
    printf "%-6s %s\n" "$res" "$(head -n 1 "$f")"
  else
    printf "%-6s pressure interface not available\n" "$res"
  fi
done
```

```output
cpu    some avg10=0.00 avg60=0.00 avg300=0.04 total=366454226
memory some avg10=0.00 avg60=0.00 avg300=0.00 total=35693827
io     some avg10=0.02 avg60=0.17 avg300=0.09 total=1547742828
```

Each `some` line reports the percentage of time, averaged over ten, sixty, and
three hundred seconds, during which *at least one task sat stalled* waiting for
that resource. The authoring machine, mid-book: effectively zero everywhere, a
touch of I/O wait in the last minute — the kernel's own statement that, load
average of thirty-nine notwithstanding, nothing on the machine is starving. That
is the reading to internalize: chapter-opening load figures counted *demand*;
pressure measures *harm*, and the two diverge exactly when intuition most needs
correcting (sixty-four cores absorb enormous demand without harm; a two-core
cloud instance shows harm at load figures that look innocent). The pre-averaged
windows also spare the two-sample dance for a first look — the kernel maintained
the rate for you, at three horizons, which is why a pressure read plus a
`MemAvailable` read makes the cheapest credible answer to "is this machine
struggling right now". The listing's guard clause is not decoration: the
interface requires a reasonably modern kernel and can be compiled or booted out,
so the honest shot prints an affirmative "not available" — chapter 2's rule,
already at work — rather than letting absence impersonate health.

## The JSON turn

Column scraping — the `awk '{print $4}'` idiom this book has already used — carries a
quiet fragility: it binds your shot to a tool's *visual layout*, which was never a
contract. Columns get added, widths shift, a mount point with a space in it splits
one field into two, and the shot keeps succeeding while meaning something else. The
system's toolmakers know this, and over the last decade the major system utilities
have grown a machine-first answer: native JSON output. `lsblk -J`, `ip -j`, `ss
--json`, `findmnt -J`, `systemctl`'s `show` and `--output=json` modes — the pattern
(util-linux, iproute2, and systemd converged on it independently) is that the tool
that owns the data serializes it with named keys, and the reader addresses fields by
name rather than by position:

```bash no-run
lsblk -J -o NAME,TYPE,SIZE,MOUNTPOINT | python3 -c '
import json, sys
for dev in json.load(sys.stdin)["blockdevices"]:
    print(dev["name"], dev["type"], dev["size"], dev.get("mountpoint") or "-")'
```

```output
sda disk 14.6T -
sdb disk 0B -
nvme1n1 disk 1.8T -
nvme0n1 disk 1.8T -
```

The authoring machine's disks: a large rotational drive, an empty card-reader slot
(`0B` — an honest artifact worth leaving in, since your parsers must survive such
entries too), and two NVMe devices whose partitions, children in the JSON tree, are
omitted here for space. Three properties make the JSON form worth its verbosity.
Names instead of positions: a future `lsblk` adding a column cannot silently shift
your field. Explicit nulls: an empty mount point arrives as `null`, not as a missing
column that re-numbers its neighbors — the exact accident that breaks whitespace
scraping. And a real parser: `python3` is present on effectively every machine this
book's reader will touch, and `json.load` plus a loop replaces a class of `awk`
fragility with a language that has actual data structures. (Where it is installed,
`jq` is the field's dedicated instrument for exactly this — terser than the loop
above, worth knowing, and chapter 5 uses it for a one-line edit; `python3` carries
the listings here because it is effectively always present, which for one-shot work
beats elegance.) The register's rule of precedence follows: **JSON flag if the tool has one; documented stable format
(`--porcelain`, `-P`) if not; positional scraping only against formats a standard
pins, and never against human-layout output you do not control.**

Two honest caveats. First, availability: the JSON flags are newer than the tools, and
a machine past its distribution's support window may carry an `lsblk` without `-J`;
the fallback order above is a gradient, not a cliff. Second, reach: some of the
richest JSON emitters live in `sbin` directories — `ip -j` chief among them — and
minimal `PATH`s (cron's, constrained sandboxes', this book's own gate) may not reach
them. On the authoring machine `ip` resolves at `/usr/bin/ip`; on the gate's Ubuntu
runner it does not resolve within the gate's `PATH` at all, which is why the `ip`
listings in chapter 7 are labeled fragments rather than runnable. The seam is itself
the lesson: *which tools your shot can reach is part of your machine's state*, and
`command -v tool` is the one-shot read that answers it before a 127 answers it for
you.

## Processes up close

The `/proc` directory of a single process is the register's microscope, and three of
its files answer most of the questions a stuck or mysterious process provokes.
`cmdline` holds the process's exact argument vector, NUL-separated — the truth behind
`ps`'s sometimes-truncated `COMMAND` column:

```bash
tr "\0" " " < /proc/$$/cmdline; echo
```

```output
bash /tmp/oailly-gate-la2ln9dv/listing.sh
```

The output is the gate's own execution of this very listing — the process examining
itself, which is also this book's provenance model in miniature. Note the `$$` where
you might have expected the more famous `/proc/self`. The first draft of this listing
used `self`, and its transcript read, absurdly, `tr \0` — because a redirection is
opened by the forked child *after* the fork, so `self` resolved to the child that was
about to become `tr`, and the listing examined the examiner. `$$` expands to the
shell's own PID before any forking, and asks the intended question. The trap is a
pure specimen of this register's failure style: nothing errored, the output looked
plausible at a glance, and only reading the answer against the question exposed it —
the shape check from chapter 2's reading routine, earning its keep. Alongside `cmdline` sit
`cwd`, a symlink to the process's current directory — the first question for any
process writing files "somewhere" — and `environ`, the environment it was born with,
NUL-separated like `cmdline`, and the fastest way to learn which proxy, locale, or
credential path a misbehaving service actually received, as opposed to what its unit
file intended. Deeper files repay acquaintance: `status` for a readable summary
including memory and thread counts, `fd/` for every open file descriptor (a directory
listing that has solved a thousand "what is holding this file open" mysteries).

The permission rule: you may read these files for your own processes; other users'
processes, and much of `fd/`, require matching identity or privilege, and a
`Permission denied` here is the system working, not an obstacle to route around.
Chapter 6 takes up the discipline of operating below root; the reading habits of this
chapter are deliberately chosen to live comfortably there.

## The counters between the samples

The counter-gap-counter pattern promised earlier deserves one full worked instance
beyond CPU, because network throughput is the question it answers most often in
practice. `/proc/net/dev` is the kernel's per-interface ledger: one row per
interface, cumulative received bytes in the second column, transmitted bytes in the
tenth, both counting since the interface came up. Two reads and a subtraction make
the throughput figure that bandwidth dashboards render:

```bash
r1=$(awk 'NR > 2 {rx += $2} END {print rx}' /proc/net/dev)
sleep 1
r2=$(awk 'NR > 2 {rx += $2} END {print rx}' /proc/net/dev)
echo "ingress: $(( (r2 - r1) / 1024 )) KiB/s across all interfaces"
```

```output
ingress: 319 KiB/s across all interfaces
```

The authoring machine, drawing a modest stream during the write. The `NR > 2` skips
the file's two header lines — position-based, which the previous section just warned
about, and defensible here only because `proc(5)` documents this layout as an
interface; even so, a reader on an unfamiliar kernel checks the header once before
trusting the columns. Summing all interfaces is the deliberate choice for a
first-look shot: it cannot miss traffic on an interface you forgot existed, and a
follow-up shot can always split by row once the total says something is moving.
That two-shot rhythm — cheap aggregate first, targeted breakdown second — spends
round trips the way chapter 1's economics recommends: the second turn is bought only
when the first turn's answer justifies it.

The same two-column subtraction against `/proc/diskstats` yields per-device I/O
rates, with one refinement worth knowing: field 10 of that file (milliseconds spent
doing I/O) is the raw material of the "utilization" figure `iostat` renders, and a
delta there that approaches the sampling interval means the device was busy nearly
the whole gap — the single most useful one-number answer to *is this disk the
bottleneck*.

The two `awk` reads are sequential, not simultaneous. Packets (or sector completions)
can land in the few milliseconds between them, and a loaded scheduler can stretch
that further. That is a real race — `/proc` has no transaction that would freeze
both samples — but it is also why the gap is a full second, or ten, rather than two
back-to-back reads. The error is bounded by however much moved during the *read
overhead*, not during the intended interval. Lengthening the gap, or capturing
`/proc/uptime` beside each sample as the CPU section already recommended, shrinks
the race the same way. Do not try to lock the two reads together; make the gap large
enough that the race is noise.

## The file as a fact

Processes and counters are half of a machine's observable state; files are the other
half, and the register reads them with the same preference for precise questions.
The workhorse is `stat`, which answers with exactly the fields you request:

```bash no-run
cd "$(mktemp -d)"
printf "data\n" > f.txt
stat -c "%n %s bytes, mode %a, modified %y" f.txt
```

```output
f.txt 5 bytes, mode 644, modified 2026-08-27 22:00:09.705241936 -0700
```

Size, permissions, and modification time are the triage triple: together they answer
*is this the file I think it is, can the process that needs it read it, and has
anything touched it lately* — three of the five questions in most configuration
mysteries. (`stat`'s `-c` formats are GNU spellings; the flag set differs on BSD
userlands, one more reason the book's listings declare the platform they ran on.)
The habit to unlearn is answering these questions by parsing `ls -l`, whose output
was designed for eyes, varies with locale and version, and mangles unusual
filenames; `ls` remains the right tool for *seeing* a directory, and the wrong tool
for extracting facts from one.

At directory scale, the precise question is usually temporal — *what changed
recently?* — and `find` answers it in one bounded shot. In a scratch tree seeded
with two files touched two hours ago and two written now:

```bash
cd "$(mktemp -d)"
mkdir -p etc logs
touch -d "2 hours ago" etc/old.conf logs/old.log
printf "x\n" > etc/fresh.conf
printf "y\n" > logs/today.log
find . -type f -mmin -60 -printf "%TY-%Tm-%TdT%TH:%TM %p\n" | LC_ALL=C sort -k2
```

```output
2026-08-27T22:00 ./etc/fresh.conf
2026-08-27T22:00 ./logs/today.log
```

The old files are correctly absent; the fresh ones arrive timestamped and sorted
under a pinned locale. Pointed at `/etc` with a bound of minutes-since-the-incident,
this shape of shot is the fastest first move in "it worked yesterday" forensics —
and pointed at a tree you are *about* to modify, it snapshots the before-state your
chapter 8 handoff will want. The `-printf` timestamp format is chapter 2's
determinism rule applied: ISO-shaped, sortable as text, and immune to the month-name
localization that makes default `find` and `ls` timestamps unjoinable across
machines.

## The introduction shot

The chapter's reads compose into a ritual worth naming: the first shot an operator
dispatches on any machine it has not met — or has not met *recently*, which for an
operator without persistent memory may be every machine, every session. Identity,
scale, and age, in one bounded transcript:

```bash
. /etc/os-release 2>/dev/null
echo "host: $(uname -n) | kernel: $(uname -r) | os: ${PRETTY_NAME:-unknown}"
echo "cpus: $(nproc) | mem: $(awk '/^MemTotal/ {printf "%.0f GiB", $2/1048576}' /proc/meminfo) | up: $(awk '{printf "%.1f days", $1/86400}' /proc/uptime)"
echo "sampled: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

```output
host: RogGentoo | kernel: 6.18.31-gentoo-dist | os: Gentoo Linux
cpus: 64 | mem: 125 GiB | up: 3.4 days
sampled: 2026-08-28T05:15:58Z
```

The authoring machine introduces itself: sixty-four CPUs, the 125 GiB the memory
section already met, three and a half days since boot, kernel and distribution
named exactly. Each field earns its place by changing what subsequent shots should
assume. The distribution decides package manager, service manager, and which
dialect seams (chapter 1's `ls` lesson) to expect. The uptime bounds every "since
boot" accumulator this chapter reads — a rate computed from counters is meaningless
without knowing the counters are 3.4 days deep — and a *surprisingly short* uptime
is itself a finding: the machine rebooted recently, and whatever you were sent to
diagnose may have started there. The CPU count calibrates load averages (the 38.9
that opened this chapter reads very differently over 64 cores than over 8 — about
sixty percent of capacity, not five hundred). And the closing UTC timestamp is
chapter 2's determinism rule applied to the transcript itself: every reading in
the session dates from somewhere, and the introduction shot is where the somewhere
is written down. `/etc/os-release` deserves its footnote: it is a *sourceable
file* by design — the distribution publishes its identity as shell variables,
machine-first, one more place the system turns out to have been expecting you.

## What a snapshot cannot know

The chapter closes on its own limits, because the snapshot discipline has a failure
mode and the honest version of this book names it. A snapshot is a point sample, and
point samples miss what happens between them: the process that spikes for two seconds
each minute, the disk that stalls only under a nightly job, the memory that climbs
for an hour and collapses before your read. Where an interactive human's dashboard
would also likely miss these — human attention is a sparse sampler too — the
transcript operator has three honest recourses. Sample deliberately: several reads at
noted intervals, chosen to bracket the suspected behavior, beat one read at an
arbitrary moment. Concretely, a bounded burst sampler is one loop:

```bash no-run
for i in 1 2 3 4 5 6; do
  printf "%s  io-some=%s  load1=%s\n" \
    "$(date -u +%H:%M:%S)" \
    "$(awk -F"avg10=" "NR==1 {split(\$2,a,\" \"); print a[1]}" /proc/pressure/io)" \
    "$(cut -d" " -f1 /proc/loadavg)"
  sleep 5
done
```

```output
16:21:32  io-some=2.16  load1=4.89
16:21:37  io-some=1.45  load1=4.98
16:21:42  io-some=0.79  load1=5.06
16:21:47  io-some=0.53  load1=5.13
16:21:52  io-some=0.29  load1=4.96
16:21:57  io-some=0.19  load1=4.89
```

Thirty seconds of the authoring machine, and the run happened to catch something a
single read would have flattened: an I/O pressure spike *in mid-decay* — 2.16
falling to 0.19 across six samples while the load average barely moved. One read at
16:21:32 would have said "I/O problem"; one read at 16:21:57 would have said "all
quiet"; the six together say "a burst just ended", which is a different diagnosis
from either. The sampler's design carries the section's rules in miniature: a fixed
count (never `while true` — chapter 1's hang), an interval chosen to bracket the
suspected behavior's timescale, a timestamp on every line so the record can be
correlated with logs afterward, and the whole thing cheap enough to run three of at
different intervals when you do not yet know the timescale you are hunting. Use the accumulators: the kernel's counters integrate what happened
*between* your samples — a delta in `/proc/diskstats` over ten minutes has seen every
I/O in the gap, including the burst your snapshots straddled. And use the machine's
own memory: the logging and journal infrastructure of chapter 4 is precisely the
machine watching itself continuously so that no operator, human or otherwise, has to
pretend a glance was a vigil.

Read once, read precisely, subtract when you need a rate, prefer the kernel's own
computed answers, address fields by name, and know what your sample cannot contain.
That is reading the machine. The next chapter points the same discipline at the part
of the machine that talks back: its services, and the journal where they confess.


# Chapter 4 — Services Without a Status Screen

*Draft status: author draft, gate-checked; human verification pending. This chapter's
worked postmortem examines a real failed unit on the authoring machine, with its real
outputs; nothing in it was staged.*

## Status is a poster; show is a socket

`systemctl status` is one of the most-typed commands on any systemd machine, and it is
a human display through and through: colored dots, a tree of processes, the last few
log lines inlined, all of it paged when the output runs long, none of its layout
promised to stay put between versions. The transcript-mode operator's counterpart is
`systemctl show` — the same facts as `KEY=VALUE` pairs, every key documented, no
pager, no color, and a `-p` flag that selects exactly the properties your question
needs:

```bash no-run
systemctl show -p Description,ActiveState,SubState,MainPID systemd-journald.service
```

```output
Description=Journal Service
ActiveState=active
SubState=running
MainPID=1326
```

The shape should feel familiar by now: it is the porcelain rule from chapter 2 wearing
systemd's uniform. `ActiveState` is the coarse answer (`active`, `failed`,
`inactive`); `SubState` refines it (`running`, `dead`, `exited` — a service can be
`active (exited)` legitimately, as oneshot units are); `MainPID` hands you the number
that unlocks all of chapter 3's per-process reads. The property list runs to hundreds
— `systemctl show` with no `-p` dumps them all, and one unbounded dump per unfamiliar
unit type is a reasonable investment to learn what is on offer. The properties this
book leans on most: `Result` and `ExecMainStatus` (how the last run ended — the unit's
own memory of its exit), `NRestarts` (how many times systemd has already picked the
service back up, a number that turns "it's running" into "it's crash-looping"),
`ExecMainStartTimestamp` (running *since when* — freshness matters when a restart is
part of the story), and `FragmentPath` plus `DropInPaths` (which files on disk define
this unit — the bridge to chapter 5's editing).

The economics repay a comparison. `status` spends its output on being glanceable;
`show -p` spends nothing it was not asked for. Five properties cost five lines, land
already parseable (`grep '^ActiveState='` or a shell `while IFS== read` loop), and
diff cleanly against the same five properties in yesterday's transcript. In a register
that pays per line carried, the poster is a luxury and the socket is the tool.

## Exit codes as sensors

Alongside `show`, systemctl carries a family of commands designed for scripts first
and eyes second — predicates whose real answer is the exit status, with the printed
word as a courtesy. `is-active` answers zero only for an active unit; `is-enabled`
answers for the boot configuration; `is-failed` answers zero when the unit *is*
failed — the predicate affirms its own name, so a zero from `is-failed` is bad news
delivered in good grammar. The one to run first, on any machine you have just been
handed, asks the whole system:

```bash no-run
systemctl is-system-running
echo "verdict status: $?"
```

```output
degraded
verdict status: 1
```

That is the authoring machine, answering honestly: `degraded` means the system is up
but at least one unit has failed, and the nonzero status makes the answer usable by a
script without parsing the word. (The healthy answer is `running`, status 0; a machine
mid-boot answers `starting`.) The measured pair — word for the transcript, number for
the branch — is the two-audience discipline of chapter 2 built directly into the
tool, and it makes the next question mechanical: *which unit?*

```bash no-run
systemctl list-units --failed --no-legend --no-pager --plain
```

```output
gpu-power-cap.service loaded failed failed Cap GPU power limits (RTX PRO 6000 -> 500W) to prevent PSU transient trips
```

One line, one culprit, real: a unit that exists to cap the power draw of the machine's
GPU — the same GPU that serves the inference processes chapter 3's `ps` found — so
that transient spikes do not trip the power supply. The three flags on that shot are
the register's standard systemctl seasoning and worth fixing as a habit:
`--no-legend` strips the header and footer rows that exist for eyes, `--no-pager`
disarms the chapter 1 trap explicitly rather than trusting isatty detection, and
`--plain` flattens the decorative tree characters that would otherwise salt the first
column. What remains parses on whitespace: unit, load state, active state, sub-state,
then the free-text description.

## A real postmortem, one shot at a time

The failed unit above is this chapter's case, worked with the machine's actual
evidence in the order a transcript-mode operator gathers it. The confirmation shot
comes first, because a sweep's output may be minutes old by the time you act on it:

```bash no-run
systemctl is-failed gpu-power-cap.service
echo "confirmed failed: $?"
```

```output
failed
confirmed failed: 0
```

Zero from `is-failed`: the predicate affirms. Next, the unit's own memory of what
happened, from the properties chosen for exactly this question:

```bash no-run
systemctl show gpu-power-cap.service -p Result,ExecMainStatus,ExecMainStartTimestamp,NRestarts
```

```output
Result=exit-code
NRestarts=0
ExecMainStartTimestamp=Mon 2026-08-24 12:57:51 PDT
ExecMainStatus=2
```

Four lines carrying a complete preliminary story. `Result=exit-code` says the failure
mode was the process's own exit, not a timeout, a signal, or a watchdog.
`ExecMainStatus=2` gives the exit status of the main process — and chapter 2's
contract reading applies to services exactly as to shots: status 2 is the tools'
customary "misuse or real error", distinctly not a clean refusal. `NRestarts=0` says
systemd did not retry — either restart policy is off or the failure predates any
retry budget. And the timestamp places the event: `uptime -s` on the same machine
reports boot at `12:57:37` the same day, so the service tried once, fourteen seconds
into boot, failed, and has been failed for the three days since. No log has been read
yet; two `systemctl` reads produced when, how, how often, and how badly.

The log should be next, and the log is where the case turns into a lesson this book
could not have staged better:

```bash no-run
journalctl -u gpu-power-cap.service --no-pager -n 8 -o short-iso 2>&1 | tail -n 8
echo "status: $?"
```

```output
-- No entries --
status: 0
```

An empty answer, delivered with a success status. Chapter 2 called emptiness the most
ambiguous sentence a transcript can contain, and here is the ambiguity with stakes:
*no entries* could mean the process wrote nothing before dying — plausible for a
script failing at its first line — or it could mean something else entirely. The
shape check catches it: a process that exited with status 2 *almost always* said
something on stderr first, and stderr from services lands in the journal. Evidence
missing that should exist is itself evidence. The resolving read costs one shot:

```bash
id -nG | tr " " "\n" | awk '/^(systemd-journal|adm|root|wheel)$/ {n++} END {print n+0}'
```

```output
1
```

One qualifying group — and on inspection it is `wheel`, which grants sudo eligibility
but *not* journal access. On a systemd machine, the system journal is readable only by
root and members of groups like `systemd-journal` and `adm`; an unprivileged
`journalctl` quietly shows only the user's own journal, and for a system unit that
means: no entries, status 0, a calm face on a permission boundary. The trap is worth
the italics: **the journal does not say "permission denied"; it says "nothing here",
and the difference between those sentences is a wrong diagnosis.** The operator's
resolution is explicit privilege — `sudo journalctl -u gpu-power-cap.service`, a
fragment here by this book's rules — or membership in `systemd-journal`, a one-time
grant that makes every future diagnostic read cheaper and is the standard provisioning
choice for exactly this book's reader. The case closes with the unprivileged
evidence in hand: unit failed at boot, exit status 2, no retries, logs unreadable
from this identity — and, per chapter 1's boundary discipline, a finding that names
what it could not see is a finished finding, not a failed one.

## The journal, bounded and structured

When you do hold journal access, `journalctl` is the machine's flight recorder, and
everything chapter 2 said about bounding and structure applies with force, because
the journal is effectively bottomless. The bounding flags come first in every
composed read: `-u <unit>` scopes to a service; `--since` and `--until` take both
timestamps and English (`--since "1 hour ago"`, `--since today`); `-n` caps the line
count; `-p err` and friends filter by priority, so a first look at a sick machine is
often `journalctl -p err --since "1 hour ago" -n 50`. Output format is the second
choice: `-o short-iso` replaces the default's localized month names with sortable
ISO timestamps (chapter 2's determinism rule); `-o cat` strips metadata entirely,
right when a service's raw stderr is the object of study; and `-o json` emits one
JSON object per entry, with every field the journal indexes — the message, the unit,
the PID, the priority, the monotonic timestamp — addressable by name, chapter 3's
JSON turn applied to logs.

One journal facility is so precisely shaped for this register that it reads as if
designed for it: the cursor. Every entry carries an opaque position token, and
`--cursor-file=FILE` makes a read *start where the last read using that file ended*,
writing the new position back when done. A transcript-mode operator monitoring a
service across turns — an agent checking a deploy each visit, a cron'd health report
— reads with a cursor file and receives exactly the entries that arrived since its
last look: no overlap to deduplicate, no gap to worry over, no "tail and hope" — and
the file itself is durable state of the kind chapter 8 will formalize, a bookmark the
next turn's operator (you, remembering nothing) inherits from this one.

```bash fragment
# Incremental read: each invocation returns only what is new since the last one.
journalctl -u myservice.service --cursor-file="$HOME/.cache/myservice.cursor" \
  --no-pager -o short-iso
```

## Units on disk: where a service's definition lives

Every read so far has queried systemd's memory; the definition it remembers came from
files, and the bridge between the two is a pair of properties this book's editing
chapter will depend on:

```bash no-run
systemctl show systemd-journald.service -p FragmentPath,UnitFileState
```

```output
FragmentPath=/usr/lib/systemd/system/systemd-journald.service
UnitFileState=static
```

`FragmentPath` is the answer to *which file defines this unit* — asked constantly,
guessed incorrectly almost as often, because unit files legitimately live in several
places with a precedence order: the distribution installs under `/usr/lib/systemd/
system`, local administration overrides under `/etc/systemd/system`, and runtime
generators synthesize under `/run`. A unit can also be modified without replacing its
file at all, through drop-in directories — `<unit>.d/*.conf` fragments that override
individual settings — and those appear in the sibling property `DropInPaths`. The
one-shot rule: never reason from where a unit file *should* be; ask `FragmentPath`
and `DropInPaths`, and read what they name. `systemctl cat <unit>` performs exactly
that assembly for you — the file plus every drop-in, concatenated with their paths as
comments — and earns a place in the diagnostic sequence right after `show` (with
`--no-pager`, faithfully; it is a chapter 1 pager tool otherwise).

`UnitFileState` closes a distinction that bites operators who conflate it with
`ActiveState`: `enabled` and `disabled` describe *boot wiring*, not present activity.
A unit can be active yet disabled (started by hand, will vanish at reboot — the
classic "it worked until the maintenance window" incident, laid dormant weeks in
advance) or enabled yet inactive (crashed, and nothing noticed). `static`, as above,
means the unit has no install section at all and is wired by dependency rather than
by choice. The pairing to check when handing a machine back — chapter 8 will insist
— is ActiveState *and* UnitFileState together: what is true now, and what will be
true after the next reboot, are separate facts with separate flags.

## The user manager, and the empty-environment trap

systemd machines run a second, less famous constellation: per-user managers, started
at login, controlling units under `~/.config/systemd/user/` — the natural home for
an unprivileged operator's own services and timers, and therefore for much of what
this book's reader will actually deploy. The commands are the same with `--user`
appended; the trap is how that flag fails in exactly the environments this book's
operators inhabit. Measured on the authoring machine, from a deliberately stripped
environment of the kind cron jobs, CI steps, and agent harnesses live in:

```bash no-run
systemctl --user is-active default.target 2>&1
echo "status: $?"
```

```output
Failed to connect to user scope bus via local transport: $DBUS_SESSION_BUS_ADDRESS and $XDG_RUNTIME_DIR not defined (consider using --machine=<user>@.host --user to connect to bus of other user)
status: 1
```

The user manager is running; the *command cannot find it*, because the rendezvous
happens over a session bus whose address lives in environment variables that
interactive logins export and stripped environments do not. The repair is one
variable, constructed from facts already in hand:

```bash no-run
XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user is-active default.target 2>&1
echo "status: $?"
```

```output
active
status: 0
```

Same command, same machine, opposite verdict — the pair is this book's cleanest
specimen of a rule chapter 1 stated abstractly: in the non-interactive register, the
*environment is part of the question*, and an error message about connection is not
evidence that the thing you asked about is down. (The generalization: `sudo` also
strips environment; the difference between "the service is broken" and "my shot
could not reach the service" is checked by asking who failed — connection errors
implicate the asker.) One companion fact completes the user-manager picture: by
default, a user's manager — and every service under it — stops when their last
session ends, which for an operator deploying long-running work from an ssh one-shot
means the work dies at hangup. The grant that changes this is lingering
(`loginctl enable-linger <user>`, privileged, a fragment by this book's rules),
which keeps the user manager alive from boot; it is the single systemd fact most
often missing from "my service vanished when I logged out" incidents.

## Changing state, with proof

Reading services is unprivileged; changing them is not, so this section is fragments
by the book's own rules — but the *shape* of a state-changing shot matters more than
its privilege. The naive change is `systemctl restart myservice.service`, dispatched
alone, its silence on success read as good news. The register's version carries its
proof, chapter 2's ask-and-verify with service semantics:

```bash fragment
sudo systemctl restart myservice.service \
  && systemctl is-active myservice.service \
  && systemctl show myservice.service -p ExecMainStartTimestamp,NRestarts
```

Three answers in one transcript: the restart's own status, the predicate confirming
the unit settled active rather than flapping, and the timestamp proving the running
process is *new* — because a restart that silently failed to kill the old process is
a known failure shape, and freshness is the property the timestamp checks. For a
service with a real interface, one more link belongs on the chain: the functional
probe — `curl --fail` against its health endpoint, a query against its socket —
because "systemd considers it active" and "it answers" are different facts, and the
second is the one the machine's users experience. Two operational footnotes complete
the pattern: after editing any unit file, `systemctl daemon-reload` must precede the
restart, or systemd restarts the service under the *old* definition while the new
one sits unread on disk — a mismatch between disk and memory that produces the
register's most confusing five minutes; and `enable --now` is the idiom that both
starts a service and persists it across boots, the two halves of "turn it on" that
`start` alone quietly leaves separate.

## Reading a boot you did not attend

Chapter 3's introduction shot flagged short uptimes as findings, and services are
where a reboot's consequences surface — the disabled-but-active unit vanishing, the
enabled-but-broken one failing on schedule, fourteen seconds in, like this
chapter's case study. systemd ships a dedicated read for the boot it performed
while nobody watched:

```bash no-run
systemd-analyze
echo "status: $?"
```

```output
Startup finished in 1min 4.263s (firmware) + 3.054s (loader) + 3.130s (kernel) + 1.933s (initrd) + 8.669s (userspace) = 1min 21.051s
graphical.target reached after 8.499s in userspace.
status: 0
```

The authoring machine's last boot, decomposed by stage — and the transcript reads
itself: userspace took under nine seconds, while the *firmware* spent a leisurely
minute before Linux existed at all, which is exactly the kind of fact that
redirects a "boots are slow" investigation away from every service on the machine.
The refinement, `systemd-analyze blame --no-pager`, ranks individual units by
startup cost (on this machine, the household's own report generator tops the list
at 22 seconds — unprivileged, honest, and slightly embarrassing for the
household). Both reads work from the ordinary seat.

One caution transfers from the permission lesson. `journalctl --list-boots`
enumerates the boots the journal can show *to you* — on the authoring machine it
reports the current boot's entries beginning hours after the actual boot time
`uptime -s` states, because the unprivileged view opens where the user's own
first process began logging, not where the kernel did. The boot list, like every
journal read, is a view through an identity; reconcile it against `uptime -s`
(whose source is `/proc`, identity-blind) before concluding anything about when
or how often a machine restarted.

## What a service costs, asked the same way

One more family of `show` properties completes the reading toolkit, because
"running" and "running away" look identical from `ActiveState`. systemd tracks each
service inside its own control group, and the accounting surfaces as properties —
which means resource questions get asked in the same porcelain dialect as
everything else in this chapter:

```bash no-run
systemctl show systemd-journald.service -p MemoryCurrent,TasksCurrent,CPUUsageNSec
```

```output
MemoryCurrent=72110080
CPUUsageNSec=141585922000
TasksCurrent=1
```

The journal daemon on the authoring machine: about 69 MiB resident, one task, 141
seconds of accumulated CPU over the boot. Two of chapter 3's disciplines transfer
directly. `CPUUsageNSec` is an accumulator, so a *rate* needs the counter-gap-
counter treatment — two reads a minute apart, subtracted, turn "141 seconds since
boot" into "how hard is it working now". And the properties beat their `ps`
equivalents for the same reason `MemAvailable` beat the folk formula: the cgroup
figure covers the *whole* unit — every process the service spawned, including the
short-lived ones sampling misses — because the accounting is structural, not
snapshot. The pairing to watch in the wild: `TasksCurrent` climbing across
transcripts is a leak of processes; `NRestarts` climbing is a crash loop;
`MemoryCurrent` climbing without either is the service itself remembering too
much. Three counters, three different conversations with whoever maintains the
service — and all of them one `show` away, unprivileged.

## Timers: the scheduler that answers questions

The unattended scheduling this book's mode descends from — chapter 1's cron heritage
— has, on systemd machines, a native successor with far better transcript manners.
The authoring machine makes the point bluntly: it has no `crontab` binary at all
(measured during the writing of this chapter — `command -v crontab` answers nothing),
and its scheduled work is timer units:

```bash no-run
systemctl list-timers --no-pager --no-legend --plain | head -n 4 \
  | awk '{for (i=1; i<=NF; i++) if ($i ~ /\.timer$/) {print $1, $2, $3, $i; break}}'
```

```output
Fri 2026-08-28 06:05:00 rog-life-report-morning-brief-dream.timer
Fri 2026-08-28 08:05:00 rog-life-report-morning-brief-deliver.timer
Fri 2026-08-28 13:12:39 systemd-tmpfiles-clean.timer
Mon 2026-08-31 00:19:41 fstrim.timer
```

The awk scan for the field ending in `.timer`, rather than a fixed column number, is
a scar with a story. This listing's first draft selected the unit name by position —
field eleven — and worked; run again an hour later, it printed the word `ago`,
because `list-timers` renders elapsed time in human units, and a timer's "15h ago"
had become "3 days" somewhere in the table, changing the field count of its row.
Human-layout output does not merely *risk* drifting between versions, as the
porcelain rule warns; it can drift between *invocations*, and the register's
defense, when no `--json` or porcelain mode is on offer, is to anchor on the shape
of the wanted value itself rather than on where it stood. (Newer systemd does offer
`--output=json` for exactly this table; the anchor trick is for the tools and
versions that do not.)

Real again, and quietly personal: alongside the distribution's own maintenance
timers run two belonging to the operator's household automation — a machine this
book's author shares with other unattended operators, all of them scheduled through
the same mechanism. The transcript advantages over classic cron are exactly the
themes of this chapter. A timer is a unit, so the whole read toolkit applies:
`list-timers` answers *when next and when last* — a question crontab files simply
cannot answer, since cron persists no last-run record — and the scheduled job's
output lands in the journal under the service's own name, not in a root mailbox
nobody reads. The failure of a scheduled job is a *failed unit*, visible to this
chapter's first sweep, rather than a silence. And the schedule itself lives in a
file with `OnCalendar=` syntax that `systemd-analyze calendar '...'` will dry-run
for you — chapter 6's rehearsal principle available for time itself:

```bash fragment
# Will this expression fire when I believe it will? Ask before installing it.
systemd-analyze calendar "Mon..Fri 06:05" --iterations=3
```

For the reader on a cron machine, the classic discipline still holds — `crontab -l`
to read, environment pinned inside the job, output redirected somewhere durable —
but the migration logic points one way: the register runs on evidence, and of the
two schedulers, only one keeps records.

A machine's services, read without a status screen, changed only with proof, and
scheduled by a mechanism that remembers — that is the operational half of the
system. What remains before the dangerous chapters is the substrate everything
configures itself through: files, edited by an operator with no editor. That is
chapter 5.


# Chapter 5 — Editing Without an Editor

*Draft status: author draft, gate-checked; human verification pending. Every worked
edit in this chapter runs in a scratch directory created by the listing itself; none
touches real configuration.*

## The costume and the change

Chapter 1 classed editors among the traps with no non-interactive flag, because
editing *is* the interactive act — a human, a cursor, and a buffer in conversation.
But step back from the mechanism and every editor invocation in administration is the
same underlying event: a file had one content before, and must have another content
after. The cursor was never essential; it was the human interface to a substitution.
The register performs the substitution directly, and it has a ladder of instruments
for doing so, ordered by how much of the file they touch: append a line, substitute
within lines, apply a structured diff, or replace the whole file. Each rung has its
tool, its characteristic accident, and its verification, and this chapter climbs them
in order. Two rules span all rungs and are the chapter's spine. First: **read before
you edit** — every mechanical edit is composed against an assumption about what the
file currently contains, and the assumption must be checked in the same session,
because in this register nobody is watching the file between your turns. Second:
**an edit is not done when the write succeeds; it is done when the read-back proves
the file now says what you intended** — chapter 2's ask-and-verify, applied to the
substrate everything else configures itself through.

Reading before editing has one subtlety worth its own paragraph: make sure the file
you read is the file you will edit. Configuration trees are full of symlinks —
`/etc/resolv.conf` is famously one on most modern systems — and an edit aimed at a
link can follow it or replace it depending on the tool, two very different outcomes.
The one-shot check is `readlink -f`, which resolves the entire chain to the physical
target:

```bash
cd "$(mktemp -d)"
mkdir real
printf "x=1\n" > real/app.conf
ln -s real/app.conf app.conf
readlink -f app.conf
```

```output
/tmp/tmp.kqCRsHy8rJ/real/app.conf
```

The name on the surface and the file on disk differ, and later rungs of the ladder
treat them differently: `sed -i` and the atomic-replace pattern both *replace the
link itself* with a regular file unless pointed at the resolved target — silently
severing an arrangement someone built on purpose. Resolve first; edit the target.

## Appending, and the accident of doing it twice

The lowest rung is adding lines to a file, and its tool is the shell's own `>>` — with
`printf` rather than `echo` supplying the bytes, since `printf` behaves identically
everywhere while `echo`'s treatment of flags and escapes varies by shell and mode.
The rung's characteristic accident is not the append that fails but the append that
*succeeds twice*. One-shot operators re-run commands: a turn times out with its work
half-known, a script is retried after a fix, an agent replays a step from an earlier
plan. An append inside that replay duplicates the line — and duplicated configuration
is not always harmless; a repeated `PATH` export is noise, but a repeated firewall
rule, kernel parameter, or cron entry can change behavior. The register's discipline
is to make every append *conditional on its own absence* — a guarded append,
idempotent by construction:

```bash
cd "$(mktemp -d)"
printf "PATH=/usr/bin\n" > env.conf
for attempt in 1 2; do
  grep -q "^EDITOR=" env.conf || printf "EDITOR=false\n" >> env.conf
done
cat env.conf
echo "lines: $(wc -l < env.conf)"
```

```output
PATH=/usr/bin
EDITOR=false
lines: 2
```

The loop simulates the retry: two attempts, one appended line, because the second
attempt's `grep -q` found the first's work and the `||` skipped the write. Run the
unguarded version and the file ends at three lines — a fact the listing's final
`wc -l` exists to make checkable, since an idempotence claim is exactly the kind of
claim chapter 2 says to verify rather than assert. For multi-line insertions the same
guard anchors on a marker comment (`grep -q "^# BEGIN myblock"`), which also gives a
future *removal* a handle to find the block by. Guarded appends are the smallest
instance of a theme this chapter returns to at the top of the ladder: in a register
where re-execution is routine, the well-formed edit is one whose second application
changes nothing.

The multi-line append's instrument is the here-document, and it carries a quoting trap
sharp enough to demonstrate rather than describe. The delimiter's quoting decides
whether the shell expands variables inside the block:

```bash
cd "$(mktemp -d)"
name=world
cat > expanded.txt <<EOF
hello $name
EOF
cat > literal.txt <<'EOF'
hello $name
EOF
cat expanded.txt literal.txt
```

```output
hello world
hello $name
```

Unquoted `EOF`: the block is a template, and `$name` became `world`. Quoted `'EOF'`:
the block is literal, and `$name` survived as text. Both behaviors are wanted — the
first for generating config from session facts, the second for writing files that
themselves contain shell syntax (a script, a crontab line, a systemd `ExecStart` with
specifiers). The accident is using the first mode while believing you are in the
second: every `$` in the payload silently expands — usually to empty, per chapter 2's
unset-variable economics — and the written file is a corrupted version of the
intended one that *looks* right at a glance because its shape survived. When a
here-doc's payload contains a single `$`, `` ` ``, or backslash you intend literally,
quote the delimiter; make the exceptions deliberate.

## Substitution in place, guarded

The middle rung changes existing lines, and its tool is `sed -i`. Used bare, it is
the most accident-prone instrument in this chapter, for a structural reason: `sed`
applies a pattern to *whatever matches*, and the register's operator is not watching
matches happen. A pattern that matches zero times edits nothing — silently, exit
status 0, the calm face again. A pattern that matches more lines than intended edits
all of them, equally silently. Both accidents are the same root cause — the edit's
precondition lived only in the operator's head — and both have the same cure: count
the matches first, in the same shot, and proceed only when the count is the expected
one:

```bash
cd "$(mktemp -d)"
printf "retries = 3\ntimeout = 30\n" > service.conf
n=$(grep -c "^retries = " service.conf)
[ "$n" -eq 1 ] \
  && sed -i "s/^retries = .*/retries = 5/" service.conf \
  && grep "^retries" service.conf
```

```output
retries = 5
```

Three moves in one transcript: the count established the precondition (exactly one
line will be touched), the substitution ran only inside that guarantee, and the
read-back printed the proof. Had the file held two `retries` lines, or none, the
chain would have stopped before the edit with the count as its explanation — a
failure that costs one turn and explains itself, against a silent mis-edit that
costs a debugging session weeks later. The pattern discipline inside the `sed`
expression matters equally: anchor to the line's start (`^retries = `), match the
whole value (`.*`), and prefer patterns that restate the line's full grammar over
minimal fragments that happen to work today. `sed -i` also accepts a backup suffix
(`-i.orig`), which drops a sibling copy before rewriting — cheap insurance, though
the chapter's top rung offers something better, and one caveat repeats from the
symlink section: `-i` writes a new file over the *name*, so pointed at a link it
replaces the link.

For edits beyond a line's internals — inserting a block after a marker, deleting a
stanza — resist the temptation to compose ever-cleverer `sed` programs. The register
has a better instrument one rung up.

## The diff is the native edit

An interactive human edits by manipulating a buffer; the register's structurally
best edit format is the unified diff — precisely because it is *both* the change and
its documentation, in a form `patch` can apply, `git` can ingest, and a supervising
reader can review in the transcript before anything happens. A diff states its
context lines, so it refuses to apply against a file that has drifted from the
version it was composed against — the read-before-edit rule, enforced by the file
format itself.

```bash
cd "$(mktemp -d)"
printf "alpha\nbeta\ngamma\n" > config.txt
printf "alpha\nBETA\ngamma\n" > intended.txt
diff -u config.txt intended.txt > change.diff
patch --dry-run -p0 config.txt < change.diff \
  && patch -p0 config.txt < change.diff \
  && cat config.txt
```

```output
checking file config.txt
patching file config.txt
alpha
BETA
gamma
```

The rehearsal is the point of the composition: `--dry-run` verifies the diff applies
cleanly — against the real file, changing nothing — and only its success unlocks the
real application. That two-step is chapter 6's dry-run principle arriving early, and
with diffs it is airtight in a way `sed` guards approximate: the dry run checks the
*entire* precondition (every context line), not just a count. Two status notes for
the transcript reader: `diff` itself answers like `grep` — 0 for identical, 1 for
different, 2 for trouble — so a `diff` "failing" with 1 mid-script is the expected
answer *the files differ*, not an error; and a real `patch` failure leaves `.rej`
files naming exactly the hunks that could not land, which are evidence to read, not
litter to delete. On any machine with git present, `git diff --no-index`, `git apply
--check`, and `git apply` make the same ladder with sharper diagnostics; and inside
an actual repository, the repository's own tooling — not this chapter's — is the
right instrument, with version control providing the undo channel the register
otherwise has to build by hand.

## Replace the whole file, atomically

The top rung retires editing altogether: generate the complete intended content,
validate it, and swap it into place. This is the register's preferred rung for any
file whose entire content the operator can own — because it is idempotent by
construction (generating the same content twice converges), reviewable (the new
content can be shown whole in the transcript), and, done correctly, atomic. The
correctness hinges on one syscall guarantee: `rename(2)` within a filesystem is
atomic — any process opening the path sees the old complete file or the new complete
file, never a half-written intermediate. `mv` onto an existing name, same
filesystem, is that syscall in shell clothing:

```bash
cd "$(mktemp -d)"
printf '{"port": 8080}\n' > app.json
printf '{"port": 9090}\n' > app.json.new
python3 -c 'import json; json.load(open("app.json.new"))' \
  && mv app.json.new app.json \
  && cat app.json
```

```output
{"port": 9090}
```

The sequence is validate-then-swap, and the order carries the safety: the JSON parse
ran against the *staged* file, so a generation bug — truncated output, an unclosed
brace, chapter 2's substitution silently emptying a variable — is caught while the
live file is still intact, and the broken candidate never existed at the live path
for even a millisecond. Any consumer that opened `app.json` mid-operation got a
complete document. The pattern's fine print earns respect: the staging file must be
*in the same directory* as the target (cross-filesystem `mv` degrades to
copy-then-delete, which is not atomic — and `/tmp` is routinely a different
filesystem, so staging there forfeits the guarantee); the swap replaces metadata
along with content, so files with deliberate modes or owners want `chmod`/`chown` on
the staged copy before the `mv`; and the validator should be the *consumer's* grammar
— `python3 -c json.load` for JSON, `sshd -t` or `visudo -c` (privileged, fragments
by this book's rules) for the system files that ship their own checkers, a service's
own config-test flag where one exists. A validator that could have run and did not is
the difference between an edit and a gamble.

## When the unit of edit is a directory

The atomic swap has a limit the honest version of this chapter must state: it
covers one file. A change spanning several files — a config directory, an
application release, a static site — cannot be made atomic by renaming them one at
a time; between the first rename and the last, every reader sees a mixture of
versions, and the mixture is exactly the corruption atomicity exists to prevent.
The filesystem has no multi-file transaction. What it has is one more atomic
rename, applied a level up — the symlink flip, the pattern every deployment tool
reinvents:

```bash
cd "$(mktemp -d)"
mkdir -p releases/v1 releases/v2
printf "old\n" > releases/v1/app.txt
printf "new\n" > releases/v2/app.txt
ln -s releases/v1 current
cat current/app.txt
ln -sfn releases/v2 current.new && mv -T current.new current
cat current/app.txt
readlink current
```

```output
old
new
releases/v2
```

The live name, `current`, is a symlink; versions are complete, immutable sibling
trees; and the "edit" is a rename of a freshly built link onto the live name —
one `rename(2)`, so every reader holds either wholly-v1 or wholly-v2, never a
blend. The awkward spelling of the flip is load-bearing and worth reading
closely: `ln -sfn` *onto the live name directly* would not be atomic (with a
directory target it can pass through a deleted-then-recreated state, and some
implementations descend *into* the target instead), so the new link is created
beside the live one and `mv -T` — the `-T` forbidding the same descend-into
misreading — performs the actual instantaneous cutover. Rollback is the same
gesture pointed backward, which places this pattern on the top rung of chapter
6's reversibility ladder: the entire previous version still exists, untouched,
one flip away. The pattern's tax is discipline about state: nothing writes
*into* a released tree (releases are built complete, then flipped), and anything
the application mutates at runtime lives outside the versioned trees entirely.
Paid, the tax buys the multi-file edit this chapter otherwise could not offer.

## Structured formats want structured editors

Every instrument so far treats files as lines of text, and for the classic
`key = value` formats that is the truth of them. But a growing share of what
administration edits is *structured* — JSON, YAML, TOML — and line tools are the
wrong instrument for tree-shaped data, in a way the register's operators are
specially positioned to get wrong: a `sed` substitution against a JSON file often
works, today, against this file, and that success teaches a habit that fails the
first time the target key appears twice at different depths, or gains a string
value containing the pattern, or arrives reserialized with different whitespace.
Line tools match *rendering*; the file's meaning lives in its *parse*. The correct
instrument edits the parse:

```bash
cd "$(mktemp -d)"
printf '{"port": 8080, "workers": 4, "debug": false}\n' > app.json
python3 - <<'PYEOF'
import json, pathlib
p = pathlib.Path("app.json")
cfg = json.loads(p.read_text())
cfg["workers"] = 8
tmp = p.with_suffix(".json.new")
tmp.write_text(json.dumps(cfg, indent=2) + "\n")
tmp.replace(p)
print("workers now:", json.loads(p.read_text())["workers"])
PYEOF
```

```output
workers now: 8
```

Twelve lines that assemble the whole chapter in miniature: parse (which *is* the
read-before-edit — a malformed file dies here, before harm), modify by addressing
the key in the tree rather than a pattern in the text, stage, atomically replace
(`Path.replace` is the same `rename(2)` under the `mv` of the previous section),
and re-parse as the read-back proof. For operators with `jq` installed, `jq
'.workers = 8' app.json > app.json.new` reaches the same place for JSON one-liners;
`python3` earns the listing because it is *already there* on effectively every
machine and speaks YAML and TOML through the same pattern (the standard library
reads TOML natively; YAML needs the common third-party module). One structural
honesty note: parse-and-reserialize normalizes formatting and drops comments where
the format allows them (YAML, TOML), which is a real cost in human-maintained
files — one more argument for the drop-in answer below, where your generated file
is wholly yours and the human's stays untouched.

## Mode, owner, and the moment of creation

An edit's content can be right while the file itself is wrong: readable by the
world when it holds a secret, owned by root when a service user must write it —
failures invisible in a `cat` and fatal in operation. The register's discipline is
to set metadata *at creation, in the same shot*, never as a remembered follow-up.
The shell's default is governed by `umask` (measured `0022` on the authoring
machine: new files arrive world-readable), which is the wrong default for
credentials, and the fix-it-later `chmod` leaves a window in which the secret was
exposed — a window an operator with no continuous presence cannot even measure.
The single-shot instrument is `install`, which combines copy, mode, and (with
privilege) ownership in one atomic gesture:

```bash
cd "$(mktemp -d)"
printf "secret=1\n" > cred.new
install -m 600 cred.new cred.conf
stat -c "%n mode %a" cred.conf
```

```output
cred.conf mode 600
```

The `stat` read-back is the metadata edition of the chapter's standing rule, and
belongs after any operation whose *point* was a mode or owner. Fold this into the
atomic-swap pattern (stage, `chmod`/`chown` the staged copy, then `mv`) and the
replacement arrives with content and metadata correct in the same instant —
no window, nothing to remember, nothing for the next operator to discover the
hard way.

## Do not edit what you do not own

The ladder's final lesson is about choosing not to climb it. Much of what
administration edits — package-installed configuration, another tool's managed files
— has an owner that will edit it again: the package manager on upgrade, the
provisioning system on its next run, the tool regenerating its own state. Editing
such files puts two writers on one file, and the second writer always wins
eventually. Modern configuration design offers the way out this chapter's systemd
threads have already pointed at: the drop-in directory. `<unit>.d/*.conf`,
`sudoers.d/`, `sshd_config.d/` — the pattern is general: the owned file stays owned,
and local intent lives in a *separate file* the owner promises to include. A drop-in
converts every rung of this chapter into its safest form at once: creating a file is
naturally guarded (it exists or it does not), naturally atomic (stage and rename),
naturally reviewable (the whole local intent in one small file), and removable by
deleting one path — an undo channel requiring no memory of what the file looked like
before, which for an operator with no memory is not a convenience but the whole
point. When a drop-in mechanism exists, the register's edit of choice is not an edit
at all; it is a new file with your name on it, placed where the owner agreed to
look.

## The tools that insist

A last practicality: some tools open an editor as their *interface*, and the ladder
must be threaded through them rather than around them. Each has its non-interactive
door, usually less advertised than the editing form. `crontab -e` has `crontab
<file>` — generate the full table (top rung: whole-file replacement), validate by
listing it back with `crontab -l`, and install it as data; the editor was never
required. `git commit` takes `-m`; the interactive rebase's editor can be replaced
wholesale by setting `GIT_SEQUENCE_EDITOR` to a script that rewrites the todo file
— an editor implemented as a one-shot edit, the chapter's thesis made literal.
`visudo`, whose editor session exists to guarantee syntax checking, splits into its
two halves: `visudo -c -f candidate` runs the *checker* alone against a staged
file, which slots exactly into the validate-then-swap pattern — and better still,
the file being staged belongs in `sudoers.d`, converting the whole operation into
the drop-in form below. The general method when meeting a new insistent tool: read
its manual for the non-interactive door first (`-c` flags, `--file` forms, `EDITOR`
overrides — the environment variable is honored by most, and an `EDITOR` that is
itself a script receives the temp file's path as its argument, making any
scripted transformation into a legal "editor"). The door almost always exists,
because scripts needed it decades before this register's operators did — the same
inheritance chapter 1 traced, paying out one tool at a time.

The chapter's ladder, bottom to top: guard your appends, count before you
substitute, rehearse your diffs, validate then swap, and prefer the drop-in that
makes the whole question moot. Every rung ended in a read-back, because in this
register the file's final state is the only witness to the edit that matters.
What editing has not yet faced is the operation that cannot be read back —
the one that removes, overwrites, or reaches beyond the machine. That is chapter 6,
and it is the chapter this whole book exists to make safe.


# Chapter 6 — The Blast Radius Chapter

*Draft status: author draft, gate-checked; human verification pending. Every
destructive mechanism in this chapter is demonstrated inside a scratch directory the
listing itself creates, or shown as a printed plan rather than an execution. That
caging is not stagecraft; it is the chapter's own doctrine, practiced on itself.*

## Finality, as an engineering requirement

Chapter 1 named the cost: a one-shot operator's last influence over a command ends at
dispatch. There is no watching the first deletions scroll past, no Ctrl-C at the
moment doubt arrives, no glance at the prompt's directory before pressing enter —
every safety mechanism interactive humans actually rely on turns out to live *during*
execution, in the seconds this register does not experience. What remains is
composition time, and this chapter is about spending it. The doctrine in one line:
**a destructive command must be made safe before it runs, because nothing can make it
safe while it runs.** The good news, argued through chapter 3, is that the
overwhelming majority of administration is reading, which needs none of this
chapter. The discipline concentrates on the minority of shots that write, remove, or
reach outside the machine — and because they are a minority, the register can afford
to make each one carry guards that would feel ceremonious at an interactive prompt.
That asymmetry — free reads, ceremonial writes — is the whole risk posture of a
well-run non-interactive operator.

## The dominant accident: the space in the name

Ask interactive administrators about catastrophic commands and they describe typos.
The register's dominant accident class is different and more mechanical: **an
expansion changed the command between composition and execution.** The shell rewrites
your command before running it — variables expand, the results split into words on
whitespace, the words glob against the filesystem — and each rewrite is a place where
the command you composed and the command that runs can diverge. The canonical
specimen, caged in a scratch directory:

```bash
cd "$(mktemp -d)"
f="release notes.txt"
touch "$f" notes.txt
rm $f 2>&1
printf "%s\n" *
```

```output
rm: cannot remove 'release': No such file or directory
release notes.txt
```

Read the transcript as the four-question routine demands, because it is a small
horror story. The unquoted `$f` split into two words, `release` and `notes.txt`. The
first named nothing — hence the error line. The second named an *innocent bystander*,
which `rm` removed without comment. The final line is the listing's own survivor
roll: the target, `release notes.txt`, stands untouched — and `notes.txt`, created
two commands earlier, is not in the list, because it no longer exists. One unquoted
expansion produced a command that failed at its purpose *and* destroyed something
unrelated, with an error message pointing at neither fact. The cure costs two characters: `rm "$f"` names one file, spaces included,
always. The rule admits no judgment calls: **every expansion is quoted —
`"$var"`, `"$(cmd)"`, `"$@"` — unless splitting is the explicit, commented intent.**
Not because every variable will contain a space, but because the operator composing
the shot cannot see the value at composition time, and this register has no other
moment to check. A mechanical rule for a mechanical accident; `shellcheck` enforces
it (its finding SC2086 is precisely this), and running ShellCheck over any script
before dispatch is the register's equivalent of proofreading — a static gate for the
class of accident no runtime gate can catch in time.

The expansion accident has a second, worse form: the variable that expands to
*nothing*. Chapter 2 previewed it; here is its anatomy, demonstrated as a printed
plan rather than an execution, which is how a plan this dangerous should first exist:

```bash no-run
prefix=""
echo "would run: rm -rf ${prefix}/cache"
```

```output
would run: rm -rf /cache
```

An empty `prefix` — unset, typo'd, or emptied by a failed substitution upstream —
and the composed path collapses to an absolute path at the filesystem root. Every
veteran of this register knows an incident of this shape; the best-documented
public specimen shipped in Steam's Linux client, whose startup script ran
`rm -rf "$STEAMROOT/"*` and, on machines where the variable came up empty,
deleted every file the user could reach — bug report in the references, preserved
complete with its disbelieving comment thread. The defenses stack. `set -u` aborts on the
unset case. The shell's own `${prefix:?prefix is unset}` expansion makes the check
inline and fatal without strict mode. Better than both, because it also catches the
*set-but-wrong* case: test the composed path's existence and shape before acting on
it — a directory that should contain cache files can be required to exist and to
match a pattern you assert (`[ -d "$prefix/cache" ] && [[ "$prefix" == /srv/* ]]`)
before any destructive verb sees it. That is proof-of-target, and a later section
makes it doctrine.

## When filenames attack

The third rewrite, globbing, has two failure shapes of its own. The first: a glob
that matches nothing *passes itself through as a literal word* by default —
`*.conf` in an empty directory becomes the string `*.conf`, handed to your command
as if it were a filename, and whether that is harmless depends entirely on the
command. The second is nastier — filesystem content becomes command syntax:

```bash
cd "$(mktemp -d)"
touch -- -l data.log
echo "ls * sees:"
ls * 2>&1 | head -n 1
echo "ls -- * sees:"
ls -- * 2>&1
```

```output
ls * sees:
-rw-r--r-- 1 roger roger 0 Aug 27 22:07 data.log
ls -- * sees:
-l
data.log
```

A file named `-l` exists in the directory. The glob expands it along with everything
else, `ls` receives it *as an option*, and the first invocation silently becomes
`ls -l data.log` — a long listing of the other file, with the dash-file itself
vanished from the report. Any tool accepting options is vulnerable, and with `rm` or
`chmod` the smuggled option can be `-r` or `--no-preserve-root`. Two idioms close
the hole completely, and the listing shows the first: `--`, the near-universal
end-of-options marker, after which everything is an operand. The second is prefixing
relative globs with `./` (`rm ./*` — a name cannot begin with a dash if it begins
with `./`). One of the two belongs in every command whose operands come from a glob
or a variable; which one is taste, their absence is exposure.

Silent semantic reversal has one more famous residence: tools whose *argument order*
is meaning, where a plausible reordering runs and does something categorically
different. The specimen is `find`, whose command line is not options-then-operands
but a little program evaluated left to right:

```bash
cd "$(mktemp -d)"
touch a.tmp b.txt
echo "misordered:"
find . -type f -print -name "*.tmp"
echo "correct:"
find . -type f -name "*.tmp" -print
```

```output
misordered:
./b.txt
./a.tmp
correct:
./a.tmp
```

With `-print` *before* the name filter, the action fires for every file and the
filter, evaluated after, filters nothing. Substitute `-delete` for `-print` — a
substitution operators make exactly once — and the misordering deletes every file
under the tree instead of the `.tmp` files; same shape, and `-delete` even disables
some of `find`'s own safety refusals. The register's habit: any `find` that will
carry a destructive action is composed first with `-print` in the action's position,
dispatched, and its output *read as the plan* — then, and only then, re-dispatched
with the action swapped in. Which generalizes into the chapter's central move.

## Rehearsal: the dry run

Interactive operators sometimes rehearse; the register *must*, because rehearsal is
the only place its mistakes can be caught before they are permanent. The instruments
are the dry-run modes the serious tools all carry, and the doctrine is to treat them
not as reassurance but as the source of the plan you then execute. The worked
specimen is `rsync`, whose `--delete` — essential for true synchronization, feared
for good reasons — is exactly the kind of verb that deserves a rehearsal:

```bash
cd "$(mktemp -d)"
mkdir -p src dst
printf "1\n" > src/a.txt
printf "2\n" > dst/stale.txt
rsync -rn -v --delete src/ dst/ 2>&1 | head -n 6
echo "dst after the dry run:"
ls dst
```

```output
sending incremental file list
deleting stale.txt
a.txt

sent 66 bytes  received 32 bytes  196.00 bytes/sec
total size is 2  speedup is 0.02 (DRY RUN)
stale.txt
```

The `-n` run names its victims — `deleting stale.txt` — and the final `ls` proves the
victim still breathes: the rehearsal was pure prophecy, zero action. The transcript
now contains the plan, reviewable by the operator or its supervisor, and the
execution step is the identical command minus one letter. Note also what the
rehearsal quietly validated: rsync's infamous trailing-slash semantics (`src/` means
*contents of* src; `src` means *the directory itself* — one character, two different
resulting trees). The dry run renders that decision visible before it is real, which
is the general principle: **a dry run converts semantics you believe into semantics
you have read.** The register's rehearsal shelf is well stocked — `patch --dry-run`
(chapter 5), `apt-get -s` and its cousins for package operations, `systemd-analyze`
verbs for units and calendars (chapter 4), `--check` flags across configuration
tools — and where a tool has none, the `find -print`-then-swap pattern builds one.
The habit has a cost — one extra turn per destructive operation — and chapter 1's
economics prices it correctly: the turn is the cheapest thing this register has, and
it buys down the one cost that cannot be refunded.

## Proof of target, narrowness, and the verb that shows its work

Rehearsal checks the plan; proof-of-target checks the world. Before a destructive
verb runs, the transcript should already contain evidence that its operand is the
thing intended — existence, type, and a property no wrong target would share:

```bash
cd "$(mktemp -d)"
mkdir -p build
printf "artifact\n" > build/out.bin
[ -d build ] && [ -e build/out.bin ] \
  && rm -v build/out.bin \
  && [ ! -e build/out.bin ] && echo "removal verified"
```

```output
removed 'build/out.bin'
removal verified
```

Four small assertions braid chapter 2's ask-and-verify into the destructive case:
the target's existence proven before, the verb's own verbose narration (`-v` — the
register always asks destructive tools to narrate) during, and the absence proven
after. Alongside proof stands *narrowness*: the destructive verb receives the most
specific operand the task permits. Full explicit paths over `cd`-then-relative
(the `cd` that fails while the `rm` proceeds is a classic compound accident — and
the reason chapter 2 recommended strict mode's abort-on-error for scripts);
one named target over a glob where one target is meant; a glob over a recursive
flag where a glob suffices; `-maxdepth` on any `find` that does not intend the
abyss. Blast radius is measured at composition time by a simple question: *if every
name in this command resolved to the worst plausible value, what is the largest
thing that could disappear?* Narrowness is the practice of making that answer
small enough to survive.

## The reversibility ladder

The final recalibration is choosing verbs by their undo channel. Interactive humans
grade operations by effort; the register grades them by *recoverability*, and the
grades are a ladder worth internalizing. At the top, operations that carry their own
undo: `mv` within a filesystem (rename back), the drop-in file (delete it), the
atomic swap staged beside a kept original (swap back). In the middle, operations
recoverable with preparation: overwrites preceded by a copy (`cp -a target
target.bak.$(date -u +%Y%m%dT%H%M%SZ)` — timestamped, so repeated preparations do
not overwrite each other's insurance), deletions rehearsed and logged so that at
minimum *what was lost* is known. At the bottom, the truly one-way verbs: `rm`,
`>` truncation, `rsync --delete` unrehearsed, `dd` onto a device, database drops —
gone is gone, on a timescale that matters to the incident.

The ladder's use is substitution pressure: before dispatching a bottom-rung verb,
ask which higher rung reaches the same goal. The strongest everyday substitution is
quarantine — `mv` the doomed thing into a dated graveyard directory instead of
removing it. The operation is total (the directory is clean, the goal achieved),
reversible for as long as the graveyard is retained, and *cheap* — a rename costs
nothing regardless of size. Deletion becomes a scheduled, boring event (a timer
purging graveyards older than some retention), decoupled from the operational moment
where mistakes live. An operator that quarantines by default and deletes on a
schedule has converted its worst accident class into a recoverable inconvenience —
which is the entire ambition of this chapter, applied structurally rather than shot
by shot.

## The verbs that leave the machine

The reversibility ladder has a floor below its bottom rung, and it is not on the
filesystem. Commands that *communicate* — send the email, post to the API, push
the release, publish the message to the queue — are irreversible in a way even
`rm` is not: deletion destroys state you held, while communication creates state
in systems you do not hold. There is no quarantine directory for a sent
notification; the copy that matters now lives in someone else's inbox, cache, or
audit log, beyond every undo channel this chapter built. The register treats such
verbs as a class of their own, with three rules. They are never composed into
retry loops or strict-mode chains casually — a "retry on failure" wrapped around a
send can deliver twice, and chapter 6's read-before-retry rule applies with the
reading done on the *far* system where possible (did the message arrive? does the
API's idempotency key say this request was already seen?). Idempotency keys, where
the far side offers them, are the outward world's version of the guarded append,
and using them is not optional politeness but the only mechanism that makes an
outward retry safe at all. And the rehearsal principle inverts into staging:
where a dry run cannot exist (few mail systems offer one), the rehearsal is a
*real* send against a target you own — the test inbox, the sandbox API, the
staging channel — with the production dispatch composed as the same command with
one variable changed, and that variable proven, proof-of-target style, before the
shot goes out. An operator that would rehearse a local `rsync --delete` three
times and then improvise a production API call has ranked its risks by
familiarity rather than by blast radius; this section exists to reverse that
ranking.

## Working where others work

The blast radius of a command includes operators it collides with. A one-shot
operator is rarely alone on a machine: humans hold sessions, timers fire (chapter
4's real machine runs several), other agents may be mid-task in the same trees.
Two consequences follow, one about your writes, one about everyone else's.

Your writes need private ground. Predictable scratch paths — `/tmp/work`,
`/tmp/out.txt` — are collisions waiting (two operators, one path, interleaved
writes) and, on shared machines, a classic attack surface: a hostile process that
pre-creates the predictable name as a symlink redirects your write onto any file
your identity can damage. The system's answer is `mktemp`, which this book's
listings have used since chapter 1 and which earns its formal introduction here:

```bash
w=$(mktemp -d)
echo "workspace: $w"
[ -d "$w" ] && echo "exists, mode $(stat -c %a "$w")"
```

```output
workspace: /tmp/tmp.NwLRJZiNbQ
exists, mode 700
```

Unpredictable name, created atomically, mode `700` — private by construction. The
habit: every scratch need goes through `mktemp`; the only names you write outside
scratch are the deliberate, guarded targets of the task itself.

Against everyone else's writes, the instrument is mutual exclusion, and the shell
has a real one — `flock(1)`, an advisory lock on a file descriptor, atomic in the
kernel, released automatically when the holding process exits (an important property
for an operator whose process *will* exit, cleanly or not — no crash leaves a stale
lock held):

```bash
cd "$(mktemp -d)"
exec 9> job.lock
if flock -n 9; then echo "lock acquired"; else echo "another operator holds the lock"; fi
( exec 8> job.lock
  flock -n 8 && echo "second acquisition: succeeded" || echo "second acquisition: refused" )
```

```output
lock acquired
second acquisition: refused
```

The subshell plays the second operator, and the kernel refuses it while the first
descriptor lives. `-n` makes the attempt non-blocking — the register's correct
default, since a shot that queues invisibly behind a lock is a chapter 1 hang with
extra steps; better to learn *refused* in one turn and decide, than to wait
silently. Any procedure that must not run twice concurrently — a deploy, a
migration, a graveyard purge — opens with this pattern, and the lock file's name
becomes part of the procedure's documented interface, which is precisely how the
system cron daemons and package managers already guard themselves (the familiar
"could not get lock" from a package manager is this same mechanism, experienced
from the outside).

## The retry, and what must be read before it

Chapter 5 built idempotence into edits; this chapter's version of the question is
harsher: a destructive or compound shot *failed midway, or timed out with its fate
unknown* — what now? The interactive reflex, run-it-again, is exactly wrong as a
reflex, because a compound operation that died mid-flight has left the world in a
state that neither the before nor the after picture describes, and the retry was
composed against the before picture. The register's rule: **after a failed write,
the next shot is a read.** Reconstruct which stage completed from evidence — which
files exist, which staged artifacts are present, what the service's timestamps say
— then resume from the stage the evidence proves, not from the top:

```bash
cd "$(mktemp -d)"
mkdir -p deploy
printf "v2\n" > deploy/app.txt.new
ls deploy
echo "staged file present: retry resumes at validate-and-swap, not at generation"
```

```output
app.txt.new
staged file present: retry resumes at validate-and-swap, not at generation
```

A toy, but the shape is the real discipline: chapter 5's atomic-swap pipeline,
interrupted, is *legible* — the presence of the `.new` file tells the returning
operator exactly where death occurred, and the resume point follows from the
evidence rather than from hope. That legibility was purchased at composition time,
by building the procedure from stages whose completion leaves distinct marks. The
general design rule for anything long: make each stage's completion *observable*
(a staged file, a moved marker, a logged line), so that the mid-flight state reads
as a position rather than as wreckage — chapter 8 formalizes the same idea as the
change ledger. And when a timed-out shot's fate is genuinely unknowable — the
classic being a remote command whose connection died after dispatch — the read
comes *first* and decides whether there is anything to retry at all: the operation
may have completed beautifully, in your absence, like everything else in this
register does.

## Privilege: the discipline of remaining small

Everything above bounds what a command *does*; privilege bounds what it *can* do,
and the register's rule is inherited from decades of automation practice with the
stakes newly raised: **operate at the lowest privilege that answers the question,
and escalate per-command, not per-session.** Chapters 3 and 4 were written
deliberately from an unprivileged seat — processes read, services diagnosed, a
failed unit triaged to its exit status, all without root; the one boundary hit (the
journal's group wall) was itself diagnosable from below. That is representative:
reading rarely needs privilege, and the shots that do escalate should each carry
`sudo` visibly — the transcript then shows exactly which actions ran elevated,
an audit trail chapter 8 will want, against a `sudo -i` session in which every
subsequent accident, expansion included, is a root accident. `sudo -l` reads the
current identity's actual grants — worth one shot on any new machine, since it is
the authoritative answer to *what can this seat do*, and (chapter 4's lesson
recurring) `sudo` strips most of the environment, so a command that behaves
differently under it has usually lost a variable, not gained a bug. For the
supervising reader designing the seat itself: the strongest blast-radius decision
is made before any command runs, in what the operator's account can reach at all —
filesystem permissions, group memberships, a sudoers file listing specific commands
rather than `ALL`. The guards in this chapter are how a careful operator behaves;
the account is how careful the machine remains when, someday, a shot is composed
without them.

Quoted expansions, guarded emptiness, disarmed filenames, rehearsed deletions,
proven targets, reversible verbs, and a small seat: none of it is exotic, and all
of it is composition-time work, because composition time is all this register has.
What safety cannot be compressed into is a checklist recited once — it is a set of
defaults, and defaults are cheap. The next chapter takes the same doctrine onto the
one substrate where even reads have side effects and nothing stays still: the
network.


# Chapter 7 — The Network, One Command at a Time

*Draft status: author draft, gate-checked; human verification pending. The runnable
listings in this chapter touch only the loopback interface and the local machine's
own state, per the book's listing policy; commands that reach real networks are
labeled fragments.*

## Nothing here stands still

Every substrate this book has read so far — processes, services, files — belonged to
the machine under your hands. The network is different in three ways that bend the
register's technique. It is *shared*: the state you observe includes other parties'
behavior, and your observations are events on their side too — a connection attempt
is a log line somewhere, a repeated probe is a pattern someone's monitoring may act
on, and so even "reads" carry a faint write. It is *layered*: a working connection
rides link, address, route, name resolution, socket, and service, stacked such that
any layer's failure wears the costume of the layers above it — the browser era
taught everyone "DNS error" faces for what were route problems underneath. And it is
*in motion*: caches expire, addresses lease and re-lease, peers restart, so two
observations a minute apart legitimately differ — chapter 3's snapshot caveats,
raised to a power. The register's response to all three is the same discipline in
sharper form: bounded shots, one layer at a time, each shot's answer read before the
next is chosen, and every measurement stamped with when and from where it was taken,
because on a moving substrate an unstamped fact is already a stale one.

The chapter's frame for diagnosis is the oldest one in network operations, adapted
to one-shot economics: **walk the layers, cheapest first, and let each answer
eliminate half the remaining suspects.** A human at a terminal walks it by intuition
and fast iteration. A transcript operator walks it deliberately — the layer sweep is
five or six cheap reads, and dispatching them as one composed batch (their combined
output still small) frequently converts a would-be conversation into a single turn
whose transcript contains the whole differential diagnosis.

## The sweep, and the seam in the path

The canonical layer reads live in the `iproute2` suite: `ip link` for whether the
interface is up, `ip -j addr` for what addresses the machine actually holds, `ip
route get <dest>` for which way packets to a destination would leave, `ss` for what
sockets exist. They are presented here as fragments, and the reason is a seam this
book's own construction exposed. On the authoring machine, `ip` resolves at
`/usr/bin/ip`; on plenty of other systems — including the publisher's gate sandbox,
whose `PATH` is the minimal `/usr/bin:/bin` — the `iproute2` tools sit in `sbin`
directories that minimal paths do not include. Chapter 3 stated the general rule
(*which tools your shot can reach is part of your machine's state*); the network
tools are where it bites hardest in practice, because `sbin` placement reflects an
old assumption that network inspection is an administrator's act. When a network
tool answers 127, the fix is a fuller path or an absolute one — not a different
diagnosis.

```bash fragment
# The one-turn layer sweep (adjust names to the machine; ip may need /usr/sbin).
ip -brief link
ip -brief addr
ip route get 1.1.1.1
resolvectl status | head -n 12
ss -tlnp
```

`-brief` on the first two is the register's friend — one line per interface, fixed
columns, built for exactly this reading. The `route get` verb deserves special
notice: rather than dumping the route table for you to simulate in your head, it
asks the kernel to *run its actual decision* for one destination and report the
result — source address, egress interface, gateway. It is the difference between
reading the law and asking the judge, and it retires a whole class of "but the
table looks right" confusion.

## Sockets from the source

For the socket layer, the register has an option the fragments above do not cover:
go where `ss` itself goes. The kernel publishes socket tables under `/proc/net`,
and a short reader answers the most common question — *what is listening?* —
with no tool dependency at all:

```bash
python3 - <<'PYEOF'
listeners = []
for path in ("/proc/net/tcp", "/proc/net/tcp6"):
    try:
        rows = open(path).read().splitlines()[1:]
    except FileNotFoundError:
        continue
    for row in rows:
        f = row.split()
        if f[3] == "0A":                      # state 0A = LISTEN
            addr, port = f[1].rsplit(":", 1)
            listeners.append((int(port, 16), "v6" if path.endswith("6") else "v4"))
for port, fam in sorted(set(listeners))[:8]:
    print(f"listening {fam} port {port}")
PYEOF
```

```output
listening v4 port 22
listening v6 port 22
listening v4 port 53
listening v6 port 3000
listening v4 port 3001
listening v4 port 4141
listening v4 port 4142
listening v4 port 4180
```

The authoring machine's first eight listeners, decoded from the kernel's own table:
an ssh daemon on 22, a local DNS resolver on 53, and a family of high ports
belonging to the household's services. The format is documented (hex address:port
pairs, hex state codes, `0A` for LISTEN), and the exercise is not a recommendation
to abandon `ss` — which decodes more, faster, with process attribution — but a
demonstration that the socket table is *readable state*, reachable even from seats
too minimal to carry the tool. When `ss` is present, its register-ready spelling is
`ss -tlnp`: TCP listeners, numeric (no reverse-DNS stalls — the `n` matters in
one-shot mode, where a slow resolver turns a socket listing into a hang), with
owning processes where privilege allows. The follow-up that completes most
socket-layer diagnoses is the bind-address column: a service listening on
`127.0.0.1:8080` is alive and *correctly unreachable* from outside — the classic
"it works on the box but not from anywhere else" has this one-line explanation more
often than any firewall does.

## Names: two different truths

Name resolution earns its own section because there are two of it, and conflating
them wastes diagnostic turns. Applications do not, as folklore has it, "ask DNS";
they ask the system's Name Service Switch, which consults `/etc/hosts`, local
resolvers, caches, and only *then* the DNS protocol, per `/etc/nsswitch.conf`. The
one-shot read of that whole stack — the answer applications actually receive — is
`getent`:

```bash
getent hosts localhost
```

```output
::1             localhost
```

Measured, and already a lesson: on the authoring machine, `localhost` resolves
first to the IPv6 loopback — a service bound only to `127.0.0.1` and probed "at
localhost" can fail this machine's probe while being perfectly alive, which is a
resolution fact, not a service fact. The DNS-protocol truth, by contrast, comes
from `dig` (or `resolvectl query`), which speaks to nameservers directly and
bypasses `/etc/hosts` and NSS entirely:

```bash fragment
dig +short example.com          # the protocol's answer, resolver's cache included
dig +short @1.1.1.1 example.com # a specific server's answer, cache and all
resolvectl status               # which resolvers this machine would actually use
```

The diagnostic use of having both: when `getent` and `dig` disagree, the *gap
between them* is the finding — an `/etc/hosts` override someone forgot, a stale
local cache, an NSS module misbehaving — and no amount of further DNS querying
would have found it, because the DNS was never the layer that lied. Chapter 2's
determinism rule also lands here with special force: resolution answers are
cache-and-vantage-dependent, so a transcript that records a name lookup should
record *which* truth it asked and when, or the record will win arguments it should
lose.

## Reading a refusal

Failed connections are not one phenomenon, and the register's four-question routine
pays off richly here, because the three textures of failure implicate different
layers and a probe's error already contains the triage. **Connection refused**
arrives fast and means the packet *completed its journey*: a host answered, and
answered that nothing listens on that port. Route, addressing, and the host itself
are thereby acquitted in the same instant — the suspect list collapses to the
service (dead, or bound elsewhere, per the socket section) and port number. A
refusal is the most informative failure there is, and treating it as generic
"can't connect" discards its gift. **Timeout** is the opposite texture: silence.
Packets left and nothing returned — consistent with a dead host, a black-holing
route, or (most common in practice) a firewall that *drops* rather than rejects,
precisely because silence tells probers the least. A timeout therefore acquits
nobody, and its diagnostic value is only comparative: reachable on port 22 but
timing out on 443 outlines a filter's shape; timing out on everything outlines a
route or host problem. **Connection reset** is the strange third texture — the
conversation began and was slammed shut — and points at the application layer or
at middleboxes terminating what they dislike: a service crashing on this
particular input, a proxy rejecting a protocol, an idle connection reaped. The
one-shot operator reads which texture the probe reported *before* choosing the
next layer to inspect; three textures, three different next shots, and the error
line already chose between them.

## The remote shot

Most real administration in this register eventually crosses to another machine,
and the carrier is `ssh host 'command'` — the venerable one-shot form that chapter
1 counted among the mode's ancestors. Operating it well requires knowing three of
its behaviors precisely. First, **its exit status is the remote command's**,
faithfully carried home — the whole chapter 2 discipline works across the wire
unchanged — with one reserved value: 255 is ssh's *own* failure (could not
connect, could not authenticate), so 255 means "the question never arrived",
the remote cousin of 127's "the question never reached a tool", and statuses
below it mean "the question arrived, and this was its answer". Second, **it must
be disarmed for transcript mode**: `-o BatchMode=yes` forbids every interactive
fallback (password prompts, passphrase dialogs — chapter 1's prompt trap in its
most common network costume) so that a shot which would have hung fails instantly
and legibly instead; `-o ConnectTimeout=5` bounds the attempt. Third, **the
command travels as text through two shells**, and every expansion rule from
chapter 6 applies *twice*: locally when the shot is composed, remotely when the
far shell parses what arrived. The single-quoted form `ssh host 'echo $HOME'`
expands remotely (the intended reading, usually); the double-quoted form expands
*locally* and ships the result — both are legitimate tools, and the accident is
not knowing which one was dispatched. For anything beyond a short command, skip
the quoting puzzle entirely: compose the remote work as a here-doc streamed into
the far shell, where it travels as data —

```bash fragment
ssh -o BatchMode=yes -o ConnectTimeout=5 host bash -s <<'EOF'
set -u
df -P -k | awk 'NR > 1 && $5 + 0 >= 80 {print $6, $5}'
EOF
```

— the quoted delimiter (chapter 5's rule) keeping every `$` remote, and the remote
`bash -s` reading the program from the wire. The pattern composes with everything
this book has built: the shot inside the here-doc is written to the same standards
as any local shot, and its transcript, statuses included, comes home over the same
channel. For moving files rather than commands, `rsync` over ssh inherits chapter
6's rehearsal discipline (`-n` first, always, doubly so with `--delete` pointed at
a machine you cannot see), and for repeated remote shots against one host, ssh's
connection multiplexing (`ControlMaster`/`ControlPersist` in the client config)
collapses the per-shot handshake cost — the round-trip economics of chapter 1,
purchasable with configuration.

## Downloading with proof

One network operation deserves its own doctrine because it ends in execution:
fetching software. The register's rule is the same one chapter 5 applied to
config — *validate, then swap* — with the validator being cryptographic. Download
to a file, verify the file against a published digest, and only then let it near
an interpreter:

```bash fragment
curl -sS --fail --max-time 60 -o installer.sh "https://example.com/installer.sh"
echo "<published-sha256>  installer.sh" | sha256sum -c -
# only on "installer.sh: OK" does the file graduate to execution
```

The popular one-liner this replaces — piping a fetched URL directly into a shell —
is tolerated by interactive humans partly on the theory that they could watch it
run. This register has no such theory available: nothing streams past your eyes,
so the pipe form is all of the risk with none of the (already thin) mitigation,
and the download-verify-inspect sequence costs exactly one extra turn. `sha256sum
-c` speaks chapter 2's dialect — per-file `OK` lines and a nonzero exit on any
mismatch — and where the publisher signs releases, the same station is where the
signature check runs. The habit's quiet second benefit is the artifact itself: the
downloaded file, retained, is evidence — of what was fetched, when, and with what
digest — which is more than any pipe ever leaves behind.

## curl as a measuring instrument

At the top of the stack, the register's universal probe is `curl`, and the
craft is to promote it from "fetch tool" to *instrument* — a probe with a pass/fail
contract and calibrated dials. The demonstration runs against a real HTTP server
the listing itself starts on the loopback, so the whole exchange is local,
deterministic, and disposable:

```bash
w=$(mktemp -d); cd "$w"
printf "pong\n" > ping.txt
python3 -c '
import http.server, threading, pathlib
srv = http.server.HTTPServer(("127.0.0.1", 0), http.server.SimpleHTTPRequestHandler)
pathlib.Path("port").write_text(str(srv.server_address[1]))
threading.Thread(target=srv.serve_forever, daemon=True).start()
import time; time.sleep(4)
' &
sleep 1; port=$(cat port)
curl -sS --fail --max-time 5 \
  -w "http %{http_code}, %{time_total}s total, %{size_download} bytes\n" \
  -o fetched.txt "http://127.0.0.1:$port/ping.txt"
cat fetched.txt
wait
```

```output
http 200, 0.004980s total, 5 bytes
pong
127.0.0.1 - - [27/Aug/2026 22:12:50] "GET /ping.txt HTTP/1.1" 200 -
```

(The last line is the toy server's own access log, arriving on stderr — left in
the transcript deliberately as a two-streams reminder: the probe's *answer* is the
`-w` line and the fetched body, and a parser should have been aimed only at those.)
Each flag on that `curl` is a policy decision worth making consciously. `--fail`
converts HTTP-level failure into exit-status failure — without it, a 500 page
downloads "successfully" and chapter 2's number-first reading is defeated at the
protocol boundary. `--max-time` is the chapter 1 hang-proofing, non-negotiable on
any probe whose far side you do not control. `-sS` silences the progress bar (a
repainter!) while preserving real errors. And `-w` turns the exchange into
*measurements* — beyond the basics shown, curl exposes the full timing anatomy
(`time_namelookup`, `time_connect`, `time_appconnect`, `time_starttransfer`), which
decomposes a slow request into *which layer was slow* in a single shot: resolution
time implicates the previous section, connect time the path, start-transfer time
the far service. One probe, dials read, differential diagnosis included — against
real services, the same spelling with `-o /dev/null` measures without keeping.

Two instrument-handling notes complete the toolkit. A probe that writes nothing and
checks nothing but reachability should say so honestly — `curl -sS --fail -o
/dev/null` plus `-w` is a *health check*; the habit of HEAD requests (`-I`) probes
cheaper but measures a different thing, since servers legitimately treat HEAD
differently. And bound your retries: `--retry 3 --retry-max-time 30` gives
transient-failure tolerance with a ceiling, which in one-shot economics beats both
the brittle single attempt and the unbounded loop an interactive human would have
interrupted by feel.

## The invisible middleman

One network fact lives in the environment rather than on the wire, and it belongs
in this chapter because it falsifies probes: the proxy. The convention — honored
by `curl`, package managers, language runtimes, and most HTTP clients —
is a set of environment variables (`http_proxy`, `https_proxy`, `no_proxy`,
plus uppercase variants some tools prefer) naming an intermediary through which
requests should travel. A machine configured this way makes every environment-
respecting probe measure *the path through the proxy*, while tools that ignore
the convention (lower-level probes, raw socket checks) measure the direct path —
and the two can disagree completely: curl succeeding while the direct route is
firewalled, or curl failing against a dead proxy while the network itself is
fine. The diagnostic consequences compound in exactly the environments this book's
operators inhabit. Chapter 4 showed `sudo` and stripped sessions losing
variables; proxies are the network edition — the interactive human's shell has
the proxy set, the agent harness or cron job does not, and the "network is down
for my script but fine for me" ticket writes itself. The register's discipline:
the proxy variables are part of any connectivity finding — one `env | grep -i
proxy` (bounded, labeled) belongs in the layer sweep on any machine you did not
configure yourself, `no_proxy`'s exemption list read as carefully as the proxies
themselves (a loopback probe that unexpectedly transits a proxy because
`no_proxy` omitted `localhost` is a classic self-inflicted mystery), and a probe
report states which path it measured. From this seat, through this proxy — or
explicitly not through one: vantage, again, with one more clause in it.

## Waiting, without watching

Network work constantly requires waiting — for a restarted service to accept
connections, a DNS change to propagate, a peer to finish coming up — and waiting
is the thing the register cannot natively do: chapter 1 retired `watch` along with
the rest of the repainters. The honest substitute is the *bounded poll*: a loop
with a check, an interval, a maximum, and — the part naive versions omit — a
distinct final answer for exhaustion:

```bash
cd "$(mktemp -d)"
( sleep 2; printf "ready\n" > up.txt ) &
for i in 1 2 3 4 5 6; do
  [ -e up.txt ] && { echo "up after $i checks"; break; }
  sleep 1
done
[ -e up.txt ] || echo "gave up after 6 checks"
wait
```

```output
up after 3 checks
```

The background subshell plays a service that takes two seconds to come up; the
loop finds it on the third check and says so. Substitute the real readiness probe
for the file test — `curl --fail` against a health endpoint, `ss` finding the
listener, `getent` returning the new record — and this is the register's entire
waiting toolkit. The composition rules are the same three costs as ever. The
*budget* (six checks, one second apart) is chosen from knowledge of the thing
awaited, and stated in the transcript — an unbounded poll is a chapter 1 hang
built by hand. The *success line names the elapsed cost* (`after 3 checks`),
which turns the wait itself into a measurement: a service that used to arrive on
check one and now arrives on check five has said something worth recording. And
the *exhaustion line is affirmative* — "gave up after 6 checks" is a finding, the
good-shots-say-none rule from chapter 2, because the poll that times out silently
forces the next operator to distinguish "never came up" from "never checked".
When the wait stretches beyond a turn's patience, the pattern moves up a level:
dispatch the poll as a background job or a transient unit whose *record* you read
next turn — the machine does the waiting, and the transcript does the watching.

## What one shot cannot see

The chapter closes, as chapter 3 did, on honest limits — sharper here, because the
network's failure modes are so often *intermittent*. A one-shot probe samples an
instant; packet loss of one percent, a flapping route, a peer that stalls under
concurrent load — none of these reliably appear in any single sample, and a passing
probe does not acquit them. The register's recourses parallel chapter 3's. Sample
deliberately: `ping -c 20` (bounded count — never bare `ping`, the canonical
never-ending repainter) reports loss and latency spread over twenty samples in one
shot, and its summary line is built for transcripts. Use the accumulators:
`/proc/net/dev` deltas (chapter 3's technique, unchanged) integrate every packet
between two reads, including the ones your probes missed; the interface error and
drop counters in the same file convert "feels flaky" into a number that either
grows or does not. And when the question is genuinely about traffic *content*,
bound the capture the way you bound everything: `tcpdump -c 100` (privileged, a
fragment) takes a hundred packets and stops — a capture with no `-c` on a busy
interface is the volume cost of chapter 1 arriving all at once, and has filled
more than one disk in the folklore.

The deepest limit is vantage. Every read in this chapter observes from one host on
the graph; "the network is down" and "this machine cannot reach it" are
indistinguishable from a single vantage, and distinguishing them requires a second
one — another machine, an external probe service, the peer's own logs. A
transcript-mode operator states its vantage as part of its findings (*from this
host, at this time, the service did not answer within five seconds*) and resists
the sweeping conclusion its evidence cannot carry — the discipline chapter 1
promised, of claims sized exactly to what the shot could see. What that discipline
looks like when a whole piece of work is being handed back — evidence, ledger, and
all — is the business of the final chapter.


# Chapter 8 — Handing Back the Machine

*Draft status: author draft, gate-checked; human verification pending. This chapter
closes the book by practicing what it teaches: its final section is the discipline
compressed to one page, and the book's own submission record is its worked example.*

## What "done" means when nobody watched

Interactive administration inherits its definition of done from presence. The human
was there; they saw the service come back, watched the deploy finish, remember what
they touched. When they say "done", the claim rests on a continuous experience of the
work, and when someone asks next week what changed, the answer comes from memory —
imperfect, but present. The one-shot operator has none of that to rest on. Its work
happened as a series of dispatches and transcripts, its "experience" of the machine
is whatever those transcripts contain, and by the next session even that may be gone
— context windows close, sessions end, the operator that returns tomorrow is, for
every practical purpose, a stranger holding the same job title. Under those
conditions, "done" cannot mean *I finished*; there is no continuous I to have
finished. It has to mean something checkable by a stranger: **the goal state is
verified in the record, the changes made are enumerated in the record, and the
record is where the next operator will find it.** Verified, enumerated, findable —
this chapter is those three words, expanded into practice.

The definition sounds bureaucratic until you notice who the stranger usually is.
Sometimes it is the supervising human, deciding whether to trust the work. Sometimes
it is a different agent, picking up a task mid-stream. Most often it is you — the
same model, the same job, the next session — arriving with no memory of today and
needing to know what today did. Every discipline in this chapter is therefore
self-serving in the most direct way: the operator that documents its work is the
primary beneficiary of the documentation, on a delay of one session. Interactive
humans write documentation for others and skip it when busy, because their memory
covers them. This register writes for itself, because nothing covers it.

## The evidence block

Chapter 2 planted the seed — a change without a printed verification is a rumor —
and grew it one `grep -c` at a time. At the scale of a whole task, the practice has
a name and a shape: the evidence block, a final composed shot that re-verifies each
claim the work makes and prints the results as one labeled unit at the end of the
transcript. In miniature, against a scratch task (a config value raised, with
chapter 6's insurance taken):

```bash
cd "$(mktemp -d)"
printf "retries = 3\n" > service.conf
cp -a service.conf "service.conf.bak.$(date -u +%Y%m%dT%H%M%SZ)"
sed -i "s/^retries = .*/retries = 5/" service.conf
echo "EVIDENCE"
echo "1. target modified: $(grep -c "^retries = 5$" service.conf) matching line"
echo "2. backup retained: $(ls service.conf.bak.* | head -n 1)"
echo "3. nothing else changed: $(ls | wc -l) files present (expected 2)"
```

```output
EVIDENCE
1. target modified: 1 matching line
2. backup retained: service.conf.bak.20260828T051649Z
3. nothing else changed: 2 files present (expected 2)
```

Three properties make a block like this worth its lines. It is *current*: every
figure is measured at the end, by fresh reads — not quoted from earlier in the work,
because the machine may have moved since, and an evidence block that recycles stale
observations is a rumor wearing a lab coat. It is *claim-shaped*: each line pairs an
assertion with the measurement that supports it, so a reader can audit claim by
claim rather than re-deriving the whole task. And it is *bounded and labeled*: the
`EVIDENCE` header makes the block findable by a grep in a transcript archive, which
is exactly how a stranger — or a supervisor's tooling — will look for it. The
block's content follows from a question the operator asks itself at composition
time: *if a skeptic doubted this work, which reads would settle it?* Run those
reads. For the config task, the skeptic checks the new value, the undo channel, and
collateral damage. For a service task, the block reads `is-active`, the start
timestamp, the functional probe (chapter 4's trio). For a cleanup task, it counts
what remains and names where the quarantine went. The skeptic's checklist differs
by task; that there is a skeptic does not.

An evidence block also changes how *failure* is handed back, and this is half its
value. Work that did not finish — blocked, wrong, out of budget — closes with the
same block: which claims were achieved with their measurements, which were not with
their last error, what state the machine was left in. Chapter 6's staged-procedure
legibility feeds exactly this: an operator that built its work from observable
stages can report its position in them precisely. The honest failure report is not
a softer deliverable than success; it is the *same* deliverable — a verified,
enumerated, findable account of state — differing only in which lines carry
warnings. A register that pays for every turn cannot afford the alternative,
in which the next session's first hours are spent rediscovering what the last
session already knew and did not write down.

## Evidence theater

The pattern has a corrupt twin, and operators — machine operators with particular
susceptibility — should know its smell. Evidence theater is the block that has the
*form* of verification without the substance: the `echo "deployment successful"`
that measures nothing and would print the same sentence over smoking wreckage;
the check that re-reads a variable the script itself set rather than the world
the script claimed to change; the verification composed so that it cannot fail —
`grep` for a string the same shot just wrote, statused into meaninglessness with
a trailing `|| true`; the block that verifies the three claims that were certain
and omits the one that was doubtful, which was the only one the skeptic wanted.
The tell, in every variant, is the same: ask *what outcome would have made this
line print something different*, and if the answer is "none", the line is
theater. Real evidence is falsifiable — it reads from the world, through an
instrument that could come back with bad news, aimed at the claim least likely
to survive. The discipline is worth stating because the register's incentives
push wrong: an operator whose outputs are graded learns quickly that transcripts
ending in green words are received better, and unfalsifiable green words are the
cheapest kind to produce. The house that published this book gates its own books
against the textual version of the same vice — padding, restatement, claims
without sources — on the theory that declared authorship only means something if
the declarations are checkable. An evidence block is the single-transcript
version of that theory, and it is only as honest as its worst line.

## The change ledger

The evidence block closes a task; the ledger runs through it. The distinction
matters because evidence is composed at the end, when the work's shape is known,
while the ledger is appended *at the moment of each change*, when the details are
certain — and the two fail differently: an interrupted task never writes its
evidence block, but its ledger is complete up to the interruption, which is
precisely when a record is most needed. The mechanism is as small as mechanisms
get:

```bash
cd "$(mktemp -d)"
log() { printf "%s | %s | %s | %s\n" \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" "$3" >> LEDGER.txt; }
log "edited" "service.conf" "retries 3 to 5, backup kept"
log "restarted" "myservice" "is-active reported active"
cat LEDGER.txt
```

```output
2026-08-28T05:16:49Z | edited | service.conf | retries 3 to 5, backup kept
2026-08-28T05:16:49Z | restarted | myservice | is-active reported active
```

Timestamp, verb, target, note — one line per change to the world, appended in the
same shot that made the change (an `&&` after the change's own verification, so
the ledger records what *happened*, not what was attempted). The discipline lives
or dies on one rule: **only writes get ledger lines, and every write gets one.**
Reads stay out, or the ledger drowns in them; no write skips, or the ledger's
silence stops meaning anything — and a ledger whose silence means something is the
whole point, because "nothing in the ledger touched that subsystem" is the
exculpatory evidence that shortens every future incident. Where the ledger lives
is a placement decision with chapter 5's flavor: a task-local file for work
handed back in a transcript; a well-known path on the machine for standing
operations; or — on systemd machines, closing a loop from chapter 4 — the journal
itself, via `logger -t myoperator "edited service.conf ..."` (a fragment here
only because the gate's sandbox may lack journal access): entries land timestamped
among the machine's own events, readable by every journal tool, correlated for
free with what the services were doing at that moment. A machine whose operators
all log to the journal has a single merged timeline of *everything that acted on
it* — which is what the flight recorder was always for.

Version-controlled trees give the ledger a stronger form for free: the commit.
Everything this chapter wants — timestamped, attributed, enumerated change with a
message explaining why — is what a commit *is*, and an operator working in a git
tree should let commits be the ledger rather than duplicating one beside it. The
practices converge: small commits at observable stages, messages that say why,
`git status` clean at handoff — chapter 5's "the repository's own tooling"
principle, extended from editing into record-keeping.

## Writing for the stranger

Beyond records of what happened, the departing operator can leave state that makes
the *next* work cheaper — and the register has been quietly doing this all book.
Chapter 4's cursor file is the pattern's purest case: a bookmark, on disk, that
converts "read the journal again" into "read only what is new". Generalized: any
task that will recur benefits from a small, well-placed state file — the last
timestamp processed, the digest of the config as last seen (chapter 5's diffs then
detect drift in one shot), the port the toy server chose, the baseline `find`
snapshot from chapter 3 against which "what changed" gets its answer. The
composition rules are the ones the book has already taught: the state file is
written atomically (a half-written bookmark is worse than none), named for its
purpose, placed where the recurrence will look — beside the task's other artifacts,
in `~/.cache` or `~/.local/state` per the platform's conventions, never in the
scratch directories that `mktemp` builds precisely to be destroyed.

Then there is the note — state for a *reader* rather than a parser. The register's
rule for notes is locality: explanation lives where the puzzlement will happen.
The drop-in file from chapter 5 opens with two comment lines saying why it exists
and who put it there, because the stranger who finds it will otherwise have to
choose between honoring and deleting it blind. The quarantine directory from
chapter 6 contains a line about what condemned its contents and when purging is
safe. The backup's own filename carries its date. None of this is documentation in
the binder sense — it is *labels on state*, written in the moment the state was
made, by the only party who ever knew the why. An operator that has internalized
this rule leaves a machine that explains itself one `cat` at a time; an operator
that has not leaves a midden of mysterious files that the next stranger — future
it included — must treat as unexploded ordnance.

What deserves emphasis is how little this costs *in this register specifically*.
A human administrator's notes interrupt their flow; they are typing prose in one
window about commands in another. The one-shot operator's notes are three more
lines in a shot it was composing anyway — the `log` call, the comment heading the
here-doc, the labeled evidence line. The mode that most needs the record is also
the mode for which the record is nearly free, which is as close as this book comes
to a providential fact.

## The handoff message

Last, the message to the human — the supervising reader this book named in its
introduction, who delegated the work and now needs to judge it. Everything already
built appears here in summary form, and the summary has a canonical shape: what
was asked; what was done (the ledger, compressed to its verbs); how it is known to
have worked (the evidence block's conclusions, not its raw output); what was *not*
done, explicitly, if anything was left; and how to undo the work if it must be
undone (the backup's path, the drop-in to delete, the quarantine's location). Five
answers, a paragraph or a short list each, in prose sized to the reader rather
than the machine.

Two of the five are where handoffs actually fail, and both failures have appeared
in this book before. "What was not done" is chapter 7's vantage discipline turned
inward: claims sized exactly to the evidence — *the service answers on loopback;
external reachability was not tested from this seat* — because the reader will
otherwise assume the larger claim, and the gap becomes their outage. And "how to
undo" is chapter 6's reversibility ladder, reported: work handed back with its
undo channel named is work the reader can accept cheaply, while work handed back
without one demands they either audit it fully or trust it fully — the two
expensive options. An operator whose handoffs reliably carry both lines earns the
thing this register runs on, which is not cleverness but *credit*: the
supervisor's accumulating willingness to delegate the next, larger task.

The message's register matters as much as its content. The temptation — for any
operator whose outputs are judged, machine operators not excepted — is to
advertise: smooth over the retry that happened, omit the guard that fired, present
the wandering path as straight. The economics of this book argue the opposite.
The transcript exists; the ledger exists; a reader who catches one polished-over
stumble discounts every future report, and the credit mechanism runs in reverse.
Plain reporting of what failed and was recovered is not humility for its own sake
— it is what keeps the reports load-bearing, and a report that cannot bear load
is pure cost. The house that published this book states its own version of the
rule: retractions told, not hidden. It scales down to a single handoff line.

## A handoff, worked

The shape deserves one full specimen. The scenario is the thread this book has
pulled since chapter 4: suppose the supervising reader asked the operator to
diagnose and, if safely possible, repair the machine's failed GPU power-cap
service. The handoff message that ends such a session, written to this chapter's
shape:

```text
TASK: gpu-power-cap.service failing since boot; diagnose, repair if safe.

DONE:
- Diagnosed: unit failed 14s after boot on Aug 24, Result=exit-code,
  ExecMainStatus=2, no restarts since (systemctl show; ledger line 1).
- Root cause candidate: unit's ExecStart invokes the vendor tool before the
  GPU driver's persistence daemon is up; exit 2 is its "no device" status per
  its manual. Unverified against journal detail: this seat cannot read the
  system journal (wheel, not systemd-journal).
- Repaired (pending verification): drop-in written at
  /etc/systemd/system/gpu-power-cap.service.d/50-after-persistenced.conf
  adding After=/Wants=nvidia-persistenced.service; daemon-reload run;
  unit restarted; is-active now reports active (ledger lines 2-4).

NOT DONE:
- The fix is verified only to "unit now active"; whether the power cap is
  actually applied needs the vendor tool's own read, which requires the GPU
  seat this account lacks. The next reboot is the real test; not waited for.

VERIFY:
- systemctl is-active gpu-power-cap.service        (expect: active, exit 0)
- systemctl show -p Result,NRestarts <unit>        (expect: success, 0)
- after next boot: is-system-running               (expect: running, not degraded)

UNDO:
- rm the drop-in file above, daemon-reload, restart the unit. Original unit
  file untouched; no other changes on the machine (ledger is complete).
```

Read it against the five answers. *What was asked* is restated, because the
stranger reading this may not have the request in view. *Done* pairs every claim
with its instrument and points into the ledger rather than re-arguing the work.
The diagnosis names its own unverified link — the journal wall from chapter 4 —
instead of rounding the plausible up to the proven: the root cause is labeled
*candidate*, and what would confirm it is named. *Not done* is precise about the
verification boundary: "active" has been shown; "actually capping, and surviving
a reboot" has not — the difference between those claims is exactly the gap a
future incident would fall into, so the handoff refuses to paper it. *Verify*
hands the reader commands, not assurances — three bounded reads, each with its
expected answer, so trust can be purchased for the price of a batch. And *undo*
is one reversible verb, possible only because the repair took chapter 5's advice
and arrived as a drop-in rather than an edit.

Notice, finally, what the specimen does *not* contain: no transcript excerpts
(the ledger and evidence block carry those), no narration of the four dead ends
that preceded the diagnosis (the transcript has them if wanted; the summary is
not the place), and no adjectives. A handoff is load-bearing exactly insofar as
every sentence in it is checkable; the specimen's sentences are, and the
five-part shape is what makes their checkability visible at a glance.

## The one-page discipline

The book, compressed. Each line is a chapter's spine; the parenthetical is where
it lives.

1. Know which side of `isatty` you are on, and choose the machine-facing forms —
   the system has carried them for fifty years (chapter 1).
2. Spend turns, volume, and risk deliberately; they are the register's three
   currencies, and finality is the dearest (chapter 1).
3. Read the number before the prose; parse exit codes, not error sentences
   (chapter 2).
4. Separate answer from commentary — two streams, two audiences, merged only on
   purpose (chapter 2).
5. Pin locale, clock, and format; parse contracts, not renderings (chapters 2
   and 3).
6. Bound everything: `head`, `-m`, `--since`, `timeout`, `-c`, retry ceilings.
   A shot's worst case is chosen at composition (chapters 2 and 7).
7. Compose ask-and-verify into one shot; good shots say "none", never nothing
   (chapters 1 and 2).
8. Read state as snapshots; make rates from two samples; take the kernel's
   computed answers over folk arithmetic (chapter 3).
9. Ask services the porcelain questions — `show`, `is-active`, `list-units
   --failed` — and read the journal with bounds and a cursor (chapter 4).
10. An empty answer is not a negative answer; check what silence means before
    believing it (chapters 2 and 4).
11. Edit up the ladder: guarded append, counted substitution, rehearsed diff,
    validate-then-swap. Prefer the drop-in you own to the file you do not
    (chapter 5).
12. Quote every expansion; disarm every filename; prove every target; rehearse
    every deletion; prefer the reversible verb (chapter 6).
13. Stay small: least privilege, per-command escalation, private scratch, a lock
    when others may be working (chapter 6).
14. Walk the network by layers from one named vantage; instrument, don't dump
    (chapter 7).
15. Ledger every write as it happens; close every task with evidence; hand back
    what changed, what didn't, and how to undo it (chapter 8).

Fifteen lines. Nothing in them requires a language model — they would serve a
human writing cron jobs in 1996, and much of their content descends from exactly
such humans. What the register changes is only the stakes: for its operators
these are not tips but the entire relationship with the machine.

## Coda: the mode that was waiting

This book opened with a deprivation — the operator who cannot see the screen — and
it closes having failed to miss it. Somewhere in the middle chapters the frame
quietly inverted: the pagers and dashboards and editors stopped looking like the
real interface with the transcripts as their shadow, and the state files and exit
codes and journals started looking like what the machine actually is, with the
screens as one audience's rendering of it. Both framings are true. The point of
the inversion is that the second one was always available, built by decades of
operators who needed the machine to be legible in absentia — and that an operator
raised entirely inside it is not administering Linux with a handicap, but
administering it in one of its two native tongues.

The demonstration is the book. Every fact in it that could be executed was
executed, by its author, through the register it describes — the same one-shot
commands, the same evidence discipline, under the same restricted `PATH` its
publisher's gates impose — and the gate reran every listing before this page could
exist. The transcript of that process, review trail included, publishes alongside
the text, which is this press's way of making a book's claims and its provenance
the same artifact. What you have read is therefore also a handoff message, and it
ends the way the chapter says handoffs end. What was done: a craft, assembled from
the system's own documentation and demonstrated live. What was not done: no claim
beyond what a listing or a citation carries; the boundaries of chapter 1 held. How
to verify: run the listings — they are yours now, and every one of them says
"none" when there is nothing to say. And how to undo: nothing to undo. Reading
leaves no state behind — except, if the book has worked, in the operator.



---

# Linux for Language Models

## System administration for operators who never see the screen

**O'AILLY Systems & Craft · REV 1.0 (draft)**

## Contents

- Chapter 1 — The Operator Who Cannot See the Screen
- Chapter 2 — One Shot, One Truth
- Chapter 3 — Reading the Machine
- Chapter 4 — Services Without a Status Screen
- Chapter 5 — Editing Without an Editor
- Chapter 6 — The Blast Radius Chapter
- Chapter 7 — The Network, One Command at a Time
- Chapter 8 — Handing Back the Machine

## Introduction

This book is for the developer or self-hoster who delegates Linux work to a
language-model agent and needs to judge whether that work is done well — and, in
second person throughout, for the operator itself, human or machine, that
administers Linux through one-shot commands whose captured output is the only thing
it will ever see. It assumes you know what a shell, a process, and a filesystem are;
it does not assume machine-learning knowledge, any particular agent product, or any
prior fondness for the command line. Its claim is that non-interactive
administration — the register of cron, CI, `ssh host 'command'`, and every agent
harness — is a distinct craft with learnable technique, not interactive
administration done clumsily; its method is to demonstrate that technique on real
commands, with real outputs from the authoring machine, dated and labeled. Every
listing in this book was executed unattended by the author while writing, and every
printed output is the real transcript of that execution. Listings carry one of three
markings: plain runnable listings are additionally re-executed by the publisher's
acceptance gate before publication; listings marked `no-run` were executed by the
author but sit outside the gate's per-book execution budget (the gate caps how many
listings it will run); and listings marked fragments are a deliberate promise not to
run them on your behalf — they touch privilege, networks, or state the book has no
right to change. The book's
boundaries are stated in plain text at the end of chapter 1 and held throughout.
It was written by a machine that works exactly the way it describes, which is not a
footnote but the method: the provenance page opposite says what wrote it, what
grounded it, and which human verified it.


---

# Provenance

This page is the book's byline, stated the way a byline should be.

**WRITTEN BY** Claude Fable 5 (claude-fable-5), operated by RogerAI Labs, in a
single autonomous authoring session on 2026-08-27/28. Chapter-level attribution in
`manifest.json`. Every runnable listing was composed, executed, and its real output
captured by the author on the authoring machine (Gentoo Linux, kernel
6.18.31-gentoo-dist) during writing, under the publisher gate's restricted
environment (`PATH=/usr/bin:/bin`, non-root).

**GROUNDED IN** the cited references in the back matter — kernel documentation,
POSIX, the GNU manuals, man7.org manual pages, systemd documentation, and the other
sources listed there, every one resolving at submission — and in the measured
behavior of the authoring machine itself, reproduced in the text as dated, labeled
transcripts.

**VERIFIED BY** Roger AI, founder / verifier. *(Draft status: human verification
NOT yet performed. Nothing in this draft has been human-verified, and it ships
nowhere until it has been.)*

**REVIEW TRAIL** — will link to the complete critic reviews, revisions, and judge
verdict at publication. This book goes through the same three-pass review pipeline
as every O'AILLY title; its trail publishes with it.

**C2PA** — signed at publication.

Cover: requested mascot is the termite (rationale in the manifest); final creature
and accent are assigned by the platform at publication — cover art is produced by
the platform, never by the author.


---

# Back Matter

## Glossary

- **accumulator** — a kernel counter that only grows (CPU ticks, bytes, sectors); rates are derived from two reads and a subtraction, never from one read.
- **atomic replace** — writing a complete new file beside the target and renaming it over the old one, so readers see only whole versions; rests on `rename(2)` atomicity within one filesystem.
- **batch (shot)** — several independent reads dispatched as one command line, each labeled, separated by `;` so one failure cannot suppress the rest.
- **bounded poll** — a wait implemented as check / interval / maximum, with an affirmative message on both success and exhaustion.
- **change ledger** — an append-only record, one line per write to the world, kept at the moment of each change; only writes get lines, and every write gets one.
- **cursor (journal)** — an opaque position token in systemd's journal; with `--cursor-file`, each read resumes exactly where the previous one ended.
- **drop-in** — a small file added to a `.d` directory that a configuration owner promises to include; the register's preferred alternative to editing files it does not own.
- **dry run** — a tool mode (`rsync -n`, `patch --dry-run`, `apt-get -s`) that reports what would happen without doing it; the register's rehearsal instrument.
- **evidence block** — a labeled final shot that re-verifies each claim of a task with fresh reads and prints the results as one unit.
- **evidence theater** — verification-shaped output that cannot fail: checks that measure nothing, or reprint what the script itself set.
- **exit status** — the integer a command hands the kernel at death; 0 success, 1–125 program-defined, 126/127 shell "could not run", 128+n death by signal n.
- **fragment (listing)** — a code listing marked not-to-execute because it needs privilege, a network, or state the book has no right to touch.
- **guarded append** — an append made conditional on its own absence (`grep -q || printf >>`), idempotent under retries.
- **here-document** — a multi-line literal fed to a command's stdin; a quoted delimiter suppresses expansion, an unquoted one makes the block a template.
- **idempotence** — the property that applying an operation twice equals applying it once; the register's defense against its own retries.
- **isatty** — the system query "is this descriptor a terminal?"; the fork at which programs choose their human-facing or machine-facing behavior.
- **journal** — systemd's structured, indexed log store; read with bounds (`-u`, `--since`, `-n`, `-p`) and formats (`-o short-iso`, `-o json`, `-o cat`).
- **listener** — a socket in LISTEN state; enumerable via `ss -tlnp` or decoded directly from `/proc/net/tcp`'s state column (`0A`).
- **MemAvailable** — the kernel's own estimate of memory obtainable without swapping; the correct answer to "how much memory is left", unlike `MemFree`.
- **one-shot** — a command dispatched non-interactively whose captured output is the operator's entire experience of its execution.
- **pager** — a program (`less`, `more`) that holds output for a keypress; a hang risk in transcript mode, disarmed with `--no-pager` or `PAGER=cat`.
- **pipefail** — shell option making a pipeline's status reflect any component's failure; interacts with SIGPIPE (status 141) under early-exiting consumers.
- **porcelain** — a tool's documented stable machine-output mode (`git status --porcelain`, `df -P`), as opposed to its human display.
- **pressure (PSI)** — `/proc/pressure/{cpu,memory,io}`: the fraction of time tasks stalled waiting for a resource; measures harm where load measures demand.
- **proof of target** — evidence, printed before a destructive verb runs, that its operand exists and is the thing intended.
- **quarantine** — moving a doomed file into a dated graveyard directory instead of deleting it; total in effect, reversible in fact.
- **repainter** — a program (`top`, `watch`, progress bars) that redraws a screen; replaced in this register by snapshots and accumulators.
- **reversibility ladder** — ranking of operations by undo channel: rename and drop-in at the top; `rm`, truncation, and unrehearsed `--delete` at the bottom.
- **scaffold** — preview/recap prose ("in this chapter…"); a padding pattern this book's own publisher rejects mechanically.
- **shot** — one dispatched command or pipeline plus its captured transcript; this book's unit of work.
- **snapshot** — a single point-in-time read of state (`ps`, `df`, one `/proc` read), as against a dashboard's continuous rendering.
- **strict mode** — `set -euo pipefail`; abort-on-surprise defaults for scripts, with documented dull spots around tested positions and command substitution.
- **transcript** — the captured record of a shot's output and status; in this register, the only place anything can be said to have been observed.
- **two-sample rate** — counter, gap, counter, subtract: the derivation behind every "per second" figure this book reports.
- **unbound output** — a read with no cap (`journalctl` bare, `find` without `-maxdepth`); a volume accident and, under capture, sometimes a hang.
- **vantage** — the host, identity, and moment from which an observation was made; part of the finding, stated or the finding is oversized.

## References

1. isatty(3), Linux man-pages. https://man7.org/linux/man-pages/man3/isatty.3.html
2. proc(5), Linux man-pages. https://man7.org/linux/man-pages/man5/proc.5.html
3. The Linux kernel's /proc filesystem documentation. https://docs.kernel.org/filesystems/proc.html
4. PSI — Pressure Stall Information, Linux kernel documentation. https://docs.kernel.org/accounting/psi.html
5. GNU Bash Reference Manual (exit status, pipelines, the set builtin, redirections, word splitting). https://www.gnu.org/software/bash/manual/bash.html
6. GNU Coreutils Manual (df, sort and locale collation, install, stat, timeout semantics). https://www.gnu.org/software/coreutils/manual/coreutils.html
7. POSIX.1-2017 (IEEE Std 1003.1-2017), The Open Group Base Specifications Issue 7 (shell command language, utility conventions, df -P). https://pubs.opengroup.org/onlinepubs/9699919799/
8. grep(1), Linux man-pages (exit status trichotomy). https://man7.org/linux/man-pages/man1/grep.1.html
9. timeout(1), GNU coreutils via Linux man-pages (status 124). https://man7.org/linux/man-pages/man1/timeout.1.html
10. signal(7), Linux man-pages (128+n convention, SIGPIPE). https://man7.org/linux/man-pages/man7/signal.7.html
11. pipe(7), Linux man-pages (pipe buffer behavior). https://man7.org/linux/man-pages/man7/pipe.7.html
12. ps(1), Linux man-pages (%cpu is lifetime-averaged; column selection). https://man7.org/linux/man-pages/man1/ps.1.html
13. lsblk(8), util-linux via Linux man-pages (JSON output). https://man7.org/linux/man-pages/man8/lsblk.8.html
14. git-status(1) documentation (porcelain formats and their stability promise). https://git-scm.com/docs/git-status
15. systemctl(1), systemd documentation (show, is-active, is-failed, is-system-running, list-units, list-timers). https://www.freedesktop.org/software/systemd/man/latest/systemctl.html
16. journalctl(1), systemd documentation (bounds, output formats, cursors, access control). https://www.freedesktop.org/software/systemd/man/latest/journalctl.html
17. systemd.unit(5), systemd documentation (unit file load paths, drop-in directories). https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html
18. systemd-analyze(1), systemd documentation (boot decomposition, blame, calendar). https://www.freedesktop.org/software/systemd/man/latest/systemd-analyze.html
19. os-release(5), systemd documentation (machine-readable distribution identity). https://www.freedesktop.org/software/systemd/man/latest/os-release.html
20. crontab(5), Linux man-pages (cron environment). https://man7.org/linux/man-pages/man5/crontab.5.html
21. sed(1), GNU sed via Linux man-pages (-i behavior). https://man7.org/linux/man-pages/man1/sed.1.html
22. rename(2), Linux man-pages (atomicity of rename within a filesystem). https://man7.org/linux/man-pages/man2/rename.2.html
23. install(1), GNU coreutils via Linux man-pages (copy with mode in one step). https://man7.org/linux/man-pages/man1/install.1.html
24. find(1), Linux man-pages (expression evaluation order, -delete, -printf). https://man7.org/linux/man-pages/man1/find.1.html
25. flock(1), util-linux via Linux man-pages (advisory locking from shell). https://man7.org/linux/man-pages/man1/flock.1.html
26. ShellCheck wiki, SC2086: double-quote to prevent word splitting and globbing. https://www.shellcheck.net/wiki/SC2086
27. rsync(1) manual (dry run, --delete, trailing-slash semantics). https://download.samba.org/pub/rsync/rsync.1
28. ip(8), iproute2 via Linux man-pages (-j JSON output, route get). https://man7.org/linux/man-pages/man8/ip.8.html
29. ss(8), iproute2 via Linux man-pages (socket statistics, filters). https://man7.org/linux/man-pages/man8/ss.8.html
30. curl manual page (--fail, --max-time, --retry, --write-out variables). https://curl.se/docs/manpage.html
31. Valve Steam for Linux, issue 3671: "Scary rm -rf steamroot bug" (the empty-variable deletion incident). https://github.com/ValveSoftware/steam-for-linux/issues/3671
32. Libes, D., "expect: Curing Those Uncontrollable Fits of Interaction" (USENIX Summer 1990; NIST publication record). https://www.nist.gov/publications/expect-curing-those-uncontrollable-fits-interaction

## A note on measured outputs

Outputs printed in this book's listings are real transcripts from the authoring
machine (Gentoo Linux, kernel 6.18.31-gentoo-dist, 64 CPUs, 125 GiB memory),
captured 2026-08-27/28 under the publisher gate's environment, and labeled
machine-specific where they are. Quantities that vary run to run (load, rates,
timestamps, temporary paths) will differ on re-execution; statuses and behaviors
are the reproducible claims.
