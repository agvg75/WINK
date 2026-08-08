"""One serialisable description of what is being analysed, passed between tools.

Fix "A" from the reachability finding of 7 Aug 2026.

THE DEFECT THIS EXISTS TO END. Every cross-module call in WINK is
`subprocess.Popen([python, script, ...])`, so only what fits in argv can
cross, and each call site invents for itself which fragment to send. Two
failures in one week, both from the same cause:

  the GCaMP handoff sent the recording and forgot the frame range, so the
  tracker analysed all 8,999 frames of a span the caller had assessed as 234

  the tracker's `g` key sent `session_path.parent.parent` - a directory
  DERIVED from where the session file happened to sit, not the recording as
  loaded - and the workbench opened on a folder with no images in it and said
  so, which was true and useless

Neither is a bug in the receiver. Both are a caller reconstructing a fact it
already held. So the fact travels whole, in a file, and the receiver reads it
instead of being handed pieces.

WHAT IT REFUSES, AND WHY EACH REFUSAL IS THE POINT

  no source          a context whose source is empty or derived-and-wrong is
                     the `g` key defect. The source must be the recording AS
                     LOADED; there is no default and none is invented.
  half a range       frame_start without frame_end, or the reverse. The
                     existing tracker rule already refuses this on the command
                     line; a context that could carry half a range would be a
                     way around it.
  a newer schema     old code reading a file written by a newer tool FAILS
                     LOUDLY rather than ignoring fields it does not recognise.
                     Silently dropping an unknown field is how a range gets
                     lost - which is the defect this module exists to fix,
                     reintroduced one layer down.

UNKNOWN IS None, NEVER A DEFAULT. A context that does not know the frame rate
says so. Filling in 30 fps because most recordings are 30 fps would produce a
number indistinguishable from a measured one.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

SCHEMA = 1
ENV_CONTEXT = "WINK_ANALYSIS_CONTEXT"


class ContextError(ValueError):
    """A context that cannot be trusted. Never repaired, always refused."""


@dataclass
class AnalysisContext:
    """What one tool must tell another about the thing being analysed."""

    source: str
    tool: str = ""
    frame_start: Optional[int] = None      # 1-based, inclusive, as shown
    frame_end: Optional[int] = None        # 1-based, inclusive, as shown
    fps: Optional[float] = None
    um_per_px: Optional[float] = None
    session: str = ""
    note: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if not str(self.source).strip():
            raise ContextError(
                "An analysis context needs the recording it describes. The "
                "source must be the recording AS LOADED - not a directory "
                "derived from where a session file happened to sit, which is "
                "how the segmentation workbench came to open on a folder "
                "with no images in it.")
        self.source = str(self.source)
        if (self.frame_start is None) != (self.frame_end is None):
            raise ContextError(
                "A frame range needs both ends. Half a range cannot be "
                "inherited: the receiver would have to invent the other end, "
                "and would analyse a different span than the one the caller "
                "assessed.")
        if self.frame_start is not None:
            self.frame_start = int(self.frame_start)
            self.frame_end = int(self.frame_end)
            if self.frame_start < 1 or self.frame_end < self.frame_start:
                raise ContextError(
                    f"Frames are 1-based and inclusive, so a range runs from "
                    f"at least 1 upwards. Got {self.frame_start}-"
                    f"{self.frame_end}.")

    # ------------------------------------------------------------- range
    @property
    def has_range(self):
        return self.frame_start is not None

    def frame_count(self):
        if not self.has_range:
            return None
        return self.frame_end - self.frame_start + 1

    def describe_range(self):
        if not self.has_range:
            return "the whole recording"
        return (f"frames {self.frame_start}-{self.frame_end} "
                f"({self.frame_count():,} frames)")

    # ------------------------------------------------------ serialisation
    def to_dict(self):
        data = asdict(self)
        data["schema"] = SCHEMA
        return data

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ContextError("An analysis context must be a JSON object.")
        found = data.get("schema", SCHEMA)
        try:
            found = int(found)
        except (TypeError, ValueError):
            raise ContextError(f"Unreadable context schema {found!r}.")
        if found > SCHEMA:
            # FAIL LOUDLY ON A NEWER SCHEMA. The alternative - read the
            # fields we know and ignore the rest - is exactly how the frame
            # range went missing in the first place.
            raise ContextError(
                f"This context was written by a newer version of WINK "
                f"(schema {found}; this tool understands {SCHEMA}). It may "
                f"describe the analysis in terms this version does not know, "
                f"so it is refused rather than partly read. Update, or "
                f"re-export from the tool that made it.")
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def write(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path

    def write_temp(self, prefix="wink_context_"):
        """A context file for one subprocess call. Caller may delete it."""
        handle, name = tempfile.mkstemp(prefix=prefix, suffix=".json")
        os.close(handle)
        return self.write(name)

    @classmethod
    def read(cls, path):
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except OSError as exc:
            raise ContextError(f"Cannot read the analysis context: {exc}")
        except json.JSONDecodeError as exc:
            raise ContextError(
                f"The analysis context is not valid JSON: {exc}")
        return cls.from_dict(data)

    # ------------------------------------------------------ command line
    def command_arguments(self, path=None):
        """['--context', path] - what a caller appends to a subprocess call."""
        return ["--context", str(path or self.write_temp())]


def sample_indices(count, sample_limit, context=None):
    """Frame indices to sample, 0-based, honouring the caller's range.

    EVERY RECEIVER NEEDS THIS RULE, so it lives here rather than being
    rewritten per tool. Sampling across a whole recording when the caller
    assessed an interval judges the result against footage nobody asked
    about: it once produced an eighteen-fold apparent swing that was simply
    the animal being absent outside the tested range.

    A range that does not fit is REFUSED, not clamped. Trimming it would
    measure a different span than the one assessed and report it under the
    caller's numbers - wrong in a way that looks right.
    """
    count = int(count)
    if count < 1:
        raise ContextError("The recording has no readable frames.")
    low, high = 0, count - 1
    if context is not None and context.has_range:
        low, high = context.frame_start - 1, context.frame_end - 1
        if low < 0 or high >= count:
            raise ContextError(
                f"The calling tool asked for {context.describe_range()}, but "
                f"this recording has {count:,} frames. Nothing was sampled; "
                f"the range was not trimmed to fit, because measuring a "
                f"different span than the one that was assessed would be "
                f"reported under the caller's numbers.")
    span = high - low + 1
    wanted = max(1, min(int(sample_limit), span))
    if wanted == 1:
        return [low]
    step = (high - low) / (wanted - 1)
    return sorted({int(round(low + step * i)) for i in range(wanted)})


def add_argument(parser):
    """Give a tool a --context option. One line per receiving tool."""
    parser.add_argument(
        "--context", default=None, metavar="FILE",
        help=("An analysis context written by the calling tool: the "
              "recording, and the frame range if one was chosen."))
    return parser


def from_arguments(args, required=False):
    """The context named by --context, or by the environment, or None."""
    path = getattr(args, "context", None) or os.environ.get(ENV_CONTEXT)
    if not path:
        if required:
            raise ContextError("This tool needs --context.")
        return None
    return AnalysisContext.read(path)
