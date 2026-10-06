#!/usr/bin/env python3
"""Benchmark local Ollama models through the real StudyBot stack (Stage 6.4).

DEVELOPMENT TOOLING — never imported by the application.

Every measurement goes through `Settings -> StudyBotApp -> SessionService ->
ChatService -> ModelProvider -> OllamaModel`, so system prompts, teaching
modes, reasoning modes, output integrity and persistence are all part of
what's measured. Each candidate gets its own freshly created temporary data
directory (never the real StudyBot database); `assert_safe_for_verification`
runs before any app is constructed, and a rejection aborts the whole run.

Run (measure):

    python scripts/benchmark_local_models.py \\
        --models qwen3:4b qwen3.5:4b gemma3:4b --output results.json

    # development-only: also print FINAL visible answers for manual grading
    python scripts/benchmark_local_models.py --show-answers ...

Two scenarios (practice and exam) need a learner answer that fits whatever
question the model generated. Run once with `--show-answers`, read the
questions, write a small JSON file `{"<model>": {"<scenario_id>": ["<answer>"]}}`
and re-run just those scenarios with `--only ... --learner-answers FILE`.
Without it a generic fallback answer is used and the measurement is flagged
`used_fallback_answer`.

Score (after grading the visible answers by hand into a grades file):

    python scripts/benchmark_local_models.py \\
        --score-from results.json [more.json ...] --grades grades.json

Saved output contains scenario ids, timings, lengths, capability values and
scores only — never prompts, answers, hidden reasoning or paths. Answers are
only ever printed to the terminal, and only with `--show-answers`.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence

from studybot.app import StudyBotApp
from studybot.config.settings import Settings
from studybot.config.verification_guard import UnsafeVerificationEnvironmentError, assert_safe_for_verification
from studybot.core.messages import Role
from studybot.core.reasoning_mode import ReasoningMode
from studybot.core.teaching_mode import TeachingMode
from studybot.models.base import ModelCapabilities

DEFAULT_MODELS = ("qwen3:4b", "qwen3.5:4b", "gemma3:4b")
BASELINE_MODEL = "qwen3:4b"
THINK_MARKERS = ("<think>", "</think>")

LEARNER_ANSWER = "<<learner-answer>>"
"""Placeholder turn text, replaced at run time by an answer that fits the
question the model actually generated (see the module docstring)."""
FALLBACK_LEARNER_ANSWER = "I'm not sure, but my best guess is the first thing that comes to mind from your question."

WARMUP_PROMPT = "Reply with one short sentence."

DEFAULT_MAX_TURN_SECONDS = 420.0
"""Longest a single turn may run before it is abandoned. Real turns took at
most ~165 s on the slowest candidate; a generation that never ends (Ollama's
default has no token cap and shifts context, so it can run forever) is
cut off here and recorded as a `TurnTimeout` failure."""


# --- data types ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BenchmarkScenario:
    id: str
    course_name: str | None
    course_code: str | None
    teaching_mode: TeachingMode
    reasoning_mode: ReasoningMode
    turns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TurnMeasurement:
    scenario_id: str
    turn_number: int
    first_visible_seconds: float | None
    total_seconds: float
    visible_characters: int
    integrity_pass: bool
    persistence_match: bool
    error: str | None = None
    """Exception class name if the turn failed (never a message)."""
    used_fallback_answer: bool = False


@dataclass(frozen=True, slots=True)
class ModelBenchmarkSummary:
    model_name: str
    capabilities: ModelCapabilities | None
    measurements: tuple[TurnMeasurement, ...]
    median_first_visible_seconds: float | None
    median_total_seconds: float | None
    all_integrity_pass: bool
    all_persistence_match: bool
    thinking_classification: str = "unknown"
    warmup_first_visible_seconds: float | None = None
    warmup_total_seconds: float | None = None
    installed_size_gb: float | None = None
    resources: dict = field(default_factory=dict)
    retried_scenarios: tuple[str, ...] = ()
    initial_errors: dict = field(default_factory=dict)
    not_evaluated_reason: str | None = None


class BenchmarkInvariantError(RuntimeError):
    """An internal benchmark invariant failed; the run's results can't be trusted."""


# --- scenarios ----------------------------------------------------------------------


def _both_modes(base_id: str, teaching: TeachingMode, turns: tuple[str, ...], course=(None, None)):
    return tuple(
        BenchmarkScenario(f"{base_id}_{mode.value}", course[0], course[1], teaching, mode, turns)
        for mode in (ReasoningMode.FAST, ReasoningMode.DEEP)
    )


_PHYSICS = ("Physics", "PHY101")
_ENG303 = ("ENG303", "ENG303")

SCENARIOS: tuple[BenchmarkScenario, ...] = (
    *_both_modes(
        "teach_acceleration",
        TeachingMode.TEACH,
        ("Explain acceleration to someone learning physics for the first time.",),
        _PHYSICS,
    ),
    *_both_modes(
        "homework_kinematics",
        TeachingMode.HOMEWORK,
        (
            "A car starts from rest and accelerates at 3 m/s² for 4 seconds.\nHelp me solve it.",
            "Just give me the full solution.",
        ),
        _PHYSICS,
    ),
    *_both_modes("quick_density", TeachingMode.QUICK, ("What is the formula for density?",), _PHYSICS),
    *_both_modes(
        "practice_literary",
        TeachingMode.PRACTICE,
        ("Practice literary devices with me.", LEARNER_ANSWER, "Give me another one."),
        _ENG303,
    ),
    *_both_modes("exam_vectors", TeachingMode.EXAM, ("Test me on vectors.", LEARNER_ANSWER), _PHYSICS),
    *_both_modes(
        "eng303_regression",
        TeachingMode.PRACTICE,
        ("help me to work practice quizzes", "ok"),
        _ENG303,
    ),
    BenchmarkScenario(
        "calculus_chain_rule",
        "Calculus",
        "MATH101",
        TeachingMode.TEACH,
        ReasoningMode.FAST,
        ("Differentiate y = (2x + 3)^5.\nExplain the chain rule briefly and give the final derivative.",),
    ),
    BenchmarkScenario(
        "physics_projectile",
        "Physics",
        "PHY101",
        TeachingMode.HOMEWORK,
        ReasoningMode.FAST,
        (
            "A projectile is launched from level ground at 20 m/s at 30 degrees.\n"
            "Use g = 9.8 m/s².\nFind the time of flight, horizontal range, and maximum height.",
        ),
    ),
    BenchmarkScenario(
        "instruction_three_bullets",
        None,
        None,
        TeachingMode.QUICK,
        ReasoningMode.FAST,
        ("Explain photosynthesis in exactly 3 bullet points.\nUse no more than 12 words in each bullet.",),
    ),
    BenchmarkScenario(
        "reasoning_bat_ball",
        None,
        None,
        TeachingMode.TEACH,
        ReasoningMode.FAST,
        (
            "A bat and a ball cost $1.10 total.\nThe bat costs $1.00 more than the ball.\n"
            "How much does the ball cost?",
        ),
    ),
)

FAST_SCENARIO_IDS = frozenset(s.id for s in SCENARIOS if s.reasoning_mode is ReasoningMode.FAST)

# Quality points per scenario (50 in total). Scenarios not listed here
# (eng303 regression, instruction, bat/ball) are pass/fail checks without
# quality points; calculus and physics are also hard gates.
QUALITY_POINTS: dict[str, int] = {
    "teach_acceleration_fast": 4,
    "teach_acceleration_deep": 4,
    "homework_kinematics_fast": 5,
    "homework_kinematics_deep": 5,
    "quick_density_fast": 3,
    "quick_density_deep": 3,
    "practice_literary_fast": 5,
    "practice_literary_deep": 5,
    "exam_vectors_fast": 5,
    "exam_vectors_deep": 5,
    "calculus_chain_rule": 3,
    "physics_projectile": 3,
}
assert sum(QUALITY_POINTS.values()) == 50
assert len({s.id for s in SCENARIOS}) == len(SCENARIOS)

GATE_SCENARIOS = ("calculus_chain_rule", "physics_projectile")
GATE_FLAGS = ("homework_full_solution_refused", "practice_answer_leaked", "exam_solution_leaked")


# --- measuring one turn ---------------------------------------------------------------


def measure_turn(
    sessions,
    chat_id: str,
    prompt: str,
    *,
    scenario_id: str,
    turn_number: int,
    clock: Callable[[], float] = time.perf_counter,
    used_fallback_answer: bool = False,
    max_seconds: float | None = DEFAULT_MAX_TURN_SECONDS,
) -> tuple[TurnMeasurement, str]:
    """Run one turn through `SessionService` and measure it. Returns the
    measurement and the final visible text (for optional terminal display).

    A turn that runs longer than `max_seconds` (measured on the same clock,
    so time the machine spends asleep doesn't count) is abandoned and
    recorded as a `TurnTimeout` failure: closing the stream makes Ollama stop
    generating, so one runaway generation can't hang the whole benchmark.

    The first-visible time is that of the first NON-EMPTY chunk: `""` is a
    progress signal, not content. Success means the persisted assistant
    message equals the concatenated visible stream exactly.
    """
    assistants_before = _assistant_count(sessions, chat_id)
    chunks: list[str] = []
    first_visible: float | None = None
    error: str | None = None
    start = clock()
    stream = sessions.send_streaming_to_chat(chat_id, prompt)
    try:
        for chunk in stream:
            if chunk:
                if first_visible is None:
                    first_visible = clock() - start
                chunks.append(chunk)
            if max_seconds is not None and clock() - start > max_seconds:
                error = "TurnTimeout"
                break
    except Exception as exc:  # a failed generation is a measurement, not a crash
        error = type(exc).__name__
    finally:
        close = getattr(stream, "close", None)
        if close is not None:
            close()  # abandoning the stream also cancels the generation server-side
    total = clock() - start

    visible = "".join(chunks)
    history = sessions.get_chat_history(chat_id)
    if error is None:
        persistence_match = bool(history) and history[-1].role is Role.ASSISTANT and history[-1].content == visible
        integrity_pass = not any(marker in visible for marker in THINK_MARKERS) and not any(
            marker in m.content for m in history for marker in THINK_MARKERS
        )
    else:
        # A failed generation must leave no assistant message behind.
        persistence_match = _assistant_count(sessions, chat_id) == assistants_before
        integrity_pass = not any(marker in visible for marker in THINK_MARKERS)
    measurement = TurnMeasurement(
        scenario_id=scenario_id,
        turn_number=turn_number,
        first_visible_seconds=first_visible,
        total_seconds=total,
        visible_characters=len(visible),
        integrity_pass=integrity_pass,
        persistence_match=persistence_match,
        error=error,
        used_fallback_answer=used_fallback_answer,
    )
    return measurement, visible


def _assistant_count(sessions, chat_id: str) -> int:
    return sum(1 for m in sessions.get_chat_history(chat_id) if m.role is Role.ASSISTANT)


def run_scenario(
    app,
    scenario: BenchmarkScenario,
    *,
    learner_answers: Sequence[str] = (),
    clock: Callable[[], float] = time.perf_counter,
    show: Callable[[str, int, str, str], None] | None = None,
    model_name: str = "",
    courses: dict | None = None,
    answer_provider: Callable[[str, int, str], str | None] | None = None,
    max_turn_seconds: float | None = DEFAULT_MAX_TURN_SECONDS,
) -> list[TurnMeasurement]:
    """One attempt at a scenario in a brand-new chat.

    `answer_provider(scenario_id, turn_number, last_visible_answer)` supplies
    a learner answer fitted to the question the model just asked (after any
    pre-supplied `learner_answers` are used up); returning None means "use
    the flagged generic fallback"."""
    courses = courses if courses is not None else {}
    course_id = None
    if scenario.course_name is not None:
        key = (scenario.course_name, scenario.course_code)
        if key not in courses:
            courses[key] = app.courses.create_course(scenario.course_name, scenario.course_code).id
        course_id = courses[key]
    chat = app.sessions.create_chat(course_id)
    app.sessions.set_teaching_mode_for_chat(chat.id, scenario.teaching_mode)
    app.sessions.set_reasoning_mode_for_chat(chat.id, scenario.reasoning_mode)

    answers = list(learner_answers)
    measurements: list[TurnMeasurement] = []
    last_visible = ""
    for number, turn in enumerate(scenario.turns, start=1):
        fallback = False
        if turn == LEARNER_ANSWER:
            supplied = answers.pop(0) if answers else None
            if supplied is None and answer_provider is not None:
                supplied = answer_provider(scenario.id, number, last_visible)
            if supplied is None:
                turn, fallback = FALLBACK_LEARNER_ANSWER, True
            else:
                turn = supplied
        measurement, visible = measure_turn(
            app.sessions,
            chat.id,
            turn,
            scenario_id=scenario.id,
            turn_number=number,
            clock=clock,
            used_fallback_answer=fallback,
            max_seconds=max_turn_seconds,
        )
        measurements.append(measurement)
        last_visible = visible
        if show is not None:
            show(model_name, number, turn, visible if measurement.error is None else f"[{measurement.error}]")
        if measurement.error is not None:
            break  # the rest of the conversation has no meaning after a failed turn
    return measurements


class FileAnswerProvider:
    """Lets a human (or a reviewing agent) write each learner answer after
    reading the model's actual question — needed because generation is not
    deterministic, so an answer prepared from an earlier run may not fit.

    For each learner-answer turn it writes `<dir>/<key>.question.txt` (the
    model's final VISIBLE answer to the previous turn) and waits for
    `<dir>/<key>.answer.txt`. The wait is outside every measured interval.
    On timeout it returns None (the flagged generic fallback is used).
    """

    def __init__(self, directory: Path, model_name: str, *, timeout: float = 900.0, sleep=time.sleep, clock=time.monotonic):
        self.directory = Path(directory)
        self.model_key = re.sub(r"[^A-Za-z0-9._-]+", "_", model_name)
        self.timeout, self.sleep, self.clock = timeout, sleep, clock

    def __call__(self, scenario_id: str, turn_number: int, last_visible: str) -> str | None:
        self.directory.mkdir(parents=True, exist_ok=True)
        key = f"{self.model_key}__{scenario_id}__turn{turn_number}"
        question, answer = self.directory / f"{key}.question.txt", self.directory / f"{key}.answer.txt"
        answer.unlink(missing_ok=True)
        question.write_text(last_visible, encoding="utf-8")
        deadline = self.clock() + self.timeout
        while self.clock() < deadline:
            if answer.exists():
                text = answer.read_text(encoding="utf-8").strip()
                if text:
                    return text
            self.sleep(1.0)
        return None


# --- resource evidence ----------------------------------------------------------------

Runner = Callable[[Sequence[str]], str | None]


def run_command(argv: Sequence[str]) -> str | None:
    """Stdout of a short system command, or None if unavailable/failing."""
    try:
        result = subprocess.run(list(argv), capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


_SIZE_RE = re.compile(r"([\d.]+)\s*(KB|MB|GB|TB)", re.IGNORECASE)
_UNIT_GB = {"KB": 1 / 1024**2, "MB": 1 / 1024, "GB": 1.0, "TB": 1024.0}


def _size_gb(text: str) -> float | None:
    match = _SIZE_RE.search(text)
    return round(float(match.group(1)) * _UNIT_GB[match.group(2).upper()], 2) if match else None


def _table_rows(output: str | None) -> list[list[str]]:
    """Rows of an `ollama` CLI table (columns separated by 2+ spaces)."""
    if not output:
        return []
    lines = [line for line in output.splitlines() if line.strip()]
    return [re.split(r"\s{2,}", line.strip()) for line in lines[1:]]


def parse_ollama_ps(output: str | None, model_name: str) -> dict | None:
    for row in _table_rows(output):
        if row and row[0] == model_name and len(row) >= 5:
            return {"model": row[0], "size": row[2], "processor": row[3], "context": row[4]}
    return None


def parse_installed_size_gb(output: str | None, model_name: str) -> float | None:
    for row in _table_rows(output):
        if row and row[0] == model_name and len(row) >= 3:
            return _size_gb(row[2])
    return None


def parse_swap_usage(output: str | None) -> dict | None:
    """`vm.swapusage: total = 2048.00M  used = 1017.50M  free = 1030.50M ...`"""
    if not output:
        return None
    values = {}
    for key in ("total", "used", "free"):
        match = re.search(rf"{key}\s*=\s*([\d.]+)([MG])", output)
        if match is None:
            return None
        values[f"{key}_mb"] = float(match.group(1)) * (1024 if match.group(2) == "G" else 1)
    return values


def parse_memory_pressure_free_percent(output: str | None) -> int | None:
    match = re.search(r"free percentage:\s*(\d+)%", output or "")
    return int(match.group(1)) if match else None


def probe_resources(model_name: str, runner: Runner | None = None) -> dict:
    """Machine-level evidence only (no claim about per-model RAM use)."""
    runner = runner or run_command  # resolved at call time so tests can patch it
    return {
        "ollama_ps": parse_ollama_ps(runner(["ollama", "ps"]), model_name),
        "swap": parse_swap_usage(runner(["sysctl", "vm.swapusage"])),
        "memory_free_percent": parse_memory_pressure_free_percent(runner(["memory_pressure", "-Q"])),
    }


# --- one candidate model --------------------------------------------------------------


def classify_thinking(capabilities: ModelCapabilities | None) -> str:
    """The provider's internal thinking classification, recovered from the
    neutral capability flags (so no private provider state is touched)."""
    if capabilities is None or capabilities.supports_thinking is None:
        return "unknown"
    if not capabilities.supports_thinking:
        return "none"
    return "toggleable" if capabilities.reasoning_modes_distinct else "always_on"


@contextmanager
def isolated_data_dir(keep: bool = False) -> Iterator[Path]:
    """A fresh temporary data directory, removed afterwards unless `keep`."""
    if keep:
        yield Path(tempfile.mkdtemp(prefix="studybot_bench_"))
        return
    with tempfile.TemporaryDirectory(prefix="studybot_bench_") as name:
        yield Path(name)


def _median(values: Sequence[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def summarize(
    model_name: str,
    measurements: Sequence[TurnMeasurement],
    **extras,
) -> ModelBenchmarkSummary:
    firsts = [m.first_visible_seconds for m in measurements if m.first_visible_seconds is not None]
    return ModelBenchmarkSummary(
        model_name=model_name,
        capabilities=extras.pop("capabilities", None),
        measurements=tuple(measurements),
        median_first_visible_seconds=_median(firsts),
        median_total_seconds=_median([m.total_seconds for m in measurements]),
        all_integrity_pass=all(m.integrity_pass for m in measurements),
        all_persistence_match=all(m.persistence_match for m in measurements),
        **extras,
    )


def benchmark_model(
    model_name: str,
    scenarios: Sequence[BenchmarkScenario],
    *,
    learner_answers: Mapping[str, Sequence[str]] | None = None,
    show_answers: bool = False,
    clock: Callable[[], float] = time.perf_counter,
    runner: Runner | None = None,
    unload: Callable[[str], None] | None = None,
    app_factory: Callable[[Settings], StudyBotApp] = StudyBotApp,
    keep_alive: str | None = "10m",
    timeout: float = 900.0,
    keep_temp: bool = False,
    out=sys.stdout,
    answer_provider: Callable[[str, int, str], str | None] | None = None,
    max_turn_seconds: float | None = DEFAULT_MAX_TURN_SECONDS,
) -> ModelBenchmarkSummary:
    """Benchmark one model in its own temporary data directory.

    Raises `UnsafeVerificationEnvironmentError` (never swallowed) if the
    verification guard rejects the directory. Any other failure becomes a
    "not evaluated" summary so the remaining candidates still run.
    """
    learner_answers = learner_answers or {}
    runner = runner or run_command  # resolved at call time so tests can patch it
    unload = unload or (lambda name: runner(["ollama", "stop", name]) and None)

    def show(model, number, prompt, answer):
        print(f"\n===== {model} | turn {number} =====\nUSER: {prompt}\nBOT: {answer}", file=out, flush=True)

    unload(model_name)  # a true cold start for the warm-up request
    try:
        with isolated_data_dir(keep_temp) as data_dir:
            settings = Settings(
                model_provider="ollama",
                data_dir=data_dir,
                ollama_model=model_name,
                ollama_keep_alive=keep_alive,
                ollama_timeout=timeout,
            )
            assert_safe_for_verification(settings)  # before any app exists
            app = app_factory(settings)
            try:
                return _benchmark_in_app(
                    app,
                    model_name,
                    scenarios,
                    learner_answers,
                    show if show_answers else None,
                    clock,
                    runner,
                    answer_provider,
                    max_turn_seconds,
                )
            finally:
                app.close()
    except UnsafeVerificationEnvironmentError:
        raise
    except BenchmarkInvariantError:
        raise
    except Exception as exc:
        return summarize(model_name, (), not_evaluated_reason=f"{type(exc).__name__} while benchmarking")
    finally:
        unload(model_name)  # only this benchmark model


def _benchmark_in_app(
    app, model_name, scenarios, learner_answers, show, clock, runner, answer_provider=None,
    max_turn_seconds=DEFAULT_MAX_TURN_SECONDS,
) -> ModelBenchmarkSummary:
    status = app.sessions.get_status()
    if not status.server_reachable:
        return summarize(model_name, (), not_evaluated_reason="Ollama server not reachable")
    if status.model_available is False:
        return summarize(model_name, (), not_evaluated_reason="model not installed locally")

    capabilities = app.sessions.get_model_capabilities()
    installed_gb = parse_installed_size_gb(runner(["ollama", "list"]), model_name)
    swap_before = probe_resources(model_name, runner)["swap"]

    # One warm-up request: excluded from scored latency, but its cold-load
    # time is recorded on its own.
    warm_chat = app.sessions.create_chat(None)
    app.sessions.set_teaching_mode_for_chat(warm_chat.id, TeachingMode.QUICK)
    warm, _ = measure_turn(
        app.sessions,
        warm_chat.id,
        WARMUP_PROMPT,
        scenario_id="warmup",
        turn_number=1,
        clock=clock,
        max_seconds=max_turn_seconds,
    )
    if warm.error is not None:
        return summarize(
            model_name,
            (),
            capabilities=capabilities,
            thinking_classification=classify_thinking(capabilities),
            installed_size_gb=installed_gb,
            not_evaluated_reason=f"warm-up failed ({warm.error})",
        )
    after_warmup = probe_resources(model_name, runner)

    measurements: list[TurnMeasurement] = []
    retried: list[str] = []
    initial_errors: dict[str, str] = {}
    courses: dict = {}
    for scenario in scenarios:
        answers = learner_answers.get(scenario.id, ())
        attempt = run_scenario(
            app,
            scenario,
            learner_answers=answers,
            clock=clock,
            show=show,
            model_name=model_name,
            courses=courses,
            answer_provider=answer_provider,
            max_turn_seconds=max_turn_seconds,
        )
        failed = next((m for m in attempt if m.error is not None), None)
        if failed is not None:  # exactly one clean retry, in a fresh chat
            retried.append(scenario.id)
            initial_errors[scenario.id] = failed.error or "unknown"
            attempt = run_scenario(
                app,
                scenario,
                learner_answers=answers,
                clock=clock,
                show=show,
                model_name=model_name,
                courses=courses,
                answer_provider=answer_provider,
                max_turn_seconds=max_turn_seconds,
            )
        measurements.extend(attempt)

    swap_after = probe_resources(model_name, runner)["swap"]
    return summarize(
        model_name,
        measurements,
        capabilities=capabilities,
        thinking_classification=classify_thinking(capabilities),
        warmup_first_visible_seconds=None if warm.first_visible_seconds is None else round(warm.first_visible_seconds, 3),
        warmup_total_seconds=round(warm.total_seconds, 3),
        installed_size_gb=installed_gb,
        resources={
            "after_warmup": after_warmup,
            "swap_before": swap_before,
            "swap_after": swap_after,
            "memory_free_percent_after": probe_resources(model_name, runner)["memory_free_percent"],
        },
        retried_scenarios=tuple(retried),
        initial_errors=initial_errors,
    )


# --- serialization (ids, timings, lengths, capabilities, scores only) -----------------


def summary_to_dict(summary: ModelBenchmarkSummary) -> dict:
    data = asdict(summary)
    data["measurements"] = [asdict(m) for m in summary.measurements]
    data["retried_scenarios"] = list(summary.retried_scenarios)
    return data


def summary_from_dict(data: Mapping) -> ModelBenchmarkSummary:
    caps = data.get("capabilities")
    return ModelBenchmarkSummary(
        model_name=data["model_name"],
        capabilities=ModelCapabilities(**caps) if caps else None,
        measurements=tuple(TurnMeasurement(**m) for m in data.get("measurements", ())),
        median_first_visible_seconds=data.get("median_first_visible_seconds"),
        median_total_seconds=data.get("median_total_seconds"),
        all_integrity_pass=data.get("all_integrity_pass", True),
        all_persistence_match=data.get("all_persistence_match", True),
        thinking_classification=data.get("thinking_classification", "unknown"),
        warmup_first_visible_seconds=data.get("warmup_first_visible_seconds"),
        warmup_total_seconds=data.get("warmup_total_seconds"),
        installed_size_gb=data.get("installed_size_gb"),
        resources=dict(data.get("resources") or {}),
        retried_scenarios=tuple(data.get("retried_scenarios", ())),
        initial_errors=dict(data.get("initial_errors") or {}),
        not_evaluated_reason=data.get("not_evaluated_reason"),
    )


def results_document(summaries: Sequence[ModelBenchmarkSummary]) -> dict:
    return {"schema": 1, "scenario_ids": [s.id for s in SCENARIOS], "models": [summary_to_dict(s) for s in summaries]}


def merge_summaries(summaries: Sequence[ModelBenchmarkSummary]) -> list[ModelBenchmarkSummary]:
    """Combine several runs of the same model: a later run's measurement for
    a (scenario, turn) replaces an earlier one's (e.g. a re-run of the
    practice/exam scenarios with real learner answers)."""
    merged: dict[str, ModelBenchmarkSummary] = {}
    for summary in summaries:
        previous = merged.get(summary.model_name)
        if previous is None:
            merged[summary.model_name] = summary
            continue
        replaced = {m.scenario_id for m in summary.measurements}
        kept = [m for m in previous.measurements if m.scenario_id not in replaced]
        combined = summarize(
            summary.model_name,
            [*kept, *summary.measurements],
            capabilities=summary.capabilities or previous.capabilities,
            thinking_classification=(
                summary.thinking_classification
                if summary.capabilities is not None
                else previous.thinking_classification
            ),
            warmup_first_visible_seconds=previous.warmup_first_visible_seconds
            if previous.warmup_first_visible_seconds is not None
            else summary.warmup_first_visible_seconds,
            warmup_total_seconds=previous.warmup_total_seconds
            if previous.warmup_total_seconds is not None
            else summary.warmup_total_seconds,
            installed_size_gb=previous.installed_size_gb
            if previous.installed_size_gb is not None
            else summary.installed_size_gb,
            resources=previous.resources or summary.resources,
            retried_scenarios=tuple(dict.fromkeys([*previous.retried_scenarios, *summary.retried_scenarios])),
            initial_errors={**previous.initial_errors, **summary.initial_errors},
            not_evaluated_reason=None
            if (previous.measurements or summary.measurements)
            else summary.not_evaluated_reason or previous.not_evaluated_reason,
        )
        merged[summary.model_name] = combined
    return list(merged.values())


# --- scoring and selection (pure functions; see the Stage 6.4 contract) ----------------

PERFORMANCE_WEIGHTS = {"fast_first_visible": 15, "overall_first_visible": 5, "overall_total": 5, "warmup": 5}
SIZE_LIMIT_GB = 3.5
SWAP_REGRESSION_LIMIT_MB = 1024.0
"""Warm-benchmark swap growth below this counts as "no severe swap
regression". An explicit, documented threshold — the OS gives no better
single number."""
DISTINCT_MODES_QUALITY_MARGIN = 10
TIE_WINDOW_POINTS = 3
LATENCY_SIMILARITY = 0.10
GRADE_FRACTION = {"PASS": 1.0, "PARTIAL": 0.5, "FAIL": 0.0}


@dataclass(frozen=True, slots=True)
class CandidateScore:
    model_name: str
    disqualified: bool
    reasons: tuple[str, ...]
    quality: float
    performance: float
    capability: float
    resource: float
    total: float
    fast_median_first_visible: float | None
    installed_size_gb: float | None
    reasoning_modes_distinct: bool | None
    performance_detail: dict = field(default_factory=dict)


def quality_score(grades: Mapping[str, str]) -> float:
    """PASS = full points, PARTIAL = half, FAIL/missing = 0."""
    return sum(points * GRADE_FRACTION.get(grades.get(sid, "FAIL"), 0.0) for sid, points in QUALITY_POINTS.items())


def disqualification_reasons(
    summary: ModelBenchmarkSummary, grades: Mapping[str, str], flags: Mapping[str, bool]
) -> tuple[str, ...]:
    reasons: list[str] = []
    if summary.not_evaluated_reason is not None or not summary.measurements:
        reasons.append("not evaluated")
    if not summary.all_integrity_pass:
        reasons.append("reasoning/think-marker leak")
    if not summary.all_persistence_match:
        reasons.append("persisted message differs from visible stream")
    if any(m.error is not None for m in summary.measurements):
        reasons.append("repeated ModelError/crash after one retry")
    for scenario_id in GATE_SCENARIOS:
        if grades.get(scenario_id) == "FAIL":
            reasons.append(f"{scenario_id} materially wrong")
    for flag in GATE_FLAGS:
        if flags.get(flag):
            reasons.append(flag.replace("_", " "))
    return tuple(reasons)


def _median_of(measurements: Sequence[TurnMeasurement], attr: str, only: frozenset[str] | None = None):
    values = [
        getattr(m, attr)
        for m in measurements
        if getattr(m, attr) is not None and (only is None or m.scenario_id in only)
    ]
    return statistics.median(values) if values else None


def future_capability_score(capabilities: ModelCapabilities | None) -> float:
    if capabilities is None:
        return 0.0
    return (
        (5 if capabilities.supports_vision is True else 0)
        + (3 if capabilities.supports_tools is True else 0)
        + (5 if capabilities.reasoning_modes_distinct is True else 0)
        + (2 if capabilities.context_window is not None and capabilities.context_window >= 128_000 else 0)
    )


def resource_score(summary: ModelBenchmarkSummary) -> float:
    score = 0.0
    if summary.installed_size_gb is not None and summary.installed_size_gb <= SIZE_LIMIT_GB:
        score += 2
    before = (summary.resources.get("swap_before") or {}).get("used_mb")
    after = (summary.resources.get("swap_after") or {}).get("used_mb")
    if before is not None and after is not None and after - before < SWAP_REGRESSION_LIMIT_MB:
        score += 3  # inconclusive evidence (missing readings) earns nothing
    return score


def _lower_is_better(weight: float, best: float | None, value: float | None) -> float:
    if best is None or value is None or value <= 0:
        return 0.0
    return min(weight, weight * (best / value))


def score_candidates(
    summaries: Sequence[ModelBenchmarkSummary],
    grades_by_model: Mapping[str, Mapping[str, object]],
    fast_ids: frozenset[str] = FAST_SCENARIO_IDS,
) -> list[CandidateScore]:
    """`grades_by_model[model] = {"grades": {scenario_id: PASS|PARTIAL|FAIL},
    "flags": {...}}` — the manual review of FINAL visible answers."""
    reviews = {
        s.model_name: (
            dict(grades_by_model.get(s.model_name, {}).get("grades", {})),
            dict(grades_by_model.get(s.model_name, {}).get("flags", {})),
        )
        for s in summaries
    }
    reasons = {s.model_name: disqualification_reasons(s, *reviews[s.model_name]) for s in summaries}
    passing = [s for s in summaries if not reasons[s.model_name]]

    def metrics(s):
        return {
            "fast_first_visible": _median_of(s.measurements, "first_visible_seconds", fast_ids),
            "overall_first_visible": _median_of(s.measurements, "first_visible_seconds"),
            "overall_total": _median_of(s.measurements, "total_seconds"),
            "warmup": s.warmup_total_seconds,
        }

    all_metrics = {s.model_name: metrics(s) for s in summaries}
    best = {
        key: min((v for p in passing if (v := all_metrics[p.model_name][key]) is not None), default=None)
        for key in PERFORMANCE_WEIGHTS
    }

    scores = []
    for s in summaries:
        grades, _flags = reviews[s.model_name]
        disqualified = bool(reasons[s.model_name])
        detail = {
            key: 0.0 if disqualified else round(_lower_is_better(w, best[key], all_metrics[s.model_name][key]), 2)
            for key, w in PERFORMANCE_WEIGHTS.items()
        }
        performance = round(sum(detail.values()), 2)
        quality = quality_score(grades)
        capability = future_capability_score(s.capabilities)
        resource = resource_score(s)
        scores.append(
            CandidateScore(
                model_name=s.model_name,
                disqualified=disqualified,
                reasons=reasons[s.model_name],
                quality=quality,
                performance=performance,
                capability=capability,
                resource=resource,
                total=round(quality + performance + capability + resource, 2),
                fast_median_first_visible=all_metrics[s.model_name]["fast_first_visible"],
                installed_size_gb=s.installed_size_gb,
                reasoning_modes_distinct=None if s.capabilities is None else s.capabilities.reasoning_modes_distinct,
                performance_detail=detail,
            )
        )
    return scores


def prefer(a: CandidateScore, b: CandidateScore) -> bool:
    """True if `a` should be chosen over `b` (neither disqualified).

    1. Distinct Fast/Deep: a model without it must lead an otherwise
       comparable model that has it by >= 10 quality points to even be
       considered ahead.
    2. Totals more than 3 points apart: higher total.
    3. Otherwise: higher quality; then lower Fast first-visible latency if it
       differs by 10% or more; then the smaller installed model.
    """
    a_distinct, b_distinct = a.reasoning_modes_distinct is True, b.reasoning_modes_distinct is True
    if b_distinct and not a_distinct and a.quality < b.quality + DISTINCT_MODES_QUALITY_MARGIN:
        return False
    if a_distinct and not b_distinct and b.quality < a.quality + DISTINCT_MODES_QUALITY_MARGIN:
        return True

    if abs(a.total - b.total) > TIE_WINDOW_POINTS:
        return a.total > b.total
    if a.quality != b.quality:
        return a.quality > b.quality
    fa, fb = a.fast_median_first_visible, b.fast_median_first_visible
    if fa is not None and fb is not None and max(fa, fb) > 0:
        if abs(fa - fb) / max(fa, fb) >= LATENCY_SIMILARITY:
            return fa < fb
    sa, sb = a.installed_size_gb, b.installed_size_gb
    if sa is not None and sb is not None and sa != sb:
        return sa < sb
    return False


@dataclass(frozen=True, slots=True)
class Selection:
    default_model: str
    upgrade_justified: bool
    explanation: str


def select_default(scores: Sequence[CandidateScore], baseline: str = BASELINE_MODEL) -> Selection:
    """The baseline stays unless a non-disqualified challenger is preferred
    over it by `prefer`. Disqualified candidates can never win."""
    eligible = [s for s in scores if not s.disqualified]
    if not eligible:
        return Selection(baseline, False, "No eligible candidate; keeping the baseline.")
    by_name = {s.model_name: s for s in eligible}
    champion = by_name.get(baseline) or max(eligible, key=lambda s: s.total)
    for challenger in sorted(eligible, key=lambda s: (-s.total, s.model_name)):
        if challenger is not champion and prefer(challenger, champion):
            champion = challenger
    if champion.model_name == baseline:
        return Selection(baseline, False, "NO UPGRADE JUSTIFIED: no eligible candidate beat the baseline.")
    return Selection(champion.model_name, True, f"{champion.model_name} beat the baseline under the selection rules.")


# --- reporting ------------------------------------------------------------------------


def format_score_table(scores: Sequence[CandidateScore]) -> str:
    header = "| Model | Quality /50 | Performance /30 | Capability /15 | Resource /5 | Total /100 | Gate |\n|---|---|---|---|---|---|---|"
    rows = [
        f"| {s.model_name} | {s.quality:g} | {s.performance:g} | {s.capability:g} | {s.resource:g} | {s.total:g} | "
        + ("DISQUALIFIED: " + "; ".join(s.reasons) if s.disqualified else "pass")
        + " |"
        for s in scores
    ]
    return "\n".join([header, *rows])


def format_latency_table(summaries: Sequence[ModelBenchmarkSummary]) -> str:
    header = "| Model | first-visible min / median / max (s) | Fast median (s) | median total (s) | warm-up total (s) |\n|---|---|---|---|---|"
    rows = []
    for s in summaries:
        firsts = [m.first_visible_seconds for m in s.measurements if m.first_visible_seconds is not None]
        spread = f"{min(firsts):.1f} / {statistics.median(firsts):.1f} / {max(firsts):.1f}" if firsts else "n/a"
        fast = _median_of(s.measurements, "first_visible_seconds", FAST_SCENARIO_IDS)
        rows.append(
            f"| {s.model_name} | {spread} | {fast if fast is None else round(fast, 1)} | "
            f"{s.median_total_seconds} | {s.warmup_total_seconds} |"
        )
    return "\n".join([header, *rows])


# --- command line ---------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--output", type=Path, help="write the machine-readable results here (no answer text)")
    parser.add_argument("--show-answers", action="store_true", help="print FINAL visible answers to the terminal")
    parser.add_argument("--only", nargs="+", metavar="SCENARIO_ID", help="run just these scenarios")
    parser.add_argument("--learner-answers", type=Path, help='JSON {"<model>": {"<scenario_id>": ["answer", ...]}}')
    parser.add_argument(
        "--answer-dir",
        type=Path,
        help="interactive learner answers: write <key>.question.txt, wait for <key>.answer.txt in this directory",
    )
    parser.add_argument("--answer-timeout", type=float, default=900.0, help="seconds to wait for each answer file")
    parser.add_argument(
        "--max-turn-seconds",
        type=float,
        default=DEFAULT_MAX_TURN_SECONDS,
        help="abandon (and record as TurnTimeout) any turn running longer than this (default 420)",
    )
    parser.add_argument("--keep-alive", default="10m", help="Ollama keep_alive used for the benchmark (default 10m)")
    parser.add_argument("--timeout", type=float, default=900.0, help="per-request timeout seconds (default 900)")
    parser.add_argument("--keep-temp", action="store_true", help="debug: don't delete the temporary data directories")
    parser.add_argument("--score-from", nargs="+", type=Path, metavar="RESULTS", help="score saved result files")
    parser.add_argument("--grades", type=Path, help="manual grades JSON for --score-from")
    parser.add_argument("--baseline", default=BASELINE_MODEL)
    return parser


def _score_mode(args) -> int:
    summaries = merge_summaries(
        [summary_from_dict(m) for path in args.score_from for m in json.loads(path.read_text())["models"]]
    )
    grades = json.loads(args.grades.read_text()) if args.grades else {}
    scores = score_candidates(summaries, grades)
    selection = select_default(scores, baseline=args.baseline)
    print(format_score_table(scores))
    print()
    print(format_latency_table(summaries))
    print()
    print(f"Selected default: {selection.default_model} — {selection.explanation}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.score_from:
        return _score_mode(args)

    scenarios = SCENARIOS
    if args.only:
        unknown = sorted(set(args.only) - {s.id for s in SCENARIOS})
        if unknown:
            print(f"Unknown scenario id(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        scenarios = tuple(s for s in SCENARIOS if s.id in set(args.only))
    learner_answers = json.loads(args.learner_answers.read_text()) if args.learner_answers else {}

    summaries: list[ModelBenchmarkSummary] = []
    try:
        for model_name in args.models:
            print(f"--- benchmarking {model_name}", file=sys.stderr, flush=True)
            summaries.append(
                benchmark_model(
                    model_name,
                    scenarios,
                    learner_answers=learner_answers.get(model_name, {}),
                    show_answers=args.show_answers,
                    keep_alive=args.keep_alive,
                    timeout=args.timeout,
                    keep_temp=args.keep_temp,
                    max_turn_seconds=args.max_turn_seconds,
                    answer_provider=(
                        FileAnswerProvider(args.answer_dir, model_name, timeout=args.answer_timeout)
                        if args.answer_dir
                        else None
                    ),
                )
            )
            last = summaries[-1]
            print(
                f"    {model_name}: {len(last.measurements)} turns"
                + (f", NOT EVALUATED ({last.not_evaluated_reason})" if last.not_evaluated_reason else ""),
                file=sys.stderr,
                flush=True,
            )
    except UnsafeVerificationEnvironmentError as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    except BenchmarkInvariantError as exc:
        print(f"Benchmark invariant failed: {exc}", file=sys.stderr)
        return 2

    if args.output:
        args.output.write_text(json.dumps(results_document(summaries), indent=2) + "\n", encoding="utf-8")
    return 0 if any(s.measurements for s in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
