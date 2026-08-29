# 🧪 Synthetic Usability Lab

Run AI personas through real usability tests on live websites and Figma prototypes — powered by **Gemma 4 (multimodal)** acting as a set of simulated users with distinct tech literacy, patience, and habits.

Each persona actually browses the page with a headless Chromium session, looks at the screenshot, reasons about what to click, and reports back an internal monologue, a confusion score, and a UX finding — so you can compare how a first-time, low-patience user experiences your flow next to a power user, before you ever recruit a real participant.

<p align="center">
  <img src="assets/screenshots/dashboard.png" width="800" alt="Live Testing Sandbox" />
</p>

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![GPU required](https://img.shields.io/badge/GPU-CUDA%20required-orange)

---

## What it does

1. **Browses the real page.** A Playwright/Chromium session loads your URL (or Figma prototype), extracts every visible interactive element, and draws numbered [Set-of-Marks](https://arxiv.org/abs/2310.11441) badges directly onto the screenshot.
2. **Asks the model to act like the persona.** The annotated screenshot, the element list, the persona's traits, and the task goal go to Gemma 4 as a multimodal prompt. The model returns a decision — `CLICK` / `TYPE` / `SCROLL` / `COMPLETE` / `DROP_OFF` — plus a first-person internal monologue, a confusion percentage, sentiment, and one actionable UX finding.
3. **Executes it for real.** The chosen element actually gets clicked/typed into/scrolled via Playwright, and the loop repeats for up to N steps or until the persona finishes (or gives up).
4. **Replays it.** The Gradio UI renders an animated step-by-step replay per persona, a comparative benchmark table across personas, and a confusion-over-time chart — so friction points are visible at a glance instead of buried in a transcript.

<p align="center">
  <img src="assets/screenshots/replay-step.png" width="800" alt="Step replay with internal monologue and UX finding" />
</p>

## Features

- **Multi-persona comparative benchmarking** — run up to 3 personas against the same task in isolated browser sessions and see them side by side.
- **Set-of-Marks visual grounding** — the model chooses elements by looking at numbered badges on the actual screenshot, not by blindly matching text.
- **Figma prototype support** — raw coordinate-based clicking for canvas-driven prototypes with no accessible DOM.
- **Persona editor + AI persona generation** — hand-tune the built-in personas or describe a new one in plain English and have the model turn it into a structured profile.
- **Post-task interview mode** — ask a persona follow-up questions about their experience after a run.
- **Per-step latency telemetry** — see where time actually went (AI deliberation vs. page load vs. action execution) for each step.

<p align="center">
  <img src="assets/screenshots/comparative-matrix.png" width="800" alt="Comparative benchmark matrix across personas" />
</p>

## How the model decides where to click

This is worth understanding before you trust the results: the model is **not** doing pixel-level visual grounding from scratch. Each step, a JS scraper collects every visible interactive element, sorts them by on-screen position, numbers them, and burns those numbers directly into the screenshot as red badges. The model picks a badge number (or, for Figma canvases with no DOM, raw `x%`/`y%` coordinates), and that choice is executed as a deterministic Playwright click — the model never produces free-form pixel coordinates on a real page. This makes the pipeline far more reliable than pure vision-coordinate clicking, but it also means result quality is bounded by two things: whether the real target element survived the (generous, but finite) element cap, and whether the model correctly maps its stated intent to the right badge number — small multimodal models can and do occasionally pick the wrong badge while describing the right one in their monologue.

## Try it: a scenario that shows both low and high friction

```
Persona:  Carol, 68 — Low tech literacy, low patience (4/10), reads every
          word before acting, doesn't scroll unless content is obviously cut off.

Website:  https://books.toscrape.com

Task:     "Find a Science Fiction book that costs under £20 and has a 4-star
          or higher rating, then add it to your basket."

Max steps: 5
```

Navigating to the category is trivial (low friction). But star ratings on this site are pure CSS classes with no visible text — the model has to actually *read the star icons off the screenshot* and cross-reference them against price with no sort/filter tool available, which reliably produces a visible confusion spike mid-run before dropping back down once a qualifying book is found and added to the basket. Good for sanity-checking that the confusion signal is actually responsive to real friction rather than constant.

## Setup

### Option A — Google Colab (recommended)

This project needs a CUDA GPU with enough VRAM for a 4-bit-quantized multimodal model, which most local machines don't have handy. `colab.ipynb` is the fastest path:

1. Upload this whole folder to your Google Drive.
2. Open `colab.ipynb` in Colab, set `PROJECT_DIR` in the second cell to match where it landed.
3. Add your Hugging Face token to Colab Secrets as `HF_TOKEN` (key icon in the left sidebar) — or paste it when prompted if you skip that step.
4. Run all cells. The last cell launches the Gradio app and prints a local URL.

### Option B — Local

Requires a CUDA-capable GPU and drivers already set up.

```bash
git clone <your-repo-url>
cd synthetic-usability-lab
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env   # then fill in HF_TOKEN
python app.py
```

The app binds to localhost only by default. Public sharing is opt-in via `GRADIO_SHARE=1` (the Colab notebook sets this automatically, since Colab has no reachable localhost). Leave it unset locally: this app drives a headless browser to whatever URL it is given, so a public tunnel hands that capability to anyone with the link.

## Project structure

```
synthetic-usability-lab/
├── app.py                  # Gradio dashboard — entry point
├── colab.ipynb             # Google Colab bootstrap notebook
├── requirements.txt
├── .env.example
├── data/
│   ├── flows.json          # sample UX flow/screen definitions
│   └── personas.json       # default personas (David, Maya)
├── assets/
│   └── screenshots/        # UI screenshots referenced by this README
├── tests/                  # pytest suite (no GPU/model required)
└── src/
    ├── model.py             # Gemma4VisionClient — HF transformers wrapper
    ├── engine.py             # UsabilityEngine — prompt construction + JSON parsing
    ├── browser_agent.py      # WebBrowserRunner — Playwright automation + Set-of-Marks
    └── visualizer.py         # HTML/CSS generation for the Gradio replay UI
```

## Running the tests

The suite covers the most failure-prone part of the pipeline — parsing free-form
model output into a usable decision — and needs no GPU or model download:

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Known limitations

- **Small-model grounding accuracy.** Gemma 4 E4B-it is an edge-oriented model; on visually dense or unfamiliar pages it can occasionally pick the wrong element while describing the right one — treat findings as directional signal, not ground truth.
- **No anti-bot evasion.** Sites with aggressive automation detection (large e-commerce, banking) may block the session outright before the model gets a real screenshot.
- **Single-process, synchronous execution.** Each browser session runs to completion before the next persona starts; there's no request queueing or concurrency limiting for multiple simultaneous users of the same running app.
- **Element budget.** At most 60 elements per screen get badges (form controls hold reserved slots so inputs are never truncated away). On extremely dense pages, some links below the cut simply aren't addressable until the persona scrolls.
- **Unparseable model output aborts the step** as `BLOCKED` rather than guessing — visible in the replay's diagnostics panel along with the parse-failure counter in the logs.

## License

MIT — see [LICENSE](LICENSE).
# synthetic-usability-lab
