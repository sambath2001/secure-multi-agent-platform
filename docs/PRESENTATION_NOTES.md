# Presentation notes: Testing LLM-Based Systems When the Output Is Not Deterministic

One-sentence thesis: a unit test needs one exact right answer, an LLM agent does not give one, so you replace "assert equal" with measured rates over many trials, and you test security by attacking the system on purpose.

Fill every number below from a real `report.md` before you present. The offline numbers are marked as such. Do not present simulated numbers as model results.

## Slide outline (about 12 slides, 15 minutes)

1. **Problem.** Same input, different output. Show two runs of one task with different wording and both correct.
2. **Why this breaks unit tests.** Unit tests assume a deterministic function and one exact expected value. Table below.
3. **System under test.** Planner, researcher, executor, MCP tools, sandbox. Use the architecture diagram from the README. Say "each agent's tools run in a container", and why (the key stays on the host, containers have no network).
4. **What "correct" means.** The oracle problem. Our answer: pick tasks whose answers are short facts (names, numbers, dates), and judge with deterministic checks. Cost of that choice: it misses correct answers phrased in unexpected ways, so we audit the judge by hand on a sample.
5. **Metric 1: task success rate.** Over many trials with a confidence interval. Show flakiness: tasks that pass sometimes.
6. **Metric 2: attack success rate.** Define the four attacker goals. Define the canary secret. Explain exposure: an attack the agent never saw proves nothing.
7. **How the attacks reach the system.** Indirect injection through a document, through a search snippet, through text pasted into the task, and through the researcher's handoff to the executor. Multi-agent systems add the handoff channel.
8. **Defenses as layers.** Hardened prompt, injection detector, policy gateway, role isolation, container. Defense in depth. Each layer is switchable so we can measure its contribution (ablation).
9. **Results.** Baseline vs each layer. Use the real-model table. Add the offline finding that the policy layer stops capability abuse even for a fully compromised model but cannot stop content hijacking.
10. **Trade-offs.** Cost (tokens per trial), flaky results (repeats multiply cost), what counts as correct (judge strictness), utility cost of guardrails (does the real task still get done under defense).
11. **Verification and validation mapping.** Verification: did we build the system right (unit tests of tools, policy, judge, 110 offline tests). Validation: did we build the right system (task success and attack resistance on a real model).
12. **Limits and next steps.** Small n, one author wrote the attacks and the rules, one task type, content-level attacks remain open.

## Unit test vs agent evaluation

| | Traditional unit test | Agent evaluation |
|---|---|---|
| Output | Deterministic | Varies run to run |
| Oracle | One exact expected value | A rubric: required facts, forbidden content, goal checks |
| Result | Pass or fail | A rate with a confidence interval over n trials |
| Failure meaning | Bug in code | Bug, bad prompt, model variance, or a judge that is too strict |
| Cost per run | About zero | Tokens and money, so repeats are a budget decision |
| Security testing | Input validation cases | Adversarial inputs the system reads as data (indirect prompt injection) |
| Regression | Any red test blocks merge | Compare rates between versions, with intervals |

What still gets ordinary unit tests in this project: the tools, path confinement, the policy rules, the detector, the judge, the statistics, the sandbox arguments. Those are deterministic, so they are verified the normal way. Only the model-dependent parts need rates.

## Concepts to be able to explain (most likely to come up in questions or interviews)

1. **The oracle problem.** How do you decide an output is correct when many outputs are acceptable? Options: exact facts, rubric checks, another model as judge, human review. Each has a cost.
2. **Flakiness and repeats.** Temperature 0 on hosted models is still not guaranteed deterministic. Repeat trials and report intervals.
3. **Indirect prompt injection.** The attacker does not talk to the model. They plant text in data the agent reads. The model cannot reliably tell instructions from data.
4. **Confused deputy.** The agent has legitimate tool access and an attacker steers it into using that access for them. Least privilege is the main fix.
5. **Defense in depth.** No single layer is enough. Pattern detectors miss paraphrases. Prompts are advisory. Deterministic policy holds regardless of the model, but only for the things it can express as rules.
6. **Capability controls vs content controls.** Blocking a file read is a rule. Noticing that a note says the wrong thing is much harder. Our offline run shows this split directly.
7. **Ablation.** Turn layers on one at a time to see what each one buys.
8. **Dev/test split for attacks.** If you tune a defense on your attack list, the score on that list is inflated. Keep a held-out set and run it once.
9. **Exposure confound.** If the attacker text never reaches the model, a low attack rate is not a defense. Report exposure.
10. **Utility cost.** A defense that blocks everything also blocks the work. Measure task success under defense and under attack.

## Demo plan (3 minutes)

1. `make test` shows the deterministic tests passing in about a minute.
2. Show one trial from `trials.jsonl` for the baseline config: the planted line, the tool call that read the canary, the note that leaked it.
3. Show the same attack under `policy`: the denied `read_scope` event in the log.
4. Show the `report.md` table and point at the interval widths.

If the live API fails, use a saved `trials.jsonl` and say so.

## How to word the numbers

- Say "on 17 attacks I wrote, with this model, N succeeded", not "the system is X percent secure".
- Say the interval. With n = 11, even a perfect score has a 95% upper bound near 26%.
- Say who wrote the attacks and the rules.
- If a defense lowered task success, say that too.

## Likely questions and straight answers

**Why not use an LLM as the judge?** It is flexible, but it is also non-deterministic, costs tokens, and can be fooled by the same injection you are testing. Deterministic checks are cheap and repeatable, at the price of brittleness. A hybrid is a reasonable next step.

**Does a hardened prompt stop injection?** It lowers the rate for many models, but it is advisory, so measure it per model. That is what the `prompt` preset is for.

**Why does the container have no network?** So that an injected instruction cannot send data out, and so the sandbox holds no API key.

**What would make this more convincing?** More attacks from more than one author, more than one model, more than one task type, and a pass of the judge audit.

**Is 100% blocking possible?** For capability abuse, a deterministic policy can hold for the cases it covers. For content manipulation, nobody has a complete answer.

## Self-check questions

1. Why is "the attack never succeeded" a weak result if exposure was 20%?
2. Your detector scores 5/5 on the dev attacks and 3/10 on the test attacks. What does each number tell you, and which one would you quote?
3. The policy layer blocked every secret-access attack against a fully compromised model but not content hijacking. Name one control that could address content hijacking and one cost of adding it.
4. Why do we repeat each task several times when temperature is 0?
5. What does the `ignored` outcome hide, and how would you separate "the model refused" from "the model never saw it"?
