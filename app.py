import os
import sys
import json
import logging
from dotenv import load_dotenv
load_dotenv()

# Persona avatars are emoji and model output is arbitrary text, so the log stream
# must tolerate characters the console encoding can't represent (Windows consoles
# default to cp1252, where an unencodable glyph raises and kills the run).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

import gradio as gr
from src.model import Gemma4VisionClient
from src.engine import UsabilityEngine
from src.browser_agent import WebBrowserRunner
from src.visualizer import generate_persona_roster_html, generate_multi_persona_replay_html

# ==========================================
# 1. LOAD CONFIGS & STATE
# ==========================================
with open("data/personas.json", "r", encoding="utf-8") as f:
    DEFAULT_PERSONAS = json.load(f)

# NOTE: persona rosters are per-session (gr.State), not a module-level global —
# a global list here would be shared/mutated across every concurrent Gradio user.

# Initialize Engine & Playwright Browser Runner
print("🚀 Initializing Gemma 4 Vision Engine & Runner...")
client = Gemma4VisionClient()
engine = UsabilityEngine(client)
browser_runner = WebBrowserRunner()

# ==========================================
# 2. EVENT HANDLERS
# ==========================================
def run_live_web_test(target_url, user_task, selected_persona_names, max_steps, active_personas):
    if not target_url.strip() or not user_task.strip():
        return "<p style='color: #ef4444; font-weight: bold;'>⚠️ Please provide both a valid Website/Figma URL and a task.</p>"

    if not selected_persona_names:
        return "<p style='color: #ef4444; font-weight: bold;'>⚠️ Please select at least one persona to test.</p>"

    # Retrieve selected persona objects
    chosen_personas = [p for p in active_personas if p["name"] in selected_persona_names]

    # Run multi-persona isolated sessions
    multi_results = browser_runner.run_multi_persona_task(
        url=target_url.strip(),
        task=user_task.strip(),
        selected_personas=chosen_personas,
        engine=engine,
        max_steps=int(max_steps)
    )

    return generate_multi_persona_replay_html(multi_results)

# --- PERSONA EDITOR HANDLERS ---
# Each handler receives the caller's persona roster via gr.State (`active_personas`)
# and returns the updated roster as state, rather than mutating a shared global —
# keeps concurrent Gradio sessions isolated from each other's persona edits.
def load_persona_for_edit(persona_name, active_personas):
    """Populates the editor fields when a persona is selected."""
    persona = next((p for p in active_personas if p["name"] == persona_name), active_personas[0])
    return (
        persona.get("name", ""),
        persona.get("age", 30),
        persona.get("tech_literacy", "Medium"),
        persona.get("patience", 6),
        persona.get("avatar", "👤"),
        persona.get("habits", "")
    )

def save_edited_persona(edit_select_name, name, age, tech_literacy, patience, avatar, habits, active_personas):
    """Saves edits to an existing persona in the roster."""
    for p in active_personas:
        if p["name"] == edit_select_name:
            p["name"] = name.strip() if name.strip() else p["name"]
            p["age"] = int(age)
            p["tech_literacy"] = tech_literacy
            p["patience"] = int(patience)
            p["avatar"] = avatar.strip() if avatar.strip() else "👤"
            p["habits"] = habits.strip()
            break

    names = [p["name"] for p in active_personas]
    msg = f"💾 Successfully updated persona: **{name}**"
    roster_html = generate_persona_roster_html(active_personas)
    return (
        msg,
        roster_html,
        gr.update(choices=names, value=names[0]),
        gr.update(choices=names, value=[names[0]]),
        gr.update(choices=names, value=names[0]),
        active_personas
    )

def create_custom_persona(natural_desc, active_personas):
    if not natural_desc.strip():
        names = [p["name"] for p in active_personas]
        return "⚠️ Please enter a description first.", generate_persona_roster_html(active_personas), gr.update(choices=names), gr.update(choices=names), gr.update(choices=names), active_personas

    new_persona = engine.generate_custom_persona(natural_desc)

    if len(active_personas) >= 3:
        active_personas[2] = new_persona
        msg = f"✅ Replaced 3rd persona with: **{new_persona['name']}**"
    else:
        active_personas.append(new_persona)
        msg = f"✅ Added persona ({len(active_personas)}/3): **{new_persona['name']}**"

    names = [p["name"] for p in active_personas]
    roster_html = generate_persona_roster_html(active_personas)
    return msg, roster_html, gr.update(choices=names, value=names[-1]), gr.update(choices=names, value=[names[-1]]), gr.update(choices=names, value=names[-1]), active_personas

def reset_personas():
    active_personas = list(DEFAULT_PERSONAS[:2])
    names = [p["name"] for p in active_personas]
    roster_html = generate_persona_roster_html(active_personas)
    msg = "🔄 Reset active roster to defaults (David & Maya)."
    return msg, roster_html, gr.update(choices=names, value=names[0]), gr.update(choices=names, value=[names[0]]), gr.update(choices=names, value=names[0]), active_personas

def conduct_interview(persona_name, question, context_site, active_personas):
    if not question.strip():
        return "Please type a question for the persona."
    persona = next((p for p in active_personas if p["name"] == persona_name), active_personas[0])
    return engine.interview_agent(persona, context_site, question)

# ==========================================
# 3. GRADIO DASHBOARD
# ==========================================
with gr.Blocks(theme=gr.themes.Soft(primary_hue="blue")) as demo:
    gr.Markdown("# 🧪 Synthetic Usability Lab (Gemma 4 Multimodal VLA)")
    gr.Markdown("Run comparative multi-persona usability sessions on live websites or **Figma prototypes**, inspect per-step latency telemetry, and customize personas.")

    # Per-browser-session persona roster (isolated per user, unlike a module-level global)
    persona_state = gr.State(value=list(DEFAULT_PERSONAS[:2]))


    # TAB 1: LIVE TESTING SANDBOX
    with gr.Tab("🌐 Live Testing Sandbox (Web & Figma)"):
        gr.Markdown("### Enter any URL/Figma link and select one or more personas to benchmark")
        with gr.Row():
            with gr.Column(scale=3):
                url_input = gr.Textbox(
                    label="Website or Figma Prototype URL",
                    placeholder="e.g., https://books.toscrape.com or https://www.figma.com/proto/...",
                    value="https://books.toscrape.com"
                )
                task_input = gr.Textbox(
                    label="Task / Goal for Personas",
                    placeholder="e.g., Find a book in the Travel category under £30 and click Add to Basket",
                    value="Find a book in the Travel category that costs under £30 and click Add to Basket"
                )
            with gr.Column(scale=2):
                web_persona_checkboxes = gr.CheckboxGroup(
                    label="Select Personas to Test (Comparative Benchmark)",
                    choices=[p["name"] for p in DEFAULT_PERSONAS[:2]],
                    value=[p["name"] for p in DEFAULT_PERSONAS[:2]]
                )
                steps_slider = gr.Slider(minimum=1, maximum=8, value=5, step=1, label="Max Navigation Steps")
                run_web_btn = gr.Button("🚀 Launch Comparative Usability Test", variant="primary")

        web_output_html = gr.HTML(value="<p style='color: #94a3b8;'>Select personas, enter a URL, and click Launch to start testing.</p>")

        run_web_btn.click(
            fn=run_live_web_test,
            inputs=[url_input, task_input, web_persona_checkboxes, steps_slider, persona_state],
            outputs=[web_output_html]
        )

    # TAB 2: PERSONA CUSTOMIZER & MANAGER
    with gr.Tab("🎭 Persona Customizer & Manager"):
        gr.Markdown("### Edit existing personas or generate new ones (Max 3 Active Personas)")
        with gr.Row():
            # LEFT: EDIT EXISTING PERSONA
            with gr.Column(scale=3):
                gr.Markdown("#### ✏️ Edit Active Persona")
                edit_persona_dropdown = gr.Dropdown(
                    label="Select Persona to Edit",
                    choices=[p["name"] for p in DEFAULT_PERSONAS[:2]],
                    value=DEFAULT_PERSONAS[0]["name"]
                )
                with gr.Row():
                    edit_name = gr.Textbox(label="Persona Name", value=DEFAULT_PERSONAS[0]["name"])
                    edit_age = gr.Number(label="Age", value=DEFAULT_PERSONAS[0].get("age", 30))
                    edit_avatar = gr.Textbox(label="Avatar Emoji", value=DEFAULT_PERSONAS[0].get("avatar", "👤"))
                with gr.Row():
                    edit_tech = gr.Dropdown(label="Tech Literacy", choices=["Low", "Medium", "High"], value=DEFAULT_PERSONAS[0].get("tech_literacy", "Medium"))
                    edit_patience = gr.Slider(minimum=1, maximum=10, step=1, label="Patience Meter", value=DEFAULT_PERSONAS[0].get("patience", 6))
                edit_habits = gr.Textbox(label="Usability Habits, Biases & Frustrations", value=DEFAULT_PERSONAS[0].get("habits", ""), lines=3)
                
                with gr.Row():
                    save_edit_btn = gr.Button("💾 Save & Update Persona", variant="primary")
                    reset_btn = gr.Button("🔄 Reset All to Defaults", variant="secondary")
                edit_status_box = gr.Markdown()

            # RIGHT: GENERATE NEW & ROSTER PREVIEW
            with gr.Column(scale=2):
                gr.Markdown("#### ✨ Generate New Persona via AI")
                custom_desc_input = gr.Textbox(
                    label="Describe a new persona in plain English",
                    placeholder="e.g., A 72-year-old retired gardener who is anxious about entering passwords...",
                    lines=2
                )
                create_btn = gr.Button("✨ Create with Gemma 4", variant="secondary")
                roster_preview = gr.HTML(value=generate_persona_roster_html(DEFAULT_PERSONAS[:2]))

    # TAB 3: POST-TASK INTERVIEW
    with gr.Tab("🎙️ Post-Task Interview"):
        gr.Markdown("### Interview a persona about their experience, friction points, and mental model")
        with gr.Row():
            interview_persona_dropdown = gr.Dropdown(
                label="Choose Persona",
                choices=[p["name"] for p in DEFAULT_PERSONAS[:2]],
                value=DEFAULT_PERSONAS[0]["name"]
            )
            site_context_input = gr.Textbox(label="Website / Prototype Tested", value="https://books.toscrape.com")
            
        user_question = gr.Textbox(
            label="Your Question as UX Researcher", 
            placeholder="e.g., Why did you hesitate to click that link?"
        )
        answer_box = gr.Textbox(label="Persona Response", interactive=False, lines=4)
        ask_btn = gr.Button("Ask Persona", variant="secondary")
        
        ask_btn.click(
            fn=conduct_interview,
            inputs=[interview_persona_dropdown, user_question, site_context_input, persona_state],
            outputs=[answer_box]
        )

    # --- WIRING UP REACTIVE UI EVENTS ---
    # 1. When persona is selected for editing, populate fields
    edit_persona_dropdown.change(
        fn=load_persona_for_edit,
        inputs=[edit_persona_dropdown, persona_state],
        outputs=[edit_name, edit_age, edit_tech, edit_patience, edit_avatar, edit_habits]
    )

    # 2. Save edited persona
    save_edit_btn.click(
        fn=save_edited_persona,
        inputs=[edit_persona_dropdown, edit_name, edit_age, edit_tech, edit_patience, edit_avatar, edit_habits, persona_state],
        outputs=[edit_status_box, roster_preview, edit_persona_dropdown, web_persona_checkboxes, interview_persona_dropdown, persona_state]
    )

    # 3. Create new persona
    create_btn.click(
        fn=create_custom_persona,
        inputs=[custom_desc_input, persona_state],
        outputs=[edit_status_box, roster_preview, edit_persona_dropdown, web_persona_checkboxes, interview_persona_dropdown, persona_state]
    )

    # 4. Reset to defaults
    reset_btn.click(
        fn=reset_personas,
        inputs=[],
        outputs=[edit_status_box, roster_preview, edit_persona_dropdown, web_persona_checkboxes, interview_persona_dropdown, persona_state]
    )

# ==========================================
# 4. LAUNCH
# ==========================================
if __name__ == "__main__":
    # Sharing is opt-in. This app drives a headless browser to arbitrary
    # user-supplied URLs (SSRF-shaped), so a public tunnel should be a deliberate
    # choice — but Colab has no reachable localhost, so it needs one to be usable.
    # Set GRADIO_SHARE=1 there; leave it unset for local runs.
    share = os.getenv("GRADIO_SHARE", "").strip().lower() in {"1", "true", "yes"}
    if share:
        logger.warning(
            "GRADIO_SHARE is set: creating a PUBLIC tunnel. Anyone with the link can "
            "drive this browser agent at any URL. Do not leave it running unattended."
        )
    demo.launch(share=share, debug=False)