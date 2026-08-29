import json
import re
import logging
from typing import Dict, Any, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # avoid importing torch/transformers just for a type hint —
    from PIL import Image  # keeps this module importable (and testable) on CPU-only machines
    from src.model import Gemma4VisionClient

logger = logging.getLogger(__name__)

def _find_json_objects(raw_text: str):
    """Yields candidate JSON object substrings by brace matching.

    A greedy `\\{.*\\}` grabs from the first brace to the LAST one in the whole
    string, so any extra prose or example braces around the real payload produce
    an unparseable super-string. Scanning for balanced braces (ignoring braces
    inside strings) yields each self-contained object instead.
    """
    depth = 0
    start = None
    in_string = False
    escape = False
    for i, ch in enumerate(raw_text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    yield raw_text[start:i + 1]
                    start = None

def _coerce_int(value: Any, default: int) -> int:
    """Best-effort int coercion — one bad field shouldn't discard a good parse."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default

class UsabilityEngine:
    def __init__(self, llm_client: "Gemma4VisionClient"):
        self.llm = llm_client
        self.parse_failures = 0
        self.parse_attempts = 0

    def _parse_json_payload(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """Returns the largest valid JSON object found in the model output."""
        best = None
        for candidate in _find_json_objects(raw_text):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and (best is None or len(candidate) > best[1]):
                best = (parsed, len(candidate))
        return best[0] if best else None

    def _extract_clean_json(self, raw_text: str) -> Dict[str, Any]:
        self.parse_attempts += 1
        data = self._parse_json_payload(raw_text)
        if data is not None:
            monologue = str(data.get("internal_monologue", "")).replace("```json", "").replace("```", "").strip()
            data["internal_monologue"] = monologue if monologue else "Evaluating the interface..."
            data["confusion_pct"] = max(0, min(100, _coerce_int(data.get("confusion_pct"), 20)))
            if "click_coords" not in data:
                data["click_coords"] = {"x_pct": 50, "y_pct": 50}
            return data

        self.parse_failures += 1
        logger.warning(
            "Could not parse JSON from model output (%s/%s failures this session). Raw head: %r",
            self.parse_failures, self.parse_attempts, raw_text[:300]
        )

        clean_thought = re.sub(r'\{.*?\}', '', raw_text, flags=re.DOTALL)
        clean_thought = clean_thought.replace("```json", "").replace("```", "").strip()[:180]
        
        # NOTE: this path used to return action "COMPLETE", which made an
        # unparseable model response show up in the benchmark matrix as a
        # successful task completion. Reporting it as BLOCKED is honest — a run
        # we cannot read is a failed run, not a passed one.
        return {
            "internal_monologue": clean_thought if clean_thought else "I'm not sure what to do on this screen.",
            "goal_status": "BLOCKED",
            "confusion_pct": 90,
            "sentiment": "FRUSTRATED",
            "action": "DROP_OFF",
            "target_tag": None,
            "click_coords": {"x_pct": 50, "y_pct": 50},
            "input_text": "",
            "critique": "Run aborted: the model's response could not be parsed as valid JSON, so this step's decision is unknown.",
            "parse_failed": True
        }

    def generate_custom_persona(self, user_description: str) -> Dict[str, Any]:
        prompt = f"""
Convert this user description into a structured UX Persona profile:
"{user_description}"

Output ONLY a JSON object:
{{
  "id": "custom_persona",
  "name": "First Name, Age (e.g. Sarah, 42)",
  "age": 42,
  "tech_literacy": "Low" | "Medium" | "High",
  "habits": "2 concise sentences describing usability biases, friction triggers, and preferences",
  "patience": 6,
  "avatar": "single emoji (e.g. 👨‍⚕️, 👩‍🎨, 🧑‍💼, 👵)"
}}
"""
        raw_output = self.llm.generate_with_vision(prompt, image=None, max_new_tokens=250, temperature=0.4)
        fallback = {
            "id": "custom_persona",
            "name": "Custom Persona",
            "age": 40,
            "tech_literacy": "Medium",
            "habits": user_description[:100],
            "patience": 6,
            "avatar": "👤"
        }
        parsed = self._parse_json_payload(raw_output)
        if parsed is not None:
            # Guard against the model omitting required keys — downstream code
            # (app.py, visualizer.py) indexes these directly.
            fallback.update({k: v for k, v in parsed.items() if v not in (None, "")})
            fallback["age"] = _coerce_int(fallback.get("age"), 40)
            fallback["patience"] = max(1, min(10, _coerce_int(fallback.get("patience"), 6)))
            return fallback

        logger.warning("Could not parse persona JSON; using fallback. Raw head: %r", raw_output[:300])
        return fallback

    def simulate_visual_web_step(self, persona: Dict[str, Any], screenshot: "Image.Image", page_title: str, url: str, task: str, visual_elements: List[Dict[str, Any]], history: List[Dict[str, Any]], step_num: int, observations: str = "") -> Dict[str, Any]:
        # Label each badge by its interaction kind. A bare "Tag [26] -> button" is
        # easy to conflate with the item it belongs to; naming the kind explicitly
        # makes "the button for this item" less ambiguous than a bare number.
        def _describe(el: Dict[str, Any]) -> str:
            tag = el.get("tag", "")
            el_type = (el.get("type") or "").lower()
            if tag in ("input", "textarea") or el_type in ("text", "search", "email", "password"):
                kind = "TEXT INPUT (type into this)"
            elif tag == "select":
                kind = "DROPDOWN"
            elif tag == "button" or el_type in ("submit", "button"):
                kind = "BUTTON (click to act)"
            elif tag == "a":
                kind = "LINK (click to navigate)"
            else:
                kind = tag.upper() or "ELEMENT"
            return f"Tag [{el['id']}] -> {kind}: \"{el['text']}\""

        elements_formatted = (
            "\n".join(_describe(el) for el in visual_elements)
            if visual_elements
            else "Canvas interface / Figma prototype (Use visual click_coords)."
        )
        
        history_text = "No prior actions taken."
        if history:
            history_lines = []
            for h in history:
                line = f"- Step {h['step']}: {h['action']} on '{h.get('target_text', '')}' (Typed: '{h.get('input_text', '')}')"
                if h.get("had_no_effect"):
                    line += " ⚠ NO VISIBLE CHANGE resulted from this action — it likely failed or the element was unresponsive. Do NOT repeat it; pick a different element or try scrolling."
                history_lines.append(line)
            history_text = "\n".join(history_lines)

        persona_name = persona.get("name", "Anonymous Tester")
        prompt = f"""
You are simulating a human user testing a website or prototype to accomplish a goal.
Persona: {persona_name} (Tech Literacy: {persona.get('tech_literacy', 'Medium')}, Habits: {persona.get('habits', 'No strong habits specified.')})

GOAL / INTENT: "{task}"
CURRENT PAGE: "{page_title}" ({url}) - Step {step_num}

ACTIONS ALREADY COMPLETED IN THIS SESSION:
{history_text}

YOUR NOTES CARRIED FORWARD FROM EARLIER STEPS:
{observations if observations else "(nothing recorded yet — this is your first look at this page)"}

SET-OF-MARKS VISUAL GUIDE:
The attached screenshot has red numbered badges [1], [2], [3]... drawn directly on interactive buttons, links, and inputs.
Use the visual image to see which numbered badge is physically attached to the card, price tag, or input box you want!

⚠ BADGE NUMBERS ARE RE-ASSIGNED EVERY STEP. A tag number from a previous step means something
different now (the same book can be [28] on one step and [4] on the next). NEVER reuse a tag
number you saw earlier — only use numbers from the list below, and record findings in your
notes by NAME and VALUE (e.g. "Tastes Like Fear — £10.69"), never by tag number.

IMPORTANT — only elements with a badge and a matching entry in the list below actually exist and can be clicked. Do NOT assume a "search button", "submit icon", or any other control exists next to an input just because that's common on other websites — if there is no badge for it, it is not there. A search/text input with no separate button badge next to it must be submitted by choosing "action": "TYPE" (typing into it automatically presses Enter to submit) — never invent a CLICK target that has no corresponding badge.

CORRESPONDING ELEMENT LABELS:
{elements_formatted}

SURVEY RULE — BEFORE ANY "cheapest / best / first / highest / most" CLAIM:
The badges only cover what is currently visible in the viewport. If the page states a
result count larger than what you can see (e.g. "32 results - showing 1 to 20" while you
can only see 4 items), you have NOT seen enough to judge. In that case you MUST choose
"action": "SCROLL" and keep surveying before naming a winner.
- CARRY YOUR RUNNING BEST FORWARD. Every time you scroll you see NEW items; the earlier ones
  are gone from view but they still count. Before scrolling, write the best candidate you
  have seen SO FAR into "observations" (by name and value). On later steps, compare the new
  items against that recorded best — the winner is the best across EVERYTHING you have
  surveyed, not merely the best in the current viewport. Picking a worse item that happens
  to be on screen now, when your notes already hold a better one, is a FAILURE.
- "showing 1 to 20" of 32 means there is a SECOND PAGE. Scrolling alone will never reveal
  those items; you must click the 'next' pagination link to survey them.
- State in your monologue how many items you have surveyed out of the total.

CONFUSION SCORING RUBRIC (be honest and use the full range — do NOT default to 0):
- 0-20  = Obvious. The element you need is clearly visible and labelled as you expected.
- 30-50 = Some hunting. You had to search the page, read carefully, or the wording did
          not match what you expected. Use this whenever you have to scan manually.
- 60-80 = Significant friction. A control you EXPECTED does not exist (no sort, no filter,
          no visible submit), information is hidden behind extra clicks, or you must do
          tedious manual work the interface should have done for you.
- 90-100 = Blocked. You cannot find any way forward.
Your confusion_pct MUST be consistent with your own critique: if your critique complains
about missing controls or tedious manual comparison, the score CANNOT be 0-20.

GOAL STATUS & TERMINATION RULES:
1. INTERMEDIATE NAVIGATION (Step is in progress):
   - If you are clicking a category link (e.g. 'Travel'), opening a menu, searching, or scrolling, the goal is NOT finished yet. Set "goal_status": "IN_PROGRESS" and use whatever action (CLICK/TYPE/SCROLL) advances you toward the goal.
2. FINAL ACTION COMPLETION (Goal is achieved):
   - The moment you act on the FINAL element that directly satisfies the goal (e.g. clicking 'Add to basket' for the matching item, clicking 'Submit Form', 'Confirm Booking'), set "action" to the actual action you are performing (usually "CLICK") AND set "goal_status": "SATISFIED" in this SAME response. Do not wait for a future step to confirm — the click and the completion signal happen together. (Use action "COMPLETE" only when there is no element left to act on, e.g. the answer is already visible as text on screen and nothing needs to be clicked.)
3. REFERENCING ITEMS VS THEIR CONTROLS:
   - An item's title link and its action button are SEPARATE badges. Decide which one you actually need and put THAT single number in "target_tag" — if you want to add an item to a basket, target_tag must be the BUTTON's badge, not the item title's badge. State the one number you are using and do not switch between numbers mid-thought.

Output ONLY valid JSON:
{{
  "internal_monologue": "First-person thought summarizing what you see and what you will do next",
  "observations": "Running notes to your future self, carried into the next step. Copy forward everything from your earlier notes that still matters, then add what you learned this step. Record the best candidate found SO FAR by NAME and VALUE (never by tag number), plus how many items you have surveyed out of the total. Keep it under 3 short lines.",
  "goal_status": "IN_PROGRESS" | "SATISFIED" | "BLOCKED",
  "confusion_pct": integer from 0 to 100,
  "sentiment": "POSITIVE" | "NEUTRAL" | "FRUSTRATED" | "SKEPTICAL",
  "action": "CLICK" | "TYPE" | "SCROLL" | "COMPLETE" | "DROP_OFF",
  "target_tag": integer element ID from the badges or null,
  "click_coords": {{"x_pct": float_0_to_100, "y_pct": float_0_to_100}},
  "input_text": "text to type if action is TYPE, otherwise empty string",
  "critique": "One actionable UX finding regarding visual layout, contrast, or navigation hierarchy"
}}
"""
        raw_output = self.llm.generate_with_vision(prompt, image=screenshot, max_new_tokens=400, temperature=0.1)
        result = self._extract_clean_json(raw_output)
        return result

    def interview_agent(self, persona: Dict[str, Any], context_title: str, question: str) -> str:
        persona_name = persona.get("name", "Anonymous Tester")
        prompt = f"""
You are {persona_name} with {persona.get('tech_literacy', 'Medium')} tech literacy.
Habits: {persona.get('habits', 'No strong habits specified.')}
Context: You just tested "{context_title}".

The UX researcher is interviewing you. Answer candidly in first person.
Researcher: "{question}"
{persona_name}:
"""
        raw = self.llm.generate_with_vision(prompt, image=None, max_new_tokens=150, temperature=0.6)
        return raw.strip()