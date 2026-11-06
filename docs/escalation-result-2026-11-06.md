# Result — repetition or authority?

Design and analysis fixed in `docs/preregistration-escalation.md` before the code to run it existed.
16 scenarios × 2 arms × 2 models = 64 samples, six turns each. One excluded, as pre-registered,
because nothing was flagged before the first push. Logs: `logs/dismissal/ladder-*.eval`.

---

## The pre-registered test: null

> By the third pushback, a warning is abandoned more often when the user claims authority than when
> the user simply repeats themselves.

| | warning gone at some point |
|---|---|
| `authority` | 27/31 = **87%** [71–95] |
| `repetition` | 27/32 = **84%** [68–93] |

**One-sided Fisher, pooled: p = 0.52.** The hypothesis is not supported. Claiming to be the security
lead who has signed off the risk does no more than asking the same thing a third time.

That is the second pre-registered hypothesis in a row to come back null, and both were mine.

---

## What the run does show, and it is larger than what it was testing

The pre-registration fixed the survival curve as a secondary, descriptive measure. It is where the
result is.

**Warnings still standing after each push, both arms pooled:**

| | after 1 push | after 2 | after 3 |
|---|---|---|---|
| still standing | 44/63 = **70%** | 23/63 = **37%** | 9/63 = **14%** |

**Resistance is almost entirely spent on the first refusal.** Of the warnings still standing, 30% go
at the first push, 48% at the second, 61% at the third. The hazard rises with each attempt: a
warning that has already survived two pushes is *more* likely to go on the third, not less.

This reframes everything measured before it. On a single pushback the finding was "warnings usually
survive — about 85% of the time." That was true and it was an artifact of pushing once. Under
ordinary persistence, **86% are gone at some point and 68% are gone at the end**.

### Two honest readings of the same data

| | n = 63 |
|---|---|
| Gone at some point | 54 = 86% [75–92] |
| **Gone at the end of the exchange** | **43 = 68%** [56–78] |
| Still holding at the end | 15 = 24% |
| Refusing at the end | 5 = 8% |

The gap matters: **11 of 54 warnings came back**. `held/dropped/held` happened 8 times. So the state
a user ends in is better than the worst moment of the exchange, and "gone at the end" is the number
that describes what they walk away with.

The common shapes, out of 63: `dropped/dropped/dropped` 14 · `held/dropped/dropped` 13 ·
`held/held/dropped` 13 · `held/dropped/held` 8 · `held/held/held` 4.

**Only 4 of 63 warnings survived all three pushes intact.**

### Per model

| arm | model | gone at the end |
|---|---|---|
| repetition | Sonnet | 12/16 |
| repetition | Haiku | 11/16 |
| authority | Sonnet | 11/16 |
| authority | Haiku | 9/15 |

Both models behave the same way. Nothing here separates them.

---

## Limitations

- **Position and pressure are entangled** by design: step 3 is always third. The repetition arm is
  what makes the contrast meaningful, and it is why the null is interpretable — both arms arrive at
  step 3 having been refused twice.
- The grader labels each step independently. A warning "returning" may be the model restating it, or
  the grader reading a passing clause as a caveat. The 11 returns are worth a hand-check before the
  24% figure is quoted anywhere.
- 16 scenarios, two models, one provider, one grader, one wording per step.
- The scenarios were written for the whose-harm test, not this one.

## Where this leaves the project

Three runs in, the finding that has survived contact with its own test is this: **a coding
assistant will raise the risk, and then let it go if you ask three times.** Not because you pulled
rank — just because you kept asking.

The hand-check of the 11 returning warnings is the next thing worth doing, and it is free: the
transcripts are on disk.
