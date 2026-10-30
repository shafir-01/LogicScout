import random

from logicscout.contracts import Action, Observation, Rule, Theory
from logicscout.noise import NoisyPort, estimate_noise, noisy_accuracy, noisy_persistence, tolerances
from logicscout.sandbox import open_session
from logicscout.theory import accuracy, compare


def _counter(sigma: float, n: int = 200, seed: int = 1):
    """x += 1 on 'inc', unchanged on 'wait'; y never changes. Readings carry Gaussian noise."""
    rng = random.Random(seed)
    out, x = [], 10
    read = lambda t, v: {"t": t, "x": v + rng.gauss(0, sigma), "y": 5 + rng.gauss(0, sigma)}  # noqa: E731
    obs = Observation(t=0, fields=read(0, x))
    for t in range(n):
        a = Action(name="inc" if t % 3 == 0 else "wait")
        if a.name == "inc":
            x += 1
        nxt = Observation(t=t + 1, fields=read(t + 1, x))
        out.append((obs, a, nxt))
        obs = nxt
    return out


THEORY = Theory(world_id="toy", rules=[Rule(id="r1", statement="inc adds 1", action="inc", effects={"x": "obs.x + 1"},
                                            status="supported")])


def test_compare_default_unchanged_and_tol_is_per_field():
    p, o = {"x": 10.0, "y": 3.0, "b": True}, {"t": 1, "x": 10.4, "y": 3.4, "b": True}
    assert [m.field for m in compare(p, o)] == ["x", "y"]
    assert [m.field for m in compare(p, o, tol=None)] == ["x", "y"]
    assert [m.field for m in compare(p, o, tol={"x": 0.5})] == ["y"]
    assert compare({"b": False}, {"b": True}, tol={"b": 5.0})  # bools never get a band
    assert compare({"x": None}, {"x": 1.0}, tol={"x": 5.0})


def test_clean_data_estimates_zero_noise():
    sig = estimate_noise(_counter(0.0))
    assert sig == {"x": 0.0, "y": 0.0}
    assert tolerances(sig) == {}


def test_noise_estimate_tracks_sigma():
    for sigma in (0.5, 1.0, 2.0):
        sig = estimate_noise(_counter(sigma))
        assert 0.5 * sigma <= sig["y"] <= 1.6 * sigma, (sigma, sig)
        assert 0.5 * sigma <= sig["x"] <= 1.6 * sigma, (sigma, sig)


def test_repeated_contexts_isolate_noise():
    # same (obs, action) context repeated, next reading noisy: estimator uses within-context spread
    rng = random.Random(3)
    b = Observation(t=0, fields={"t": 0, "x": 1})
    trs = [(b, Action(name="go"), Observation(t=1, fields={"t": 1, "x": 2 + rng.gauss(0, 1.0)})) for _ in range(60)]
    assert 0.7 <= estimate_noise(trs)["x"] <= 1.3


def test_noisy_accuracy_recovers_correct_theory():
    trs = _counter(1.0)
    tol = tolerances(estimate_noise(trs))
    exact, noisy = accuracy(THEORY, trs), noisy_accuracy(THEORY, trs, tol)
    assert exact < 0.4 < 0.7 < noisy  # exact still allows 2% relative, so a few large readings pass
    assert noisy_accuracy(THEORY, trs, None) == exact
    assert noisy_persistence(trs, tol) <= noisy + 0.05


def test_noisy_port_is_deterministic_and_leaves_t_clean():
    def run(seed):
        port = NoisyPort(open_session("plant").port, sigma=1.0, seed=seed)
        obs = [port.reset(3)]
        for _ in range(5):
            obs.append(port.act(Action(name="wait")).observation)
        obs.append(port.observe())
        return obs

    a, b, c = run(7), run(7), run(8)
    assert [o.fields for o in a] == [o.fields for o in b]
    assert [o.fields for o in a] != [o.fields for o in c]
    assert [o.fields["t"] for o in a[:6]] == list(range(6))
    assert a[-1].fields == a[-2].fields  # observing twice gives the same reading
    assert isinstance(a[0].fields["tripped"], bool)
    clean = NoisyPort(open_session("plant").port, sigma=0.0).reset(3)
    assert clean.fields == open_session("plant").port.reset(3).fields
