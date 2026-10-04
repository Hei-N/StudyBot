"""Output integrity: keep a model's internal reasoning out of its answer.

Stage 6.3. Some local models (Qwen3's thinking variants in particular) can
emit their chain-of-thought *inside* the ordinary content channel instead
of Ollama's separate `thinking` field — e.g. a thinking-only model asked to
not think (`think=False`) still reasons, but its template's pre-opened
`<think>` block means the only visible marker is a bare closing `</think>`
somewhere in the middle of `content`. Nothing downstream of the model
provider can tell reasoning from answer after the fact, so the separation
happens here, once, at the provider boundary, for both the streaming and
non-streaming paths.

Two pieces:

* `ReasoningOutputFilter` — a stateful, incremental filter a provider runs
  its raw content chunks through. It strips a reasoning span that opens the
  response (`<think>…</think>`, also split across any number of chunks),
  buffers anything that is still ambiguous rather than emitting it and
  "taking it back" later, and **fails closed** (`UnsafeModelOutputError`)
  on anything it cannot separate confidently: an unterminated span, or a
  `</think>` marker appearing in answer prose outside code. Legitimate
  mentions of the tags inside fenced code blocks or inline code spans (a
  student asking how Qwen's template works, say) pass through untouched.
  A response with no visible answer at all also fails closed.

* `strip_confident_reasoning` — the non-streaming, *non-destructive*
  counterpart for already-persisted history (conversations saved before
  this stage). It only returns a changed string when the reasoning portion
  is identified with confidence; callers use it on the copy of history
  they send to the model, never to rewrite storage.

Nothing in this module logs message content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from studybot.core.exceptions import UnsafeModelOutputError

OPEN_TAG = "<think>"
CLOSE_TAG = "</think>"

_UNSAFE_OUTPUT_MESSAGE = (
    "The model's reply could not be safely separated from its internal reasoning, "
    "so it was discarded. Please try again."
)
_EMPTY_ANSWER_MESSAGE = "The model finished without producing an answer. Please try again."

# A fence opener/closer: up to three spaces of indentation, then a run of at
# least three backticks or tildes (CommonMark).
_FENCE_RE = re.compile(r" {0,3}(`{3,}|~{3,})")


class _LeakDetected(Exception):
    """Internal signal from `_AnswerScanner`; converted to
    `UnsafeModelOutputError` by the filter."""


class _AnswerScanner:
    """Scans answer text line by line, tracking Markdown code (fenced blocks
    and inline code spans), and raises `_LeakDetected` for a `</think>`
    marker that appears outside code.

    Text is released progressively; the only things held back are pieces
    whose meaning isn't known yet: a line start that may still turn into a
    code fence, a trailing fragment that may still complete into
    `</think>`, and an inline code span whose closing backticks haven't
    arrived (inline spans never cross a line here — an unmatched backtick
    run is just literal text, as in CommonMark, so it can't hide a marker).
    """

    def __init__(self) -> None:
        self._in_fence = False
        self._fence_char = ""
        self._fence_len = 0
        self._line = ""
        self._pos = 0  # index in _line up to which text has been released
        self._line_kind: str | None = None  # None (undecided) / "code" / "text"
        self._opens_fence: tuple[str, int] | None = None

    def feed(self, text: str) -> str:
        out: list[str] = []
        while text:
            newline = text.find("\n")
            if newline == -1:
                self._line += text
                text = ""
                out.append(self._advance(complete=False))
            else:
                self._line += text[: newline + 1]
                text = text[newline + 1 :]
                out.append(self._advance(complete=True))
                self._end_line()
        return "".join(out)

    def finish(self) -> str:
        out = self._advance(complete=True)
        self._end_line()
        return out

    def _decide_line_kind(self, complete: bool) -> bool:
        """Classify the current line as code or text; False if it's still
        too early to tell."""
        stripped = self._line.lstrip(" ")
        indent = len(self._line) - len(stripped)
        if not complete and indent <= 3 and (not stripped or set(stripped) <= {"`"} or set(stripped) <= {"~"}):
            return False
        fence = _FENCE_RE.match(self._line)
        if self._in_fence:
            self._line_kind = "code"
        elif fence is not None and not (fence.group(1)[0] == "`" and "`" in self._line[fence.end() :]):
            self._line_kind = "code"
            self._opens_fence = (fence.group(1)[0], len(fence.group(1)))
        else:
            self._line_kind = "text"
        return True

    def _advance(self, complete: bool) -> str:
        if self._line_kind is None and not self._decide_line_kind(complete):
            return ""
        line = self._line
        if self._line_kind == "code":
            out = line[self._pos :]
            self._pos = len(line)
            return out

        i = self._pos
        limit = len(line)
        while i < limit:
            char = line[i]
            if char == "`":
                run_end = i
                while run_end < limit and line[run_end] == "`":
                    run_end += 1
                if run_end == limit and not complete:
                    break  # the run may still grow
                run = line[i:run_end]
                close = _find_closing_run(line, run_end, len(run))
                if close != -1:
                    i = close + len(run)  # skip the whole inline code span
                    continue
                if not complete:
                    break  # the closing run may not have arrived yet
                i = run_end  # unmatched: literal backticks
                continue
            if char == "<":
                fragment = line[i : i + len(CLOSE_TAG)]
                if fragment == CLOSE_TAG:
                    raise _LeakDetected
                if not complete and i + len(fragment) == limit and CLOSE_TAG.startswith(fragment):
                    break  # may still complete into the marker
            i += 1

        out = line[self._pos : i]
        self._pos = i
        return out

    def _end_line(self) -> None:
        if self._line_kind == "code":
            if self._in_fence:
                fence = _FENCE_RE.match(self._line)
                if (
                    fence is not None
                    and fence.group(1)[0] == self._fence_char
                    and len(fence.group(1)) >= self._fence_len
                    and not self._line[fence.end() :].strip()
                ):
                    self._in_fence = False
            elif self._opens_fence is not None:
                self._in_fence = True
                self._fence_char, self._fence_len = self._opens_fence
        self._line = ""
        self._pos = 0
        self._line_kind = None
        self._opens_fence = None


def _find_closing_run(line: str, start: int, length: int) -> int:
    """Index of the next backtick run of exactly `length` in `line` at or
    after `start`, or -1."""
    i = start
    while True:
        i = line.find("`", i)
        if i == -1:
            return -1
        end = i
        while end < len(line) and line[end] == "`":
            end += 1
        if end - i == length:
            return i
        i = end


class _State(Enum):
    IMPLICIT = "implicit"  # reasoning may have started without an opening tag
    LEADING = "leading"  # nothing visible released yet
    IN_SPAN = "in_span"  # inside a reasoning span: discard
    PASS = "pass"  # answer text: released through _AnswerScanner


@dataclass(frozen=True)
class FilterStats:
    """Content-free counters, safe to log."""

    reasoning_spans: int
    reasoning_chars_discarded: int
    visible_chars: int


class ReasoningOutputFilter:
    """Incrementally separates a model's answer from inline reasoning.

    Usage: call `feed(chunk)` for each raw content chunk and release
    whatever it returns (possibly ""); call `finish()` once at the end and
    release that too. Either may raise `UnsafeModelOutputError`, after which
    the generation must be treated as failed — nothing it produced should be
    persisted.

    `implicit_open=True` is for a model that may begin reasoning with *no*
    opening tag (a thinking-only model whose template pre-opens the block,
    driven without structured thinking separation). Then everything is
    buffered until a `</think>` arrives — whatever precedes it is reasoning —
    or the response ends without one, in which case it is all answer. That
    gives up progressive streaming, so providers only use it when they can't
    establish the model's thinking behavior up front.
    """

    def __init__(self, *, implicit_open: bool = False) -> None:
        self._state = _State.IMPLICIT if implicit_open else _State.LEADING
        self._pending = ""
        self._scanner = _AnswerScanner()
        self._spans = 0
        self._discarded = 0
        self._visible = 0
        self._finished = False

    @property
    def stats(self) -> FilterStats:
        return FilterStats(self._spans, self._discarded, self._visible)

    def feed(self, text: str) -> str:
        if self._finished:
            raise RuntimeError("ReasoningOutputFilter.feed() after finish()")
        if not text:
            return ""
        self._pending += text
        return self._release(self._drain(final=False))

    def finish(self) -> str:
        if self._finished:
            return ""
        out = self._drain(final=True)
        self._finished = True
        if self._state is _State.IN_SPAN:
            raise UnsafeModelOutputError(_UNSAFE_OUTPUT_MESSAGE)
        try:
            out += self._scanner.finish()
        except _LeakDetected:
            raise UnsafeModelOutputError(_UNSAFE_OUTPUT_MESSAGE) from None
        out = self._release(out)
        if self._visible == 0:
            raise UnsafeModelOutputError(_EMPTY_ANSWER_MESSAGE)
        return out

    def _release(self, text: str) -> str:
        if text.strip():
            self._visible += len(text)
        elif self._visible == 0:
            return ""  # never release leading whitespace on its own
        return text

    def _drain(self, *, final: bool) -> str:
        out: list[str] = []
        while True:
            if self._state is _State.IMPLICIT:
                index = self._pending.find(CLOSE_TAG)
                if index != -1:
                    self._discard(index + len(CLOSE_TAG))
                    self._spans += 1
                    self._state = _State.LEADING
                    continue
                if final:
                    self._state = _State.LEADING
                    continue
                return ""

            if self._state is _State.LEADING:
                stripped = self._pending.lstrip()
                if not stripped:
                    if final:
                        self._pending = ""
                    return "".join(out)
                if stripped.startswith(OPEN_TAG):
                    self._discarded += len(OPEN_TAG)
                    self._pending = stripped[len(OPEN_TAG) :]
                    self._state = _State.IN_SPAN
                    continue
                if OPEN_TAG.startswith(stripped) and not final:
                    self._pending = stripped
                    return "".join(out)  # could still be an opening tag
                self._pending = stripped
                self._state = _State.PASS
                continue

            if self._state is _State.IN_SPAN:
                index = self._pending.find(CLOSE_TAG)
                if index != -1:
                    self._discard(index + len(CLOSE_TAG))
                    self._spans += 1
                    self._state = _State.LEADING
                    continue
                # Discard reasoning as it arrives; keep only a tail that
                # might be the start of a split closing tag.
                keep = len(CLOSE_TAG) - 1
                if len(self._pending) > keep:
                    self._discard(len(self._pending) - keep)
                return "".join(out)

            # PASS
            text, self._pending = self._pending, ""
            try:
                out.append(self._scanner.feed(text))
            except _LeakDetected:
                raise UnsafeModelOutputError(_UNSAFE_OUTPUT_MESSAGE) from None
            return "".join(out)

    def _discard(self, count: int) -> None:
        self._discarded += count
        self._pending = self._pending[count:]


def filter_complete_output(text: str, *, implicit_open: bool = False) -> str:
    """Run a complete (non-streamed) response through the same filter the
    streaming path uses, so both paths apply one identical policy."""
    output_filter = ReasoningOutputFilter(implicit_open=implicit_open)
    return output_filter.feed(text) + output_filter.finish()


# --- persisted history ---------------------------------------------------------

_STANDALONE_CLOSE_RE = re.compile(r"^[ \t]*</think>[ \t]*$", re.MULTILINE)


class HistoryVerdict(Enum):
    CLEAN = "clean"
    CONTAMINATED = "contaminated"  # reasoning confidently identified
    AMBIGUOUS = "ambiguous"  # marker present, reasoning not confidently identified


@dataclass(frozen=True)
class HistoryAssessment:
    verdict: HistoryVerdict
    repaired: str | None  # the answer alone, only when CONTAMINATED
    removed_chars: int = 0


def assess_stored_reply(content: str) -> HistoryAssessment:
    """Classify one stored assistant reply.

    Deliberately narrow — no guessing about prose that merely *sounds* like
    planning. A reply is CONTAMINATED only for the two exact shapes the
    Stage 6.3 leak produced:

    * a leading `<think>…</think>` span followed by a non-empty answer, or
    * no opening tag, exactly one `</think>` alone on its own line outside
      code, and a non-empty answer after it (a thinking-only model's
      template pre-opens the block, so everything before the marker is
      reasoning).

    Any other occurrence of a marker outside code is AMBIGUOUS: reported by
    the audit, left untouched everywhere.
    """
    if OPEN_TAG not in content and CLOSE_TAG not in content:
        return HistoryAssessment(HistoryVerdict.CLEAN, None)

    try:
        answer = filter_complete_output(content)
    except UnsafeModelOutputError:
        answer = None
    if answer is not None:
        if answer.strip() == content.strip():
            return HistoryAssessment(HistoryVerdict.CLEAN, None)  # markers only inside code
        return _contaminated(content, answer)  # a leading <think>…</think> span

    if content.lstrip().startswith(OPEN_TAG):
        return HistoryAssessment(HistoryVerdict.AMBIGUOUS, None)

    closes = list(_STANDALONE_CLOSE_RE.finditer(content))
    if len(closes) == 1 and OPEN_TAG not in content[: closes[0].start()]:
        answer_part = content[closes[0].end() :]
        try:
            answer = filter_complete_output(answer_part)
        except UnsafeModelOutputError:
            return HistoryAssessment(HistoryVerdict.AMBIGUOUS, None)
        return _contaminated(content, answer)

    return HistoryAssessment(HistoryVerdict.AMBIGUOUS, None)


def _contaminated(original: str, answer: str) -> HistoryAssessment:
    answer = answer.strip()
    return HistoryAssessment(HistoryVerdict.CONTAMINATED, answer, len(original) - len(answer))


def strip_confident_reasoning(content: str) -> str:
    """The answer alone if `content` is a confidently-identified
    contaminated reply; otherwise `content` unchanged. Never raises."""
    assessment = assess_stored_reply(content)
    if assessment.verdict is HistoryVerdict.CONTAMINATED and assessment.repaired:
        return assessment.repaired
    return content
