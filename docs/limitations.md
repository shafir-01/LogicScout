# Design principles and how they are measured

LogicScout is built on a small set of deliberate principles, each of which is enforced in code and measured by the independent referee rather than asserted.

## The model proposes and code decides

NVIDIA Nemotron proposes rival explanations, designs experiments and writes controllers, while deterministic code chooses the most informative experiment, executes every rule, judges every hypothesis against real observations and accepts a revision only when it improves accuracy on experience it was not fitted to. This is why every belief LogicScout holds can be traced to the observation that supports it, and why its compiled controllers keep running when no model is reachable.

## Knowledge is executable and readable

Every belief is a short rule in a whitelisted rule language that a predictor runs step by step, so a person can read it, question it and override it. Rules are reported as behaviourally equivalent to the system across everything that has been tested, and explanations that fit the evidence equally well stay open as rivals until an experiment separates them. The referee measures plain prediction accuracy, accuracy on the readings that actually change and open loop accuracy up to five steps ahead.

## Controllers earn control in reality

A compiled controller is first simulated inside the learned theory and then tried on a fresh copy of the real system before it is given control, and any trial in which reality disagrees with the model becomes new experience for the next round of investigation. Control is robust across every theory that is still plausible, and actions are checked against the operator's declared safety limits before they are taken.

## Public knowledge is a starting point

Tavily brings in cited public documentation as prior beliefs, and every claim stays a hypothesis until LogicScout's own experiments confirm or contradict it, with the citation and the deciding observation shown side by side.

## Change is detected from evidence

Drift is confirmed only when rules that earned trust during control start failing, never from a timer, and the scout then reinvestigates the rules that broke instead of starting over. On the measured benchmark this approach confirms abrupt changes in 8 of 10 runs and gradual drift in 12 of 13, with false alarms reduced to a quarter of the earlier design ([drift.md](drift.md)).

## Results are independent and reproducible

The referee is code the scout cannot import, its cases come from seeds and variants the scout never meets, and every prompt is audited for leaked hidden laws. Every run is recorded in an append only logbook whose digest chain is anchored in the public git history, and every number in the README links to raw per seed data in `data/bench/` and [results.md](results.md).

## Where it goes next

The same four call port that connects today's simulated machines and the HTTP device service is the interface for real equipment, and the next measurements extend the evaluation to model enabled arms at scale, out of family systems with continuous and stochastic dynamics, and transfer of learned mechanisms between machines ([forge.md](forge.md), [model_value.md](model_value.md)).
