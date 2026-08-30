"""Code-enforced bookkeeping for "find the cheapest/best X" tasks.

Motivation: asking the model to maintain its own running best across steps does
not work reliably at this model size. In testing it would record
"Tastes Like Fear - GBP 10.69", scroll once, and overwrite it with
"Hide Away - GBP 11.84" — a worse value — despite an explicit instruction (and a
worked example using those exact numbers) telling it not to. It also re-estimated
the page's stated result total on every step (20 -> 32 -> 24 -> 36 -> 16), which
meant a survey rule keyed on "have I seen everything yet?" could never terminate.

So the model is now asked only to REPORT what it can see this step (a list of
name/value candidates). All comparison, accumulation, and termination logic lives
here, where it is deterministic and testable.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def parse_numeric_value(raw: Any) -> Optional[float]:
    """Extracts a number from a model-supplied value like "GBP 10.69" or "1,234.50"."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str):
        return None
    match = _NUM_RE.search(raw.replace(" ", ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


class SurveyTracker:
    """Accumulates candidates across steps and owns the running best."""

    def __init__(self) -> None:
        self.items: Dict[str, Tuple[str, float]] = {}  # key -> (display name, value)
        self.total: Optional[int] = None
        self.objective: str = "NONE"
        self.last_new_count: int = 0
        self.scroll_rounds_without_new: int = 0

    def set_objective(self, objective: Any) -> None:
        """First declared objective wins; it should not flip mid-task."""
        if self.objective != "NONE":
            return
        if isinstance(objective, str) and objective.upper() in ("MINIMIZE", "MAXIMIZE"):
            self.objective = objective.upper()

    def set_total(self, total: Any) -> None:
        """The page's stated result count is locked to the first value seen.

        The model re-reads (and mis-reads) this number every step once it scrolls
        past the header, so later reports are ignored rather than trusted.
        """
        if self.total is not None:
            return
        parsed = parse_numeric_value(total)
        if parsed is not None and parsed > 0:
            self.total = int(parsed)

    def add_candidates(self, candidates: Any) -> int:
        """Records this step's visible items. Returns how many were new."""
        new_count = 0
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                name = str(candidate.get("name", "")).strip()
                value = parse_numeric_value(candidate.get("value"))
                if not name or value is None:
                    continue
                key = name.lower()
                if key not in self.items:
                    new_count += 1
                self.items[key] = (name, value)

        self.last_new_count = new_count
        if new_count == 0:
            self.scroll_rounds_without_new += 1
        else:
            self.scroll_rounds_without_new = 0
        return new_count

    @property
    def best(self) -> Optional[Tuple[str, float]]:
        if not self.items or self.objective == "NONE":
            return None
        values = list(self.items.values())
        if self.objective == "MINIMIZE":
            return min(values, key=lambda item: item[1])
        return max(values, key=lambda item: item[1])

    @property
    def seen_count(self) -> int:
        return len(self.items)

    @property
    def is_exhausted(self) -> bool:
        """True once scrolling has stopped yielding anything new."""
        return self.scroll_rounds_without_new >= 1

    @property
    def is_complete(self) -> bool:
        """True when we've seen at least as many items as the page advertised."""
        return self.total is not None and self.seen_count >= self.total

    def render(self) -> str:
        """The authoritative survey block injected into the next prompt."""
        if self.objective == "NONE" and not self.items:
            return ""

        lines = ["SURVEY STATE (system-maintained ground truth — trust this over your memory):"]
        if self.objective != "NONE":
            direction = "lowest" if self.objective == "MINIMIZE" else "highest"
            lines.append(f"- You are looking for the {direction} value.")

        best = self.best
        if best:
            lines.append(f'- BEST FOUND SO FAR: "{best[0]}" at {best[1]:g} <- this is the current winner.')
            lines.append("  Only report a different winner if you can see something strictly better than this.")
        else:
            lines.append("- No candidates recorded yet.")

        if self.total is not None:
            lines.append(f"- Items surveyed: {self.seen_count} of {self.total} stated on the page.")
        else:
            lines.append(f"- Items surveyed: {self.seen_count}.")

        return "\n".join(lines)
