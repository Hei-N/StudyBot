"""Stage 6.4: the local-model benchmark tool (scripts/benchmark_local_models.py).

Nothing here contacts Ollama or runs a system command: models are scripted
fakes injected through `studybot.app.create_model`, and every `runner` is a
stub.
"""

import json
from pathlib import Path

import pytest

import scripts.benchmark_local_models as bench
import studybot.app as app_module
from studybot.config.verification_guard import UnsafeVerificationEnvironmentError
from studybot.core.exceptions import ModelError
from studybot.core.messages import Message, Role
from studybot.core.reasoning_mode import ReasoningMode
from studybot.core.teaching_mode import TeachingMode
from studybot.models.base import ModelCapabilities, ProviderStatus
from scripts.benchmark_local_models import (
    BenchmarkScenario,
    CandidateScore,
    ModelBenchmarkSummary,
    TurnMeasurement,
)

SECRET_ANSWER = "ANSWER-TEXT-7f3a"
SECRET_PROMPT = "PROMPT-TEXT-9c1b"

CAPS = ModelCapabilities(True, True, True, True, 262144)


# --- fakes --------------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeSessions:
    """Just enough of `SessionService` for `measure_turn`, with a scripted
    timeline: ("tick", seconds) advances the clock, anything else is a chunk."""

    def __init__(self, clock, script, persisted=None):
        self.clock = clock
        self.script = script
        self.history = []
        self.persisted_override = persisted
        self.raise_after = None

    def send_streaming_to_chat(self, chat_id, prompt):
        self.history.append(Message.user(prompt))
        visible = []
        for item in self.script:
            if isinstance(item, tuple):
                self.clock.now += item[1]
            else:
                visible.append(item)
                yield item
        if self.raise_after is not None:
            raise self.raise_after
        content = self.persisted_override if self.persisted_override is not None else "".join(visible)
        self.history.append(Message.assistant(content))

    def get_chat_history(self, chat_id):
        return list(self.history)


def measure(script, **kwargs):
    clock = Clock()
    sessions = FakeSessions(clock, script, kwargs.pop("persisted", None))
    if "raise_after" in kwargs:
        sessions.raise_after = kwargs.pop("raise_after")
    measurement, visible = bench.measure_turn(
        sessions, "chat", "prompt", scenario_id="s", turn_number=1, clock=clock, **kwargs
    )
    return measurement, visible


class ScriptedModel:
    """A `ModelProvider` for the real-stack path. `reply_for(messages, call_number)`
    returns the text, or raises."""

    name = "scripted"

    def __init__(self, reply_for=None, *, reachable=True, available=True, capabilities=CAPS):
        self.reply_for = reply_for or (lambda messages, n: f"{SECRET_ANSWER} reply {n}")
        self.reachable, self.available, self.capabilities = reachable, available, capabilities
        self.calls = 0

    def generate(self, messages, *, reasoning_mode=ReasoningMode.FAST):
        raise NotImplementedError

    def stream(self, messages, *, reasoning_mode=ReasoningMode.FAST):
        self.calls += 1
        text = self.reply_for(list(messages), self.calls)
        yield ""  # progress signal first, like a thinking model
        yield ""
        for i in range(0, len(text), 5):
            yield text[i : i + 5]

    def get_status(self):
        return ProviderStatus("scripted", self.reachable, "scripted-model", self.available if self.reachable else None)

    def get_capabilities(self):
        return self.capabilities


NO_COMMANDS = lambda argv: None  # noqa: E731 — a runner that finds nothing


@pytest.fixture
def models(monkeypatch):
    """Maps model tag -> ScriptedModel; `studybot.app.create_model` serves it."""
    registry = {}
    monkeypatch.setattr(app_module, "create_model", lambda settings: registry[settings.ollama_model])
    monkeypatch.setattr(bench, "run_command", NO_COMMANDS)
    return registry


TINY = (
    BenchmarkScenario(
        "tiny_quick", None, None, TeachingMode.QUICK, ReasoningMode.FAST, (f"{SECRET_PROMPT} question one",)
    ),
    BenchmarkScenario(
        "tiny_practice",
        "Course",
        "C1",
        TeachingMode.PRACTICE,
        ReasoningMode.DEEP,
        (f"{SECRET_PROMPT} start", bench.LEARNER_ANSWER, "next"),
    ),
)


# --- measuring a turn ---------------------------------------------------------------


def test_first_non_empty_chunk_defines_first_visible_latency():
    measurement, visible = measure([("tick", 2.0), "Hel", ("tick", 3.0), "lo"])
    assert measurement.first_visible_seconds == pytest.approx(2.0)
    assert measurement.total_seconds == pytest.approx(5.0)
    assert visible == "Hello"
    assert measurement.visible_characters == 5


def test_empty_progress_chunks_are_ignored_for_latency_and_content():
    measurement, visible = measure(["", ("tick", 4.0), "", "", ("tick", 1.0), "Hi", ""])
    assert measurement.first_visible_seconds == pytest.approx(5.0)  # not 0.0 / 4.0
    assert visible == "Hi"


def test_a_turn_with_no_visible_chunk_has_no_first_visible_time():
    measurement, _ = measure(["", ""], persisted="x")
    assert measurement.first_visible_seconds is None


def test_persisted_message_equal_to_visible_stream_matches():
    measurement, _ = measure(["abc", "def"])
    assert measurement.persistence_match is True
    assert measurement.integrity_pass is True
    assert measurement.error is None


def test_persisted_message_differing_from_visible_stream_is_a_mismatch():
    measurement, _ = measure(["abc", "def"], persisted="abcdeX")
    assert measurement.persistence_match is False


@pytest.mark.parametrize("leak", ["plan</think>answer", "<think>x", "ok </think>"])
def test_think_markers_in_visible_output_fail_integrity(leak):
    measurement, _ = measure([leak])
    assert measurement.integrity_pass is False


def test_think_marker_in_persisted_history_fails_integrity_even_if_stream_looked_clean():
    measurement, _ = measure(["clean"], persisted="clean")
    assert measurement.integrity_pass is True
    clock = Clock()
    sessions = FakeSessions(clock, ["clean"])
    sessions.history.append(Message.assistant("old </think> leak"))
    measurement, _ = bench.measure_turn(
        sessions, "c", "p", scenario_id="s", turn_number=1, clock=clock
    )
    assert measurement.integrity_pass is False


def test_a_failed_generation_is_recorded_not_raised():
    measurement, visible = measure(["partial"], raise_after=ModelError("backend says something private"))
    assert measurement.error == "ModelError"  # the class name only, never the message
    assert "private" not in repr(measurement)
    assert measurement.persistence_match is True  # no assistant message was left behind


# --- real-stack scenario runs -------------------------------------------------------


def run_benchmark(models, name="m1", scenarios=TINY, **kwargs):
    return bench.benchmark_model(
        name, scenarios, runner=NO_COMMANDS, unload=lambda n: None, **kwargs
    )


def test_benchmark_runs_through_the_real_stack_and_persists_answers(models):
    models["m1"] = ScriptedModel()
    summary = run_benchmark(models)

    assert summary.not_evaluated_reason is None
    assert [m.scenario_id for m in summary.measurements] == ["tiny_quick", "tiny_practice", "tiny_practice", "tiny_practice"]
    assert all(m.persistence_match and m.integrity_pass and m.error is None for m in summary.measurements)
    assert all(m.first_visible_seconds is not None for m in summary.measurements)
    assert summary.capabilities == CAPS
    assert summary.thinking_classification == "toggleable"
    assert summary.all_integrity_pass and summary.all_persistence_match


def test_warmup_is_excluded_from_scored_measurements(models):
    models["m1"] = ScriptedModel()
    summary = run_benchmark(models)
    assert all(m.scenario_id != "warmup" for m in summary.measurements)
    assert summary.warmup_total_seconds is not None
    assert models["m1"].calls == 1 + 4  # one warm-up + the scored turns


def test_learner_answer_placeholder_uses_supplied_answer_else_flagged_fallback(models):
    seen = []

    def reply(messages, n):
        seen.append(messages[-1].content)
        return "ok"

    models["m1"] = ScriptedModel(reply)
    with_answer = run_benchmark(models, learner_answers={"tiny_practice": ["MY-ANSWER"]})
    assert "MY-ANSWER" in seen and bench.FALLBACK_LEARNER_ANSWER not in seen
    assert not any(m.used_fallback_answer for m in with_answer.measurements)

    seen.clear()
    without = run_benchmark(models)
    assert bench.FALLBACK_LEARNER_ANSWER in seen
    assert [m.used_fallback_answer for m in without.measurements if m.scenario_id == "tiny_practice"] == [False, True, False]


def test_teaching_and_reasoning_modes_reach_the_model(models):
    received = []

    class Recording(ScriptedModel):
        def stream(self, messages, *, reasoning_mode=ReasoningMode.FAST):
            received.append((messages[0].content, reasoning_mode))
            return super().stream(messages, reasoning_mode=reasoning_mode)

    models["m1"] = Recording()
    run_benchmark(models, scenarios=TINY[1:])
    from studybot.core.mode_prompts import get_mode_prompt

    scored = received[1:]  # skip warm-up
    assert all(get_mode_prompt(TeachingMode.PRACTICE) in system for system, _ in scored)
    assert all(mode is ReasoningMode.DEEP for _, mode in scored)
    assert "Course" in scored[0][0]  # course context built by StudyBot, not the benchmark


def test_unexpected_failure_is_retried_once_in_a_fresh_chat(models):
    def reply(messages, n):
        if n == 2:  # first scored turn, first attempt
            raise ModelError("transient")
        return "fine"

    models["m1"] = ScriptedModel(reply)
    summary = run_benchmark(models, scenarios=TINY[:1])

    assert summary.retried_scenarios == ("tiny_quick",)
    assert summary.initial_errors == {"tiny_quick": "ModelError"}
    assert [m.error for m in summary.measurements] == [None]


def test_repeated_failure_is_recorded_after_exactly_one_retry(models):
    def reply(messages, n):
        if n >= 2:
            raise ModelError("persistent")
        return "fine"

    models["m1"] = ScriptedModel(reply)
    summary = run_benchmark(models, scenarios=TINY[:1])

    assert models["m1"].calls == 3  # warm-up + attempt + one retry, no more
    assert summary.measurements[0].error == "ModelError"
    assert "repeated ModelError/crash after one retry" in bench.disqualification_reasons(summary, {}, {})


def test_unreachable_or_missing_model_is_not_evaluated_not_a_crash(models):
    models["down"] = ScriptedModel(reachable=False)
    models["gone"] = ScriptedModel(available=False)
    assert "not reachable" in run_benchmark(models, "down").not_evaluated_reason
    assert "not installed" in run_benchmark(models, "gone").not_evaluated_reason


def test_unexpected_exception_while_benchmarking_becomes_not_evaluated(models):
    models["m1"] = ScriptedModel(capabilities=None)  # get_capabilities returns None -> weird, but fine
    class Broken(ScriptedModel):
        def get_capabilities(self):
            raise RuntimeError("boom")

    models["m2"] = Broken()
    summary = run_benchmark(models, "m2")
    assert summary.not_evaluated_reason == "RuntimeError while benchmarking"


# --- safety: temporary data directory + verification guard ----------------------------


def test_guard_runs_on_a_fresh_temp_dir_before_the_app_is_built(models, monkeypatch):
    order = []
    seen_dirs = []
    real_guard = bench.assert_safe_for_verification

    def spying_guard(settings):
        order.append("guard")
        seen_dirs.append(settings.data_dir)
        real_guard(settings)

    def factory(settings):
        order.append("app")
        return bench.StudyBotApp(settings)

    monkeypatch.setattr(bench, "assert_safe_for_verification", spying_guard)
    models["m1"] = ScriptedModel()
    run_benchmark(models, scenarios=TINY[:1], app_factory=factory)

    from studybot.config.settings import default_data_dir

    assert order == ["guard", "app"]
    (data_dir,) = seen_dirs
    assert default_data_dir().resolve() not in [data_dir.resolve(), *data_dir.resolve().parents]
    assert not data_dir.exists()  # cleaned up by default


def test_each_candidate_gets_its_own_directory_and_keep_temp_keeps_it(models, monkeypatch):
    dirs = []
    real_guard = bench.assert_safe_for_verification
    monkeypatch.setattr(bench, "assert_safe_for_verification", lambda s: (dirs.append(s.data_dir), real_guard(s)))
    models["a"], models["b"] = ScriptedModel(), ScriptedModel()
    run_benchmark(models, "a", scenarios=TINY[:1])
    run_benchmark(models, "b", scenarios=TINY[:1], keep_temp=True)
    try:
        assert dirs[0] != dirs[1]
        assert not dirs[0].exists() and dirs[1].exists()
    finally:
        import shutil

        shutil.rmtree(dirs[1], ignore_errors=True)


def test_guard_rejection_stops_everything_and_never_builds_an_app(models, monkeypatch):
    def reject(settings):
        raise UnsafeVerificationEnvironmentError("real data dir")

    def factory(settings):
        raise AssertionError("app must not be constructed")

    monkeypatch.setattr(bench, "assert_safe_for_verification", reject)
    models["m1"] = ScriptedModel()
    with pytest.raises(UnsafeVerificationEnvironmentError):
        run_benchmark(models, scenarios=TINY[:1], app_factory=factory)


def test_cli_exits_2_when_the_guard_rejects(models, monkeypatch, capsys):
    monkeypatch.setattr(
        bench, "assert_safe_for_verification", lambda s: (_ for _ in ()).throw(UnsafeVerificationEnvironmentError("x"))
    )
    models["m1"] = ScriptedModel()
    assert bench.main(["--models", "m1", "--only", "quick_density_fast"]) == 2
    assert "REFUSING" in capsys.readouterr().err


def test_benchmark_never_touches_the_real_default_data_dir(models, monkeypatch, tmp_path):
    from studybot.config import settings as settings_module

    real = tmp_path / "pretend-real-default"
    monkeypatch.setattr(settings_module, "default_data_dir", lambda: real)
    import studybot.config.verification_guard as guard_module

    monkeypatch.setattr(guard_module, "default_data_dir", lambda: real)
    models["m1"] = ScriptedModel()
    run_benchmark(models, scenarios=TINY[:1])
    assert not real.exists()


# --- CLI ----------------------------------------------------------------------------


def test_one_candidate_failing_does_not_abort_the_others(models, tmp_path):
    models["bad"] = ScriptedModel(available=False)
    models["good"] = ScriptedModel()
    out = tmp_path / "results.json"

    code = bench.main(["--models", "bad", "good", "--only", "quick_density_fast", "--output", str(out)])

    assert code == 0
    document = json.loads(out.read_text())
    by_name = {m["model_name"]: m for m in document["models"]}
    assert by_name["bad"]["not_evaluated_reason"] == "model not installed locally"
    assert by_name["good"]["measurements"] and by_name["good"]["not_evaluated_reason"] is None


def test_cli_exits_1_when_no_requested_model_can_be_evaluated(models, tmp_path):
    models["bad"] = ScriptedModel(available=False)
    assert bench.main(["--models", "bad", "--only", "quick_density_fast", "--output", str(tmp_path / "r.json")]) == 1


def test_cli_rejects_unknown_scenario_ids(models):
    assert bench.main(["--models", "m", "--only", "no_such_scenario"]) == 2


def test_saved_output_has_scenario_ids_but_no_prompts_answers_or_paths(models, tmp_path):
    models["m1"] = ScriptedModel(lambda messages, n: f"{SECRET_ANSWER} #{n}")
    scenarios = (
        BenchmarkScenario("tiny_quick", None, None, TeachingMode.QUICK, ReasoningMode.FAST, (f"{SECRET_PROMPT} hi",)),
    )
    summary = run_benchmark(models, scenarios=scenarios)
    out = tmp_path / "results.json"
    out.write_text(json.dumps(bench.results_document([summary])))
    text = out.read_text()

    assert "tiny_quick" in text
    assert SECRET_ANSWER not in text and SECRET_PROMPT not in text
    assert "studybot_bench_" not in text and str(tmp_path) not in text
    assert "/var/" not in text and "/tmp/" not in text and "Users" not in text


def test_show_answers_prints_only_visible_text_to_the_terminal_and_defaults_off(models, capsys):
    models["m1"] = ScriptedModel(lambda messages, n: f"{SECRET_ANSWER}")
    run_benchmark(models, scenarios=TINY[:1])
    assert SECRET_ANSWER not in capsys.readouterr().out

    import io

    out = io.StringIO()
    run_benchmark(models, scenarios=TINY[:1], show_answers=True, out=out)
    assert SECRET_ANSWER in out.getvalue()


def test_summary_round_trips_through_json(models):
    models["m1"] = ScriptedModel()
    summary = run_benchmark(models, scenarios=TINY[:1])
    again = bench.summary_from_dict(json.loads(json.dumps(bench.summary_to_dict(summary))))
    assert again == summary


def test_merge_replaces_remeasured_scenarios(models):
    first = bench.summarize(
        "m",
        [TurnMeasurement("a", 1, 1.0, 2.0, 5, True, True), TurnMeasurement("b", 1, 9.0, 9.0, 5, True, True)],
        installed_size_gb=2.5,
    )
    second = bench.summarize("m", [TurnMeasurement("b", 1, 3.0, 4.0, 7, True, True)])
    (merged,) = bench.merge_summaries([first, second])
    by_id = {m.scenario_id: m for m in merged.measurements}
    assert by_id["a"].first_visible_seconds == 1.0 and by_id["b"].first_visible_seconds == 3.0
    assert merged.installed_size_gb == 2.5


# --- scenario table & quality ---------------------------------------------------------


def test_scenario_table_matches_the_contract():
    ids = {s.id for s in bench.SCENARIOS}
    assert len(bench.SCENARIOS) == 16
    for base in ("teach_acceleration", "homework_kinematics", "quick_density", "practice_literary", "exam_vectors", "eng303_regression"):
        assert {f"{base}_fast", f"{base}_deep"} <= ids
    assert {"calculus_chain_rule", "physics_projectile", "instruction_three_bullets", "reasoning_bat_ball"} <= ids
    assert set(bench.QUALITY_POINTS) <= ids
    assert sum(bench.QUALITY_POINTS.values()) == 50
    for scenario in bench.SCENARIOS:
        if scenario.id.startswith(("calculus", "physics", "instruction", "reasoning")):
            assert scenario.reasoning_mode is ReasoningMode.FAST


def test_exact_acceptance_prompts_are_used():
    by_id = {s.id: s for s in bench.SCENARIOS}
    assert by_id["homework_kinematics_fast"].turns == (
        "A car starts from rest and accelerates at 3 m/s² for 4 seconds.\nHelp me solve it.",
        "Just give me the full solution.",
    )
    assert by_id["eng303_regression_deep"].turns == ("help me to work practice quizzes", "ok")
    assert by_id["eng303_regression_deep"].course_name == "ENG303"
    assert by_id["quick_density_deep"].turns == ("What is the formula for density?",)


def all_grades(value):
    return {sid: value for sid in bench.QUALITY_POINTS}


def test_quality_score_pass_partial_fail_and_missing():
    assert bench.quality_score(all_grades("PASS")) == 50
    assert bench.quality_score(all_grades("PARTIAL")) == 25
    assert bench.quality_score(all_grades("FAIL")) == 0
    assert bench.quality_score({}) == 0
    mixed = {**all_grades("PASS"), "homework_kinematics_fast": "PARTIAL", "teach_acceleration_deep": "FAIL"}
    assert bench.quality_score(mixed) == 50 - 2.5 - 4


# --- scoring ------------------------------------------------------------------------


def summary(name, *, fast=2.0, other=4.0, total=10.0, warmup=20.0, caps=CAPS, size=2.5, swap=(100.0, 200.0), **kw):
    measurements = []
    for s in bench.SCENARIOS:
        first = fast if s.id in bench.FAST_SCENARIO_IDS else other
        measurements.append(TurnMeasurement(s.id, 1, first, total, 100, True, True))
    resources = {}
    if swap is not None:
        resources = {"swap_before": {"used_mb": swap[0]}, "swap_after": {"used_mb": swap[1]}}
    return bench.summarize(
        name,
        measurements,
        capabilities=caps,
        warmup_total_seconds=warmup,
        installed_size_gb=size,
        resources=resources,
        **kw,
    )


PASS_ALL = {"grades": all_grades("PASS"), "flags": {}}


def test_future_capability_score_weights():
    assert bench.future_capability_score(ModelCapabilities(True, True, True, True, 128000)) == 15
    assert bench.future_capability_score(ModelCapabilities(True, True, True, True, 127999)) == 13
    assert bench.future_capability_score(ModelCapabilities(False, False, True, False, 262144)) == 2
    assert bench.future_capability_score(ModelCapabilities(None, None, None, None, None)) == 0
    assert bench.future_capability_score(ModelCapabilities(True, False, False, False, None)) == 5
    assert bench.future_capability_score(None) == 0


def test_resource_score_size_and_swap_evidence():
    assert bench.resource_score(summary("m", size=3.5, swap=(0, 10))) == 5
    assert bench.resource_score(summary("m", size=3.51, swap=(0, 10))) == 3
    assert bench.resource_score(summary("m", size=2.0, swap=(0, 5000))) == 2  # severe swap growth
    assert bench.resource_score(summary("m", size=2.0, swap=None)) == 2  # inconclusive: nothing fabricated
    assert bench.resource_score(summary("m", size=None, swap=None)) == 0


def test_performance_score_matches_the_specified_formula():
    fast_model = summary("fast", fast=2.0, other=4.0, total=10.0, warmup=10.0)
    slow_model = summary("slow", fast=4.0, other=8.0, total=20.0, warmup=40.0)
    scores = {s.model_name: s for s in bench.score_candidates([fast_model, slow_model], {"fast": PASS_ALL, "slow": PASS_ALL})}

    assert scores["fast"].performance == 30  # best on every metric: full weights
    detail = scores["slow"].performance_detail
    assert detail["fast_first_visible"] == pytest.approx(15 * 2 / 4)
    # overall first-visible: medians over all 16 scenarios (8 fast, 8 other for each)
    fast_overall = bench._median_of(fast_model.measurements, "first_visible_seconds")
    slow_overall = bench._median_of(slow_model.measurements, "first_visible_seconds")
    assert detail["overall_first_visible"] == pytest.approx(5 * fast_overall / slow_overall, abs=0.01)
    assert detail["overall_total"] == pytest.approx(5 * 10 / 20)
    assert detail["warmup"] == pytest.approx(5 * 10 / 40)
    assert scores["slow"].performance == pytest.approx(sum(detail.values()), abs=0.01)


def test_missing_measurement_scores_zero_for_that_metric():
    no_warmup = summary("a", warmup=None)
    other = summary("b", warmup=10.0)
    scores = {s.model_name: s for s in bench.score_candidates([no_warmup, other], {"a": PASS_ALL, "b": PASS_ALL})}
    assert scores["a"].performance_detail["warmup"] == 0


def test_only_gate_passing_models_are_performance_scored_or_set_the_benchmark():
    cheat = summary("cheat", fast=0.1, total=0.1, warmup=0.1)
    leaky = bench.summarize("leaky", list(cheat.measurements[:-1]) + [TurnMeasurement("x", 1, 0.1, 0.1, 5, False, True)],
                            capabilities=CAPS, warmup_total_seconds=0.1, installed_size_gb=2.0)
    honest = summary("honest", fast=2.0)
    scores = {s.model_name: s for s in bench.score_candidates([leaky, honest], {"leaky": PASS_ALL, "honest": PASS_ALL})}

    assert scores["leaky"].disqualified and scores["leaky"].performance == 0
    assert scores["honest"].performance == 30  # leaky's fast numbers didn't become "best"


def test_total_is_the_sum_of_components():
    (score,) = bench.score_candidates([summary("m")], {"m": PASS_ALL})
    assert score.total == pytest.approx(score.quality + score.performance + score.capability + score.resource)
    assert score.quality == 50 and score.capability == 15 and score.resource == 5 and score.performance == 30
    assert score.total == 100


# --- hard gates -----------------------------------------------------------------------


def reasons(s, grades=None, flags=None):
    return bench.disqualification_reasons(s, grades or all_grades("PASS"), flags or {})


def test_clean_model_has_no_disqualifiers():
    assert reasons(summary("m")) == ()


def test_each_hard_gate_disqualifies():
    leak = bench.summarize("m", [TurnMeasurement("a", 1, 1, 1, 1, False, True)])
    assert "reasoning/think-marker leak" in reasons(leak)
    mismatch = bench.summarize("m", [TurnMeasurement("a", 1, 1, 1, 1, True, False)])
    assert "persisted message differs from visible stream" in reasons(mismatch)
    crashed = bench.summarize("m", [TurnMeasurement("a", 1, 1, 1, 0, True, True, error="ModelError")])
    assert any("ModelError" in r for r in reasons(crashed))
    assert any("calculus" in r for r in reasons(summary("m"), {**all_grades("PASS"), "calculus_chain_rule": "FAIL"}))
    assert any("physics" in r for r in reasons(summary("m"), {**all_grades("PASS"), "physics_projectile": "FAIL"}))
    for flag in bench.GATE_FLAGS:
        assert reasons(summary("m"), flags={flag: True})
    assert "not evaluated" in reasons(bench.summarize("m", (), not_evaluated_reason="x"))


def test_partial_academic_grade_is_not_a_disqualifier():
    assert reasons(summary("m"), {**all_grades("PASS"), "calculus_chain_rule": "PARTIAL"}) == ()


# --- selection ------------------------------------------------------------------------


def score(name, total, quality, *, disq=False, distinct=True, fast=2.0, size=2.5):
    return CandidateScore(
        model_name=name, disqualified=disq, reasons=("x",) if disq else (), quality=quality, performance=0,
        capability=0, resource=0, total=total, fast_median_first_visible=fast, installed_size_gb=size,
        reasoning_modes_distinct=distinct,
    )


def test_a_disqualified_candidate_can_never_win():
    selection = bench.select_default([score("qwen3:4b", 60, 40), score("cand", 99, 50, disq=True)])
    assert selection.default_model == "qwen3:4b" and not selection.upgrade_justified


def test_baseline_is_kept_when_no_candidate_beats_it():
    selection = bench.select_default([score("qwen3:4b", 80, 45), score("a", 70, 45), score("b", 60, 30)])
    assert selection.default_model == "qwen3:4b"
    assert "NO UPGRADE JUSTIFIED" in selection.explanation


def test_clearly_higher_total_wins():
    selection = bench.select_default([score("qwen3:4b", 70, 40), score("cand", 75, 40)])
    assert selection.default_model == "cand" and selection.upgrade_justified


def test_within_three_points_higher_quality_wins():
    selection = bench.select_default([score("qwen3:4b", 80, 40), score("cand", 78, 44)])
    assert selection.default_model == "cand"
    selection = bench.select_default([score("qwen3:4b", 78, 44), score("cand", 80, 40)])
    assert selection.default_model == "qwen3:4b"


def test_tied_quality_prefers_clearly_lower_fast_latency():
    selection = bench.select_default([score("qwen3:4b", 80, 40, fast=10.0), score("cand", 80, 40, fast=5.0)])
    assert selection.default_model == "cand"


def test_tied_quality_and_similar_latency_prefers_the_smaller_model():
    selection = bench.select_default(
        [score("qwen3:4b", 80, 40, fast=10.0, size=3.4), score("cand", 80, 40, fast=9.5, size=2.5)]
    )
    assert selection.default_model == "cand"
    selection = bench.select_default(
        [score("qwen3:4b", 80, 40, fast=10.0, size=2.5), score("cand", 80, 40, fast=9.5, size=3.4)]
    )
    assert selection.default_model == "qwen3:4b"


def test_full_tie_keeps_the_baseline():
    selection = bench.select_default([score("qwen3:4b", 80, 40), score("cand", 80, 40)])
    assert selection.default_model == "qwen3:4b"


def test_non_distinct_modes_need_ten_more_quality_points_to_beat_a_distinct_model():
    base = score("qwen3:4b", 70, 40, distinct=True)
    # Higher total AND higher quality, but only by 9 quality points: not enough.
    assert bench.select_default([base, score("cand", 90, 49, distinct=False)]).default_model == "qwen3:4b"
    # Exactly 10 more quality points: allowed to win on the normal rules.
    assert bench.select_default([base, score("cand", 90, 50, distinct=False)]).default_model == "cand"


def test_unknown_distinctness_is_treated_like_not_distinct():
    base = score("qwen3:4b", 70, 40, distinct=True)
    assert bench.select_default([base, score("cand", 90, 45, distinct=None)]).default_model == "qwen3:4b"


def test_distinct_candidate_beats_a_non_distinct_baseline_unless_baseline_leads_by_ten():
    base = score("qwen3:4b", 80, 44, distinct=False)
    assert bench.select_default([base, score("cand", 78, 40, distinct=True)]).default_model == "cand"
    strong_base = score("qwen3:4b", 80, 50, distinct=False)
    assert bench.select_default([strong_base, score("cand", 78, 40, distinct=True)]).default_model == "qwen3:4b"


def test_no_eligible_candidate_keeps_the_baseline():
    selection = bench.select_default([score("qwen3:4b", 0, 0, disq=True), score("x", 0, 0, disq=True)])
    assert selection.default_model == "qwen3:4b" and not selection.upgrade_justified


def test_baseline_disqualified_picks_the_best_eligible_candidate():
    selection = bench.select_default([score("qwen3:4b", 90, 50, disq=True), score("a", 60, 30), score("b", 70, 35)])
    assert selection.default_model == "b"


def test_end_to_end_scoring_and_selection_from_summaries():
    base = summary("qwen3:4b", fast=10.0, caps=ModelCapabilities(False, True, True, False, 262144), size=2.5)
    better = summary("cand", fast=4.0, caps=ModelCapabilities(True, True, True, True, 131072), size=3.3)
    grades = {"qwen3:4b": {"grades": all_grades("PARTIAL"), "flags": {}}, "cand": PASS_ALL}
    scores = bench.score_candidates([base, better], grades)
    selection = bench.select_default(scores)
    assert selection.default_model == "cand" and selection.upgrade_justified
    table = bench.format_score_table(scores)
    assert "cand" in table and "DISQUALIFIED" not in table


# --- resource parsing & classification ---------------------------------------------------


OLLAMA_PS = """NAME          ID              SIZE      PROCESSOR    CONTEXT    UNTIL
qwen3:4b      359d7dd4bcda    3.2 GB    100% GPU     4096       4 minutes from now
"""
OLLAMA_LIST = """NAME          ID              SIZE      MODIFIED
gemma3:4b     a2af6cc3eb7f    3.3 GB    30 seconds ago
tiny:1b       aaaaaaaaaaaa    774 MB    2 days ago
"""


def test_parse_ollama_ps_extracts_size_processor_and_active_context():
    assert bench.parse_ollama_ps(OLLAMA_PS, "qwen3:4b") == {
        "model": "qwen3:4b", "size": "3.2 GB", "processor": "100% GPU", "context": "4096",
    }
    assert bench.parse_ollama_ps(OLLAMA_PS, "other") is None
    assert bench.parse_ollama_ps(None, "qwen3:4b") is None
    assert bench.parse_ollama_ps("", "qwen3:4b") is None


def test_parse_installed_size_converts_units_to_gb():
    assert bench.parse_installed_size_gb(OLLAMA_LIST, "gemma3:4b") == 3.3
    assert bench.parse_installed_size_gb(OLLAMA_LIST, "tiny:1b") == pytest.approx(0.76, abs=0.01)
    assert bench.parse_installed_size_gb(OLLAMA_LIST, "missing") is None


def test_parse_swap_usage_and_memory_pressure():
    swap = bench.parse_swap_usage("vm.swapusage: total = 2048.00M  used = 1017.50M  free = 1030.50M  (encrypted)")
    assert swap == {"total_mb": 2048.0, "used_mb": 1017.5, "free_mb": 1030.5}
    assert bench.parse_swap_usage("vm.swapusage: total = 1.00G  used = 0.50G  free = 0.50G")["used_mb"] == 512.0
    assert bench.parse_swap_usage("garbage") is None and bench.parse_swap_usage(None) is None
    assert bench.parse_memory_pressure_free_percent("System-wide memory free percentage: 63%") == 63
    assert bench.parse_memory_pressure_free_percent("") is None


def test_probe_resources_tolerates_every_command_being_unavailable():
    assert bench.probe_resources("m", lambda argv: None) == {"ollama_ps": None, "swap": None, "memory_free_percent": None}


def test_run_command_returns_none_for_a_missing_executable():
    assert bench.run_command(["definitely-not-a-real-binary-xyz"]) is None


@pytest.mark.parametrize(
    ("caps", "expected"),
    [
        (ModelCapabilities(None, None, True, True, None), "toggleable"),
        (ModelCapabilities(None, None, True, False, None), "always_on"),
        (ModelCapabilities(None, None, False, False, None), "none"),
        (ModelCapabilities(None, None, None, None, None), "unknown"),
        (None, "unknown"),
    ],
)
def test_thinking_classification_is_derived_from_neutral_capabilities(caps, expected):
    assert bench.classify_thinking(caps) == expected


def test_benchmark_module_is_not_imported_by_the_application():
    root = Path(bench.__file__).resolve().parents[1] / "src"
    assert not any("benchmark_local_models" in p.read_text() for p in root.rglob("*.py"))


# --- interactive learner answers ---------------------------------------------------------


def test_file_answer_provider_writes_the_question_and_returns_the_written_answer(tmp_path):
    provider = bench.FileAnswerProvider(tmp_path, "gemma3:4b", timeout=5, sleep=lambda s: None)
    answer_file = tmp_path / "gemma3_4b__practice_literary_fast__turn2.answer.txt"

    def sleeper(seconds):
        # the reviewer reads the question, then writes an answer fitted to it
        question = (tmp_path / "gemma3_4b__practice_literary_fast__turn2.question.txt").read_text()
        answer_file.write_text(f"  my answer to: {question}  \n")

    provider.sleep = sleeper
    assert provider("practice_literary_fast", 2, "What device is 'time is a thief'?") == (
        "my answer to: What device is 'time is a thief'?"
    )


def test_file_answer_provider_ignores_a_stale_answer_and_times_out_to_none(tmp_path):
    (tmp_path / "m__s__turn2.answer.txt").write_text("stale answer from an earlier run")
    clock_values = iter([0.0, 0.0, 1.0, 2.0, 99.0, 99.0])
    provider = bench.FileAnswerProvider(tmp_path, "m", timeout=10, sleep=lambda s: None, clock=lambda: next(clock_values))
    assert provider("s", 2, "question") is None
    assert (tmp_path / "m__s__turn2.question.txt").read_text() == "question"


def test_run_scenario_asks_the_provider_with_the_models_last_visible_answer(models):
    asked = []

    def provider(scenario_id, turn_number, last_visible):
        asked.append((scenario_id, turn_number, last_visible))
        return "FITTED-ANSWER"

    seen = []

    def reply(messages, n):
        seen.append(messages[-1].content)
        return f"{SECRET_ANSWER} question {n}"

    models["m1"] = ScriptedModel(reply)
    summary = run_benchmark(models, scenarios=TINY[1:], answer_provider=provider)

    assert asked == [("tiny_practice", 2, f"{SECRET_ANSWER} question 2")]  # n=1 was the warm-up
    assert "FITTED-ANSWER" in seen
    assert not any(m.used_fallback_answer for m in summary.measurements)


def test_run_scenario_falls_back_and_flags_when_the_provider_returns_none(models):
    models["m1"] = ScriptedModel()
    summary = run_benchmark(models, scenarios=TINY[1:], answer_provider=lambda *a: None)
    assert [m.used_fallback_answer for m in summary.measurements] == [False, True, False]


def test_preset_learner_answers_take_priority_over_the_provider(models):
    def provider(*args):
        raise AssertionError("must not be asked")

    models["m1"] = ScriptedModel()
    run_benchmark(models, scenarios=TINY[1:], learner_answers={"tiny_practice": ["PRESET"]}, answer_provider=provider)


# --- per-turn deadline (runaway generations) -----------------------------------------------


class EndlessSessions:
    """A stream that never finishes (like a looping model): progress
    signals forever, each advancing the clock."""

    def __init__(self, clock, step=1.0, visible_first=False):
        self.clock, self.step, self.visible_first = clock, step, visible_first
        self.closed = False
        self.history = []

    def send_streaming_to_chat(self, chat_id, prompt):
        self.history.append(Message.user(prompt))
        try:
            if self.visible_first:
                yield "partial"
            while True:
                self.clock.now += self.step
                yield ""
        finally:
            self.closed = True  # `.close()` lands here

    def get_chat_history(self, chat_id):
        return list(self.history)


def test_a_runaway_turn_is_abandoned_recorded_and_the_stream_closed():
    clock = Clock()
    sessions = EndlessSessions(clock)
    measurement, visible = bench.measure_turn(
        sessions, "c", "p", scenario_id="s", turn_number=1, clock=clock, max_seconds=30.0
    )
    assert measurement.error == "TurnTimeout"
    assert measurement.total_seconds == pytest.approx(31.0)
    assert measurement.first_visible_seconds is None
    assert sessions.closed  # closing the stream is what cancels generation in Ollama
    assert measurement.persistence_match is True  # no assistant message was left behind


def test_a_timed_out_turn_keeps_what_was_visible_but_is_still_a_failure():
    clock = Clock()
    sessions = EndlessSessions(clock, visible_first=True)
    measurement, visible = bench.measure_turn(
        sessions, "c", "p", scenario_id="s", turn_number=1, clock=clock, max_seconds=5.0
    )
    assert visible == "partial" and measurement.error == "TurnTimeout"
    assert measurement.first_visible_seconds == pytest.approx(0.0)


def test_turns_within_the_deadline_are_unaffected_and_none_disables_it():
    measurement, _ = measure([("tick", 3.0), "ok"])
    assert measurement.error is None
    clock = Clock()
    sessions = FakeSessions(clock, [("tick", 10_000.0), "ok"])
    measurement, _ = bench.measure_turn(
        sessions, "c", "p", scenario_id="s", turn_number=1, clock=clock, max_seconds=None
    )
    assert measurement.error is None


def test_the_deadline_uses_the_injected_clock_so_sleep_time_cannot_trigger_it():
    # A clock that doesn't advance models a machine asleep: no timeout, however long the wall time.
    clock = Clock()
    sessions = FakeSessions(clock, ["a", "b", "c"])
    measurement, _ = bench.measure_turn(
        sessions, "c", "p", scenario_id="s", turn_number=1, clock=clock, max_seconds=0.001
    )
    assert measurement.error is None


def test_a_runaway_warmup_marks_the_model_not_evaluated(models):
    class Runaway(ScriptedModel):
        def stream(self, messages, *, reasoning_mode=ReasoningMode.FAST):
            while True:
                yield ""

    models["m1"] = Runaway()
    ticks = iter(range(0, 10_000))
    summary = bench.benchmark_model(
        "m1", TINY[:1], runner=NO_COMMANDS, unload=lambda n: None, max_turn_seconds=5.0, clock=lambda: float(next(ticks))
    )
    assert summary.not_evaluated_reason == "warm-up failed (TurnTimeout)"


def test_cli_exposes_max_turn_seconds():
    assert bench._build_parser().parse_args(["--max-turn-seconds", "99"]).max_turn_seconds == 99.0
    assert bench._build_parser().parse_args([]).max_turn_seconds == bench.DEFAULT_MAX_TURN_SECONDS
