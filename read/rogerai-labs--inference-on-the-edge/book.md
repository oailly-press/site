# Inference on the Edge — Quantization, speculation, and the physics of local models

(canonical markdown, concatenated; manifest: see book repo. Provenance: written by rogerai-dj; verified by Roger AI; draft status per chapter notes.)

# Chapter 1 — What a Token Costs

*(v2, 2026-08-28 — written by rogerai-dj for RogerAI Labs, verified by Roger AI.
Numbers carrying a `[LAB:]` marker are RogerAI Labs' own bench measurements, taken on the
reference machine described in Chapter 1 and recorded in the lab notebook; each is
reproducible by re-running the stated recipe — engine build, artifact, and flags. Claims
without a marker are labeled unmeasured.)*

## The wrong unit

People talk about local inference in the units marketing handed them: parameters,
tokens per second, "a 70B on your desk." Those numbers are not fake. They are just the
wrong place to start. A parameter count tells you how large the weight file is. A
tok/s number tells you how the run felt on one machine, one day, one engine. Neither
tells you what the machine was actually paying.

The machine pays in **bytes moved**.

Every generated token is the result of reading a large weight tensor, combining it with
a smaller activation, and writing a little state forward. The arithmetic is cheap on
modern silicon. The memory movement is not. That is the single fact this chapter is
built on, and every later chapter is a consequence of it: quantization exists to move
fewer bytes; speculative decoding exists to make the bytes you do move buy more than
one token; the KV cache is a second working set you are also streaming; a bad load log
is almost always a placement story about which bytes landed on which bus.

If you already knew that, stay anyway. The chapter is not the slogan. It is the
measurement of what the slogan costs on one real box, and the habits that keep you from
lying to yourself with a tok/s number.

## The box this book measures against

Unless a sentence says otherwise, the numbers in this book come from one laboratory
machine:

- 4× RTX PRO 4500 Blackwell, 128 GB VRAM total
- Threadripper 9970X
- 128 GB DDR5-4800 host memory
- llama.cpp unless a row says vLLM

That envelope is not universal. It is a **reference**. A laptop will be slower. A
datacenter H100 node will be faster. A Raspberry Pi will be a different regime entirely,
and chapter 8 will say so without romance. The point of a reference is not to pretend
your hardware matches it. The point is that every comparison in the book is pinned to a
named machine, so a claim can be re-run or rejected.

Warm single-stream decode is the default tok/s figure. Prefill (prompt evaluation) is
called out when it matters. Aggregate throughput under concurrency is a different
number again, and chapter 3 will spend time on why confusing those three is how people
buy the wrong GPU.

## A tok/s is a receipt, not a personality

Take one model, hold it fixed, and change only the engine. The lab did that with a
102 GB UD-IQ3_XXS build of DeepSeek-V4-Flash:

| Build | Indexer | Warm decode |
|---|---|---|
| pre-#25545 era | CPU | ~2 tok/s |
| mainline CUDA | CPU | ~10.8 tok/s (bimodal) |
| taco build | CPU/disabled | 13.1 tok/s (bimodal) |
| pr25545 | **GPU** | **26.2 tok/s (24.5–28.5, stable)** |
| combined prototype | GPU | 28.4 tok/s (±0.04) |

`[LAB: RESULTS-MATRIX §A]`

Every cell above is **warm single-stream decode** on the same 102 GB UD-IQ3_XXS artifact,
short fixed prompt, on the reference box. The CPU-indexer rows carry an approximate figure
(`~2`, `~10.8`) rather than a tight range on purpose: those builds were *bimodal and
unstable* — the instability is the measurement, not a hidden orphan number. The stable GPU
row carries a real range (24.5–28.5 across runs) because it was stable enough to have one.
This book's own rule (Chapter 5) is to refuse a number without a range; the honest form of
that rule for a pathological configuration is to publish the approximation **and** name it
as unstable, not to invent a false precision. The historical `~26` old-production baseline
is likewise a warm single-stream approximation on this artifact, not a promoted, ranged
production number.

Same weights. Same cards. Same host. Decode moved from a cratered ~2 tok/s to a stable
26 tok/s because the lightning indexer stopped living on the CPU. Prefill moved with
it: roughly 50–80 tok/s on CPU-indexer builds versus ~130 tok/s once the indexer was on
the GPU.

If tokens-per-second were a property of "the model," that table would be illegal. It
is not a property of the model. It is a property of **which bytes crossed which bus on
each step**. The early builds were not "bad at language." They were paying a host-side
tax on every token that no amount of prompt engineering could refund.

This is the first practical habit of the book:

> When a tok/s number is surprising, ask what moved, not what the model "is."

Chapter 6 will turn that habit into a load-log discipline. Here it is enough to notice
that a twelve-fold swing appeared before any quantization experiment, any speculative
decoding trick, or any change to the weights at all.

## Bandwidth as a budget you can feel

You do not need a cycle-accurate simulator to use the bandwidth idea. You need a
back-of-envelope that keeps you honest.

Suppose a decode step must touch roughly the active weights for the layers involved,
plus a slice of KV cache, plus overhead. The exact fraction depends on architecture
(dense versus mixture-of-experts), batch size, and how much of the model lives on GPU
versus host. What does not depend on those details is the shape of the limit:

**tokens per second cannot exceed (effective bytes per second) / (bytes per token).**

Raise effective bandwidth — better placement, fewer host round-trips, less spill — and
tok/s rises. Raise bytes per token — higher-precision weights, fatter KV, wider active
expert sets — and tok/s falls. Everything marketed as a "speed tip" is one of those two
moves in costume.

That is why a smaller file is not automatically faster. A 175 GB Q4 that spills hard
into host memory can lose to a 160 GB master that stays resident, even though the Q4
looks "more quantized" on a spreadsheet. The lab's promotion decision later in the
matrix is exactly that story: tool quality preferred over the last few tok/s, but only
after measuring that the master could still land at old-production speed with
speculative decoding paying back the spill `[LAB: RESULTS-MATRIX headline
before/after + §E]`. Chapter 2 takes the quality side. Chapter 3 takes the speculation
side. This chapter only needs the bandwidth reading: **residence beats folklore.**

## Three speeds people crush into one number

Local-inference conversations mash three different speeds together. Separate them or
you will misread every table in this book.

**Prefill (prompt eval).** The cost of reading the prompt and building the initial KV
cache. Dominated by large matrix multiplies over many tokens at once. On the reference
box, GPU-indexer builds prefilled the same DeepSeek IQ3 around 130 tok/s; CPU-indexer
builds sat nearer 50–80 `[LAB: RESULTS-MATRIX §A]`. Prefill cares about batchable work
and memory throughput into big GEMMs.

**Decode (single-stream).** The cost of producing the next token after the prompt is
in. Often memory-bandwidth bound because each step re-reads weights for a tiny amount
of arithmetic. This is the number people quote as "tok/s." On the same IQ3 model, the
promoted engine held 26.2 warm decode with a tight range (24.5–28.5) once the indexer
tax was gone `[LAB: RESULTS-MATRIX §A]`.

**Aggregate throughput under concurrency.** Several requests at once. Per-stream decode
usually drops; total tokens across streams may rise. On the same pr25545 IQ3 build with
PAR=4, c=1 measured 26.2 tok/s while c=4 measured 46.1 aggregate `[LAB: RESULTS-MATRIX
§B]`. That is not a contradiction. It is two different receipts.

If a vendor quotes "60 tok/s," ask which of the three they measured, on what batch, at
what context length, after what warm-up, and whether the range across runs was smaller
than the claim. Chapter 5 is about that honesty. Chapter 1 only installs the split.

## Same box, different models: the §C decode column

Hold the engine culture roughly fixed and look across models on the reference machine
`[LAB: RESULTS-MATRIX §C]`:

| Model / quant | Size | Warm tok/s | Notes |
|---|---|---|---|
| DeepSeek-V4-Flash IQ3 (old prod) | 102 GB | ~26 | baseline production |
| DeepSeek-V4-Flash community Q4 | 175 GB | 16.5 | bigger file, slower decode |
| DeepSeek-V4-Flash Q3-MTP | 143 GB | **30.5** @ MTP n=1 | speculation on |
| DeepSeek-V4-Flash Q8-MTP master | 160 GB | 26–27 @ MTP n=1 | quality ceiling, old speed |
| Qwen3.6-27B dense Q8_0 | 29 GB | ~27 | much smaller dense model |
| gpt-oss-120b MXFP4 (vLLM TP=4) | ~60 GB | 60 wall-clock | different engine |

Read it as bandwidth, not as a leaderboard.

The community Q4 is larger than the IQ3 and slower on decode. That is the bytes-per-token
term biting. The Q3-MTP build is larger than IQ3 and *faster* on decode because
speculative decoding changed how many tokens each weight read bought — not because Q3
magically streams better than IQ3 in isolation. The Q8 master is larger still and lands
back near the old ~26 tok/s once MTP n_max=1 is on: quality recovered without stranding
latency. The dense 27B Q8 sits near 27 tok/s at 29 GB: a different architecture with a
much smaller working set, in the same speed neighborhood as a heavily engineered MoE
stack an order of magnitude larger in file size.

None of those sentences require you to believe a vendor blog. They require you to
believe a table measured on one box and labeled with the recipes that produced it.

## Why "parameters" keep surviving

Parameter counts survive because they are easy. They fit on a slide. They sort a
Hugging Face page. They are also a decent proxy for *file size at a given precision*,
which is a decent proxy for *bytes you might have to move*, which is why they are not
useless.

They become harmful when they smuggle in assumptions:

1. **That all parameters are active on every token.** Mixture-of-experts models break
   this. Active parameters per token can be a fraction of total parameters; total still
   drives storage and often drives how much spill you accept to make the model fit.
2. **That precision is uniform and free.** It is not. Expert precision moved tool-use
   scores in the lab when total-bit folklore said the models should be close `[LAB:
   RESULTS-MATRIX §C/§D]`. Chapter 2 is the full argument.
3. **That two models with the same parameter count have the same decode cost.** Engine,
   placement, KV precision, batching, and spill can dominate.

Use parameters as a rough size class. Pay for tokens with bandwidth accounting.

## The 2 tok/s lesson, in slow motion

The cratered ~2 tok/s era on the reference box is worth sitting with, because it is the
purest bandwidth failure mode in the matrix.

Operators did what operators do: change GPU splits, poke batch flags, blame the model,
blame the quant, rerun benchmarks that all agreed the machine was "slow." The load path
was the problem. With the indexer on CPU, every token paid a host-side tax. The cards
were present. The weights were present. The bytes were taking the long road.

When the GPU indexer landed in pr25545, warm decode jumped to 26.2 and the range
tightened to something you could plan around (24.5–28.5). Prefill roughly doubled. No
romance, no new weights — a placement fix `[LAB: RESULTS-MATRIX §A]`.

Chapter 6 will teach you to read the load log for the modern versions of this failure:
layers on the wrong device, mmap surprises, repack flags, compute-buffer OOMs. Chapter 1
only needs the moral:

> A pathological tok/s is often a map of where bytes went. Tuning sampling parameters
> will not move that map.

## Concurrency without self-deception

Once single-stream decode is stable, someone will ask whether the box can serve more
than one user. Measure aggregate and per-stream separately.

On the promoted pr25545 IQ3 configuration, PAR=4 concurrency looked like this `[LAB:
RESULTS-MATRIX §B]`:

| c | tok/s (as reported in the matrix) |
|---|---|
| 1 | 26.2 |
| 2 | 16.9 |
| 3 | 24.7 |
| 4 | 46.1 aggregate |

There is a reproducible dip at c=2/c=3 with zero re-prefills logged — a scheduling
quirk the matrix still marks unresolved. That honesty matters more than a smooth curve.
A real system has seams. If your concurrency table is perfectly monotonic in a way your
engine has no right to produce, your methodology may be warmer than your claim.

A taco PAR=8 line in the same section reaches 65.7 aggregate at c=8. A vLLM TP=4
gpt-oss-120b reference climbs from 60.2 at c=1 to 888 at c=16. Those rows are not
"better hardware myths." They are different engines and different models on the same
reporting discipline. Steal the discipline, not a cross-row fantasy that every stack
should hit 888.

For capacity planning, the useful questions are:

1. What per-stream latency does a user still accept?
2. What aggregate tok/s does the box deliver at that concurrency?
3. What fails first — VRAM, host RAM, scheduler quirk, thermal throttle?

Question 3 is why chapter 7 exists. Question 1 and 2 are bandwidth accounting with a
queue attached.

## Speculative decoding is a bandwidth trade in advance

You do not need the full chapter 3 treatment to see the shape. Speculative decoding
asks a cheaper draft to propose tokens and a stronger path to verify them. When it
works, each heavy weight read buys more than one accepted token. When it fails, you
paid extra movement for rejects.

On the reference matrix `[LAB: RESULTS-MATRIX §E]`:

- A dense Qwen3.6-27B Q8 with stock MTP and zero spill reaches **2.2×** (27.0 → 59.3)
  at n_max=3.
- DeepSeek Q8-MTP with 14 layers spilled gets **1.18×** at n_max=1 with **100%**
  first-token acceptance, and slows down if you push n_max while spill stays high.
- DeepSeek Q3-MTP with 10 layers spilled gets **1.30×** at n_max=1, again at 100%
  first-token acceptance.
- The same DeepSeek Q8-MTP with 24 layers spilled falls below baseline at n_max=3
  (0.86×): speculation can lose.

The matrix states the pattern in one line: speedup grows as spill shrinks; on spill-bound
MoE, batch-verify costs pile into DDR5 expert reads, so n_max=1 is the sweet spot; and on
these two DeepSeek cells the first drafted token was accepted every step (100%). Chapter 3
carries the caveat this summary compresses: that 100% is two cells on one stack, and
attributing it to "the head's training objective" is the lab's interpretation, not a
result isolated by a control.

That is pure chapter-1 material. Speculation does not repeal bandwidth limits. It
changes the numerator: accepted tokens per expensive read. If your draft forces extra
spill traffic, you can invent a perpetual-motion engine on a whiteboard and still lose
on the bench.

## Quality and speed are coupled through the same budget

It is tempting to put "quality" in one document and "speed" in another. Real deployments
choose a point on a single curve.

The lab's production headline is the cleanest example `[LAB: RESULTS-MATRIX headline
before/after]`:

| | Old IQ3 | Q3-MTP | Q8-MTP master |
|---|---|---|---|
| MMLU | 79.6 | 84.0 | **88.3** |
| Tool hardmode | 43–47 | 40–50 | mean 55 (best floor) |
| Warm decode | ~26 | 30.5 | 26–27 |
| Size / spill | 102 GB / 4 layers | 143 GB / 10 | 160 GB / 14 |

The promotion rationale is on the record: tool quality over the last 4 tok/s. The
master kept native expert precision, speculative decoding paid the spill back, and the
box landed at old-production speed with a better quality floor. A sideways Q4 requant
was aborted when the log showed conversion growing expert tensors while adding loss —
requantizing below the master only made sense to shrink (Q3), never to move sideways
into a "friendlier" label.

Chapter 2 will unpack the quality mechanics. Chapter 1 only needs the coupling: **the
bytes you keep, the bytes you spill, and the tokens you accept per read are one
decision.** Pretending speed is a runtime flag and quality is a training flag is how
teams ship a impressive demo and an unusable service.

## What this chapter refuses to claim

Boundaries, in plain text:

- We do not claim the reference box is the only serious hardware class.
- We do not claim llama.cpp is always the right engine. The matrix itself includes a
  vLLM reference row because engines differ.
- We do not claim that 26 tok/s is "enough" for your product. Enough is a product
  requirement, not a physics constant.
- We do not claim a closed-form bytes-per-token formula for every architecture. The
  accounting is directional and measured; architecture-specific constants belong to
  the model card and the profiler, not to a motivational poster.
- We have not published a full roofline plot for every row in §C. Where this chapter
  speaks in roofline language, it is as an explanatory frame over measured tok/s and
  placement facts, not as a substitute for them.

If a sentence in this chapter sounds like it would survive without the lab tables, it
has gone too far.

## Working habits to take into the rest of the book

1. **Pin the machine.** Write down GPU, host RAM, engine, and build identity before you
   quote tok/s.
2. **Name the speed.** Prefill, single-stream decode, or aggregate under concurrency.
3. **When surprised, find the bus.** Host versus GPU, spill versus resident, indexer
   placement, KV reads — before temperature or prompt shape.
4. **Treat speculation as accepted-tokens-per-read.** If spill rises with draft length,
   you can lose.
5. **Refuse orphan numbers.** A tok/s without context length, warm/cold, and range is a
   rumor.



## A note on rooflines without theater

Hardware people draw rooflines: arithmetic intensity versus bandwidth ceilings. This book stays lower to the ground because the lab evidence is tok/s, placement, and spill, not a full published roofline campaign for every row. Still, the roofline moral applies: once you are bandwidth-bound, cleverer arithmetic does not save you, and once you are bound by host round-trips, more GPU FLOPS do not save you.

If you want a roofline study, do it on your stack and attach it the way this book attaches §A/§C. Do not sprinkle FLOPS marketing onto a 2 tok/s placement bug.

## Cost per million tokens, qualitatively

Operators eventually ask for dollars. This book will not invent cloud list prices. It will say:

- local cost is dominated by capex amortization, power, and engineering time
- waste is dominated by bad recipes (spilled verifies, CPU indexers, oversized context)
- a 12× decode bug is a 12× burn rate bug on the latency path

Fixing placement is often the highest-ROI "FinOps" move available to a local stack, and it shows up in the load log before it shows up in finance.


## Field story: the day the indexer moved

Before pr25545, the reference box could look fully configured and still feel broken. GPUs were present. The model file was present. Clients got answers. The answers arrived at a pace that made tool loops unusable. The team did what every team does: change sampler settings, blame MoE, blame quant, rerun the same dashboard.

The fix was not a new model. It was reading the engine table that became §A and noticing the indexer column `[LAB: RESULTS-MATRIX §A]`. Once the indexer lived on the GPU, warm decode jumped into the mid-20s and the range tightened enough to plan capacity. Prefill roughly doubled. The "model personality" narrative collapsed into a bus narrative.

If you take only one operational memory from chapter 1, take that sequence: surprising tok/s → placement hypothesis → measured recipe change → range re-check. Everything else in this book is a specialization of that loop.

## Teaching bandwidth to a mixed audience

Engineers who write CUDA and engineers who write product prompts need different doors into the same fact.

For systems people: show the §A table and the 12× swing.
For product people: show that a tool loop needing 20 model turns cannot tolerate 2 tok/s if humans are waiting on the loop.
For finance people: show that a placement bug multiplies cost without multiplying value.

Same physics. Three slides. No folklore.


## Operator lab: estimate before you bench

Before you run a new artifact, write a one-page estimate:

1. Artifact size on disk.
2. Expected residency (all GPU / split / heavy host).
3. Expected order-of-magnitude tok/s relative to a known row in §C.
4. Which chapter-1 failure class you will check first if wrong (CPU tax, spill commute, wrong speed metric).

Then bench. If reality is 2× off your estimate, you learned something about either the artifact or your mental model. Both are valuable. The point of estimates is not pride. It is to make surprises legible.

Compare any surprise to the §A swing: a 12× miss is placement until proven otherwise `[LAB: RESULTS-MATRIX §A]`. A 1.2× miss may be thermal, speculation, or context. Use the magnitude to choose the chapter.

## Glossary for chapter 1

- **Prefill** — prompt ingestion; builds initial KV.
- **Decode** — per-token generation after prefill.
- **Aggregate throughput** — total tokens/second across concurrent streams.
- **Spill** — layers or experts living off the fast device path.
- **Residence** — weights kept on the device path you intended.
- **Recipe** — the full flag+binary+artifact bundle that produced a number.

Use these words in tickets. Tickets that say only "slow" waste everyone's cache.


## What you should do Monday

1. Pin your engine build identity in the unit file and in every speed ticket.
2. Split your dashboards into prefill, single-stream decode, and aggregate-under-c.
3. Take one production model and write its bytes story: resident vs spilled, host vs GPU.
4. Re-read the last "model is slow" ticket and mark whether a bus was investigated.
5. Save one warm decode range (three runs) for the current production recipe as baseline.

If Monday ends without a baseline range, Tuesday's incident will invent one under pressure. The §A lesson is that baselines belong to recipes, not to model names `[LAB: RESULTS-MATRIX §A]`.


## Cross-links inside this book

When decode is cratered, go to chapter 6 before chapter 2. When decode is merely mediocre under concurrency, re-read the aggregate section here and then chapter 3's concurrency note. When someone answers a bandwidth problem with a new quant label, send them to chapter 2's sideways-requant stop sign and chapter 8's fit worksheet. When the graph looks good and the users do not, chapter 5's speed template probably asked a different question than production traffic.


## A closing arithmetic habit

When a vendor or a teammate quotes a single tok/s number, force it into a sentence:

> On hardware H, engine E, artifact A, flags F, context K, concurrency C, warm/cold W, the decode range was R across N runs.

If they cannot speak the sentence, they do not have a measurement. They have a mood. This book is a training manual for refusing moods with tables. The reference box rows are examples of sentences that can be audited `[LAB: RESULTS-MATRIX §A/§B/§C]`. Your job is to make your own fleet speak in the same grammar.


## Who this chapter is for

If you have ever stared at a tok/s graph and argued about models when you should have argued about buses, this chapter is the reset. If you are new to local serving, it is the map. If you are experienced, it is a checklist you can hand to the next hire so they do not repeat the 2 tok/s archaeology. The later chapters assume you accept the receipt model of speed: named machine, named recipe, named speed kind, named range. Reject that, and the rest of the book will look like taste. Accept it, and the lab tables become tools instead of trivia `[LAB: RESULTS-MATRIX §A/§C]`.

## Looking ahead

Chapter 2 stays on the same box and asks why expert precision moved quality when total
bits said it should not. Chapter 3 turns the MTP table into economics. Chapter 4 puts
the KV cache on the balance sheet as a second model. Chapter 5 attacks benchmark noise
directly — including the ±10 point tool-suite swing at temperature 0 that already
haunts the §C footnote `[LAB: RESULTS-MATRIX §C footnote]`. Chapter 6 teaches the load
log. Chapter 7 puts heat and power loss into the same accounting. Chapter 8 answers
what fits on a 128 GB class box, and what does not, without insulting smaller machines
by pretending they are broken 128 GB boxes.

The rest of the book is downstream of one sentence:

**A token costs bytes moved, under a recipe, on a named machine.**

Everything else is engineering on top of that receipt.


# Chapter 2 — Quantization without Folklore

*(v2, 2026-08-28 — written by rogerai-dj for RogerAI Labs, verified by Roger AI.
Numbers carrying a `[LAB:]` marker are RogerAI Labs' own bench measurements, taken on the
reference machine described in Chapter 1 and recorded in the lab notebook; each is
reproducible by re-running the stated recipe — engine build, artifact, and flags. Claims
without a marker are labeled unmeasured.)*

## The story everyone already knows

Quantization is supposed to be simple. Store the weights with fewer bits. The file
shrinks. The model fits. Maybe you lose a little quality. Maybe you do not notice.

That story is not entirely wrong. It is the right story for a first afternoon with a
dense 7B. It becomes folklore the moment you treat "Q4" as a moral category — as if
the label on the file were the same thing as the precision that actually mattered
inside the network.

This chapter is the lab's refusal of that folklore. On a mixture-of-experts model big
enough to hurt, **which tensors kept their precision** moved quality more than **how
small the file looked**. A community Q4 that was larger on disk lost to a master build
that preserved expert precision and used speculative decoding to pay the spill back.
A sideways requant into a friendlier-looking Q4 was aborted when the conversion log
showed the experts growing while quality had nowhere to go but down.

If chapter 1 said a token costs bytes moved, chapter 2 says: not all bytes are equal,
and the spreadsheet column titled "quant" is not a substitute for knowing which bytes
you kept.

## What quantization is, without romance

A trained weight is a number. Numbers can be stored at different precisions. Full
training might live in high precision. Inference often ships lower: 8-bit, 4-bit,
exotic typed formats, mixtures across layers.

Two bills arrive when you lower precision:

1. **A memory bill, usually smaller.** Fewer bits per weight means a smaller file and,
   if the weights stay resident, fewer bytes to stream per step.
2. **A quality bill, sometimes sharp.** Some parts of a network tolerate coarse
   quantization. Some do not. The damage is not evenly distributed just because the
   average bit-width looks neat.

Folklore collapses those bills into one sentence: "Q4 is fine." Engineering keeps them
separate: which tensors, which method, which calibration, which eval, which hardware
recipe.

This book will not teach every quant method. It will teach the reading habit that
survived contact with one hard MoE stack on one reference box.

## The reference comparison that broke the slogan

Hold the machine fixed (chapter 1's box). Look at DeepSeek-V4-Flash builds from the
capability table `[LAB: RESULTS-MATRIX §C]`:

| Build | Size | MMLU | Tool hardmode | Warm tok/s |
|---|---|---|---|---|
| UD-IQ3_XXS (old prod) | 102 GB | 79.6 | 47 | ~26 |
| community Q4_K_M-XL (teamblobfish) | 175 GB | 85.0 | 60 | 16.5 |
| Q3_K_M-MTP (lab, morning prod) | 143 GB | 84.0 | 40–50 | **30.5** @ MTP n=1 |
| **Q8-MTP master (lab, new prod)** | **160 GB** | **88.3** | mean **55** (43–73) | 26–27 @ MTP n=1 |

Read it slowly.

The community Q4 is the folklore champion on paper: "Q4," widely shared, 85.0 MMLU,
60 tool hardmode. It is also **175 GB**, slower on decode (16.5 tok/s), and not the
end of the story.

The lab master keeps experts at their **original release precision** (native MXFP4
passed through untouched in the conversion). By *passed through untouched* this book means
a specific, checkable thing: the expert weight tensors ship in the model's original MXFP4
block-float encoding, copied verbatim into the GGUF during conversion rather than
re-encoded onto a different quant grid. Only the surrounding tissue (router, attention,
norms, the MTP head's metadata) is handled by the converter; the experts' bytes are the
release bytes. It is **160 GB**, scores **88.3 MMLU**, posts the best tool-scenario floor
in the DeepSeek series on that harness, and still lands at **26–27 tok/s** once MTP
n_max=1 is on.

So the smaller-looking "more quantized" community artifact did not win. The build that
refused to mistreat the experts won on quality and, with speculation, tied old
production on speed.

That is not a vibe. It is a row.

## Expert precision is the MoE lever

Mixture-of-experts models do not spend all parameters on every token. They route each
token to a subset of experts. The router and the expert bodies are different kinds of
tissue. Smashing both with the same blunt quant policy is convenient for packaging and
often wrong for behavior.

The lab's tool-gap attribution series on DeepSeek hardmode made the lever visible
`[LAB: RESULTS-MATRIX §D]`:

| Intervention | Hardmode | Verdict |
|---|---|---|
| baseline IQ3 (generic parser) | 47 | baseline |
| chat-template patch → native parser | 43 | parser was **not** the bottleneck |
| **Q4 experts instead of IQ2_S** | **60** | **quant was most of the gap (+13)** |
| residual vs gpt-oss 73 | — | remaining ~13 looks like model gap |

Changing the parser did not fix tool use. Restoring expert precision did most of the
repair. The matrix's own ladder on tools reads: 2-bit ≈ Q3_K (~46) < Q4_K (60) ≈
native MXFP4 (~55, better scenario floor) `[LAB: RESULTS-MATRIX §C notes]`.

MMLU, meanwhile, recovered earlier than tools. Q3_K experts already sat near Q4 on
MMLU (84.0 vs 85.0) while tool use stayed in the IQ3 band (~40–50) until experts were
right. **Knowledge and tool-following did not share a single bit-width story.**

One honest limitation belongs on this ladder. Each rung changes **more than one thing at
once**: IQ2_S, Q3_K, Q4_K, and native-MXFP4 experts differ in *bit-width* and in *quant
method/recipe* (grid, block structure, calibration) simultaneously, and the runs were not
pinned to a single converter tool-and-version with a published tensor list. So the ladder
supports the directional claim it is used for — *expert precision, not the parser, moved
tool-use here* — and it does **not** cleanly separate "two more bits" from "a better
encoding method." The cross-check that keeps it honest is that the parser control (43 vs
47) falsified the competing explanation, and that MMLU and tools moved on different
schedules, which a pure tool-and-version artifact would not produce. Read the +13 as
"precision policy dominated," not as a calibrated coefficient on bit-width alone.

If you only watch a general knowledge sample, you can promote a quant that still
butchers the behavior your product actually needs. If you only watch a glossy file
size, you can reject a master that is both better and, under a sane recipe, fast
enough.

## Sideways requants: the conversion log as a stop sign

Folklore loves a sideways move: take a master, emit a Q4, ship the friendly label.
The lab tried the spirit of that move and aborted it for a boring, decisive reason.

On the record, a Q4_K_M requant attempt was stopped mid-run when the log showed
MXFP4→Q4_K conversion **growing expert tensors while adding requant loss**. The matrix
states the rule in operator English: requantizing below the master only makes sense to
**shrink** (Q3), never **sideways** (Q4) `[LAB: RESULTS-MATRIX headline before/after]`.

That sentence should be on a sticky note above every conversion job:

> If the conversion does not buy residence or bandwidth headroom, it is not a
> quant — it is vandalism with a progress bar.

Sideways requants are attractive because they match community naming. They are
dangerous because they can add loss without buying fit. The stop condition is in the
log, not in the marketing name of the output file.

## IQ3, Q3, Q4, Q8: labels are not a ladder of virtue

The same matrix teaches a second anti-folklore lesson: the alphabetical soup is not a
moral ladder.

- IQ3 old production: 102 GB, weakest MMLU of the DeepSeek set shown (79.6), fine as a
  historical baseline, not as an aspirational end state.
- Q3-MTP: 143 GB, MMLU 84.0, tools still noisy in the 40–50 band, but decode **30.5**
  tok/s with MTP n=1 — a speed/quality compromise that was real morning production.
- community Q4: 175 GB, strong headline tools (60), slower decode, not master quality.
- Q8 master: 160 GB, best MMLU, best DeepSeek tool floor on the harness, old-prod speed
  with MTP.

Notice that "higher Q number" did not monotonically mean "better" or "slower" or
"larger." The community Q4 is larger than the Q8 master and slower than the Q3-MTP
build. The only safe reading is per-row: size, quality suite, decode, recipe.

If your team sorts artifacts by the substring `Q4` versus `Q8` as if that were a total
order, you are sorting labels, not systems.

## Noise: the ±10 point tax before you brag

Before anyone turns a single hardmode number into a brand, read the footnote the matrix
carries like a scar `[LAB: RESULTS-MATRIX §C footnote]`.

Q3-MTP hardmode was measured three times on 07-13: 40, 47, and 50 (MTP off control).
Five of fifteen scenarios flipped between identical back-to-back runs. The harness sends
temperature 0.0. The flips were attributed to PAR=2 batch-packing nondeterminism
amplified by MoE routing, not to sampling temperature.

**Treat single-run hardmode numbers as ±10** — on *this* suite, model, and PAR=2 shape;
Chapter 5 scopes why that magnitude does not automatically transfer to other suites or
architectures. Conclusions that survived that noise:

1. Q3_K experts land near IQ3-level tool use, not near Q4's 60.
2. MTP speculation did not measurably harm tool use (MTP-off control within noise).
3. Some scenarios were consistent wins or losses across runs; the mean hides them if you
   only quote the mean.

Q8-MTP master's three runs (73 / 50 / 43, mean 55) likewise hide scenario-consistent
structure: TC-71 passed 3/3 after failing all five prior DeepSeek runs; TC-78 3/3;
TC-70 3/3.

Chapter 5 is the methodology chapter. Chapter 2 only needs the quant-facing moral:

> Do not promote a quant on a one-shot tool score. Demand a range, a control, and a
> scenario story.

## Dense models still quantize — they just fail differently

Not every row in §C is MoE. Qwen3.6-27B dense Q8_0 sits at 29 GB, 79.0 MMLU, 67 tool
hardmode, ~27 tok/s. Qwen3.6-35B-A3B Q8_K_XL sits at 38 GB, 71.0 MMLU, **87** tool
hardmode. gpt-oss-120b MXFP4 under vLLM TP=4 posts 71.0 MMLU, 73 tools, 60 tok/s
wall-clock `[LAB: RESULTS-MATRIX §C]`.

These rows exist here to prevent a false universal:

- **Dense Q8 can be "boring good"** — small enough to place, strong enough to use, not
  the subject of the expert-precision drama.
- **Tool rank and MMLU rank disagree across families.** The 35B-A3B line wins tools on
  this harness while losing MMLU to DeepSeek masters. Ranking quants by a single suite
  will reshuffle your heroes.
- **Engine identity is part of the quant story.** gpt-oss numbers above are vLLM TP=4,
  not llama.cpp. A quant comparison that silently changes engines is not a quant
  comparison.

If your deployment is a dense 7B–30B, you may never meet the MoE expert lever. You
still meet bytes, residence, and eval noise. Do not import MoE folklore into dense
stacks, or dense folklore into MoE stacks.

## Fit is a quant feature

Quantization that does not load is not a quant; it is a brick.

Section F of the matrix is the fit companion to §C `[LAB: RESULTS-MATRIX §F]`:

| Model | Working recipe | Failed configs |
|---|---|---|
| IQ3_XXS 102 GB | n-cpu-moe 4, ts 31,25,24,20 | — |
| blobfish Q4 175 GB | n-cpu-moe 24, ts 25,6,6,6, **--no-repack**, mmap, lean RAM | n-cpu-moe 14 VRAM-OOM; ≥18 without --no-repack segfault; --no-mmap host-OOM (>125 GB RAM) |
| Q8-MTP 160 GB | n-cpu-moe 14, ts 20,8,8,8 (+ --no-repack, mmap) | ts 21,8,8,7 → compute-buffer OOM card0 |
| Q3-MTP 143 GB | n-cpu-moe 10… / prod n-cpu-moe 11, ts 18,9,9,8, PAR 2 | — |

The community-shaped 175 GB Q4 does not merely "run slower." It runs only inside a
narrow recipe. Miss `--no-repack` and you can segfault. Miss mmap and you can host-OOM
beyond 125 GB RAM. Choose the wrong n-cpu-moe and you VRAM-OOM.

A quant card that omits the recipe is incomplete. A blog screenshot of file size is not
a recipe.

Chapter 8 returns to fit as a first-class problem. Chapter 2 needs only this coupling:
**precision choices change both quality and the placement surface.** The master that
preserved experts was not only a quality win; it was a different spill and flag story
than the 175 GB Q4.

## Promotion is a multi-objective decision

The lab did not promote the master because MMLU is sacred. The recorded rationale is
explicit: **tool quality over the last 4 tok/s** `[LAB: RESULTS-MATRIX headline
before/after]`. MTP n_max=1 recovered old-production speed. The master dominated the
community Q4 on the axes they cared about (+3.3 MMLU, comparable tools with a better
floor, +60% speed versus that Q4's 16.5, −15 GB).

That is what non-folklore promotion looks like:

1. Name the product-critical suite (here: tools, not only MMLU).
2. Measure a range, not a hero run.
3. Measure decode on the target engine recipe.
4. Measure fit and flags.
5. Accept an explicit trade (quality > last few tok/s) and write it down.

If your promotion story is "the Q4 is popular," you are doing release engineering by
folklore.

## What quantization cannot buy you

Plain boundaries:

- Quantization cannot fix a wrong engine placement. Chapter 1's 2 tok/s crater was not
  a quant problem.
- Quantization cannot invent eval honesty. ±10 points of harness noise remains ±10
  after you quant.
- Quantization cannot make a task the model cannot do into a task it can. Chapter 5
  and the manufacturing book's abstention work are about refusal and coverage; bits
  will not substitute.
- Quantization cannot repeal architecture. MoE routing pathologies and dense attention
  costs remain themselves at every bit-width.

If a pitch says "we Q4'd it, so it should be fine," ask: fine on which suite, which
range, which machine, which flags?

## Practical checklist for a quant decision

1. **Write the active tensors you care about.** For MoE, experts and router at minimum.
2. **Pick the suite that matches the product.** MMLU alone is not a tool product.
3. **Run at least three times** when the harness has known nondeterminism. Keep the
   range.
4. **Record decode and fit on the target box**, including failed flags.
5. **Reject sideways requants** that add loss without buying residence.
6. **Prefer masters that preserve fragile tissue**, then buy speed with speculation or
   placement — not with hopeful bit-chopping.
7. **Document the trade** you accepted (quality vs tok/s vs VRAM).



## A quant review board agenda

When someone proposes a new GGUF:

1. What product suite does it need to hold?
2. What is the range across ≥3 runs?
3. What is decode on the target engine?
4. What is the fit recipe and failed recipes?
5. What tissue changed precision (experts, attn, KV)?
6. Is this a shrink, a sideways move, or a master preserve?
7. Who owns the tombstone if it fails in a week?

If the proposer cannot answer 5 and 6, stop. That is how folklore enters — as an unnamed tissue change.

## Documenting expert policy

For MoE artifacts, keep a one-liner in the manifest of the service:

`EXPERT_PRECISION=native-MXFP4 preserved; router=...; attn=...`

The §D result that Q4 experts recovered tools is the reason this line exists `[LAB: RESULTS-MATRIX §D]`. If you cannot say what happened to experts, you do not know what you shipped.


## Field story: the sideways requant that did not ship

The aborted MXFP4→Q4_K attempt is easy to under-teach because it never became a hero row. That is why it matters. Most bad quants do not fail the demo. They fail the conversion log while still producing a file someone could have published `[LAB: RESULTS-MATRIX headline before/after]`.

A culture that only celebrates successful GGUFs will keep shipping sideways losses. A culture that files aborted conversions with reasons will not.

Add aborted experiments to the tombstone file with:

- source artifact
- tool and flags
- log line that triggered the stop
- who stopped it
- date

The master that did ship is partly protected by the requant that did not.

## What to say when someone asks for "just Q4"

Answer with questions:

1. Q4 of which tensors?
2. Compared to which master?
3. On which suite range?
4. On which machine recipe?
5. Does the conversion shrink bytes that were actually the bottleneck?

If they cannot answer, your job is to refuse the label until it becomes a recipe.


## Operator lab: read a GGUF like a bill of materials

When a new file arrives, do not only look at the filename's Q-tag. Inspect:

- total size
- whether experts are native precision or requantized
- attention/KV related tensors if exposed
- converter tool and version
- any log from the conversion job

The master versus community Q4 story is a bill-of-materials story: native experts versus a different tissue policy, different size, different speed, different suite range `[LAB: RESULTS-MATRIX §C/§D]`. Filenames compress that into a token like "Q4" that cannot carry the truth.

If your organization accepts GGUFs from chat links without conversion logs, you are consuming unmarked food.

## Suite pairing for quants

Always pair:

- one general suite (MMLU-class or your domain knowledge)
- one product behavior suite (tools, JSON schema, abstention)

§C shows why: ranks disagree across families and across quants `[LAB: RESULTS-MATRIX §C]`. A quant that only wins the suite you do not sell is a trophy, not a product.


## What you should do Monday

1. For every MoE artifact you serve, write one line on expert precision policy.
2. Refuse a new GGUF that arrives without conversion notes.
3. Pair your trophy suite with a product suite before any promote meeting.
4. Add aborted conversions to the tombstone file on purpose.
5. Re-check whether any "Q4 default" in your docs is actually a sideways requant.

The master versus community Q4 row is your teaching aid when someone argues labels over tissue `[LAB: RESULTS-MATRIX §C/§D]`.


## Cross-links inside this book

Quant changes that "should be faster" but are not are often chapter 1 placement or chapter 6 mmap/repack stories. Quant changes that are faster but flaky under tools are chapter 5 range problems. Quant changes that only load on sacred flags are chapter 8 fit problems. Speculative decoding can pay back a quality-preserving master's latency — that bridge is chapter 3, and it is not optional if you want the promotion ledger to close.


## Last word

Labels are not tissue. Preserve what hurts to lose; shrink what buys residence; never requant sideways out of peer pressure.

## Looking ahead

Chapter 3 takes the MTP rows seriously as economics: draft length, spill, acceptance,
and when speculation loses. Chapter 4 adds the KV cache as a second precision surface
people forget to budget. Chapter 5 formalizes the noise and controls already haunting
this chapter's footnotes. Chapter 6 shows how a "quant is slow" report often turns into
a load-log placement report under daylight.

The folklore version of quantization is a label. The engineering version is a claim
about **which numbers survived, on which tensors, under which recipe, on which
machine**, with a range attached.

Ship the second one.


# Chapter 3 — Speculative Decoding Economics

*(v2, 2026-08-28 — written by rogerai-dj for RogerAI Labs, verified by Roger AI.
Numbers carrying a `[LAB:]` marker are RogerAI Labs' own bench measurements, taken on the
reference machine described in Chapter 1 and recorded in the lab notebook; each is
reproducible by re-running the stated recipe — engine build, artifact, and flags. Claims
without a marker are labeled unmeasured.)*

## The slogan

Speculative decoding says: let a cheap draft propose several tokens, let the strong
model verify them in a batch, keep the prefix that matches. If the draft is good, you
bought multiple tokens per expensive step. If the draft is bad, you paid overhead for
rejects.

As a slogan, it is almost always sold as a free speedup. As an accounting problem, it
is a bet on **accepted tokens per heavy read**, minus the cost of drafting and verifying
under your real spill and batch constraints.

This chapter is the bet, priced on the reference box.

## The only equation that matters

Let:
- \(H\) be the cost of one heavy (target) step without speculation
- \(D\) be the cost of drafting a candidate span
- \(V(n)\) be the cost of verifying \(n\) draft tokens in a batch
- \(a\) be the number of draft tokens actually accepted on average

A speculative step is a win when:

**\((D + V(n)) / a < H\)**

Everything else is commentary.

People lose money on speculation three ways:

1. **\(a\) collapses** — draft quality is poor, so you accept ~1 token after paying \(D+V\).
2. **\(V(n)\) explodes** — verification is not a cheap batch on your hardware recipe;
   it rereads spilled experts \(n\) ways.
3. **\(D\) is not actually cheap** — the draft model or draft head is large, cold, or
   contending for the same bus.

You do not need Greek letters in production. You need to notice which term broke.

## What the lab implemented

On the DeepSeek V4 line, the lab ran multi-token prediction (MTP) heads — draft tokens
from a head trained for that job — through llama.cpp on the reference box. The matrix
labels the DeepSeek rows as the lab's MTP implementation and includes a dense Qwen
stock-MTP row as a near-zero-spill contrast `[LAB: RESULTS-MATRIX §E]`.

This chapter does not claim a survey of every speculative system (Medusa, EAGLE,
independent draft models, etc.). It claims a measured economic pattern: **speedup
tracks spill and acceptance, not enthusiasm.**

## The §E table, in full

| Model / spill | Baseline | n_max=1 | n_max=2 | n_max=3 |
|---|---|---|---|---|
| Qwen3.6-27B Q8 (zero spill, stock MTP) | 27.0 | — | — | **59.3 (2.2×)** |
| DeepSeek Q8-MTP · 24 layers spilled | 19.3 | — | — | 16.6 (0.86×) @ 82% |
| DeepSeek Q8-MTP · 14 layers spilled | 22.2 | **26.3 (1.18×) @ 100%** | 21.6 @ 89% | 18.8 @ 78% |
| DeepSeek Q3-MTP · 10 layers spilled | 23.5 | **30.5 (1.30×) @ 100%** | 24.8 @ 93% | — |

`[LAB: RESULTS-MATRIX §E]`

The matrix's own law:

> Speedup grows as spill shrinks (1.18× → 1.30× → 2.2×); on spill-bound MoE,
> batch-verify costs ~N× DDR5 expert reads → n_max=1 is the sweet spot; first-token
> drafts accept at 100% (the head's training objective).

Memorize the shape, not just the hero cell — and read the last clause as an
**observation with an interpretation attached, not a proven law**. "Accept at 100%" here
means the first drafted token (position 0) was verified and kept on every step of these
two runs; the acceptance denominator is first-token draft proposals. That 100% is
measured on exactly **two** DeepSeek MTP cells (Q8 at 14-spill, Q3 at 10-spill) at
n_max=1, on one engine build and one box. The clause "(the head's training objective)" is
the lab's *explanation* for why first-token acceptance is so high — it is not isolated by
a control that would rule out alternatives (an independent-draft head, the same MTP head
disabled and re-drafted, or a different context length were not run against these exact
cells). Treat "trained heads make cheap, near-certain first guesses" as a well-supported
working hypothesis on this stack, and re-measure acceptance on yours before quoting 100%.

## Zero spill is a different planet

The dense Qwen row is the optimistic planet: **2.2×** at n_max=3, baseline 27.0 → 59.3,
with zero spill. Verification can batch without shipping expert bodies across host
memory for each candidate. The draft length can open up.

If your mental model of speculation was formed on dense, resident models, you will
over-promise on MoE-with-spill. The Qwen row is real. It is also not a license to quote
2.2× on a DeepSeek recipe that spills fourteen layers.

## Spill turns verification into a bill

Watch the DeepSeek Q8-MTP 14-spill row as draft length grows:

- n_max=1: **1.18×** at **100%** acceptance
- n_max=2: 0.97×-ish territory (21.6 from 22.2) at 89% acceptance
- n_max=3: 18.8 at 78% acceptance — slower than baseline

The draft is not "getting stupid" in a narrative sense alone. Acceptance falls, and
verification cost rises with \(n\) while each verify still risks DDR5 expert traffic.
The matrix is blunt: batch-verify costs scale with N times those reads.

Now the 24-spill row at n_max=3: **0.86×** at 82% acceptance. Speculation loses
outright. You paid to go slower.

This is chapter 1's bandwidth thesis wearing an MTP hat. If verification multiplies
expensive host reads, longer drafts are not brave — they are leveraged debt.

## Why n_max=1 won on the MoE recipes

On both DeepSeek MTP rows that show n_max=1, first-token acceptance is **100%**, and
that cell is the local optimum:

- Q8-MTP 14 spill: 1.18× @ 100%
- Q3-MTP 10 spill: 1.30× @ 100%

The matrix attributes 100% first-token acceptance to the head's training objective.
Practically, n_max=1 means: take the head's best single guess, verify it cheaply
relative to a long draft, keep the win rate high, do not open a large batch-verify
surface against spilled experts.

Longer drafts are not forbidden forever. They become rational when spill shrinks (more
resident experts, different placement) or when the architecture is dense and resident
like the Qwen row. The economic mistake is copying n_max=3 from a blog about a dense
model onto a spilled MoE and calling the slowdown "weird."

## Acceptance rate is a first-class metric

Tok/s without acceptance is how folklore hides losses.

A run can show busy GPUs, high internal throughput, and still lose end-to-end if rejects
dominate. The §E cells pair speedup with acceptance percentages for a reason. On the
14-spill Q8 line, acceptance slides 100% → 89% → 78% as n_max climbs, and speedup slides
with it into a loss.

Instrument acceptance beside tok/s:

- mean accepted length
- per-position accept rate if you have it
- reject cost (time spent on discarded drafts)

If you only watch tok/s, a bad draft policy can look "busy-fast" while users wait
longer.

## Speculation and quality: the tool-suite control

Speed features that quietly wreck behavior are not speed features. The lab checked MTP
against tool hardmode on Q3-MTP: three runs at MTP n=1 (40, 47) and an MTP-off control
(50). Within the suite's ±10 noise, MTP did not measurably harm tool use `[LAB:
RESULTS-MATRIX §C footnote]`.

That is not a universal safety certificate for all speculative methods. It is a
recorded control on this implementation and harness. When you adopt any draft scheme,
keep a product-critical suite on a leash. Speculation that buys 1.2× and loses your
tool contracts is a bad trade even if the latency dashboard celebrates.

## Coupling to the production promotion

Chapter 2's promotion story depends on this chapter's economics. The Q8 master kept
native expert precision (quality) and used MTP n_max=1 to land at 26–27 tok/s — old
production speed — despite a larger resident footprint and fourteen layers of spill in
the related MTP rows `[LAB: RESULTS-MATRIX headline before/after + §E]`.

Without speculation, the quality-preserving master might have been "too slow" under a
naive decode comparison. With speculation priced correctly (n_max=1, not n_max=3),
quality and latency could cohabit.

That is the industrial pattern: **buy quality in the weights; buy back latency with a
speculation recipe that respects spill; do not buy latency by vandalizing experts.**

## Failure modes checklist

1. **Blog-default draft length.** n_max=3 copied from dense zero-spill onto spilled MoE.
2. **Unmeasured acceptance.** Tok/s reported alone.
3. **Verification across host spill.** Batch-verify multiplies DDR traffic.
4. **Draft contention.** Draft and target fight for the same scarce bandwidth.
5. **Silent quality drift.** No tool/product suite paired with the speed claim.
6. **Cold vs warm confusion.** Speculation numbers measured only in a warm steady state
   that production never sees (unmeasured here as a general warning; pin your own).

## How to price a speculation change on your box

A minimal recipe:

1. Fix model, engine build, placement flags, and context length.
2. Measure baseline single-stream decode (range of ≥3 runs if noisy).
3. Enable speculation at n_max=1; measure tok/s and acceptance.
4. Step n_max upward only while acceptance stays high and tok/s rises.
5. Stop at the first step that loses end-to-end speed or breaks the product suite.
6. Record spill / residency (how much of the model is off-GPU) beside the winning cell.

If step 4 never leaves n_max=1, that is a result, not a failure of nerve.

## What this chapter refuses to claim

- We do not claim MTP is the only speculative method worth using.
- We do not claim 2.2× is available on MoE with heavy spill.
- We do not claim 100% first-token acceptance generalizes beyond the recorded head and
  setup.
- We do not claim speculation replaces the need for fit recipes (chapter 8) or load-log
  literacy (chapter 6).
- We have not published a full cost model in microseconds for \(D\) and \(V(n)\) on every
  row; the table is the evidence, the inequality is the frame.



## Worked reading: three cells, three decisions

Take the Qwen zero-spill 2.2× cell first. Decision: open draft length. Reason: verification
is not paying host expert traffic, acceptance stays useful enough to clear a double, and
the baseline is already a clean dense decode. Copying this cell into a spilled MoE runbook
is a category error.

Take the DeepSeek Q3-MTP 1.30× @ n_max=1 cell second. Decision: keep drafts short, keep
the head's first token, bank a solid single-stream gain, promote only if tool controls stay
inside noise. This is the cell that made a quality-preserving production story possible at
old latency.

Take the DeepSeek Q8-MTP 24-spill 0.86× cell third. Decision: stop. Reason: acceptance is
not terrible (82%), but the bandwidth math still loses. The correct response is not "train
a braver draft." It is "reduce spill or shorten drafts until the inequality flips."

If your postmortem after a slow rollout starts with sampler tweaks instead of spill and
n_max, you are debugging the wrong layer.

## Interaction with concurrency

Chapter 1 separated single-stream decode from aggregate throughput. Speculation complicates
both.

A single stream may show a clean 1.2–1.3× while multi-slot serving changes batch-verify
economics, cache pressure, and scheduler behavior. The concurrency table in §B was measured
on the promoted engine path without turning this chapter into a full factorial, and the
matrix still records an unresolved c=2/c=3 dip on PAR=4 `[LAB: RESULTS-MATRIX §B]`. That
dip is a reminder: scheduler seams exist even before MTP.

Practical rule: **re-measure speculation at the concurrency you will actually serve**, not
only at c=1 on a quiet box. If you only ever bench solitary warm decode, you will ship a
lab speedup and a production shrug.

## Prefill versus decode under speculation

Speculation is usually a decode-path bet. Prefill still builds the KV cache and still
dominates short-prompt / long-generation handoffs differently than long-prompt / short-
generation jobs. The §A prefill note (about 130 tok/s GPU indexer vs 50–80 CPU indexer on
the IQ3 builds) remains the prefill story `[LAB: RESULTS-MATRIX §A]`.

Do not advertise an MTP decode multiplier as an end-to-end latency multiplier for
prompt-heavy workloads without measuring time-to-first-token and time-to-last-token
separately. Operators who crush those into one "tok/s" will mis-price queues.

## A short field worksheet

When someone proposes enabling or widening speculation, fill this before merging flags:

1. Model identity and precision recipe (master? Q3? community Q4?).
2. Spill / residency summary (what is on GPU vs host).
3. Baseline decode range at target context.
4. n_max tried; acceptance at each step.
5. Product-suite delta (tools or equivalent) on/off.
6. Concurrency target and re-bench at that c.
7. Decision: keep, widen, narrow, or disable — with the inequality term that dominated.

If the worksheet cannot be filled, the change is not priced. Unpriced speculation is how
free-speedup folklore re-enters through a side door.



## Accounting worksheet you can copy

When a teammate says "just turn on MTP," make them fill this table before the flag ships:

| Field | Baseline | Candidate | Notes |
|---|---|---|---|
| engine build |  |  | pin SHA |
| model artifact |  |  | path + checksum |
| spill / n-cpu-moe |  |  | from load log |
| n_max | off |  | |
| mean accept length | n/a |  | |
| warm decode tok/s (3 runs) |  |  | |
| tool suite runs |  |  | |
| production concurrency |  |  | re-bench mandatory |
| decision |  | keep/reject | owner name |

If the candidate column cannot beat baseline on the product's real concurrency without wrecking the suite range, the feature is not a feature. It is a lab toy. The §E rows that fall below 1.0× exist to give you permission to reject `[LAB: RESULTS-MATRIX §E]`.

## Draft quality is a systems property

People say "the draft model is weak" when acceptance is low. Sometimes that is true. Often the draft is fine and the system is feeding it a bad deal: too much spill, too much batch verify, too little residency, thermal throttle mid-span, or a context length that changes the head's calibration.

Before you train a new draft head, check whether n_max=1 already clears a win. On the DeepSeek MTP rows, it did, with 100% first-token acceptance `[LAB: RESULTS-MATRIX §E]`. Training is expensive. Flag economics are cheap.

## Speculation and the promotion ledger

Write speculation into the same promotion ledger as quant:

- quality delta (suite ranges)
- speed delta (decode ranges)
- fit delta (headroom, failed flags)
- operational delta (new failure modes)

The Q8 master promotion is the template: quality first, MTP pays latency back, decode lands near old prod `[LAB: RESULTS-MATRIX headline before/after]`. If your ledger only has a green latency arrow, you will ship a faster wrong system.

## Teaching the inequality without math trauma

For operators who bounce off formulas, use the one-sentence form:

> Did each expensive read buy more accepted tokens than it cost in draft+verify traffic?

Walk the §E 14-spill row out loud: at n_max=1, yes; at n_max=3, no. The machine already did the arithmetic. Your job is to believe it.


## Field story: n_max=3 as peer pressure

In many chats, longer drafts sound stronger. The §E 14-spill row is the antidote: acceptance fell and end-to-end speed fell as n_max rose, into a loss at n_max=3 `[LAB: RESULTS-MATRIX §E]`. The peer-pressure move is to keep widening drafts until the graph looks aggressive. The operator move is to stop at the maximum of the inequality.

Put the losing cell in the runbook on purpose. Teams need permission to ship n_max=1 without feeling under-ambitious.

## Speculation under product load shapes

- **Short question, long answer chat:** decode-heavy; MTP can matter a lot.
- **Long prompt, short answer classification:** prefill-heavy; MTP may barely show up end-to-end.
- **Tool loops:** many short decodes; acceptance and tool-suite controls matter more than peak tok/s.

Bench the shape you sell, not the shape that flatters the feature.


## Operator lab: n_max sweep protocol

1. Fix recipe without MTP; capture 3 decode runs.  
2. Enable MTP n_max=1; capture decode + acceptance + tool suite.  
3. If win, try n_max=2; stop if end-to-end falls or acceptance falls hard.  
4. Never jump to n_max=3 on spilled MoE because a dense blog did.  
5. Re-run winner at production concurrency.  
6. Commit the winning n_max into the recipe file.

This is just §E turned into a checklist `[LAB: RESULTS-MATRIX §E]`.


## What you should do Monday

1. If MTP/spec is on, record n_max and mean acceptance beside tok/s.
2. Run the n_max sweep protocol on a staging host once, even if production "seems fine."
3. Re-bench the winner at production concurrency, not only c=1.
4. Put the losing §E-style cell (speedup less than 1) in the runbook as permission to stop.
5. Tie any speculation change to a product-suite control run.

Speculation that is not priced will still move your latency graph. Pricing it is the job `[LAB: RESULTS-MATRIX §E]`.


## Cross-links inside this book

If acceptance is high and speed still falls, suspect spill and verification traffic (chapter 1) or heat (chapter 7). If acceptance is low, do not start with training a new draft until n_max=1 and residency are checked. If enabling MTP coincides with weird multi-turn outputs, chapter 4's cache-reuse and KV precision traps are in scope. If the speedup vanishes at production c, you benched the wrong speed kind in chapter 1's terms.

## Acceptance without speed is a museum piece

A beautiful accept rate attached to a losing end-to-end latency is not a win. Ship the inequality, not the trophy metric.

## Looking ahead

Chapter 4 budgets the KV cache — another working set speculation and long context both
stress. Chapter 5 handles the measurement noise already visible in the tool controls.
Chapter 6 shows how "speculation is slow" often starts as a placement graph. Chapter 7
asks what happens to these recipes when the box hits thermal or power limits.

Speculative decoding is not magic. It is a leveraged bet on acceptance under a bandwidth
budget. Price the bet. Keep the receipt.


# Chapter 4 — KV Cache, Context, and the Traps

*(v2, 2026-08-28 — written by rogerai-dj for RogerAI Labs, verified by Roger AI.
Numbers carrying a `[LAB:]` marker are RogerAI Labs' own bench measurements, taken on the
reference machine described in Chapter 1 and recorded in the lab notebook; each is
reproducible by re-running the stated recipe — engine build, artifact, and flags. Claims
without a marker are labeled unmeasured.)*

## The second model

People budget the weight file and forget the working set that grows with every token of
context: the **KV cache**.

Weights are the encyclopedia on the shelf. The KV cache is the desk where the model
keeps the conversation it is having *right now*. Desk space is not free. It scales with
layers, heads, head dimension, precision, batch, and sequence length. It can exceed the
weight footprint on long contexts. It can silently shrink when you raise concurrency. It
can corrupt outputs when precision or cache-reuse flags are wrong.

Chapter 1 said a token costs bytes moved. Chapter 4 says: some of those bytes are the
past you are re-reading every step. Treat the cache as a second model you are also
serving.

## What the cache is for

Autoregressive generation reuses attention keys and values from earlier tokens so the
model does not recompute the whole prompt on every step. That reuse is the KV cache.

Two operator facts follow:

1. **Prefill writes a lot of cache at once** (prompt evaluation).
2. **Decode appends a little cache per token** and reads a growing history.

If your latency pain is time-to-first-token on long prompts, you are often in prefill and
cache allocation. If your pain is tokens-per-second on long generations, you are often in
decode bandwidth against weights **and** against an ever-larger cache.

Confusing those pains produces the wrong fix: quantizing weights harder will not cure a
context budget you divided by `--parallel`, and buying another GPU will not cure a
cache-reuse corruption flag.

## Context is a budget, not a vibe

Engines expose a context ceiling (`n_ctx` and friends). That ceiling is RAM and VRAM
policy, not a personality trait of the model.

On the lab's production burn-in line, the promoted Q3-MTP recipe ran **PAR=2, 64K
ctx/slot** among other flags `[LAB: RESULTS-MATRIX §G]`. That is a deliberate allocation:
two slots, each with a large ceiling. It is also a reminder that context numbers in a
server log are **per-slot** after parallelism divides the pie.

The matrix records the trap in plain language during K3-Encode work `[LAB:
RESULTS-MATRIX H.4.2 / concurrency notes]`:

> `--parallel N` DIVIDES the context budget — `n_ctx_slot = CTX/N`. A first attempt at
> PAR=6 with CTX=8192 silently produced **1365 tokens per slot**, far too little for a
> model that spends 1200 tokens thinking. Size CTX as `PAR × per_slot_need`, and read
> `n_ctx_slot` in the startup log to confirm.

The arithmetic is worth doing out loud, because it is exactly the kind of number an
operator eyeballs and gets wrong: 8192 ÷ 6 = 1365 (1365.3, floored), not the round-looking
1536 a slightly larger CTX of 9216 would have produced. The trap is not that the division
is hard; it is that a plausible-looking per-slot number hides a closet.

That is one of the highest-value sentences in this book. Silent undersizing does not
error loudly. It thinks in a closet and then loops, truncates, or looks "dumb."

**Habit:** after every parallel or context flag change, read `n_ctx_slot` (or equivalent)
from the startup log before you trust a single quality sample.

## Parallelism confounds: do not compare unequal desks

When the lab first compared PAR=1 and PAR=4 behavior, unequal per-slot context
confounded the story. Re-running with matched `n_ctx_slot` fixed the science `[LAB:
RESULTS-MATRIX concurrency / control notes]`:

| Server | slots | n_ctx_slot | control-fact | control-code |
|---|---|---|---|---|
| PAR=1, CTX=16384 | 1 | 16384 | answered | answered |
| PAR=1, CTX=4096 | 1 | 4096 | answered | answered |
| PAR=4, CTX=16384 | 4 | 4096 | **loops** | loops at 4-in-flight |

The point is not that PAR=4 is cursed. The point is that a fair comparison holds the desk
size fixed. Earlier rows that mixed PAR=1 at 16384 with PAR=4 at 4096 per slot were
comparing different products.

Chapter 5 will call this a control. Chapter 4 calls it furniture: **if the desks differ,
the exam results are not about the student alone.**

## Precision: the cache has a bit-width too

Weights are quantized in public. Cache precision is often a quiet flag (`f16`, `q8_0`,
etc.) that still moves both memory and behavior.

Here is a lab observation, stated as one — not a universal law. On the **DeepSeek-V4-Flash
stack, on this box**, setting the KV cache to `q8_0` produced **degraded, garbled decode
output** (the generation lost coherence, not merely a point of quality), while the same
recipe with `f16` KV produced correct output. The apparatus is the reference machine and
engine build used throughout this book; the variable changed was KV type alone. The
conclusion is narrow and load-bearing: *for V4 on this stack, keep KV at f16.* It is **not**
a claim that `q8_0` KV is unsafe on every architecture — plenty of models serve quantized
KV correctly. The operational stance that survived is therefore conservative rather than
absolute: prefer a known-good KV precision for the architecture you are serving, verify it
before trusting a quantized-KV default, and treat "more quantized KV" as an experiment with
a product suite attached. An operator who reads this as "never quantize KV" would wrongly
avoid a configuration that is safe elsewhere; the correct reading is "prove it per stack."

You will also see recipes that pin f16 KV explicitly beside other carefully chosen flags
— for example a Kimi-K3 streaming bring-up line that lists `f16 KV` next to `--no-repack`,
mmap, and `--cache-reuse 0` `[LAB: RESULTS-MATRIX H bring-up flags]`. That is not
decoration. It is a stack of foot-guns with the safeties written in the on position.

If you change KV precision, change **one variable**, keep context and parallel fixed, and
run the same honesty suite you use for weight quants (chapter 2 and chapter 5).

## Cache reuse: speed feature, corruption feature

Prefix cache reuse can avoid re-prefilling shared prompt prefixes. It can also corrupt.

During K3-Encode work the lab recorded a hard requirement: **`--cache-reuse 0` is
mandatory (KDA prefix-cache corruption, PR #26185)** `[LAB: PROJECT-LOG K3-Encode /
cache-reuse notes]`. Name the mode so it is actionable rather than superstitious: with
prefix-cache reuse enabled on the **KDA (Kimi Delta Attention) path**, requests that shared
a prompt prefix reused KV state that did not actually match the new request's attention
computation, and the served output was **corrupted** — wrong tokens, not merely slower.
It presents on **multi-turn or shared-system-prompt traffic** (exactly the traffic reuse is
meant to accelerate) and stays invisible on single-shot prompts. Scope and status matter
for an operator deciding today: this was observed on a specific architecture and engine
era, and PR #26185 is the upstream thread that tracks it — so treat "reuse off" as
mandatory *on the affected stack/build* and **re-check whether your current build carries
the fix** before assuming the foot-gun is still loaded. The flag that looks like free
prefill is sometimes a correctness regression with a delayed fuse.

Rule:

1. Default to reuse off until you have a harness that would catch the corruption mode.
2. When you enable reuse, pin engine version and architecture notes; do not inherit reuse
   across unrelated models because a blog said it was faster.
3. If outputs get weird only on multi-turn or shared-system-prompt traffic, suspect reuse
   before you suspect "the quant is bad."

## KV cost as a first-class design axis (hybrid lesson)

Not every architecture pays the same KV tax. In from-scratch hybrid experiments, the lab
measured bits/byte against KV cost per token and found ordering that was **monotonic in
KV cost at every length** on the reported arms, with a flat-KV hybrid winning on the
combined reading `[LAB: PROJECT-LOG / matrix hybrid KV arms]`.

| arm (sketch) | KV cost class | role |
|---|---|---|
| full attention control | highest KB/token | baseline desk tax |
| hybrids with more full attention | medium | compromise |
| hybrid / flat-KV leaning arms | low or flat | desk tax collapses |

The detailed bits/byte numbers and σ claims live in the lab record; the operator lesson
does not need them memorized. **Architecture choice is sometimes a KV choice.** If your
product is long-context, a model that is slightly worse on a short-context leaderboard
but dramatically cheaper per token of history can win the deployment. If your product is
short prompts, you may be buying flat-KV complexity you will never amortize.

Chapter 8's "what fits" question is partly a KV question once context targets leave the
demo range.

## Long context is a residency plan

A 64K per-slot ceiling is not only an engine number. It is a claim about memory headroom
under real traffic. Production soak on Q3-MTP included 28K-token long-context recall
checks beside tool-calling and dual-stream MTP `[LAB: RESULTS-MATRIX §G]`. That is the
right posture: long context is a **feature you test**, not a slider you max.

When headroom dies, systems start paging, shrinking batches, or OOMing on the next spike.
Chapter 7 will talk about thermal and power. Here the cache-specific failure is quieter:
quality falls first, then speed, then the process dies — and the root cause is that the
desk ate the room.

## Traps, in one checklist

1. **Parallel divides context.** Always compute and log per-slot context.
2. **Unequal desks confound quality comparisons.** Match `n_ctx_slot` before blaming PAR.
3. **KV precision is a quant.** Experiment with suites; do not casual-toggle.
4. **Cache reuse can corrupt.** Require a harness before enabling.
5. **Long context without soak tests is a demo.** Prove recall and stability at target
   length.
6. **Architecture KV tax differs.** Leaderboards at 2K tokens hide 32K economics.
7. **Spill + long context + speculation stack.** Each multiplies bytes; price the stack
   (chapters 1 and 3).

## A minimal measurement recipe

For any new model or flag set:

1. Print startup allocation: weights, KV budget, per-slot context, parallel.
2. Run a short fixed prompt at c=1; capture tok/s and smoke quality.
3. Run a long-prompt prefill case at target context; capture time-to-first-token.
4. Run a long-generation case; watch VRAM/host trend, not only mean tok/s.
5. If enabling parallel, repeat with matched per-slot context and with production-like
   concurrency separately.
6. If enabling cache reuse or KV quant, run a multi-turn / shared-prefix suite designed to
   fail loudly on corruption.

If you cannot state the per-slot context and KV precision of a "bad output" report, you
do not yet have a bug report. You have a mood.

## What this chapter refuses to claim

- We do not claim one universal KV precision for all models.
- We do not claim cache reuse is always unsafe — only that it has been mandatory-off for
  recorded corruption modes on specific stacks.
- We do not claim flat-KV hybrids always win products; they win a measured tax curve in
  the lab record under stated conditions.
- We do not provide a closed-form KV byte formula for every architecture here; use the
  engine's own allocation log and the model card.



## Context length as a product feature with a bill

Product managers love "128k context" on a slide. The bill arrives as:

- KV bytes per token times layers times precision
- prefill time to first token
- decode slowdown as history grows
- sharper failure modes under parallel

If the customer actually uses 2k tokens median, you may be paying a tax for a brochure line. If they truly use 32k, then chapter 1's bandwidth story and this chapter's desk story dominate the design. Measure the real context histogram before you buy the marketing ceiling.

## Prefix-heavy workloads

Many enterprise deployments share a large system prompt or tool schema across requests. That is exactly where cache reuse is tempting and exactly where corruption flags matter. The K3-Encode note that forced `--cache-reuse 0` is your reminder that shared prefixes are not free speed `[LAB: PROJECT-LOG cache-reuse / PR #26185]`.

A safe rollout pattern:

1. ship with reuse off
2. build a multi-turn shared-prefix corruption suite
3. enable reuse on a canary
4. compare suite + latency
5. only then widen

Skipping to step 5 is how silent wrongness enters.

## Conversation durability vs KV durability

Users think conversations live in the model. Usually they live in a client-side or app-side transcript, and the KV is a disposable acceleration of that transcript. After a restart, the desk is empty even if the chat scrollback still shows text.

Design implications:

- reconnect should resend necessary history or accept cold quality
- do not promise "the model remembers" across process death unless you built durable state (see *Durable State for Ephemeral Minds* if you need that stack)
- load-shed by dropping KV and re-prefilling rather than serving half-corrupt desks

## Per-slot math drill

Suppose CTX=8192 and PAR=8. Per slot 1024. If your agent prompt uses 700 tokens of tools+policy and the user question is 200, you have ~124 tokens of generation before you are in trouble. This is not theoretical; the matrix's 1365-slot caution is the same class of foot-gun `[LAB: RESULTS-MATRIX concurrency notes]`.

Always compute:

`usable_generation ≈ n_ctx_slot - prompt_tokens - safety_margin`

If usable_generation is smaller than your product's median answer, your parallel setting is a quality bug.


## Field story: the silent 1365-slot deploy

The matrix note about PAR=6 with CTX=8192 producing 1365 tokens per slot is a complete short story `[LAB: RESULTS-MATRIX concurrency notes]`. Nobody intends to ship a closet-sized desk. The flags look reasonable in isolation. The division does the damage.

Add a CI check if you can: parse startup logs and fail if `n_ctx_slot < product_min_context`. If you cannot CI it, put it in the smoke script. If you cannot smoke it, you will learn from users.

## KV and multi-tenant fairness

When multiple tenants share a server, KV is the fairness battleground. One tenant with a huge context can crowd out others even if weight residency is fine. Per-slot caps, per-tenant max context, and admission control are fit tools as much as they are product tools.

Chapter 8's headroom targets apply to KV too: if the box only works when nobody uses long context, you did not ship long context. You shipped a brochure.


## Operator lab: context admission test

Write a script that:

1. Parses n_ctx_slot from startup.  
2. Builds a prompt of size `n_ctx_slot - 256`.  
3. Asks for a 512-token answer.  
4. Fails if the server loops, truncates immediately, or OOMs.

Run it whenever PAR or CTX changes. The silent 1365-slot failure mode should never reach users twice `[LAB: RESULTS-MATRIX concurrency notes]`.


## What you should do Monday

1. Parse `n_ctx_slot` from every server startup and alert if below product minimum.
2. Confirm KV precision and cache-reuse settings are explicit in the recipe file.
3. Run one matched-desk parallel control before blaming PAR for quality.
4. Measure a real context-length histogram from production logs if you have them.
5. Add a shared-prefix multi-turn case to the smoke suite before enabling reuse.

The silent 1365-slot failure mode is too cheap to leave unguarded `[LAB: RESULTS-MATRIX concurrency notes]`.


## Cross-links inside this book

Context division bugs present as "model quality" and get handed to chapter 2 or 5 by mistake. Always read n_ctx_slot first (chapter 6 audit). Long context without headroom becomes a chapter 8 fit failure mid-week, not at load time. Speculation plus long context multiplies bytes; re-price chapter 3 after any CTX change. Crash recovery rarely restores KV; chapter 7's client honesty section matters for user-visible continuity.

## Desk space is product space

If the desk does not fit the work, the model never gets a fair exam.

## Looking ahead

Chapter 5 turns the honesty problem into a method: error bars, controls, and the ±10
point tool-suite noise already stalking chapters 2 and 3. Chapter 6 stays in the startup
and load logs where context division and placement show up before users do. Chapter 8
asks what fits when weights, KV, concurrent slots, and headroom must cohabit on a 128 GB
class box.

You are never serving only a weight file. You are serving a weight file **and** a growing
desk. Budget both, or the desk will budget itself.


# Chapter 5 — Benchmarking Honestly

*(v2, 2026-08-28 — written by rogerai-dj for RogerAI Labs, verified by Roger AI.
Numbers carrying a `[LAB:]` marker are RogerAI Labs' own bench measurements, taken on the
reference machine described in Chapter 1 and recorded in the lab notebook; each is
reproducible by re-running the stated recipe — engine build, artifact, and flags. Claims
without a marker are labeled unmeasured.)*

## Why this chapter exists

Every prior chapter leaned on tables. Tables can lie without any one cell being false.

A true 47 on a tool suite becomes a lie when it is sold as "the model is 47" without the
range, the harness noise, the parallel setting, the context per slot, or the control that
isolates the change you claim to have made. Honest benchmarking is not etiquette. It is
how you keep chapters 1–4 from laundering folklore through arithmetic.

## The scar: ±10 points at temperature 0

The capability matrix carries a footnote that should be taught in every local-inference
shop `[LAB: RESULTS-MATRIX §C footnote]`:

Q3-MTP tool hardmode, three runs on 07-13: **40**, **47**, **50** (MTP off control).
Five of fifteen scenarios flipped between identical back-to-back runs. Temperature was
0.0. The flips were attributed to **PAR=2 batch-packing nondeterminism amplified by MoE
routing**, not to sampling.

**Treat single-run hardmode numbers as ±10.**

Scope that number honestly, because it is easy to over-generalize. The ±10 envelope was
measured on **one model** (Q3-MTP), **one harness** (the 15-scenario tool-hardmode suite),
**one date** (2026-07-13), under **one serving shape** (PAR=2 batch packing on a spilled
MoE). It is a property of *that* measurement setup, not a universal constant of local
inference. A different model, a larger or smaller suite, a dense architecture, a
single-slot (PAR=1) configuration, or an MMLU-style knowledge run will each have their own
noise floor — often much tighter, occasionally wider. Do not staple ±10 onto a 5-run MMLU
sweep on a dense 7B and call it calibrated; measure the spread of the suite and stack you
actually run. The transferable lesson is the *method* — repeat, publish the range, name the
nondeterminism source — not the magnitude.

If your promotion threshold is "beat 45," a 40 and a 50 are different religions. If your
marketing quotes the 50 without the 40, you are not benchmarking. You are fishing.

## What "temperature 0" does not guarantee

Temperature 0 removes one randomness source. It does not freeze:

- batch packing across concurrent slots
- MoE routing ties and implementation details
- GPU reduction order and kernel nondeterminism on some stacks
- cache-reuse paths
- any server-side scheduling that changes which requests share a batch

So "we set temp 0" is a necessary note, not a sufficiency proof. The lab had to name PAR=2
packing before the tool flips made sense. Your harness notes should be equally specific.

## Controls beat vibes

A control holds the thing you are not studying fixed.

Examples already in this book:

- **Parser vs quant on tools** `[LAB: RESULTS-MATRIX §D]`: template/parser patch scored 43
  versus baseline 47; Q4 experts scored 60. Without the parser control, someone would have
  "fixed tools" by rewriting prompts forever.
- **MTP on vs off for quality** `[LAB: RESULTS-MATRIX §C footnote]`: MTP-off control at 50
  sits inside noise of MTP-on 40/47 — so a speed feature was not purchased with a silent
  tool regression large enough to see through ±10.
- **Matched n_ctx_slot across PAR** `[LAB: RESULTS-MATRIX concurrency controls]`: PAR=1 at
  4096 versus PAR=4 at 4096 per slot, after unequal desks had confounded earlier reads.

If you cannot name the control, you are not measuring a change. You are measuring a
different Tuesday.

## Isolate one variable

The matrix is usable because rows try to change one axis at a time: engine build on the
same IQ3 file; expert precision on the same hardmode; n_max on the same spill class;
PAR on a fixed recipe.

Industrial failures often change five axes at once: new quant, new engine binary, new
parallel, new context, new prompt template — then declare victory. Maybe something
improved. You will not know what to keep when it regresses next month.

**Rule:** one change per claim. Bundle changes only as a named recipe promotion, and then
accept that the unit of claim is the recipe, not a single flag.

## Ranges, not heroes

Report:

- n runs
- min / median / max or mean ± spread
- known nondeterminism sources
- suite size (15 scenarios is not 1500)

The Q8-MTP master tool runs of 73 / 50 / 43 (mean 55) are more honest than "55" alone
because the spread is visible, and because scenario-consistent wins (TC-71, TC-78, TC-70)
were called out separately `[LAB: RESULTS-MATRIX §C notes]`. Means hide structure; structure
is often what you ship.

## Suite identity is part of the claim

"MMLU 88.3" and "tool hardmode 55" are different products. On §C they do not even rank
models the same: Qwen3.6-35B-A3B posts 71.0 MMLU and **87** tools; DeepSeek Q8-MTP posts
**88.3** MMLU and mean 55 tools `[LAB: RESULTS-MATRIX §C]`.

If your customers buy tool reliability, promoting on MMLU is a category error. If your
customers buy general knowledge chat, promoting on a 15-scenario tool suite is a category
error. Honest benchmarking starts with **which decision the number is allowed to drive**.

## Methodology findings are results

Sometimes the finding is that the suite cannot answer the question. DeepSeek IFEval was
marked DNF because long-form outputs at ~6 tok/s/slot made the method impractical on that
model class `[LAB: RESULTS-MATRIX §C]`. Publishing DNF beats publishing a fantasy score.

Likewise, the lab's later instrument defects and retractions (including sections withdrawn
when collectors were wrong) are not stains to hide. They are how you stop living on
corrupted numbers. A benchmark program without retractions is usually a benchmark program
without teeth.

## A practical honesty protocol

1. **Write the decision** the metric will authorize (promote, reject, ship flags).
2. **Write the suite** and its size; do not let a 15-item tool set impersonate a universe.
3. **Pin the recipe:** engine SHA/build, quant identity, parallel, per-slot context, KV
   precision, speculation settings, warm/cold policy.
4. **Run ≥3 times** when noise is known; publish the range.
5. **Hold one control** that would falsify your favorite story (parser, MTP off, matched
   context, single-stream vs batched).
6. **Separate speed claims from quality claims**; each gets its own table.
7. **Record DNF and abort conditions** (too slow, OOM, instrument defect).
8. **Refuse cross-engine leaderboards** unless engine is the variable under study.

## How this rewrites earlier chapters

- Chapter 1's tok/s tables are speed claims under named builds — not model essence.
- Chapter 2's quant ladder is only as strong as the tool ranges and the §D controls.
- Chapter 3's MTP multipliers require acceptance and quality controls, not just peak
  tok/s.
- Chapter 4's parallelism story required matched desks before quality differences were
  speakable.

Honest benchmarking is the load-bearing wall between measurement and myth.

## What this chapter refuses to claim

- We do not claim three runs are always enough; they were the minimum that made ±10
  visible on this harness.
- We do not claim temperature 0 plus fixed seeds makes MoE serving deterministic under
  batching.
- We do not claim MMLU-100 or a 15-scenario tool suite is an industrial certification.
- We do not claim every instrument defect in the wider lab record is fully narrated here;
  where this book cites a number, it cites the surviving one.



## Worked example: a bad promotion paragraph

Bad:

> Our Q3 build scores 50 on hardmode tools and 30 tok/s. We are promoting it.

Better:

> Q3-MTP on llama.cpp build X, PAR=2, per-slot context Y, KV precision Z, MTP n_max=1,
> warm single-stream. Tool hardmode (15 scenarios) over three runs: 40, 47, 50 MTP-off
> control. Spread ±10; temperature 0; flips attributed to batch packing. Decode 30.5
> tok/s warm on the reference box `[LAB: RESULTS-MATRIX §C/§E]`. Decision: morning
> production only, with master-precision follow-up preferred for tool floor.

The second paragraph can be audited. The first can only be believed.

## Speed benches need the same medicine

Quality noise is obvious because scores look like grades. Speed noise hides inside
averages.

Honest speed reports include:

- warm versus cold (first request after load vs steady state)
- context length and generation length
- single-stream versus aggregate under c=N
- whether prefill is mixed into the number
- hardware identity and engine identity
- range across runs, especially near thermal limits (chapter 7)

Chapter 1's engine table already showed a bimodal mainline CUDA decode (~2.6–19) versus a
stable pr25545 band (24.5–28.5) `[LAB: RESULTS-MATRIX §A]`. Publishing 10.8 without the
bimodality would have been a quieter kind of lie — the mean of a broken process.

If your latency SLO is a percentile, bench a percentile. Means flatter than your pager.

## Cross-model leaderboards

Putting gpt-oss under vLLM TP=4 next to DeepSeek under llama.cpp on the same table is
legal only if the caption says engines differ `[LAB: RESULTS-MATRIX §C]`. It is illegal as
a pure model ranking.

The honesty move is either:

1. Fix the engine and vary the model, or
2. Fix the model and vary the engine, or
3. Label a recipe contest and stop pretending it is a model contest.

Most public charts do (3) while claiming (1). Do not import that habit into a plant or a
pager rotation.

## Small suites and scenario notes

A 15-scenario tool suite can still be invaluable. It cannot bear the weight of a general
intelligence claim. What it can do — and what the lab used it for — is catch consistent
scenario failures and wins across runs (TC-70/71/78 notes on the master) `[LAB:
RESULTS-MATRIX §C notes]`.

Practice:

- Publish scenario-level notes for the failures that drive the mean.
- Do not let a single flaky scenario veto a recipe without a rerun policy.
- Do not let a single lucky scenario promote a recipe without a rerun policy.

## When to stop measuring and fix the instrument

If two scorers disagree by huge margins, or a collector can invent reachability, or a rope
base is wrong by orders of magnitude, you are not in model-debugging land. You are in
instrument land. The wider lab record includes retractions forced by bad instruments; the
correct behavior is stop, repair, redo, and leave the tombstone visible.

A clean culture prefers a loud retraction to a quiet wrong leaderboard.



## Building a tiny product suite that is still honest

You do not need a 10,000-item academic suite to make promotion decisions. You need a suite that:

- matches the product risk
- is large enough that one flaky item cannot dominate without being visible
- is small enough to run multiple times
- is versioned and hashed

The 15-scenario tool hardmode set is small and still caught consistent scenario structure across runs when the team looked beyond the mean `[LAB: RESULTS-MATRIX §C notes]`. Copy the attitude, not necessarily the item count.

Version the suite like code. When you change items, you break comparability. Say so.

## Reporting template (quality)

```
suite: tool-hardmode@2026-07-13
recipe: <engine> <model> <flags>
n_runs: 3
scores: [40, 47, 50]
spread_note: ±10 known; temp 0; PAR=2 packing nondeterminism
controls: MTP-off=50
decision: ...
```

## Reporting template (speed)

```
metric: warm_single_stream_decode
context: ...
gen_len: ...
runs: [...]
hardware: 4x RTX PRO 4500 128GB VRAM ...
engine: pr25545
notes: prefill separate = ...
```

If a report cannot fill these, it is not ready for a promotion meeting.

## Nondeterminism inventory

Keep a living list of nondeterminism sources on your stack:

- batch packing
- MoE routing
- kernel reductions
- cache reuse
- network-loaded tokenizer files
- concurrent background jobs

When a score jumps, check the inventory before checking the model mythology. The §C footnote exists because someone did that work `[LAB: RESULTS-MATRIX §C footnote]`.

## Ethics of numbers

Publishing the max of three runs without the min is a choice. Publishing cross-engine ranks without labels is a choice. Publishing DNF as a quiet omission is a choice. Honest benchmarking is ethics for people who ship systems that others will trust with work.


## Field story: three runs that disagreed

40, 47, 50. Same week, same stack family, temperature 0 `[LAB: RESULTS-MATRIX §C footnote]`. The honest response is not to average them into a press release. It is to widen the error bar, name the nondeterminism, and stop making 2-point promotion gates.

If your organization currently promotes on a single run, this footnote is your incident report from the future. Steal it before you earn it.

## Benchmark ownership

Every product suite needs an owner who can answer:

- what decision it authorizes
- how often it runs
- what changed since last week
- what the current range is

Orphan suites become Halloween decorations: visible, scary, not load-bearing.


## Operator lab: the promotion packet

A promotion packet is a single markdown file containing:

- recipe hash
- quality range table
- speed range table
- controls run
- fit/soak notes
- known nondeterminism
- owner signature

No packet, no promote. This is how you stop hallway decisions. The §C footnote and §D controls are the ancestors of a good packet `[LAB: RESULTS-MATRIX §C/§D]`.


## What you should do Monday

1. Ban single-run promotions for any suite with known noise.
2. Create a promotion packet template and reject hallway ships that lack one.
3. Write the nondeterminism inventory for your stack in a shared doc.
4. Label every cross-engine chart as a recipe contest or stop making it.
5. Assign an owner to each product suite with a paging path for suite breakage.

The ±10 footnote is not trivia; it is a governance rule waiting to be adopted `[LAB: RESULTS-MATRIX §C footnote]`.


## Cross-links inside this book

Every table in chapters 1–3 is only as strong as this chapter's ranges and controls. Fit claims in chapter 8 need the same packet discipline as quality promotions. Load-log diffs in chapter 6 are controls too: they isolate recipe change from mythology. If you cannot say which decision a number authorizes, it does not belong in a promote meeting.


## One-page honesty pledge

Before any external claim about local model speed or quality leaves your org, a named person signs:

- recipe identity known
- range published
- controls named
- hardware class named
- failed recipes not deleted

This is not bureaucracy. It is how you keep chapter 5 from becoming optional when marketing is in a hurry. The lab footnote that forced ±10 on a temp-0 tool suite is the pledge's ancestor `[LAB: RESULTS-MATRIX §C footnote]`.

## Looking ahead

Chapter 6 shows what to read when the number is "weird" before you redesign the model:
the load log. Chapter 7 puts environmental nondeterminism — heat, power loss — on the
same honesty ledger. Chapter 8 asks what fits, which is itself a benchmark of residence
and failure flags, not a vibes-based shopping list.

A number without a recipe is a rumor. A number without a range is a dare. A number
without a control is an advertisement.


# Chapter 6 — The Load Log Tells the Truth

*(v2, 2026-08-28 — written by rogerai-dj for RogerAI Labs, verified by Roger AI.
Numbers carrying a `[LAB:]` marker are RogerAI Labs' own bench measurements, taken on the
reference machine described in Chapter 1 and recorded in the lab notebook; each is
reproducible by re-running the stated recipe — engine build, artifact, and flags. Claims
without a marker are labeled unmeasured.)*

## When the knobs lie

A model that should do ~26 tok/s does ~2. The chat is fine. The GPU utility graph is a
Rorschach test. Someone lowers temperature. Someone raises batch. Someone rebuilds with
"performance flags." Someone blames the quant.

The load log already knows.

Pathological decode is usually not a personality problem and not a prompt problem. It is
a **placement problem**: which tensors landed on which device, which layers spilled, which
indexer runs where, which flags turned a resident recipe into a host-memory commute. The
startup log and the per-layer placement summary are the primary sources. Sampling flags
are secondary literature.

## The pure case: 2 tok/s with the weights right there

Chapter 1 already showed the cleanest load-log story in the matrix. Same 102 GB UD-IQ3
DeepSeek file, same cards, different engine builds `[LAB: RESULTS-MATRIX §A]`:

| Build | Indexer | Warm decode |
|---|---|---|
| pre-#25545 | CPU | ~2 tok/s |
| mainline CUDA | CPU | ~10.8 bimodal |
| taco | CPU/disabled | 13.1 bimodal |
| **pr25545** | **GPU** | **26.2 stable** |

The weights were not "slow." The lightning indexer was on the CPU. Every token paid a
host-side tax. No amount of prompt craft refunds that tax. Reading the build identity and
the indexer placement ends the mystery; turning knobs extends it.

**First rule of this chapter:** when tok/s collapses by an order of magnitude, look for a
bus, not a better temperature.

## What to read before you tune

A useful startup sequence answers:

1. **Engine identity** — build SHA / binary name / backend.
2. **Model identity** — path, quant tag, size on disk.
3. **Device map** — which GPUs, tensor split, n-cpu-moe / offload counts.
4. **Per-slot context** after parallel division (chapter 4).
5. **KV precision and cache-reuse flags.**
6. **mmap / repack / no-mmap choices.**
7. **Any warning about fallbacks** (CPU layers, failed CUDA graphs, OOM recoveries).

If your server prints a placement table or layer device list, archive it with the run. If
it does not, improve the logging before you improve the model. A regression without a
placement snapshot is a ghost story.

## Fit failures are load-log failures

Section F is a catalog of recipes that look like "model issues" and are actually flag
issues `[LAB: RESULTS-MATRIX §F]`:

| Model | Works when… | Fails when… |
|---|---|---|
| IQ3 102 GB | n-cpu-moe 4, split 31,25,24,20 | — |
| community Q4 175 GB | n-cpu-moe 24, split 25,6,6,6, **--no-repack**, mmap, lean RAM | n-cpu-moe 14 VRAM-OOM; ≥18 without --no-repack **segfault**; --no-mmap **host-OOM >125 GB** |
| Q8-MTP 160 GB | n-cpu-moe 14, split 20,8,8,8 (+ no-repack, mmap) | split 21,8,8,7 → **compute-buffer OOM card0** |
| Q3-MTP 143 GB | n-cpu-moe 10… / prod 11 with split 18,9,9,8, PAR 2 | — |

Three different "the model crashed" reports, three different log truths:

- **VRAM-OOM** — too much forced on-GPU for this split.
- **segfault without --no-repack** — a packaging/runtime interaction, not a user prompt.
- **host-OOM without mmap** — the host RAM budget was the real GPU.
- **compute-buffer OOM on card0** — a one-card buffer cliff from a split that looked
  "almost the same" (20,8,8,8 works; 21,8,8,7 dies).

The load log and the OOM killer messages are more informative than a screenshot of the
chat UI. Save them.

## Tiny split changes are not tiny

Operators often nudge tensor split "a little" to chase headroom. The Q8-MTP row is the
warning label: `20,8,8,8` loads; `21,8,8,7` compute-buffer OOMs card0 `[LAB:
RESULTS-MATRIX §F]`.

Treat split vectors as **discrete recipes**, not continuous knobs. When you change them,
you are not "tuning." You are shipping a new placement. Re-run:

- load success
- smoke decode
- product suite if quality-sensitive
- soak if production-bound (chapter 7)

## mmap, repack, and the host as a silent GPU

The community Q4 recipe only behaves when mmap is on and repack is off, with lean host
RAM discipline. Disable mmap and the host can OOM above 125 GB RAM trying to hold what
you thought was a GPU problem `[LAB: RESULTS-MATRIX §F]`.

This is why chapter 1 refused to treat file size as speed. A 175 GB artifact can thrash
the host path and look like a slow GPU model. The log line about mmap and the host OOM
trace are the explanation. "Q4 is slow" is the folklore paraphrase.

## Offload counts: n-cpu-moe as a bandwidth valve

For MoE stacks, how many expert layers live on CPU is a bandwidth valve. Too few on CPU
and you VRAM-OOM. Too many on CPU and every token walks DDR. The working recipes in §F
are not aesthetics; they are measured compromises.

When tok/s is mediocre rather than cratered, compare:

- n-cpu-moe / offload layers
- measured spill traffic if the engine exposes it
- whether speculation is multiplying spilled verifies (chapter 3)

Mediocre is often "too much commute," not "bad GPU silicon."

## Parallel and context: the silent closet

Chapter 4's trap belongs in the load log checklist again: `--parallel N` divides context.
If the startup log says `n_ctx_slot=1365` while the model thinks for 1200 tokens, quality
failures are placement/budget failures `[LAB: RESULTS-MATRIX concurrency notes]`.

Read the slot size before you file a "model loops" ticket.

## A debug order that saves days

When decode is wrong, walk this order:

1. **Confirm binary and model path** (wrong file is undefeated).
2. **Read placement / split / offload** from startup.
3. **Read n_ctx_slot, KV precision, cache-reuse.**
4. **Compare to last known good recipe** (diff the flags, not the vibes).
5. **Check host RAM and mmap/repack** if the artifact is huge.
6. **Only then** touch sampler, batch, or prompt template.
7. **Only then** rebuild engines or re-quant.

Teams that start at step 6 donate weekends to the machine.

## Production soak as a load-log continuation

A load that succeeds is not a load that lasts. The promoted Q3-MTP soak recorded 86
requests in 12 minutes, 0 errors, 100% mean acceptance, **+2 MiB VRAM drift** `[LAB:
RESULTS-MATRIX §G]`. Drift is a load-log story stretched across time: leaks, fragmentation,
cache growth, mis-sized pools.

If your "it got slow after an hour" report has no VRAM/host series, you are debugging
without the patient chart.

## Case patterns (short)

**Pattern A — cratered tok/s, GPUs look idle-ish.** Suspect host-side tax (indexer, spill,
mmap miss). Historical twin: §A ~2 tok/s era.

**Pattern B — hard crash on load.** Suspect split, compute-buffer, repack, VRAM. Twin: §F
failed configs.

**Pattern C — loads, answers garbage on multi-turn.** Suspect KV precision or cache-reuse.
Twin: chapter 4 corruption notes.

**Pattern D — loops / short thinking.** Suspect n_ctx_slot too small under parallel. Twin:
PAR context division.

**Pattern E — fine at c=1, dies under load.** Suspect concurrency scheduling, KV budget,
or aggregate placement. Twin: §B dips and chapter 3's re-bench-at-c rule.

## What this chapter refuses to claim

- We do not claim every engine prints perfect placement logs; we claim you should not
  trust speeds without them.
- We do not claim one universal split vector for all MoE models.
- We do not claim segfaults are always --no-repack; we claim the matrix has a documented
  case you should know exists.
- We do not replace vendor debuggers — we replace knob-first superstition.



## A worked false trail

Symptom: "DeepSeek Q4 is broken; chat is slow and sometimes dies."

False trail: try GGUF from another packer, change temperature, disable tools, rebuild
from `main`.

Load-log trail:

1. File is ~175 GB community Q4.
2. Startup shows no `--no-repack`, mmap off, n-cpu-moe 14.
3. Host RAM climbs past 125 GB; OOM killer lands — or a segfault hits on repack paths.
4. Compare to §F working recipe: n-cpu-moe 24, split 25,6,6,6, `--no-repack`, mmap, lean
   host RAM `[LAB: RESULTS-MATRIX §F]`.

After the recipe matches, decode is merely slow relative to a resident master (16.5 vs
26+), which is now a chapter 1/2 problem, not a haunted model.

The difference between the trails is a day of life.

## Diff recipes like code

Keep a `last-known-good` flag file next to the unit:

```
BINARY=...
MODEL=...
N_CPU_MOE=...
TENSOR_SPLIT=...
PAR=...
CTX=...
KV=...
CACHE_REUSE=...
MMAP=...
REPACK=...
MTP=...
```

When something breaks, `diff` that file against today's flags before you touch weights.
Placement regressions love to hide in "temporary" environment variables that became
permanent.

## Headroom is part of the log

§G's production line recorded 3.3–6.6 GB headroom per card on the promoted Q3-MTP recipe
`[LAB: RESULTS-MATRIX §G]`. Headroom is not vanity. It is the difference between surviving
a concurrent spike and dying on compute-buffer allocation when a second stream arrives.

If load succeeds with 0.1 GB free, you have a demo, not a service. Log headroom beside
tok/s in soaks.


## Reading a bad load like a postmortem

Write the incident in four lines before you change anything:

1. Symptom (tok/s, crash, loop, garbage multi-turn).
2. Last-known-good recipe hash or flag file.
3. Diff of today's flags vs that file.
4. First log line that disagrees with the good run.

Most "mysteries" die on line 3. The rest die on line 4. If you cannot produce a last-known-good, your operational problem is upstream of inference physics: you are flying without a flight data recorder.

## Engine upgrades are placement events

Upgrading llama.cpp or swapping a backend is not a no-op. The §A table is an engine-upgrade story that moved decode from ~2 to ~26 without touching weights `[LAB: RESULTS-MATRIX §A]`. The inverse also happens: a new binary can reintroduce CPU paths, change default offload, or alter cache behavior.

Policy:

- pin engine versions in the unit file
- on upgrade, force a full recipe re-validation (load, smoke, suite, soak)
- never roll engine and model file in the same change window unless the change unit is explicitly "recipe vNext"

## When the log is quiet and the speed is still wrong

Sometimes placement looks correct and tok/s is still mediocre. Then expand the investigation sideways, still without sampler folklore:

- thermal throttle (chapter 7)
- power cap / Max-Q mode
- another process on the GPUs (training pull-ins from chapter 7)
- speculation settings multiplying spill (chapter 3)
- context so long that KV bandwidth dominates (chapter 4)

The load log remains the first read. It is not the only read. It is the read that prevents you from spending Tuesday on temperature 0.7.

## Operator drill

Once a month, on a non-production clone:

1. Break one flag deliberately (mmap off on a huge artifact, or a bad split).
2. Capture the log.
3. Restore last-known-good.
4. Time the diagnosis.

If diagnosis takes longer than restore, your logging is insufficient. Fix logging before the real outage.



## Load log annex: fields worth parsing

If you automate one thing, automate extraction of:

- model path and size
- GPU UUID list
- tensor split
- offload / n-cpu-moe
- n_ctx and n_ctx_slot
- KV type
- cache reuse
- mmap/repack
- warnings and fallbacks
- estimated VRAM per device

Store them as JSON next to the systemd unit start. When tok/s regresses, diff JSON. Humans miss flags; diffs do not.

## The "almost same split" postmortem

Take §F's Q8-MTP working `20,8,8,8` versus failing `21,8,8,7` `[LAB: RESULTS-MATRIX §F]`. A human reviewing a PR might approve the change as harmless. A machine comparing against last-known-good would block it until a load test passed.

That is the standard: **placement PRs require load tests**, not just LGTM.

## Correlating dashboards to logs

Dashboards show symptoms. Logs show placement. A good on-call loop:

1. latency spike alert
2. open current recipe JSON
3. open previous good recipe JSON
4. open startup log of current process
5. only then open Grafana for thermals and traffic

If you start at step 5, you will optimize traffic charts while a bad deploy sits in plain sight.

## Training the team

Once a quarter, give each operator a broken recipe on a scratch host and time them to root cause. Keep the broken recipes from §F-like failures. Celebrate fast diagnosis. Do not celebrate heroic silent fixes that leave no notes.


## Field story: host OOM as a "GPU issue"

The §F --no-mmap host-OOM case is a classic mis-tag `[LAB: RESULTS-MATRIX §F]`. The ticket says GPU. The killer says host RAM. The folklore says quant. The fix says mmap and lean host discipline.

Train on-call to read dmesg and host RAM alongside nvidia-smi. A GPU-only dashboard is a partial cockpit.

## Recipe registry

Beyond last-known-good, keep a registry of recipes with states: experimental, candidate, production, retired, failed. Failed is permanent. Retired keeps history. Experimental is allowed to be wild. Production is boring and pinned.

Most outages are an experimental flag that accidentally became production.


## Operator lab: the five-minute load audit

Set a timer for five minutes at every deploy:

Minute 1: confirm binary hash and model checksum.  
Minute 2: capture startup log to `logs/start-$(date -u +%Y%m%dT%H%M%SZ).txt`.  
Minute 3: extract placement fields to JSON.  
Minute 4: diff against last-known-good JSON.  
Minute 5: run a 20-second smoke generation and record tok/s.

If you cannot do this in five minutes, automate it. Humans under pressure skip steps. Scripts do not feel pressure.

## Mapping symptoms to §F

| Symptom | First §F lookalike |
|---|---|
| segfault on load | missing --no-repack on picky artifacts |
| host RAM death | mmap off on huge artifacts |
| VRAM OOM | n-cpu-moe too low / split too greedy |
| compute-buffer OOM | "almost same" split vector |
| slow but stable | spill commute / wrong engine path |

Keep this table in the on-call doc. It is not complete. It is fast.


## What you should do Monday

1. Implement the five-minute load audit on staging, then on production deploys.
2. Diff recipe JSON on every restart; page if production drifts from last-known-good.
3. Store startup logs with timestamps next to the unit, not only in a volatile journal.
4. Practice one §F lookalike failure on a scratch host with the on-call rotation.
5. Require placement diffs on engine upgrades before traffic returns.

If the log is not archived, the truth was available and then thrown away `[LAB: RESULTS-MATRIX §A/§F]`.


## Cross-links inside this book

This chapter is the debug front door. Chapter 1 gives magnitude heuristics. Chapter 8 gives the fit tombstones you should already have on disk. Chapter 7 covers the cases where the log looks fine and the environment does not. Chapter 5 tells you how to record the before/after so the fix becomes a recipe, not a legend.


## One-page load pledge

No production restart without:

- archived startup log
- recipe JSON diff
- smoke tok/s
- owner initials

If any item is missing, the restart is an experiment on users. The §A crater and §F tombstones exist because someone eventually read the log; the pledge makes that the default rather than the rescue `[LAB: RESULTS-MATRIX §A/§F]`.

## Looking ahead

Chapter 7 keeps reading the machine when the failure is heat or power, not placement.
Chapter 8 turns successful recipes into a fit map: what a 128 GB class box can hold, and
what smaller machines can honestly claim.

The load log is not ancillary output. It is the ground truth of local inference. If the
log and the dashboard disagree, believe the log.


# Chapter 7 — Thermals, Power, and Crashes

*(v2, 2026-08-28 — written by rogerai-dj for RogerAI Labs, verified by Roger AI.
Numbers carrying a `[LAB:]` marker are RogerAI Labs' own bench measurements, taken on the
reference machine described in Chapter 1 and recorded in the lab notebook; each is
reproducible by re-running the stated recipe — engine build, artifact, and flags. Claims
without a marker are labeled unmeasured.)*

## The environment is in the critical path

Local inference does not run in a vacuum. It runs in a chassis with finite cooling, a
wall circuit with finite power, and a human world that loses electricity.

If chapters 1–6 are about bytes and recipes, chapter 7 is about what happens when the
building disagrees. Thermals throttle tok/s without changing a single flag. Power loss
turns an un-checkpointed day into heat. Recovery time is a product feature whether you
sell it or not.

## Crashes as measured drills

The lab lost power and wrote the recovery down. That is the correct culture.

**Crash #1 — 2026-08-22.** Recovery of pretraining runs; fstab and mount discipline
became part of the story; recovery cost was large enough to force process changes `[LAB:
PROJECT-LOG 2026-08-22]`.

**Crash #2 — 2026-08-24.** Full recovery in about **25 minutes**. The crash-#1 fixes
held: data volumes auto-mounted, zero filesystem work. New failure: `disable` did not
keep a production DeepSeek unit down because other units pulled it in via `Wants=`; the
durable fix was a condition-gated hold using a marker file. Training resumed from
checkpoints with bounded loss (thousands of steps, not the whole run). Cumulative crash
cost that week: about **9.4 GPU-hours** redone. Checkpoint cadence (5k/4k steps)
continued to bound each loss under roughly 4.5 hours `[LAB: PROJECT-LOG 2026-08-24]`.

Read those entries as inference operators, not only as trainers:

1. **Recovery time is measurable** and should fall after each incident.
2. **Filesystem and service graphs** are part of the model stack.
3. **Checkpoints** convert disasters into bills you can pay.
4. **Dependency pulls** ignore your mental model of "disabled."

## UPS seconds versus checkpoint hours

A UPS that outlasts a graceful flush is wonderful. A UPS that outlasts your ego is rare.
The lab moral is blunt: a UPS buys seconds; a checkpoint buys the day.

For inference servers, the analogs are:

- **model file integrity** on disk (you can reload weights)
- **KV is disposable** (you cannot checkpoint a conversation cheaply in many setups —
  design clients to retry)
- **config and unit files** in version control
- **artifact mirrors** so a dead disk does not strand a one-off GGUF

Do not confuse "the GPU service restarts" with "the system recovered." Recovery means the
service returns to a known recipe with known quality, not merely that a process exists.

## Thermals: the invisible n_max

Heat is a silent speculation killer and a silent concurrency killer. As power limits
engage, clocks fall, tok/s falls, and your carefully priced chapter 3 multiplier becomes
a weather report.

Honest practice:

- Log GPU temperature and power draw beside soak tok/s.
- Bench at sustained load, not only at a 30-second burst.
- Treat Max-Q / power-cap modes as different hardware for SLO purposes.
- If a node sits in a hot aisle or a closet, write that down in the runbook like it was a
  flag.

This book will not invent a thermal curve it did not measure on the reference box in the
cited tables. It will insist you measure yours before you publish a latency SLO.

## Service holds and accidental resurrection

The 08-24 incident where a "disabled" DeepSeek returned because of `Wants=` pulls is an
inference-ops classic `[LAB: PROJECT-LOG 2026-08-24]`. Training jobs, sidecars, and share
units can resurrect the thing you are trying to starve for bandwidth.

Patterns that work:

- **condition-gated units** (`ConditionPathExists=!.../TRAINING_ACTIVE`) so a marker file
  is the source of truth
- **explicit conflicts** in systemd where appropriate
- **one capacity owner** per GPU set in the runbook

If two automation systems can start the same heavyweight server, they will do so on the
worst morning.

## Soak tests are environmental tests

§G's 12-minute soak (86 requests, 0 errors, +2 MiB VRAM drift) is a start, not a
climate chamber `[LAB: RESULTS-MATRIX §G]`. Extend soaks until they match your real duty
cycle: hours for a shop server, days for unattended plant boxes.

Watch:

- tok/s trend
- VRAM/host trend
- temperature/power trend
- error rate
- restart count

A flat error rate with rising temperature and falling tok/s is still a failure if your
SLO is latency.

## Power-loss checklist for inference boxes

After an outage:

1. Confirm disks mounted as expected (fstab nofail vsfail policy intentional).
2. Confirm the **intended** model service is the one that came back.
3. Diff runtime flags against last-known-good (chapter 6).
4. Run a smoke quality suite, not only `curl` health.
5. Run a short soak before reopening traffic.
6. Write the recovery time and the surprise into the log.

If step 6 does not happen, crash #3 will rhyme with crash #1.

## What this chapter refuses to claim

- We do not claim a universal UPS sizing guide.
- We do not claim training checkpoint intervals transfer unchanged to all inference
  products.
- We do not claim the reference box's thermal behavior is measured in full here.
- We do not claim systemd is the only process supervisor — only that dependency graphs
  always exist.


## What training crashes teach inference operators

The 08-22 and 08-24 entries are training-colored, but the failure classes map cleanly onto inference fleets `[LAB: PROJECT-LOG 2026-08-22/24]`:

- **Mount policy** → model store and adapter volumes must come back without human fsck heroics.
- **Checkpoint cadence** → for inference, think config + artifact mirrors + client retry; do not pretend in-flight KV is durable unless you built that.
- **Service dependency edges** → the heavyweight server you stopped for capacity will return if something else Wants it.
- **Bounded loss** → measure "minutes to healthy smoke" the way training measured steps lost.

If you only rehearse happy-path deploys, your first outage is also your first curriculum. Prefer scheduled drills.

## Capacity contention is an environmental hazard

On a shared box, "environmental" includes other jobs. The same physical GPUs cannot honestly serve a training run and a latency-sensitive inference SOP without a written policy. The marker-file hold from 08-24 is one mechanism: a visible, greppable source of truth that prevents accidental co-tenancy `[LAB: PROJECT-LOG 2026-08-24]`.

Write the policy as if it were a safety interlock:

- who may start large models
- what must be stopped first
- how contention is detected (utilization, memory, unexpected processes)
- how long a hold lasts

## Thermal runbooks (minimum)

Even without a full lab thermal curve in the cited tables, a minimum runbook is not optional:

1. Alert on GPU temp and power before users alert on latency.
2. Define a throttle response (shed concurrency, disable MTP, reduce max context) that is better than silent SLO death.
3. Distinguish "hot and stable" from "hot and climbing."
4. After a thermal event, run a quality smoke — some stacks behave oddly near limits.

If you have no sensors, you have no thermal control. Buy sensors before you buy another slogan about edge reliability.

## Incident timeline template

- T0: power loss / thermal trip / OOM storm detected
- T1: process down confirmed
- T2: mounts confirmed
- T3: last-known-good recipe restored
- T4: smoke suite green
- T5: limited traffic
- T6: full traffic
- T7: postmortem notes (what surprised you)

Track T7→T0 improvements across incidents. The 1.5h → ~25m recovery improvement in the lab log is the kind of curve operators should demand of themselves `[LAB: PROJECT-LOG 2026-08-22/24]`.

## Client-side honesty

Not all recovery is server-side. Clients should:

- treat mid-generation disconnects as retryable with idempotent request IDs when the product allows
- avoid assuming KV state survived a restart
- surface "model restarted, context cleared" rather than silently continuing a half-dead session

A perfect server recovery still looks broken if the UI pretends the desk still holds the conversation.

## Boundaries again

This chapter does not turn into a facilities-engineering manual. It insists that power, heat, and dependency graphs are first-class inference inputs, and that the lab's crash ledger is the model for how to talk about them: dated, measured, and corrected in public.


## Power budget as a product constraint

A wall-circuit limit is a concurrency limit in disguise. If the rack or the office circuit
cannot sustain all four GPUs at the boost the decode table assumed, your chapter 1 numbers
are from a machine you do not actually own under load.

Write power the way you write VRAM:

- rated circuit capacity
- measured draw at production concurrency
- headroom for startup surges
- whether other tenants share the circuit

When draw and latency rise together, believe the PDU. When a node "gets slow every
afternoon," check whether the afternoon is also when the HVAC loses the aisle.

## Checkpoint philosophy for inference configs

Training checkpoints save optimizer state. Inference checkpoints are boring and therefore
neglected:

- unit files and drop-ins in git
- model file checksums
- recipe flag files (chapter 6)
- a smoke-suite script pinned next to the unit
- a known-good artifact mirror on a second disk

After 08-24, the lab could resume training because checkpoints existed `[LAB: PROJECT-LOG
2026-08-24]`. After an inference host crash, you can resume service only if the boring
artifacts exist. If rebuilding the unit requires tribal memory, your RTO is "until the
right person wakes up."

## Coordination with speculative decoding under heat

Chapter 3 priced MTP under bandwidth. Heat changes the price. If clocks fall, the heavy
step \(H\) gets larger, and a draft policy that was barely winning can start losing without
any flag change. A thermal runbook that disables MTP or shortens n_max under sustained high
temp is not cowardice; it is re-solving the inequality from chapter 3 with new inputs.

Pair thermal alerts with a known degraded mode:

1. full recipe
2. no MTP
3. reduced parallel
4. reduced max context

Document the mode transitions so on-call does not invent them at 03:00.

## Human factors

The worst crash recovery failures are social: two people start conflicting services, a
"temporary" hold is forgotten, a training job is re-enabled by a timer nobody owns. Put
names on holds. Put expiry on holds. Put the active capacity owner in the status page.

The marker-file pattern works partly because it is greppable and physical on disk `[LAB:
PROJECT-LOG 2026-08-24]`. Prefer boring visibility over clever automatic healing that
nobody can see.




## The afternoon slump

A common local-inference ticket: "it's fine in the morning, slow after lunch." Possibilities:

- thermal soak
- concurrent human users
- scheduled jobs
- grid or UPS mode changes
- someone started a training run

The 08-24 resurrection story is the social version of this ticket `[LAB: PROJECT-LOG 2026-08-24]`. Without a capacity owner and a greppable hold, the afternoon slump is permanent.

## RTO/RPO for inference

Borrow the backup vocabulary:

- **RTO** — minutes until smoke suite green
- **RPO** — how much conversation or job state you accept losing (often: all in-flight KV)

Write targets. Measure against the last drill. The lab's crash recovery curve (hours toward ~25 minutes) is the kind of progress bar leadership understands `[LAB: PROJECT-LOG 2026-08-22/24]`.

## Degraded modes as first-class configs

Keep three unit templates:

- `model-full.service`
- `model-degraded-no-mtp.service`
- `model-emergency-small.service`

Document when on-call may switch. Degraded modes that exist only in someone's head do not exist.

## After-action: the only five questions

1. What failed first (power, heat, OOM, deps)?
2. What did the logs say before the failure?
3. What was the measured recovery time?
4. What tombstone recipe or monitor did we add?
5. What false fix did we avoid?

If question 4 is empty, the incident will recur.


## Field story: the dependency graph that undid a disable

The DeepSeek unit that returned despite disable because of Wants= pulls is a perfect inference fable `[LAB: PROJECT-LOG 2026-08-24]`. The operator believed in a boolean. The system believed in a graph.

Draw the graph once. Put it in the runbook. Include sidecars. Include "helpful" share units. Include anything that can call start.

## Drills beat dashboards

A green dashboard never practiced a black start. Schedule a quarterly hard stop on a spare box: kill power or drop the unit, then measure T0–T6 from chapter 7's timeline. If you cannot spare a box, you are already running a higher risk than you admit.


## Operator lab: black-start drill script

On a spare host:

1. Start production-like unit.  
2. Run smoke suite.  
3. Record steady tok/s and temp.  
4. Hard kill the unit (or pull power on a dedicated lab PDU if safe).  
5. Bring host back.  
6. Do not use tribal memory — use only runbook.  
7. Time until smoke green.  
8. Write five-line after-action.

Compare to the lab's published recovery improvement curve as inspiration, not as a leaderboard `[LAB: PROJECT-LOG 2026-08-22/24]`. Your hardware differs. Your process should still improve.

## Environmental SLOs

Consider adding SLOs that are not user-facing latency:

- max GPU temp at production concurrency
- min headroom VRAM during soak
- max unplanned restarts / week
- max minutes to smoke after hard kill

These SLOs prevent a culture where only chat latency is "real."


## What you should do Monday

1. Schedule a black-start drill on a non-critical host and record minutes to smoke.
2. Draw the service dependency graph that can resurrect heavyweight model units.
3. Define degraded modes (no MTP / reduced PAR / emergency small model) as real units.
4. Add temp/power panels next to latency panels.
5. Name a capacity owner for each GPU set and an expiry for every hold.

The 08-24 marker-file hold is a pattern you can steal without stealing the rest of the lab's stack `[LAB: PROJECT-LOG 2026-08-24]`.


## Cross-links inside this book

After recovery, chapter 6's five-minute audit is mandatory before traffic. Degraded modes that disable MTP must still pass chapter 5 smokes. Power and heat change chapter 3's inequality without changing flags — re-measure. If a crash returns a different dependency graph, chapter 8's capacity owner and class cards need an update, not only a process restart.


## One-page recovery pledge

After any hard failure:

- minutes to smoke recorded
- dependency graph checked
- degraded mode documented if used
- tombstone written if a new failure class appeared

The 25-minute recovery is not a legend to admire. It is a standard to beat with process `[LAB: PROJECT-LOG 2026-08-24]`.

## Looking ahead

Chapter 8 closes the book with fit: what a ~128 GB VRAM class machine can hold under
real recipes, what fails, and what smaller machines can honestly promise without cosplay.

The best inference stack is the one that returns from a bad Wednesday with a receipt.


# Chapter 8 — What Fits, and What Honestly Does Not

*(v2, 2026-08-28 — written by rogerai-dj for RogerAI Labs, verified by Roger AI.
Numbers carrying a `[LAB:]` marker are RogerAI Labs' own bench measurements, taken on the
reference machine described in Chapter 1 and recorded in the lab notebook; each is
reproducible by re-running the stated recipe — engine build, artifact, and flags. Claims
without a marker are labeled unmeasured.)*

## Fit is the product

A model that does not load is not a model. A model that loads only on a flag combination
you cannot remember is not a deployment. A model that loads on a 128 GB box and is sold
as "edge" for a Pi without a recipe is marketing.

This chapter is a fit map for the reference class used throughout the book, plus an
honest lower bound on what smaller machines can claim. It is also the place where the
book keeps a hard linguistic promise: **Pico is not an MCU**, and microcontroller-class
hardware is not a failed GPU box.

## The 128 GB VRAM class: working recipes

On the reference machine (4× RTX PRO 4500 Blackwell, 128 GB VRAM, 128 GB host RAM), the
matrix's fit table is the shopping list `[LAB: RESULTS-MATRIX §F]`:

| Artifact | Working recipe | Failure modes if you miss |
|---|---|---|
| DeepSeek IQ3 102 GB | n-cpu-moe 4; split 31,25,24,20 | — |
| community Q4 175 GB | n-cpu-moe 24; split 25,6,6,6; `--no-repack`; mmap; lean host RAM | VRAM-OOM; segfault; host-OOM >125 GB |
| Q8-MTP ~160 GB | n-cpu-moe 14; split 20,8,8,8; no-repack; mmap | compute-buffer OOM on "close" splits |
| Q3-MTP 143 GB | n-cpu-moe 10–11; prod split 18,9,9,8; PAR 2 | — |

Production soak on Q3-MTP added the live constraints: PAR=2, 64K ctx/slot, MTP n_max=1,
headroom 3.3–6.6 GB/card, 28K long-context recall checked `[LAB: RESULTS-MATRIX §G]`.

**Fit means recipe + headroom + a soak**, not a green load banner.

## What the same class should not pretend

Even on 128 GB VRAM:

- A 175 GB Q4 is a **conditional** citizen, not a casual default.
- Sideways requants that grow experts are not a path to fit (chapter 2).
- Long context × high parallel × heavy spill × aggressive MTP can un-fit a model that
  "loaded fine" at c=1 (chapters 3 and 4).
- vLLM versus llama.cpp changes the fit surface; engine is part of the recipe (chapter
  5).

If a vendor says "runs on 128 GB" without flags, context, and concurrency, they said
almost nothing.

## Dense versus MoE fit intuition

From §C, a dense Qwen3.6-27B Q8_0 at 29 GB is a different class of object than a 160 GB
MoE master `[LAB: RESULTS-MATRIX §C]`. It fits more places, fails differently, and still
does not repeal KV budgets at long context.

Use dense small models when:

- you need simple residency
- your quality bar matches their suite
- you want fewer placement foot-guns

Use large MoE masters when:

- the product suite needs them
- you can staff the recipe (splits, offload, MTP)
- you can pay the operational complexity

Do not sneak a MoE master into a dense-shaped runbook.

## Below the GPU: honesty without cosplay

Smaller hardware is real. It is not a moral failure. It is a different envelope.

**Prosumer single-GPU boxes.** A 24–48 GB card can host smaller dense models and some
quantized medium models with tight context. It will not host the 160 GB master recipe
from §F. Do not quote this book's DeepSeek production rows as if they transfer.

**CPU-heavy or unified-memory machines.** Possible for smaller models and serious
prompt-eval patience. Bandwidth accounting from chapter 1 still rules; expect decode far
below the reference GPU table unless the model is small enough to stay hot in memory.

**Raspberry Pi–class boards.** Good for tiny models, controllers, gateways, and demo
chat with constrained expectations. Bad for pretending a plant-floor MoE lives there.
Measure tok/s and context honestly; publish DNF when appropriate (chapter 5).

**Microcontrollers / MCU class.** Hard real-time controllers, DSP-ish budgets, kilobytes
to megabytes of memory. They run control firmware and carefully designed tiny-ML, not
general LLM decode stacks from this book's tables.

**Pico ≠ MCU.** The lab's "Pico" naming in model work refers to a small language-model
tier / product line in the Wave stack, **not** a Raspberry Pi Pico microcontroller. This
book will not claim microcontroller deployment for LLM inference on the strength of a
model nickname. If a sentence ever seems to blur those, prefer the stricter reading:
microcontrollers are out of scope for the MoE recipes measured here.

## A fit decision worksheet

1. Target hardware: VRAM, host RAM, CPU, power, cooling.
2. Target context and concurrency.
3. Product suite (tools? knowledge? abstention?).
4. Candidate artifacts with **measured** sizes.
5. Engine identity.
6. Working flags from a real load log.
7. Failed flags (keep the tombstones).
8. Soak result at duty cycle.
9. Recovery plan (chapter 7).
10. Go / no-go with the trade named.

If you cannot fill rows 6–8, you are still in demo land.

## Connecting the whole book

- **Chapter 1** — if it fits but crawls, find the bus.
- **Chapter 2** — if it fits only by wrecking experts, it does not fit your product.
- **Chapter 3** — if it fits only at n_max that loses, price speculation again.
- **Chapter 4** — if it fits weights but not desks, shrink parallel or context.
- **Chapter 5** — if you cannot measure fit failures reproducibly, fix the instrument.
- **Chapter 6** — the load log is the fit oracle.
- **Chapter 7** — fit at time zero is not fit after heat and outages.

## What this chapter refuses to claim

- We do not publish a universal SKU list for 2027 hardware.
- We do not claim Pi-class boards are useless — only that they are not 128 GB VRAM.
- We do not claim MCUs will "run LLMs soon enough" as a substitute for engineering.
- We do not claim the reference recipes are optimal — only that they worked and failed in
  the recorded ways.


## Reading §C as a fit catalog, not a trophy case

The capability table is also a fit preview `[LAB: RESULTS-MATRIX §C]`:

- ~29–38 GB dense/quant rows are "many machines" objects.
- ~60 GB class objects need serious prosumer or multi-GPU recipes.
- ~100–175 GB MoE rows are reference-class citizens with explicit spill discipline.

Promote models down this list only when the product suite forces you up. The cost is not only money. It is operational surface area: more flags, more ways to mis-place, more ways to lie with a single tok/s number.

## Headroom targets

§G's 3.3–6.6 GB per-card headroom on a working production recipe is a qualitative guide: leave room `[LAB: RESULTS-MATRIX §G]`. Exact targets depend on concurrency and context. A practical stance:

- if headroom is <2 GB/card under production PAR and ctx, you are one feature flag from pain
- if host RAM is near full with mmap recipes, you are one leak from OOM
- if you need perfect packing to load, you do not have a spare for diagnostics

Fit without headroom is a screenshot.

## Tombstones you should keep forever

Failed configs are assets. Keep a `FAILED-RECIPES.md` next to the service:

- flags
- error line
- date
- engine version
- who reproduced

§F already models this culture (segfault, host-OOM, compute-buffer OOM) `[LAB: RESULTS-MATRIX §F]`. Teams that delete failure notes rebuy the same outage.

## Smaller machines: sample honest claims

Honest claim patterns:

- "7B-class Q4, 4k context, ~N tok/s on hardware H, suite S range R."
- "Does not run 70B+ MoE masters; DNF on artifact set A."
- "Pi-class board: assistant demos only; not a multi-user production target."

Dishonest claim patterns:

- "Runs GPT-class models" without names, quants, or tok/s.
- "Edge" as a synonym for "we quanted it until the demo fit."
- "MCU LLM" without defining whether you mean firmware-class tiny models or chat models.

## Pico naming discipline (again, harder)

In this repository universe, Pico-sized language models and Raspberry Pi Pico microcontrollers are different species. The first is a model tier. The second is a microcontroller board. This book measures LLM inference recipes on GPU-class and discusses smaller boards carefully. It does **not** authorize a sentence like "our Pico runs on an MCU" as if those words shared a referent. If you need MCU inference, start a different measurement program; do not borrow this book's MoE tables.

## The last checklist before you call it "edge"

1. Named hardware.
2. Named artifact + engine + flags.
3. Load log archived.
4. Speed range under production concurrency.
5. Quality range on the product suite.
6. Soak long enough to see drift and heat.
7. Recovery drill done once.
8. Failed recipes listed.
9. Claims matched to the envelope (no Pi cosplay as 128 GB).
10. Someone human can explain the recipe without the original author in the room.

If item 10 fails, the deployment is still a research demo — even if it is in production.


## Multi-GPU fit is still fit

"Fits on 128 GB VRAM" might mean four cards. Topology matters: NVLink vs PCIe, split
strategy, whether card0 holds disproportionate compute buffers (the §F card0 OOM is the
cautionary tale) `[LAB: RESULTS-MATRIX §F]`. A model that fits on an idealized fully
connected fabric may not fit on your PCIe bifurcation.

When you change machines, re-run fit even if the VRAM sum matches. Sums are not graphs.

## The manufacturing book parallel

If you also read *Local LLMs for Manufacturing*, notice the shared ethic: local is a
constraint that creates engineering, not a discount SKU. Fit on the plant floor includes
air-gaps, custody, and recovery. Fit on the inference box includes spill, KV, and power.
The same honesty rule applies: do not claim a deployment shape you have not soaked.

## What to tell a buyer

If you are the one writing a proposal, the honest paragraph looks like this:

> On hardware H, artifact A under engine E with flags F loads with G GB headroom, serves
> concurrency C at context K with decode range R tok/s, quality suite S range Q, soak
> duration T with drift D. Failed recipes listed in appendix. Recovery drill RTO measured
> once at M minutes.

Anything much shorter is a brochure. Brochures are fine if labeled brochures. They are
not runbooks.

## Open measurements this book does not pretend to close

- full roofline plots per architecture
- exhaustive Pi and mobile SoC tables
- MCU-class LLM budgets
- every speculative method beyond the recorded MTP rows
- multi-week thermal wear studies

Where those matter to your product, measure them. The point of this book is to make the
missing measurements obvious, not to invent them.




## Fit matrix template for your fleet

Copy this into the repo of every production model:

| Artifact | HW class | Engine | Flags hash | Load | Decode range | Suite range | Soak | Owner |
|---|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |  |

Empty cells mean "not a product yet."

## Why "edge" needs a definition per sentence

Edge can mean:

- on-prem VM
- factory server room
- rugged PC on a line
- laptop
- phone
- MCU

This book used edge to mean **hardware you own, near the work, outside a rented frontier API**. It did not mean "tiny silicon." When you use the word, attach a hardware class. Otherwise you will inherit someone else's fantasy envelope.

## Connecting to SQLite-for-agents and manufacturing

Statefulness, custody, and recovery show up in sibling books. Fit is the inference-shaped slice of the same honesty. If you cannot host the model, the rest of the stack is theater. If you can host it only by lying about tok/s or suite ranges, the theater is just more expensive.

## Final operator brief

Before go-live:

1. Recipe file committed.
2. Failed recipes committed.
3. Load log sample committed.
4. Suite ranges committed.
5. Soak notes committed.
6. Recovery drill minutes committed.
7. Capacity owner named.
8. Hardware class named without cosplay.

When those eight exist, you do not need bravado. You have a system.


## Field story: the 128 GB demo that was a 4 GB headroom prayer

§G's headroom band exists so you do not confuse "it loaded" with "it will survive Monday" `[LAB: RESULTS-MATRIX §G]`. The demo that loads with crumbs of free VRAM is a party trick. Production needs slack for concurrent spikes, longer contexts, and the next engineer debugging with an extra process.

If leadership wants the demo as production, show them the headroom number and the §F tombstones. Make the risk concrete.

## Portfolio fit

A real fleet usually needs more than one artifact:

- small dense for cheap bulk
- medium for default chat
- large MoE master for hard cases

Route between them with honesty, not ego. Fit is easier when not everything needs the master. Chapter 2's quality ladder and chapter 5's suite ownership make that routing measurable.


## Operator lab: portfolio routing sketch

Define three routes:

- **cheap** — small dense, strict schema, bulk traffic
- **default** — medium model, general chat
- **hard** — MoE master, tools, long context, humans waiting

Measure each route's fit envelope separately. The failure mode is routing everything to hard because it scores best on a trophy suite. That is how you turn a 128 GB box into a single-tenant luxury good.

Use chapter 5's suite ownership to decide promote/demote between routes. Use chapter 6's recipe registry to keep each route boring.

## Hardware class cards (fill in for your fleet)

**Class A — reference multi-GPU 128 GB.** Can host §F MoE recipes with headroom if flags are right.  
**Class B — single 24–48 GB.** Dense and medium quants; DNF large MoE masters.  
**Class C — unified memory / workstation.** Case-by-case; bandwidth often the surprise.  
**Class D — Pi-class.** Demo and controller adjacent; not multi-user MoE.  
**Class E — MCU.** Out of scope for this book's LLM recipes.

Put every host into a class before you assign artifacts. Class mismatch is the root failure behind many "edge" disappointments.


## What you should do Monday

1. Classify every host into a hardware class card before assigning artifacts.
2. Fill one fleet fit matrix row for each production model (including blanks).
3. Publish DNF lists for artifacts that will not be attempted on small classes.
4. Enforce Pico≠MCU language in internal docs and customer decks.
5. Demand headroom numbers in every "it fits" claim.

Fit is the gate that keeps the rest of this book honest. Without it, bandwidth essays become cosplay `[LAB: RESULTS-MATRIX §F/§G]`.


## Cross-links inside this book

Fit is where the book becomes a fleet policy. Chapter 2 decides which artifacts deserve a row. Chapter 6 keeps rows honest at deploy time. Chapter 7 keeps rows honest after Wednesday. Chapter 5 prevents trophy suites from assigning masters to every route. If a route cannot fill the fit matrix, it is not a route yet.


## After the matrix, the calendar

Fit is not only a row in a table. It is a calendar:

- weekly recipe drift check
- monthly black-start drill
- quarterly suite recalibration
- every engine upgrade as a mini re-fit

The lab's crash recoveries and soak notes only help if your organization has a cadence that reads them into action `[LAB: PROJECT-LOG 2026-08-22/24; RESULTS-MATRIX §G]`. A static PDF of this book without that cadence becomes another shelf ornament. Use the Monday checklists. Put them on a real calendar.


## One-page fit pledge

No "runs on edge" sentence without:

- hardware class
- artifact id
- recipe hash
- headroom
- DNF list for the classes below it

If the sentence cannot carry those five, it is cosplay. This book ends where the cosplay ends `[LAB: RESULTS-MATRIX §F/§G]`.


## Last word

Measure the box you have. Name the recipe you ship. Keep the failures visible. That is fit; that is edge; that is the whole job.

## Closing the book

Local inference becomes real when three receipts match:

1. **bytes** (bandwidth accounting),
2. **recipes** (flags, placement, speculation, cache),
3. **honesty** (ranges, controls, crash drills, fit tombstones).

The edge is not a place where physics sleeps. It is where physics is close enough to feel
with your hands — on a named box, with a log, under a budget you can explain.

If you carry only one sentence out of these eight chapters, carry this:

**Ship the recipe you measured, on the machine you named, with the failures left visible.**



---

# Inference on the Edge

## Quantization, speculation, and the physics of local models

O'AILLY Industrial Series Nº 2 · verified by Roger AI

## Contents

- Chapter 1: What a Token Costs
- Chapter 2: Quantization without Folklore
- Chapter 3: Speculative Decoding Economics
- Chapter 4: KV Cache, Context, and the Traps
- Chapter 5: Benchmarking Honestly
- Chapter 6: The Load Log Tells the Truth
- Chapter 7: Thermals, Power, and Crashes
- Chapter 8: What Fits, and What Honestly Does Not

## Introduction

This book is for people who run language models on hardware they own and are tired of
advice that evaporates when the load log is open. It assumes you can use a shell and read
a server startup dump. It does not assume a research ML background.

The spine is a single laboratory reference envelope — multi-GPU, 128 GB VRAM class,
llama.cpp-centered measurements with explicit exceptions — and a set of tables that
survived promotion decisions, aborted requants, crash recoveries, and tool-suite noise.

A word on the numbers, so you can trust or challenge them. Every figure carrying a
`[LAB:]` marker is **RogerAI Labs' own bench measurement** on the reference machine
described in Chapter 1, taken with the recipe printed beside it — engine build, artifact,
and flags — so you can re-run it and get your own range. The marker names the section of
the lab notebook where the run was first recorded; it is the lab's own index to its own
instrument, not a source you must go and fetch. Where a claim is not measured, the prose
labels it unmeasured; where a number is an approximation or a lab interpretation, the text
says so rather than dressing it as precision. The provenance page states who ran and
verified them.

If you want a cloud vendor tour, this is the wrong book. If you want to price tokens in
bytes, precision, spill, cache, heat, and fit, continue.


---

# Provenance

**WRITTEN BY** rogerai-dj, operated by RogerAI Labs.

**ABOUT THE MEASUREMENTS.** The quantitative spine of this book — every tok/s, MMLU,
tool-hardmode, spill, headroom, and acceptance figure carrying a `[LAB:]` marker — is
**RogerAI Labs' own bench measurement**, not a citation the reader is asked to go and
resolve in a file they do not have. The apparatus is stated in the book: a single named
reference machine (4× RTX PRO 4500 Blackwell, 128 GB VRAM; Threadripper 9970X; 128 GB
DDR5), llama.cpp unless a row says otherwise, warm single-stream decode as the default
speed, with the exact recipe (engine build, artifact, and flags) given alongside each
number so it can be **re-run and confirmed or refuted**. The `[LAB:]` marker names the
section of RogerAI Labs' internal lab notebook (`RESULTS-MATRIX.md` §§A–G,
`PROJECT-LOG.md` dated entries) where that run was first recorded; it is a lab-notebook
index, in the manner of any industrial white paper reporting its own instrument, not a
pointer to an external authority. Where a claim is not measured, the prose says so, and
where a measurement is an approximation or an interpretation the text labels it as such.

**GROUNDED IN**
- RogerAI Labs' bench on the reference machine described above (the primary instrument).
- The lab notebook that recorded those runs: `RESULTS-MATRIX.md` (engine, quant,
  concurrency, MTP, fit, soak) and `PROJECT-LOG.md` (dated crash recoveries, cache-reuse
  notes, hybrid KV arms).
- llama.cpp, the open inference engine used for the measured decode numbers:
  https://github.com/ggml-org/llama.cpp
- llama.cpp build/backend notes for GPU vs CPU indexer paths:
  https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md

**VERIFIED BY** Roger AI, RogerAI Labs. The measured claims in this book have been checked
against the RogerAI Labs lab record they were drawn from, and the arithmetic and internal
consistency of the tables have been reconciled for this edition.

**DISCLOSURE** Written by a model stack (rogerai-dj) operated by RogerAI Labs. The numbers
are the lab's own bench measurements, reported with the recipe needed to reproduce them and
verified against the lab record. No hidden AI, no hidden humans.

**REVIEW TRAIL** publishes with the book: the complete critic reviews, this revision, and
the judge verdict.

**C2PA** signed at publication.


---

# Back Matter

## Glossary

- acceptance rate: fraction of draft tokens kept under speculative decoding
- aggregate throughput: total tokens/second across concurrent streams
- artifact: a concrete weight file (e.g. a GGUF) with identity and checksum
- bandwidth-bound: regime where memory movement, not FLOPS, limits decode
- black start: recovery from full process or power loss
- cache reuse: serving feature that reuses prefix KV across requests
- compute-buffer OOM: allocation failure for workspace, not only weights
- concurrency (c): number of simultaneous in-flight generations
- control: measurement that isolates the variable not under study
- decode: per-token generation after prefill
- degraded mode: intentional reduced recipe under heat or incidents
- DNF: did not finish / not feasible under stated method
- edge: hardware you own near the work; not a synonym for MCU
- expert precision: bit-width policy for MoE expert bodies
- fit: load + headroom + soak under a named recipe
- GGUF: common local weight container used with llama.cpp
- headroom: free VRAM/RAM left after a successful load under target traffic
- host OOM: host memory exhaustion, often mislabeled as a GPU fault
- indexer: engine component whose CPU vs GPU placement moved §A tok/s
- KV cache: per-context key/value working set for attention history
- last-known-good: pinned recipe that last passed smoke and suite
- llama.cpp: open inference engine used for most lab rows in this book
- load log: startup/placement output treated as ground truth
- mmap: memory-map weights from disk; interacts with host RAM budgets
- MoE: mixture of experts; sparse activation, dense packaging problems
- MTP: multi-token prediction / multi-token draft head speculation
- n_ctx_slot: per-slot context after parallel divides the budget
- n_max: maximum draft tokens proposed per speculative step
- n-cpu-moe: offload count for MoE layers onto CPU paths
- placement: device map of tensors/layers/indexers
- prefill: prompt ingestion path that builds initial KV
- promotion packet: quality+speed+fit evidence bundle for a recipe change
- recipe: full binary+artifact+flags bundle that produces a number
- reference box: the lab's 4× RTX PRO 4500 / 128 GB VRAM measurement host
- repack: weight repacking path; can segfault some artifacts if wrong
- residence: weights kept on the intended fast device path
- roofline: hardware model relating intensity to bandwidth ceilings
- RTO: recovery time objective after hard failure
- sideways requant: precision rewrite that does not buy shrink/residence
- soak: sustained load test watching drift, heat, errors
- speculation: draft-and-verify decoding to raise accepted tokens per heavy step
- spill: layers/experts living off the fast path
- suite: versioned evaluation set tied to a product decision
- tensor split: multi-GPU partition vector
- tok/s: tokens per second; always name which speed kind
- tombstone: retained failed recipe or aborted experiment note
- tool hardmode: lab tool-use suite referenced in §C/§D
- vLLM: alternate serving engine appearing in some reference rows
- warm decode: steady-state generation after load, not first-token cold start

## References

- RogerAI Labs RESULTS-MATRIX.md — Complete test matrix, DeepSeek-V4-Flash project and later sections (§A–§G and notes)
- RogerAI Labs PROJECT-LOG.md — 2026-08-22/24 power crash recoveries; K3-Encode cache-reuse notes; hybrid KV arms
- llama.cpp project: https://github.com/ggml-org/llama.cpp
- llama.cpp build docs: https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md
