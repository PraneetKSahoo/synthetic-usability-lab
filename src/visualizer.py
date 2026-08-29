import time
import json
import html
from typing import Dict, Any, List

def esc(value: Any) -> str:
    """Escapes text that originates from the LLM or a scraped webpage before it
    is interpolated into raw HTML (Gradio renders this HTML unsanitized)."""
    return html.escape(str(value), quote=True)

PERSONA_COLORS = [
    {"bg": "#f59e0b", "name": "Amber", "text": "#0f172a"},
    {"bg": "#06b6d4", "name": "Cyan", "text": "#0f172a"},
    {"bg": "#a855f7", "name": "Purple", "text": "#ffffff"}
]

def get_confusion_badge(pct: int) -> str:
    pct = max(0, min(100, int(pct)))
    if pct <= 35:
        color = "#22c55e"
        tier = "Low Confusion"
    elif pct <= 69:
        color = "#eab308"
        tier = "Moderate Friction"
    else:
        color = "#ef4444"
        tier = "High Friction"

    return f"""
    <span style="background: {color}; color: #0f172a; padding: 2px 8px; border-radius: 12px; font-weight: 800; font-size: 11px;">
        {pct}% • {tier}
    </span>
    """

def generate_persona_roster_html(personas: List[Dict[str, Any]]) -> str:
    cards_html = ""
    for i, p in enumerate(personas[:3]):
        color = PERSONA_COLORS[i % len(PERSONA_COLORS)]["bg"]
        patience_bar = "█" * int(p.get("patience", 6)) + "░" * (10 - int(p.get("patience", 6)))
        
        cards_html += f"""
        <div style="background: #1e293b; border-radius: 10px; padding: 12px; margin-bottom: 10px; border-left: 4px solid {color}; color: #f8fafc;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="font-weight: 700; font-size: 14px;">{esc(p.get('avatar', '👤'))} {esc(p.get('name', 'Persona'))}</span>
                <span style="background: {color}; color: {PERSONA_COLORS[i % len(PERSONA_COLORS)]['text']}; padding: 2px 6px; border-radius: 8px; font-weight: 700; font-size: 10px;">{esc(p.get('tech_literacy', 'Med'))} Tech</span>
            </div>
            <div style="font-size: 11px; color: #94a3b8; margin: 4px 0;">
                <b>Patience:</b> <span style="color: {color}; font-family: monospace;">{patience_bar}</span> ({p.get('patience', 6)}/10)
            </div>
            <div style="font-size: 12px; color: #cbd5e1; line-height: 1.35; margin-top: 4px;">
                {esc(p.get('habits', ''))}
            </div>
        </div>
        """
    return f"""
    <div style="background: #0f172a; border-radius: 16px; padding: 16px; border: 1px solid #334155; height: 100%;">
        <h4 style="margin: 0 0 12px 0; color: #f8fafc; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;">👥 Active Persona Roster ({len(personas)}/3)</h4>
        {cards_html}
    </div>
    """

def render_svg_friction_chart(steps: List[Dict[str, Any]], line_color: str = "#38bdf8") -> str:
    """Generates a responsive SVG Line Chart showing confusion % trajectory over steps."""
    if not steps:
        return ""
    
    width, height = 500, 120
    padding = 35
    
    n = len(steps)
    pts = []
    for i, s in enumerate(steps):
        x = padding + (i / max(1, n - 1)) * (width - 2 * padding) if n > 1 else width / 2
        pct = max(0, min(100, int(s.get("confusion_pct", 20))))
        y = (height - padding) - (pct / 100.0) * (height - 2 * padding)
        pts.append((x, y, pct, s.get("step", i + 1)))

    # Construct SVG path
    path_d = f"M {pts[0][0]} {pts[0][1]}"
    for x, y, _, _ in pts[1:]:
        path_d += f" L {x} {y}"

    dots_svg = ""
    for x, y, pct, st in pts:
        dot_color = "#22c55e" if pct <= 35 else "#eab308" if pct <= 69 else "#ef4444"
        dots_svg += f"""
        <circle cx="{x}" cy="{y}" r="5" fill="{dot_color}" stroke="#0f172a" stroke-width="2"/>
        <text x="{x}" y="{y - 8}" fill="{dot_color}" font-size="10" font-weight="bold" text-anchor="middle">{pct}%</text>
        <text x="{x}" y="{height - 8}" fill="#94a3b8" font-size="9" text-anchor="middle">Step {st}</text>
        """

    return f"""
    <div style="background: #0f172a; border-radius: 12px; padding: 12px; border: 1px solid #334155; margin-bottom: 16px;">
        <div style="font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; margin-bottom: 6px; display: flex; justify-content: space-between;">
            <span>📈 Cognitive Friction Journey (Confusion %)</span>
            <span style="color: #64748b;">0% (Clear) ⟷ 100% (Blocked)</span>
        </div>
        <svg viewBox="0 0 {width} {height}" style="width: 100%; height: auto; display: block;">
            <!-- Gridlines -->
            <line x1="{padding}" y1="{padding}" x2="{width - padding}" y2="{padding}" stroke="#334155" stroke-dasharray="3 3" stroke-width="1"/>
            <line x1="{padding}" y1="{height / 2}" x2="{width - padding}" y2="{height / 2}" stroke="#334155" stroke-dasharray="3 3" stroke-width="1"/>
            <line x1="{padding}" y1="{height - padding}" x2="{width - padding}" y2="{height - padding}" stroke="#334155" stroke-width="1"/>
            
            <!-- Journey Path -->
            <path d="{path_d}" fill="none" stroke="{line_color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
            {dots_svg}
        </svg>
    </div>
    """

def render_stacked_latency_bar(latency: Dict[str, Any]) -> str:
    """Renders a visual horizontal stacked bar graph showing where step time was spent."""
    total = max(0.1, latency.get("total_sec", 1))
    web = latency.get("web_settle_sec", 0)
    som = latency.get("som_tagging_sec", 0)
    vlm = latency.get("vlm_cognition_sec", 0)
    act = latency.get("action_exec_sec", 0)

    web_pct = (web / total) * 100
    som_pct = (som / total) * 100
    vlm_pct = (vlm / total) * 100
    act_pct = (act / total) * 100

    return f"""
    <div style="background: #0f172a; border-radius: 8px; padding: 8px 12px; margin: 10px 0; border: 1px solid #334155;">
        <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 4px; color: #f8fafc;">
            <span>⏱️ <b>Step Latency Breakdown:</b> <span style="color: #38bdf8; font-weight: bold;">{total}s</span></span>
            <span style="color: #94a3b8; font-size: 10px;">AI: {vlm}s | Web: {web}s | Action: {act}s</span>
        </div>
        
        <!-- Stacked Bar -->
        <div style="display: flex; height: 10px; border-radius: 5px; overflow: hidden; background: #334155; width: 100%;">
            <div style="width: {vlm_pct}%; background: #a855f7;" title="AI Cognition / VLM: {vlm}s"></div>
            <div style="width: {web_pct}%; background: #06b6d4;" title="Web Settle / Network: {web}s"></div>
            <div style="width: {act_pct}%; background: #22c55e;" title="Action Exec: {act}s"></div>
            <div style="width: {som_pct}%; background: #f59e0b;" title="SoM Tagging: {som}s"></div>
        </div>

        <!-- Legend -->
        <div style="display: flex; gap: 12px; font-size: 9px; color: #94a3b8; margin-top: 4px;">
            <span><span style="color: #a855f7;">■</span> AI Deliberation ({vlm_pct:.0f}%)</span>
            <span><span style="color: #06b6d4;">■</span> Web Load ({web_pct:.0f}%)</span>
            <span><span style="color: #22c55e;">■</span> Action ({act_pct:.0f}%)</span>
            <span><span style="color: #f59e0b;">■</span> SoM Tag ({som_pct:.0f}%)</span>
        </div>
    </div>
    """

def generate_comparative_matrix_html(multi_results: Dict[str, List[Dict[str, Any]]]) -> str:
    """Renders executive table and multi-persona comparative time bar graphs."""
    rows_html = ""
    time_bars_html = ""
    max_total_time = 1

    # Find max time for scaling comparison bars
    for p_name, steps in multi_results.items():
        t = sum(s.get("latency_telemetry", {}).get("total_sec", 0) for s in steps)
        if t > max_total_time:
            max_total_time = t

    for p_idx, (persona_name, steps) in enumerate(multi_results.items()):
        if not steps:
            continue
        color = PERSONA_COLORS[p_idx % len(PERSONA_COLORS)]["bg"]
        last_step = steps[-1]
        avatar = last_step.get("avatar", "👤")
        step_count = len(steps)
        avg_confusion = round(sum(s.get("confusion_pct", 20) for s in steps) / step_count)
        
        status = "🟢 Completed" if (last_step.get("goal_status") == "SATISFIED" or last_step.get("action") == "COMPLETE") else "🔴 Abandoned" if last_step.get("action") == "DROP_OFF" else "🟡 Max Steps"
        status_color = "#22c55e" if "Completed" in status else "#ef4444" if "Abandoned" in status else "#eab308"
        total_time = round(sum(s.get("latency_telemetry", {}).get("total_sec", 0) for s in steps), 1)
        top_finding = last_step.get("critique", "N/A")
        
        time_bar_pct = (total_time / max_total_time) * 100

        rows_html += f"""
        <tr style="border-bottom: 1px solid #334155;">
            <td style="padding: 10px 12px; font-weight: 700; color: #f8fafc;">{esc(avatar)} {esc(persona_name)}</td>
            <td style="padding: 10px 12px;"><span style="color: {status_color}; font-weight: 700;">{status}</span></td>
            <td style="padding: 10px 12px; color: #94a3b8; font-weight: 600;">{step_count} step(s)</td>
            <td style="padding: 10px 12px;">{get_confusion_badge(avg_confusion)}</td>
            <td style="padding: 10px 12px; color: #38bdf8; font-family: monospace; font-size: 11px;">{total_time}s</td>
            <td style="padding: 10px 12px; font-size: 12px; color: #cbd5e1;">{esc(top_finding)}</td>
        </tr>
        """

        time_bars_html += f"""
        <div style="margin-bottom: 8px;">
            <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 2px;">
                <span style="color: {color}; font-weight: bold;">{esc(avatar)} {esc(persona_name.split(',')[0])}</span>
                <span style="color: #94a3b8;">{total_time}s</span>
            </div>
            <div style="height: 8px; background: #1e293b; border-radius: 4px; overflow: hidden;">
                <div style="width: {time_bar_pct}%; background: {color}; height: 100%; border-radius: 4px;"></div>
            </div>
        </div>
        """

    return f"""
    <div style="background: #0f172a; border-radius: 16px; padding: 20px; border: 1px solid #334155; margin-bottom: 24px; box-shadow: 0 10px 25px rgba(0,0,0,0.3);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
            <h3 style="margin: 0; color: #38bdf8; font-size: 16px; text-transform: uppercase; letter-spacing: 0.5px;">📊 Executive Usability Benchmark Matrix</h3>
        </div>
        
        <table style="width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; margin-bottom: 18px;">
            <thead>
                <tr style="background: #1e293b; color: #94a3b8; text-transform: uppercase; font-size: 11px;">
                    <th style="padding: 10px 12px; border-top-left-radius: 8px;">Persona</th>
                    <th style="padding: 10px 12px;">Status</th>
                    <th style="padding: 10px 12px;">Steps</th>
                    <th style="padding: 10px 12px;">Avg Confusion</th>
                    <th style="padding: 10px 12px;">Total Time</th>
                    <th style="padding: 10px 12px; border-top-right-radius: 8px;">Key Finding</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>

        <!-- Total Time Visual Comparison -->
        <div style="background: #1e293b; border-radius: 10px; padding: 12px; border: 1px solid #334155;">
            <div style="font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; margin-bottom: 8px;">⏱️ Total Task Time Comparison</div>
            {time_bars_html}
        </div>
    </div>
    """

def generate_multi_persona_replay_html(multi_results: Dict[str, List[Dict[str, Any]]]) -> str:
    """Renders executive matrix, SVG friction curves, latency graphs, and replay players."""
    if not multi_results:
        return "<p style='color: white;'>No simulation results.</p>"

    matrix_html = generate_comparative_matrix_html(multi_results)
    render_id = int(time.time() * 1000)
    sections_html = ""

    for p_idx, (persona_name, steps) in enumerate(multi_results.items()):
        color = PERSONA_COLORS[p_idx % len(PERSONA_COLORS)]["bg"]
        
        # SVG Journey Graph for this persona
        friction_chart_svg = render_svg_friction_chart(steps, line_color=color)
        
        steps_html = ""
        for idx, step in enumerate(steps):
            badge = get_confusion_badge(step.get("confusion_pct", 20))
            target = step.get("target_coords", {"x": 50, "y": 50})
            tx, ty = target.get("x", 50), target.get("y", 50)
            
            action = step.get("action", "COMPLETE")
            avatar = esc(step.get("avatar", "👤"))
            bubble_text = esc(step.get("internal_monologue", "")[:85])
            typed_text = esc(step.get("input_text", ""))
            action_color = "#38bdf8" if action in ["CLICK", "TYPE"] else "#22c55e" if action == "COMPLETE" else "#ef4444"

            before_img = step.get("before_screenshot_b64", "")
            after_img = step.get("after_screenshot_b64", before_img)
            debug_info = step.get("debug_info", {})
            annotated_b64 = debug_info.get("annotated_screenshot_b64", "")
            
            # Stacked latency graph
            latency = step.get("latency_telemetry", {})
            latency_graph_html = render_stacked_latency_bar(latency)

            # The model's running scratchpad, so a wrong "cheapest" pick can be
            # traced back to what it had actually recorded at that point.
            notes = debug_info.get("observations", "")
            notes_html = (
                f'<div style="font-size: 11px; color: #a855f7; margin-top: 6px;">'
                f'<b>🧠 Notes carried forward:</b> {esc(notes)}</div>'
            ) if notes else ""

            step_css = f"""
            <style>
                @keyframes glideCursor_{render_id}_{p_idx}_{idx} {{
                    0%   {{ top: 85%; left: 50%; opacity: 0; transform: scale(0.8); }}
                    20%  {{ top: {ty}%; left: {tx}%; opacity: 1; transform: scale(1); }}
                    50%  {{ top: {ty}%; left: {tx}%; transform: scale(0.92); }}
                    75%  {{ top: {ty}%; left: {tx}%; transform: scale(1); }}
                    100% {{ top: {ty}%; left: {tx}%; opacity: 1; }}
                }}
                @keyframes typingEffect_{render_id}_{p_idx}_{idx} {{
                    0%, 25%  {{ width: 0; opacity: 0; }}
                    30%      {{ opacity: 1; }}
                    65%, 100%{{ width: 220px; opacity: 1; }}
                }}
                @keyframes pageTransition_{render_id}_{p_idx}_{idx} {{
                    0%, 65%  {{ opacity: 0; }}
                    75%, 100%{{ opacity: 1; }}
                }}
                @keyframes enterRipple_{render_id}_{p_idx}_{idx} {{
                    0%, 60%  {{ opacity: 0; transform: scale(0); }}
                    68%      {{ opacity: 1; transform: scale(1); box-shadow: 0 0 0 0 rgba(56, 189, 248, 0.8); }}
                    80%      {{ opacity: 0; transform: scale(1.6); box-shadow: 0 0 0 18px rgba(56, 189, 248, 0); }}
                    100%     {{ opacity: 0; }}
                }}
            </style>
            """

            typewriter_overlay = f"""
            <div style="position: absolute; top: calc({ty}% - 14px); left: calc({tx}% - 100px); background: #0f172a; border: 2px solid #38bdf8; border-radius: 6px; padding: 4px 8px; font-family: monospace; font-size: 11px; color: #38bdf8; font-weight: bold; white-space: nowrap; overflow: hidden; animation: typingEffect_{render_id}_{p_idx}_{idx} 4.5s steps(25, end) forwards; z-index: 40;">
                ⌨️ {typed_text}<span style="animation: blink 1s infinite;">|</span>
            </div>
            """ if action == "TYPE" and typed_text else ""

            cinema_player = f"""
            <div id="player-box-{render_id}-{p_idx}-{idx}" style="position: relative; width: 100%; border-radius: 10px; overflow: hidden; border: 1px solid #475569; box-shadow: 0 8px 24px rgba(0,0,0,0.4); aspect-ratio: 16/10;">
                <img src="data:image/png;base64,{before_img}" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover;" />
                <img src="data:image/png;base64,{after_img}" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover; animation: pageTransition_{render_id}_{p_idx}_{idx} 4.5s ease forwards;" />
                {typewriter_overlay}
                <div style="position: absolute; top: calc({ty}% - 14px); left: calc({tx}% - 14px); width: 28px; height: 28px; border-radius: 50%; border: 2px solid #38bdf8; pointer-events: none; animation: enterRipple_{render_id}_{p_idx}_{idx} 4.5s ease infinite;"></div>

                <div style="position: absolute; z-index: 50; pointer-events: none; animation: glideCursor_{render_id}_{p_idx}_{idx} 4.5s cubic-bezier(0.25, 1, 0.5, 1) forwards;">
                    <div style="position: absolute; bottom: 26px; left: 16px; background: #0f172a; color: #f8fafc; font-size: 11px; padding: 6px 10px; border-radius: 8px; width: 180px; line-height: 1.35; box-shadow: 0 6px 16px rgba(0,0,0,0.5); border: 1px solid {color};">
                        💬 {bubble_text}...
                    </div>
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                        <path d="M5.5 3.21V20.8c0 .45.54.67.85.35l4.86-4.86a.5.5 0 0 1 .35-.15h6.87c.45 0 .67-.54.35-.85L6.35 2.85a.5.5 0 0 0-.85.36z" fill="{color}" stroke="#ffffff" stroke-width="1.5"/>
                    </svg>
                    <div style="background: {color}; color: #0f172a; font-size: 10px; font-weight: 800; padding: 2px 6px; border-radius: 6px; margin-left: 14px; margin-top: -6px; white-space: nowrap; width: fit-content;">
                        {avatar} {esc(persona_name.split(',')[0])} ({esc(action)})
                    </div>
                </div>
            </div>
            """

            marked_img_html = f"""
            <div style="margin-top: 10px;">
                <div style="font-size: 10px; color: #94a3b8; margin-bottom: 4px; font-weight: bold;">👁️ Model Set-of-Marks Input Image:</div>
                <img src="data:image/jpeg;base64,{annotated_b64}" style="width: 100%; border-radius: 6px; border: 1px solid #334155;" />
            </div>
            """ if annotated_b64 else ""

            steps_html += f"""
            {step_css}
            <div style="background: #1e293b; border-radius: 14px; padding: 18px; margin-bottom: 20px; border: 1px solid #334155; color: #f8fafc;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <div>
                        <span style="font-weight: 800; font-size: 15px; color: #38bdf8;">Step {step['step']}: {esc(step.get('page_title', 'Webpage'))}</span>
                        <div style="font-size: 11px; color: #94a3b8; margin-top: 2px;">🔗 {esc(step.get('url', ''))}</div>
                    </div>
                    {badge}
                </div>
                
                <div style="display: flex; gap: 20px; align-items: flex-start;">
                    <div style="width: 55%;">
                        {cinema_player}
                        <div style="margin-top: 8px; display: flex; justify-content: space-between; align-items: center;">
                            <span style="font-size: 11px; color: #64748b;">🎞️ Action: <b>{action}</b></span>
                            <button onclick="
                                const el = document.getElementById('player-box-{render_id}-{p_idx}-{idx}');
                                const clone = el.cloneNode(true);
                                el.parentNode.replaceChild(clone, el);
                            " style="background: #334155; color: #f8fafc; border: 1px solid #475569; padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; cursor: pointer;">
                                ▶️ Replay Step {step['step']}
                            </button>
                        </div>
                    </div>
                    
                    <div style="width: 45%; font-size: 13px;">
                        <div style="background: #0f172a; border-radius: 10px; padding: 12px; border-left: 4px solid {color}; margin-bottom: 10px;">
                            <span style="font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 800;">{avatar} Internal Monologue</span>
                            <p style="margin: 6px 0 0 0; font-style: italic; color: #cbd5e1; line-height: 1.45;">
                                "{esc(step.get('internal_monologue', ''))}"
                            </p>
                        </div>

                        <!-- Graph 1: Horizontal Stacked Latency Bar -->
                        {latency_graph_html}

                        <div style="margin-bottom: 8px;">
                            <b>Action Taken:</b> <span style="background: {action_color}; color: #0f172a; padding: 2px 8px; border-radius: 6px; font-weight: 800; font-size: 12px;">{esc(action)}</span>
                            {f' <span style="color: #38bdf8;">(Typed: "{typed_text}")</span>' if typed_text else ''}
                        </div>

                        <div style="color: #38bdf8; font-size: 12px; line-height: 1.4; margin-bottom: 12px;">
                            🛠️ <b>UX Finding:</b> {esc(step.get('critique', 'N/A'))}
                        </div>

                        <details style="background: #0f172a; border-radius: 8px; padding: 8px 12px; border: 1px solid #334155; cursor: pointer;">
                            <summary style="font-size: 11px; font-weight: bold; color: #94a3b8; text-transform: uppercase;">🛠️ Step {step['step']} Diagnostics</summary>
                            <div style="font-size: 11px; color: #38bdf8; margin-top: 6px;"><b>Execution:</b> {esc(debug_info.get('execution_log', 'N/A'))}</div>
                            {notes_html}
                            {marked_img_html}
                        </details>
                    </div>
                </div>
            </div>
            """

        sections_html += f"""
        <div style="background: #0f172a; border-radius: 16px; padding: 20px; border: 2px solid {color}; margin-bottom: 30px;">
            <h2 style="color: {color}; margin: 0 0 16px 0; font-size: 18px; display: flex; align-items: center; gap: 8px;">
                👤 Persona Walkthrough: {esc(persona_name)}
            </h2>
            
            <!-- Graph 2: Cognitive Friction Journey Curve (SVG Line Chart) -->
            {friction_chart_svg}

            {steps_html}
        </div>
        """

    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
        {matrix_html}
        {sections_html}
    </div>
    """