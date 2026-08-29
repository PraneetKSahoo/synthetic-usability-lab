import os
import io
import base64
import time
import logging
from typing import Dict, Any, List
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

def draw_set_of_marks(image: Image.Image, elements: List[Dict[str, Any]]) -> Image.Image:
    if not elements:
        return image

    annotated = image.copy().convert("RGBA")
    overlay = Image.new("RGBA", annotated.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    
    vw, vh = annotated.size
    font = ImageFont.load_default()
    
    for el in elements:
        eid = el["id"]
        left = el.get("left", int((el["x_pct"] / 100.0) * vw))
        top = el.get("top", int((el["y_pct"] / 100.0) * vh))
        width = el.get("width", 50)
        height = el.get("height", 24)
        
        draw.rectangle(
            [left, top, left + width, top + height],
            outline=(239, 68, 68, 220),
            width=2
        )
        
        badge_text = f" {eid} "
        badge_w = len(badge_text) * 7 + 4
        badge_h = 13
        badge_top = max(0, top - badge_h)
        
        draw.rectangle(
            [left, badge_top, left + badge_w, badge_top + badge_h],
            fill=(239, 68, 68, 240)
        )
        draw.text(
            (left + 2, badge_top + 1),
            badge_text,
            fill=(255, 255, 255, 255),
            font=font
        )
        
    return Image.alpha_composite(annotated, overlay).convert("RGB")

class WebBrowserRunner:
    def __init__(self, screenshot_dir: str = "screenshots"):
        self.screenshot_dir = screenshot_dir
        os.makedirs(self.screenshot_dir, exist_ok=True)

    def _sanitize_url(self, url: str) -> str:
        url = url.strip()
        if not url.startswith("http"):
            url = "https://" + url
            
        if "figma.com/proto" in url:
            if "hide-ui=1" not in url:
                separator = "&" if "?" in url else "?"
                url = f"{url}{separator}hide-ui=1&hotspot-hints=0&scaling=contain"
        return url

    def extract_visual_elements(self, page) -> List[Dict[str, Any]]:
        js_scraper = """
        () => {
            // Clear marks left over from previous steps. Without this, elements
            // tagged earlier that drop out of the current candidate set keep their
            // stale data-som-id, so `[data-som-id="N"]` can match two elements and
            // `.first` may resolve to the wrong (stale) one.
            document.querySelectorAll('[data-som-id]').forEach(el => el.removeAttribute('data-som-id'));

            const candidates = document.querySelectorAll('input, button, a, select, textarea, [role="button"], [role="searchbox"], [role="textbox"], .product_pod, .product_pod button, .product_pod h3 a, .side_categories a');
            const vw = window.innerWidth;
            const vh = window.innerHeight;

            const MAX_TOTAL = 60;
            const MIN_FORM_SLOTS = 15;   // form controls are rare and task-critical
            const MAX_NAV = 12;

            function isVisible(el) {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) === 0) return false;
                const rect = el.getBoundingClientRect();
                if (rect.width <= 2 || rect.height <= 2) return false;
                // Require the element's CENTER to be on-screen. Demanding *full*
                // visibility was too strict — it hid most of a long result list
                // (e.g. only 4 of 20 products), starving the model of the items it
                // needs to compare. Centre-in-viewport keeps the recorded
                // x_pct/y_pct meaningful for the replay cursor while restoring
                // coverage of partially-cut rows.
                const cx = rect.left + rect.width / 2;
                const cy = rect.top + rect.height / 2;
                if (cy < 0 || cy > vh) return false;
                if (cx < 0 || cx > vw) return false;
                return true;
            }

            function isFormControl(el) {
                const tag = el.tagName.toLowerCase();
                if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
                const role = (el.getAttribute('role') || '').toLowerCase();
                if (role === 'searchbox' || role === 'textbox') return true;
                if (tag === 'button') {
                    const type = (el.getAttribute('type') || '').toLowerCase();
                    return type === 'submit' || type === '' || type === 'button';
                }
                return false;
            }

            // Bare inputs frequently have NO innerText, placeholder, value, or
            // aria-label (e.g. Hacker News' footer search box). Falling back to
            // the empty string would drop them from the list entirely, so derive
            // a usable label from the surrounding markup instead.
            function deriveLabel(el) {
                let label = el.innerText || el.placeholder || el.value ||
                            el.getAttribute('aria-label') || el.getAttribute('title') || '';
                label = label.trim().replace(/\\s+/g, ' ');
                if (label.length > 0) return label;

                if (!isFormControl(el)) return '';

                // <label for="id">
                const id = el.getAttribute('id');
                if (id) {
                    try {
                        const lab = document.querySelector('label[for="' + CSS.escape(id) + '"]');
                        if (lab && lab.innerText.trim()) return lab.innerText.trim().replace(/\\s+/g, ' ');
                    } catch (e) { /* invalid id for selector */ }
                }
                // wrapping <label>
                const wrapping = el.closest('label');
                if (wrapping && wrapping.innerText.trim()) {
                    return wrapping.innerText.trim().replace(/\\s+/g, ' ');
                }
                // Text immediately preceding the field (HN renders "Search:" this way)
                let prev = el.previousSibling;
                while (prev) {
                    const txt = (prev.textContent || '').trim().replace(/\\s+/g, ' ');
                    if (txt) return txt;
                    prev = prev.previousSibling;
                }
                // Last resort: describe the control so it is still addressable
                const tag = el.tagName.toLowerCase();
                const type = (el.getAttribute('type') || '').toLowerCase();
                const name = el.getAttribute('name') || '';
                return (type ? type + ' ' : '') + tag + (name ? ' (name=' + name + ')' : '');
            }

            const formCandidates = [];
            const mainCandidates = [];
            const navCandidates = [];

            for (let el of candidates) {
                if (!isVisible(el)) continue;

                const rect = el.getBoundingClientRect();
                let label = deriveLabel(el);

                const priceEl = el.querySelector('.price_color, .price');
                if (priceEl) {
                    label += ` (${priceEl.innerText.trim()})`;
                }

                if (label.length === 0) continue;

                const itemData = {
                    el: el,
                    tag: el.tagName.toLowerCase(),
                    type: (el.getAttribute('type') || '').toLowerCase() || el.tagName.toLowerCase(),
                    text: label.substring(0, 60),
                    isForm: isFormControl(el),
                    rect: {
                        top: rect.top,
                        left: rect.left,
                        width: rect.width,
                        height: rect.height
                    }
                };

                if (itemData.isForm) {
                    formCandidates.push(itemData);
                } else if (el.closest('nav, header, footer, [role="navigation"], .side_categories')) {
                    navCandidates.push(itemData);
                } else {
                    mainCandidates.push(itemData);
                }
            }

            function byPosition(a, b) {
                if (Math.abs(a.rect.top - b.rect.top) > 15) return a.rect.top - b.rect.top;
                return a.rect.left - b.rect.left;
            }
            formCandidates.sort(byPosition);
            mainCandidates.sort(byPosition);
            navCandidates.sort(byPosition);

            // Budget: form controls get reserved slots that survive truncation, so a
            // search box at the bottom of a long page is never cut off in favour of
            // the 45th story link at the top.
            const keptForms = formCandidates.slice(0, MIN_FORM_SLOTS);
            const keptNav = navCandidates.slice(0, MAX_NAV);
            const mainBudget = Math.max(0, MAX_TOTAL - keptForms.length - keptNav.length);
            const keptMain = mainCandidates.slice(0, mainBudget);

            // Renumber in reading order so badge numbers are spatially coherent.
            const combined = [...keptForms, ...keptMain, ...keptNav].sort(byPosition);
            const elements = [];

            combined.forEach((item, index) => {
                const id = index + 1;
                item.el.setAttribute('data-som-id', id);

                const x_pct = ((item.rect.left + item.rect.width / 2) / vw) * 100;
                const y_pct = ((item.rect.top + item.rect.height / 2) / vh) * 100;

                elements.push({
                    id: id,
                    tag: item.tag,
                    text: item.text,
                    type: item.type,
                    is_form: item.isForm,
                    left: Math.round(item.rect.left),
                    top: Math.round(item.rect.top),
                    width: Math.round(item.rect.width),
                    height: Math.round(item.rect.height),
                    x_pct: Math.round(x_pct * 10) / 10,
                    y_pct: Math.round(y_pct * 10) / 10
                });
            });

            return elements;
        }
        """
        try:
            return page.evaluate(js_scraper)
        except Exception as ex:
            logger.warning("Element extraction failed: %s", ex)
            return []

    def _page_signature(self, page, visual_elements: List[Dict[str, Any]]) -> str:
        """A cheap fingerprint of observable page state.

        Used instead of raw screenshot bytes for stall detection — byte comparison
        never matches on pages with carousels, ads, or blinking cursors, which
        silently disables stall detection exactly where it is most needed.
        """
        try:
            title = page.title()
            url = page.url
        except Exception:
            title, url = "", ""
        try:
            scroll_y = page.evaluate("() => Math.round(window.scrollY / 50)")
        except Exception:
            scroll_y = 0
        element_sig = "|".join(f"{el['id']}:{el.get('text', '')}" for el in visual_elements)
        return f"{url}::{title}::{scroll_y}::{element_sig}"

    def _settle(self, page, extra_wait: int = 2000) -> None:
        """Waits for navigation/DOM to settle after an interaction."""
        try:
            page.wait_for_load_state("domcontentloaded", timeout=4000)
        except Exception:
            pass
        page.wait_for_timeout(extra_wait)

    def run_single_persona_session(self, page, target_url: str, is_figma: bool, task: str, persona: Dict[str, Any], engine, max_steps: int = 5) -> List[Dict[str, Any]]:
        steps_record = []
        history_log = []
        # Rolling scratchpad the model maintains for itself. Without this, each
        # scroll wipes out what it saw: it would survey a long list, then pick the
        # best item in the CURRENT viewport while forgetting a cheaper one it had
        # already found two steps earlier.
        observations = ""

        # Stuck-loop tracking: if the same element/action keeps producing zero
        # visible change on the page (e.g. a non-responsive accordion widget),
        # the model has no way to notice on its own — it just sees the same
        # screenshot again and re-derives the same plan. We track it here instead.
        last_target_tag = None
        last_action_type = None
        last_had_no_effect = False
        stuck_count = 0
        STUCK_LIMIT = 2

        # Separate, looser counter: even if the persona keeps trying *different*
        # elements/actions each step (not a literal repeat), zero real progress
        # for several steps in a row usually means the page has no valid way
        # forward for this task — that's a UX finding worth surfacing on its
        # own, not just letting the run silently wander to max_steps.
        no_effect_streak = 0
        NO_EFFECT_STREAK_LIMIT = 3

        for step_idx in range(1, max_steps + 1):
            t_step_start = time.perf_counter()
            page_title = page.title()
            current_url = page.url

            # 1. Capture Raw Clean Screenshot
            t_ss_start = time.perf_counter()
            before_bytes = page.screenshot()
            before_img_clean = Image.open(io.BytesIO(before_bytes)).convert("RGB")
            before_b64_clean = base64.b64encode(before_bytes).decode("utf-8")
            
            # 2. Extract Elements & Draw Set-of-Marks
            visual_elements = self.extract_visual_elements(page)
            before_signature = self._page_signature(page, visual_elements)
            marked_img = draw_set_of_marks(before_img_clean, visual_elements) if visual_elements else before_img_clean
            
            marked_buffer = io.BytesIO()
            marked_img.save(marked_buffer, format="JPEG", quality=85)
            annotated_b64 = base64.b64encode(marked_buffer.getvalue()).decode("utf-8")
            t_som_end = time.perf_counter()

            # 3. VLM Cognitive Deliberation
            t_vlm_start = time.perf_counter()
            decision = engine.simulate_visual_web_step(
                persona=persona,
                screenshot=marked_img,
                page_title=page_title,
                url=current_url,
                task=task,
                visual_elements=visual_elements,
                history=history_log,
                step_num=step_idx,
                observations=observations
            )
            t_vlm_end = time.perf_counter()

            # Carry the model's own notes into the next step.
            new_observations = decision.get("observations")
            if isinstance(new_observations, str) and new_observations.strip():
                observations = new_observations.strip()[:800]

            target_tag = decision.get("target_tag")
            matched_el = next((el for el in visual_elements if el["id"] == target_tag), None) if visual_elements else None
            
            # SCROLL is checked first: _extract_clean_json always injects a
            # click_coords default, so a coords-first ordering made this branch
            # unreachable and mislabelled every scroll step in the replay.
            if decision.get("action") == "SCROLL":
                tx_pct, ty_pct = 50, 75
                target_text = "Scroll Down"
            elif matched_el:
                tx_pct = matched_el["x_pct"]
                ty_pct = matched_el["y_pct"]
                target_text = matched_el["text"]
            elif "click_coords" in decision:
                coords = decision["click_coords"]
                try:
                    tx_pct = max(0.0, min(100.0, float(coords.get("x_pct", 50))))
                    ty_pct = max(0.0, min(100.0, float(coords.get("y_pct", 50))))
                except (TypeError, ValueError):
                    tx_pct, ty_pct = 50.0, 50.0
                target_text = f"Visual ({tx_pct}%, {ty_pct}%)"
            else:
                tx_pct, ty_pct = 50, 50
                target_text = "Center"

            if target_tag is not None and matched_el is None and visual_elements:
                logger.warning(
                    "Step %s: model referenced badge [%s] which does not exist (only %s badges present)",
                    step_idx, target_tag, len(visual_elements)
                )

            decision["step"] = step_idx
            decision["page_title"] = page_title
            decision["url"] = current_url
            decision["persona_name"] = persona.get("name", "Anonymous Tester")
            decision["avatar"] = persona.get("avatar", "👤")
            decision["target_coords"] = {"x": tx_pct, "y": ty_pct}
            decision["before_screenshot_b64"] = before_b64_clean

            # 4. Action Execution & Settling
            t_act_start = time.perf_counter()
            action_type = decision.get("action", "COMPLETE")
            input_text = decision.get("input_text", "")
            exec_log = f"Action: {action_type} on [{target_tag if target_tag else 'Canvas'}]"

            px_x = (tx_pct / 100.0) * 1280
            px_y = (ty_pct / 100.0) * 800

            if action_type not in ["COMPLETE", "DROP_OFF"]:
                try:
                    # Dispatch on the declared action FIRST. Keying off target_tag
                    # first meant a SCROLL that also carried a target_tag silently
                    # executed as a click instead.
                    if action_type == "SCROLL":
                        # Scroll by ~85% of the viewport: a fixed 500px on an 800px
                        # viewport overlapped heavily, so surveying a long list ate
                        # far more steps than the max_steps budget allows.
                        try:
                            scroll_by = int(page.evaluate("() => Math.round(window.innerHeight * 0.85)"))
                        except Exception:
                            scroll_by = 650
                        page.mouse.wheel(0, scroll_by)
                        exec_log += f" | Scrolled down {scroll_by}px"
                        page.wait_for_timeout(1500)

                    elif is_figma or not visual_elements:
                        page.mouse.click(px_x, px_y)
                        exec_log += f" | Clicked Canvas at ({int(px_x)}px, {int(px_y)}px)"
                        page.wait_for_timeout(3000)

                    elif target_tag is not None:
                        selector = f'[data-som-id="{target_tag}"]'
                        locator = page.locator(selector).first
                        if not locator.is_visible():
                            exec_log += (
                                f" | ⚠ Element [{target_tag}] resolved but is not visible — "
                                "nothing executed (the model likely referenced a stale or wrong badge)"
                            )
                            logger.warning("Step %s: target [%s] not visible, no action taken", step_idx, target_tag)
                        elif action_type == "TYPE":
                            query = input_text if input_text else task
                            if not input_text:
                                exec_log += " | ⚠ TYPE had empty input_text; fell back to the task string"
                            locator.click(timeout=3000)
                            locator.fill(query, timeout=3000)
                            # Verify the fill landed on a real text field. input_value()
                            # RAISES on non-input elements, so treat the exception as the
                            # signal it is rather than swallowing it into silence.
                            try:
                                actual_value = locator.input_value(timeout=1000)
                                if actual_value.strip() != query.strip():
                                    exec_log += (
                                        f" | ⚠ Typed value mismatch: field shows '{actual_value}', "
                                        f"expected '{query}'"
                                    )
                            except Exception:
                                exec_log += (
                                    f" | ⚠ Element [{target_tag}] is not a text field — fill() "
                                    "could not be verified; the badge likely points at a wrapper or link"
                                )
                                logger.warning("Step %s: [%s] is not a text input", step_idx, target_tag)
                            locator.press("Enter", timeout=3000)
                            exec_log += f" | Typed '{query}' and pressed Enter on the field"
                            self._settle(page)

                        else:  # CLICK
                            locator.click(timeout=3000)
                            exec_log += f" | Clicked [{target_tag}]: {target_text}"
                            self._settle(page)

                    else:
                        # No target_tag on a real page — fall back to raw coordinates.
                        page.mouse.click(px_x, px_y)
                        exec_log += f" | Clicked raw coords ({int(px_x)}px, {int(px_y)}px) — no target_tag given"
                        page.wait_for_timeout(2000)
                except Exception as ex:
                    exec_log += f" | Execution warning: {str(ex)}"
                    logger.warning("Step %s action %s failed: %s", step_idx, action_type, ex)
            t_act_end = time.perf_counter()

            # 5. Capture Post-Action Screenshot
            try:
                after_bytes = page.screenshot()
                after_b64 = base64.b64encode(after_bytes).decode("utf-8")
            except Exception:
                after_b64 = before_b64_clean
            t_after_ss = time.perf_counter()

            # Latency Metrics Breakdown
            total_step_time = round(t_after_ss - t_step_start, 1)
            som_time = round(t_som_end - t_ss_start, 2)
            vlm_time = round(t_vlm_end - t_vlm_start, 1)
            act_time = round(t_act_end - t_act_start, 2)
            web_settle_time = round(total_step_time - (vlm_time + som_time + act_time), 1)

            # Stuck-loop detection: did this action change observable page state?
            # Compares a URL/title/scroll/element-list signature rather than raw
            # screenshot bytes, which never match on pages with carousels, ads, or
            # blinking cursors — silently disabling detection where it matters most.
            after_signature = self._page_signature(page, self.extract_visual_elements(page))
            had_no_effect = (
                action_type not in ["COMPLETE", "DROP_OFF"]
                and after_signature == before_signature
            )
            is_repeat_of_last = (
                target_tag is not None
                and target_tag == last_target_tag
                and action_type == last_action_type
            )
            if had_no_effect and is_repeat_of_last and last_had_no_effect:
                stuck_count += 1
            else:
                stuck_count = 0
            last_target_tag, last_action_type, last_had_no_effect = target_tag, action_type, had_no_effect

            no_effect_streak = no_effect_streak + 1 if had_no_effect else 0

            if stuck_count >= STUCK_LIMIT:
                action_type = "DROP_OFF"
                decision["action"] = "DROP_OFF"
                decision["goal_status"] = "BLOCKED"
                decision["confusion_pct"] = max(int(decision.get("confusion_pct", 20)), 80)
                decision["critique"] = (
                    (decision.get("critique") or "").rstrip(". ") +
                    f". Auto-detected stall: the same element [{target_tag}] was clicked "
                    f"{STUCK_LIMIT + 1} times in a row with no visible change on the page — "
                    "likely a non-responsive control or a broken interaction."
                )
                exec_log += " | Auto-terminated: repeated action with no visible effect"
            elif no_effect_streak >= NO_EFFECT_STREAK_LIMIT:
                action_type = "DROP_OFF"
                decision["action"] = "DROP_OFF"
                decision["goal_status"] = "BLOCKED"
                decision["confusion_pct"] = max(int(decision.get("confusion_pct", 20)), 75)
                decision["critique"] = (
                    (decision.get("critique") or "").rstrip(". ") +
                    f". Auto-detected stall: {NO_EFFECT_STREAK_LIMIT} consecutive actions "
                    "(even across different elements) produced no visible progress — the "
                    "task likely has no clear/discoverable path forward on this page as designed."
                )
                exec_log += " | Auto-terminated: no progress for several steps despite varied attempts"

            decision["after_screenshot_b64"] = after_b64
            decision["latency_telemetry"] = {
                "total_sec": total_step_time,
                "vlm_cognition_sec": vlm_time,
                "web_settle_sec": max(0.1, web_settle_time),
                "som_tagging_sec": som_time,
                "action_exec_sec": act_time
            }
            decision["debug_info"] = {
                "execution_log": exec_log,
                "target_tag": target_tag,
                "annotated_screenshot_b64": annotated_b64,
                "url_after_action": page.url,
                "observations": observations
            }
            steps_record.append(decision)

            # UNIVERSAL DUAL-CRITERIA TERMINATION
            is_terminal = (
                decision.get("goal_status") == "SATISFIED" or 
                action_type in ["COMPLETE", "DROP_OFF"]
            )
            if is_terminal:
                print(f"🛑 [Runner] Goal Finished at Step {step_idx} ({persona['name']}): Status={decision.get('goal_status')}, Action={action_type}")
                break

            history_log.append({
                "step": step_idx,
                "action": action_type,
                "target_text": target_text,
                "input_text": input_text,
                "had_no_effect": had_no_effect
            })

        return steps_record

    def run_multi_persona_task(self, url: str, task: str, selected_personas: List[Dict[str, Any]], engine, max_steps: int = 5) -> Dict[str, List[Dict[str, Any]]]:
        """Runs isolated browser sessions sequentially for each selected persona."""
        multi_results = {}
        target_url = self._sanitize_url(url)
        is_figma = "figma.com/proto" in target_url

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )

            for persona in selected_personas:
                print(f"\n👤 [Playwright] Starting Isolated Session for: {persona['name']}...")
                # Fresh isolated context per persona
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = context.new_page()

                try:
                    page.goto(target_url, timeout=35000, wait_until="domcontentloaded")
                    init_wait = 6000 if is_figma else 2000
                    page.wait_for_timeout(init_wait)
                    
                    steps = self.run_single_persona_session(
                        page=page,
                        target_url=target_url,
                        is_figma=is_figma,
                        task=task,
                        persona=persona,
                        engine=engine,
                        max_steps=max_steps
                    )
                    multi_results[persona["name"]] = steps
                except Exception as e:
                    multi_results[persona["name"]] = [{
                        "step": 1,
                        "page_title": "Failed to Load",
                        "url": target_url,
                        "before_screenshot_b64": "",
                        "after_screenshot_b64": "",
                        "internal_monologue": f"Error: {str(e)}",
                        "confusion_pct": 100,
                        "action": "DROP_OFF",
                        "target_coords": {"x": 50, "y": 50},
                        "critique": "Session failed to load.",
                        "latency_telemetry": {"total_sec": 0, "vlm_cognition_sec": 0, "web_settle_sec": 0, "som_tagging_sec": 0, "action_exec_sec": 0},
                        "debug_info": {"execution_log": str(e), "annotated_screenshot_b64": ""}
                    }]
                finally:
                    context.close()

            browser.close()
        return multi_results