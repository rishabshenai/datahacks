import re

with open('/Users/roycel/Downloads/UCSD/VS Code Stuff/404 Fish Now Found/datahacks/frontend/index.html', 'r') as f:
    original = f.read()

# We want to replace the <style> block and the HTML structure before <script type="module">.
# We also want to replace the `ZONES.forEach` blocks for zone cards and annotations.
# Let's extract the javascript.
js_match = re.search(r'(<script type="module">.*?</script>)', original, re.DOTALL)
js_content = js_match.group(1)

# Modify JS content to match new UI needs.
# 1. Annotations
new_ann = '''
// ── HTML ANNOTATION LABELS ─────────────────────────────
const annotationsEl = document.getElementById('annotations');
ZONES.forEach(zone => {
    const div = document.createElement('div');
    div.className = 'zone-annotation'; div.id = `ann-${zone.id}`;
    div.innerHTML = `
    <div class="ann-bubble">
      <div class="ann-name">${zone.name}</div>
      <div class="ann-info">Average: <span class="ann-val">${zone.temp}°C</span></div>
      <div class="ann-info">Kelp Health: <span class="ann-val" style="color: #4DA8DA;">${zone.health}%</span></div>
    </div>
    <div class="ann-dot"></div>
  `;
    annotationsEl.appendChild(div);
});
'''
js_content = re.sub(r'// ── HTML ANNOTATION LABELS ─────────────────────────────.*?// ── ZONE CARDS', new_ann + '\n\t\t// ── ZONE CARDS', js_content, flags=re.DOTALL)

# 2. Zone Cards (ZONE STATUS)
new_zones = '''
// ── ZONE CARDS ─────────────────────────────────────────
const zoneListEl = document.getElementById('zone-list');
ZONES.forEach(zone => {
    const isNominal = zone.health > 50;
    const dotColor = isNominal ? '#4DA8DA' : '#8B9AB0';
    const card = document.createElement('div');
    card.className = 'zone-list-item';
    card.innerHTML = `
        <div class="zone-list-left">
            <div class="zone-dot" style="background: ${dotColor};"></div>
            <span class="zone-name">${zone.name}</span>
        </div>
        <div class="zone-status-pill">Status</div>
    `;
    zoneListEl.appendChild(card);
});
'''
js_content = re.sub(r'// ── ZONE CARDS ─────────────────────────────────────────.*?// ── TEMP CHART', new_zones + '\n\t\t// ── TEMP CHART', js_content, flags=re.DOTALL)

# 3. Temp Chart logic
new_chart = '''
// ── TEMP CHART ─────────────────────────────────────────
const tempHistory = Array.from({ length: 24 }, (_, i) => 14.5 + Math.sin(i * 0.55) * 1.8 + (Math.random() - 0.5) * 0.6);
function updateChart() {
    const tMin = 14, tMax = 24, CW = 230, CH = 60;
    const pts = tempHistory.map((t, i) => {
        const x = (i / (tempHistory.length - 1)) * CW;
        const y = CH - ((t - tMin) / (tMax - tMin)) * CH;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    const lineEl = document.getElementById('chart-line');
    const areaEl = document.getElementById('chart-area');
    if (lineEl && areaEl) {
        lineEl.setAttribute('d', `M ${pts.join(' L ')}`);
        areaEl.setAttribute('d', `M 0,${CH} L ${pts.join(' L ')} L ${CW},${CH} Z`);
    }
    // Update dots (create dynamically if not exists)
    const svg = document.getElementById('temp-chart-svg');
    if (svg) {
        // Just an example, let's keep it simple without dots for now, or just re-render some points.
        document.querySelectorAll('.chart-dot').forEach(d => d.remove());
        const sparsePts = [0, 5, 10, 15, 20, 23];
        sparsePts.forEach(idx => {
            const t = tempHistory[idx];
            const x = (idx / (tempHistory.length - 1)) * CW;
            const y = CH - ((t - tMin) / (tMax - tMin)) * CH;
            const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            circle.setAttribute('cx', x); circle.setAttribute('cy', y); circle.setAttribute('r', '2.5');
            circle.setAttribute('fill', '#4DA8DA');
            circle.classList.add('chart-dot');
            svg.appendChild(circle);
        });
    }
}
updateChart();
'''
js_content = re.sub(r'// ── TEMP CHART ─────────────────────────────────────────.*?// ── CLOCK', new_chart + '\n\t\t// ── CLOCK', js_content, flags=re.DOTALL)

# 4. Remove X polling for simplicty to Ocean Signals text replacement?
# ACTUALLY, "OCEAN SIGNALS" should be static or filled with real variables. We can replace the X Poll.
new_poll_x = '''
async function pollX() {
    // We'll map Ocean Signals here instead
    try {
        const d = await fetch('http://localhost:5000/live').then(r => r.json());
        // Just mock some data updates for the new Ocean Signals UI
        document.getElementById('sig-avg').textContent = d.temp.toFixed(1) + '°C';
    } catch (_) {}
}
setInterval(pollX, 15000); pollX();
'''
js_content = re.sub(r'async function pollX\(\) \{.*?setInterval\(pollX, 15000\); pollX\(\);', new_poll_x, js_content, flags=re.DOTALL)


# Let's write the new HTML file skeleton.
new_html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Aegis Ocean Dashboard V1</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-color: #060B14;
            --panel-bg: rgba(20, 30, 48, 0.45);
            --panel-border: rgba(255, 255, 255, 0.08);
            --text-main: #FFFFFF;
            --text-muted: #8D99AE;
            --primary: #4DA8DA;
            --indicator-nominal: #4DA8DA;
            --indicator-warning: #DE7237;
        }}

        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }}
        
        body {{
            background: radial-gradient(circle at center, #0B1A2C 0%, var(--bg-color) 100%);
            color: var(--text-main);
            display: flex;
            flex-direction: column;
            height: 100vh;
            overflow: hidden;
            font-size: 12px;
        }}

        /* TOP BAR */
        #topbar {{
            height: 60px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 24px;
            z-index: 20;
        }}
        .title-main {{
            font-size: 18px;
            font-weight: 700;
            letter-spacing: 0.5px;
            color: var(--text-main);
        }}
        .title-v1 {{ color: var(--primary); }}
        
        #topbar-right {{
            display: flex;
            align-items: center;
            gap: 16px;
        }}
        .icon-btn {{
            background: var(--panel-bg);
            border: 1px solid var(--panel-border);
            width: 32px; height: 32px;
            border-radius: 8px;
            display: flex; align-items: center; justify-content: center;
            color: var(--text-muted);
            cursor: pointer;
        }}
        .avatar {{
            width: 32px; height: 32px;
            border-radius: 8px;
            background: #8D99AE;
            overflow: hidden;
        }}
        .desk-btn {{
            background: transparent;
            border: 1px solid var(--panel-border);
            color: var(--text-main);
            padding: 6px 14px;
            border-radius: 8px;
            font-size: 12px;
            display: flex; align-items: center; gap: 8px;
            cursor: pointer;
        }}

        /* LAYOUT */
        #main {{
            flex: 1;
            display: flex;
            padding: 0 16px 16px 16px;
            gap: 16px;
            overflow: hidden;
        }}

        .sidebar {{
            width: 280px;
            display: flex;
            flex-direction: column;
            gap: 16px;
            flex-shrink: 0;
            z-index: 10;
        }}

        .panel {{
            background: var(--panel-bg);
            border: 1px solid var(--panel-border);
            border-radius: 12px;
            padding: 16px;
            backdrop-filter: blur(12px);
            display: flex;
            flex-direction: column;
        }}
        .panel-title {{
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-main);
            margin-bottom: 14px;
        }}

        /* VIDEO PLACEHOLDER */
        .video-box {{
            background: rgba(0,0,0,0.4);
            border-radius: 8px;
            height: 140px;
            position: relative;
            display: flex; align-items: center; justify-content: center;
            border: 1px solid rgba(255,255,255,0.05);
            /* Just a linear gradient to simulate ocean */
            background: linear-gradient(180deg, #182A3A 0%, #0F1823 100%);
        }}
        .play-icon {{
            width: 0; height: 0;
            border-top: 8px solid transparent;
            border-bottom: 8px solid transparent;
            border-left: 12px solid #FFF;
            opacity: 0.8;
        }}
        .video-controls {{
            position: absolute;
            bottom: 8px; left: 8px; right: 8px;
            display: flex; align-items: center; gap: 6px;
        }}
        .vid-bar {{ flex: 1; height: 2px; background: rgba(255,255,255,0.2); border-radius: 2px; position: relative; }}
        .vid-fill {{ width: 35%; height: 100%; background: var(--text-main); border-radius: 2px; }}
        .vid-play-small {{ width: 6px; height: 6px; background: var(--text-muted); }}

        /* SENTINEL INSIGHT */
        .big-temp {{
            font-size: 42px;
            font-weight: 700;
            color: var(--primary);
            margin-bottom: 16px;
        }}
        
        .insight-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            font-size: 11px;
            color: var(--text-muted);
        }}
        .insight-row span {{ width: 70px; }}
        .insight-row .val {{ width: 40px; text-align: right; color: var(--text-main); font-weight: 500; }}
        .bar-wrap {{
            flex: 1; height: 6px; background: rgba(255,255,255,0.1);
            border-radius: 3px; margin: 0 10px; overflow: hidden;
        }}
        .bar-fill {{ height: 100%; background: var(--primary); width: 50%; border-radius: 3px; }}

        /* TEMP HISTORY CHART */
        #temp-chart {{ width: 100%; height: 80px; margin-top: 10px; position: relative; }}
        .chart-labels {{ display: flex; justify-content: space-between; font-size: 9px; color: var(--text-muted); margin-top: 6px; }}
        .y-labels {{ position: absolute; left: 0; top: 0; height: 80px; display: flex; flex-direction: column; justify-content: space-between; font-size: 9px; color: var(--text-muted); }}
        svg#temp-chart-svg {{ width: calc(100% - 20px); height: 100%; margin-left: 20px; overflow: visible; }}

        /* ZONE STATUS */
        .zone-list-item {{
            display: flex; justify-content: space-between; align-items: center;
            padding: 8px 0;
            border-bottom: 1px solid var(--panel-border);
        }}
        .zone-list-item:last-child {{ border-bottom: none; }}
        .zone-list-left {{ display: flex; align-items: center; gap: 10px; color: var(--text-muted); font-size: 12px; }}
        .zone-dot {{ width: 8px; height: 8px; border-radius: 50%; }}
        .zone-status-pill {{
            background: rgba(255,255,255,0.1);
            color: var(--text-main);
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 10px;
            font-weight: 500;
        }}

        /* DIVE TEAM STATUS */
        .team-table {{ width: 100%; border-collapse: collapse; margin-bottom: 16px; color: var(--text-muted); font-size: 12px; }}
        .team-table th {{ text-align: left; font-weight: 500; padding-bottom: 10px; border-bottom: 1px solid var(--panel-border); }}
        .team-table th:last-child {{ text-align: right; }}
        .team-table td {{ padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.02); }}
        .team-table td:last-child {{ text-align: right; }}
        .owned-pill {{ background: rgba(255,255,255,0.1); color: var(--text-main); padding: 2px 10px; border-radius: 12px; font-size: 10px; display: inline-block; }}
        
        .huge-percent {{ font-size: 36px; font-weight: 700; color: var(--primary); line-height: 1; margin-bottom: 8px; }}
        .percent-bar {{ width: 100%; height: 8px; background: rgba(255,255,255,0.1); border-radius: 4px; overflow: hidden; }}
        .percent-fill {{ width: 90%; height: 100%; background: var(--primary); border-radius: 4px; }}

        /* OCEAN SIGNALS */
        .signal-row {{ display: flex; justify-content: space-between; padding: 6px 0; color: var(--text-muted); font-size: 11px; }}
        .signal-val {{ color: var(--primary); font-weight: 600; }}

        /* CENTER CANVAS */
        #canvas-container {{
            flex: 1;
            position: relative;
            border-radius: 12px;
            border: 1px solid rgba(255,255,255,0.05);
            background: #0B111A; /* Inner fallback */
            min-height: 100%;
            overflow: hidden;
        }}
        
        /* ANNOTATIONS */
        .zone-annotation {{
            position: absolute; pointer-events: none;
            transform: translate(-50%, -100%);
            display: flex; flex-direction: column; align-items: center;
            opacity: 0; transition: opacity 0.3s;
        }}
        .ann-bubble {{
            background: rgba(16, 28, 43, 0.7);
            border: 1px solid rgba(255,255,255,0.3);
            border-radius: 6px;
            padding: 8px 12px;
            backdrop-filter: blur(8px);
            margin-bottom: 6px;
        }}
        .ann-name {{ font-size: 11px; font-weight: 600; color: var(--text-main); margin-bottom: 4px; }}
        .ann-info {{ font-size: 9px; color: rgba(255,255,255,0.6); }}
        .ann-val {{ font-weight: 500; }}
        .ann-dot {{ width: 6px; height: 6px; background: #FFF; border-radius: 50%; box-shadow: 0 0 4px #FFF; }}

        /* CONTROLS OVERLAY */
        #controls-overlay {{
            position: absolute;
            bottom: 24px;
            left: 50%;
            transform: translateX(-50%);
            display: flex;
            gap: 8px;
            z-index: 10;
        }}
        .ctrl-btn {{
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            color: var(--text-muted);
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 11px;
            cursor: pointer;
            backdrop-filter: blur(8px);
            transition: all 0.2s;
        }}
        .ctrl-btn.active {{
            background: var(--text-main);
            color: #000;
            font-weight: 600;
        }}
        
        #alert-panel {{ display: none; }}
        #alert-banner {{ display: none; }}

        /* Hidden functional elements to not break JS */
        .hidden-functional {{ display: none; }}
    </style>
</head>
<body>
    <!-- TOP BAR -->
    <div id="topbar">
        <div class="title-main">AEGIS OCEAN DASHBOARD <span class="title-v1">V1</span></div>
        <div id="topbar-right">
            <div class="icon-btn">
                <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>
            </div>
            <div class="avatar"></div>
            <button class="desk-btn">
                <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>
                Web Desktop 
                <svg width="10" height="10" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"></polyline></svg>
            </button>
        </div>
    </div>

    <!-- MAIN DASHBOARD -->
    <div id="main">
        <!-- LEFT SIDEBAR -->
        <div class="sidebar">
            <div class="panel">
                <div class="panel-title">LIVE SENTINEL FEED</div>
                <div class="video-box">
                    <div class="play-icon"></div>
                    <div class="video-controls">
                        <div class="vid-play-small"></div>
                        <div class="vid-bar"><div class="vid-fill"></div></div>
                        <div style="font-size:7px; color:#fff;">::</div>
                    </div>
                </div>
            </div>

            <div class="panel">
                <div class="panel-title">SENTINEL INSIGHT</div>
                <div class="big-temp" id="lv-temp">21.4°C</div>
                
                <div class="insight-row">
                    <span>Del Mar</span>
                    <div class="bar-wrap"><div class="bar-fill" style="width: 80%"></div></div>
                    <span class="val">21.4°C</span>
                </div>
                <div class="insight-row">
                    <span>Point Loma</span>
                    <div class="bar-wrap"><div class="bar-fill" style="width: 80%"></div></div>
                    <span class="val">21.4°C</span>
                </div>
                <div class="insight-row">
                    <span>Coronado</span>
                    <div class="bar-wrap"><div class="bar-fill" style="width: 90%; background: #4DA8DA;"></div></div>
                    <span class="val">22.5°C</span>
                </div>
            </div>

            <div class="panel">
                <div class="panel-title">TEMPERATURE HISTORY</div>
                <div id="temp-chart">
                    <div class="y-labels">
                        <span>24</span><span>22</span><span>20</span><span>18</span><span>16</span>
                    </div>
                    <svg id="temp-chart-svg" viewBox="0 0 230 60" preserveAspectRatio="none">
                        <defs>
                            <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stop-color="#4DA8DA" stop-opacity="0.3" />
                                <stop offset="100%" stop-color="#4DA8DA" stop-opacity="0" />
                            </linearGradient>
                        </defs>
                        <path id="chart-area" fill="url(#chartGrad)" />
                        <path id="chart-line" fill="none" stroke="#4DA8DA" stroke-width="2" stroke-linejoin="round" />
                    </svg>
                    <div class="chart-labels" style="margin-left:20px;">
                        <span>Jan</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- CENTER MAP / 3D SCENE -->
        <div id="canvas-container">
            <div id="annotations"></div>
            <div id="controls-overlay">
                <button class="ctrl-btn active" onclick="setMode(this,'heat')">Heat Map</button>
                <button class="ctrl-btn" onclick="setMode(this,'kelp')">Kelp Health</button>
                <button class="ctrl-btn" onclick="setMode(this,'urchin')">Urchin Density</button>
                <button class="ctrl-btn" onclick="setMode(this,'salinity')">Salinity</button>
            </div>
            
            <!-- Hidden DOM Elements needed by existing JS -->
            <div class="hidden-functional">
                <span id="top-temp"></span>
                <span id="top-turb"></span>
                <span id="top-dist"></span>
                <span id="sim-badge-top"></span>
                <div id="alert-badge"></div>
                <div id="clock"></div>
                <button id="voice-btn"></button>
                <audio id="alert-audio"></audio>
                <span id="lv-turb"></span>
                <span id="lv-dist"></span>
                <div id="temp-bar"></div>
                <div id="turb-bar"></div>
                <div id="status-pill"></div>
                <span id="sim-badge"></span>
                <div id="insight-text"></div>
                <div id="alert-panel"></div>
                <div id="alert-banner"></div>
                <div id="alert-text"></div>
                <svg><line id="thresh-line"></line><text id="thresh-label"></text></svg>
            </div>
        </div>

        <!-- RIGHT SIDEBAR -->
        <div class="sidebar">
            <div class="panel">
                <div class="panel-title">ZONE STATUS</div>
                <!-- This will be populated by JS now -->
                <div id="zone-list"></div>
            </div>

            <div class="panel">
                <div class="panel-title">DIVE TEAM STATUS</div>
                <table class="team-table">
                    <thead>
                        <tr><th>Team</th><th>Status</th></tr>
                    </thead>
                    <tbody>
                        <tr><td>Team Team 1</td><td><span class="owned-pill">Owned</span></td></tr>
                        <tr><td>Team Team 2</td><td><span class="owned-pill">Owned</span></td></tr>
                        <tr><td>Team Team 3</td><td><span class="owned-pill">Owned</span></td></tr>
                    </tbody>
                </table>
                <div class="huge-percent">90%</div>
                <div class="percent-bar">
                    <div class="percent-fill"></div>
                </div>
            </div>

            <div class="panel" style="flex:1;">
                <div class="panel-title">OCEAN SIGNALS</div>
                <div class="signal-row">
                    <span>Average</span>
                    <span class="signal-val" id="sig-avg">21.4°C</span>
                </div>
                <div class="signal-row">
                    <span>Kelp Health</span>
                    <span class="signal-val">4.5%</span>
                </div>
                <div class="signal-row">
                    <span>Urchin Density</span>
                    <span class="signal-val">0.0%</span>
                </div>
                <div class="signal-row">
                    <span>Salinity</span>
                    <span class="signal-val">337.54</span>
                </div>
            </div>
        </div>
    </div>
'''

new_file_content = new_html + js_content + "\n</body>\n</html>\n"

with open('/Users/roycel/Downloads/UCSD/VS Code Stuff/404 Fish Now Found/datahacks/frontend/index.html', 'w') as f:
    f.write(new_file_content)

