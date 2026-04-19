import re

with open('/Users/roycel/Downloads/UCSD/VS Code Stuff/404 Fish Now Found/datahacks/frontend/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# EXTRACT COMPONENTS
topbar_match = re.search(r'<div id="topbar">.*?(?=<!-- MAIN DASHBOARD -->)', html, re.DOTALL)
topbar_html = topbar_match.group(0) if topbar_match else ""

sidebar_left_match = re.search(r'<!-- LEFT SIDEBAR -->\s*(<div class="sidebar">.*?</div>)\s*<!-- CENTER MAP', html, re.DOTALL)
sidebar_left_html = sidebar_left_match.group(1) if sidebar_left_match else ""

sidebar_right_match = re.search(r'<!-- RIGHT SIDEBAR -->\s*(<div class="sidebar">.*?</div>)\s*(?=</div>\s*<script)', html, re.DOTALL)
sidebar_right_html = sidebar_right_match.group(1) if sidebar_right_match else ""

controls_overlay_match = re.search(r'<div id="controls-overlay".*?</div>', html, re.DOTALL)
controls_overlay_html = controls_overlay_match.group(0) if controls_overlay_match else ""

hidden_func_match = re.search(r'<!-- Hidden DOM Elements needed by existing JS -->\s*(<div class="hidden-functional">.*?</div>)', html, re.DOTALL)
hidden_func_html = hidden_func_match.group(1) if hidden_func_match else ""

CSS_NEW = '''
        /* BASE & MAPLIBRE */
        #canvas-container {
            position: absolute; top:0; left:0; width:100%; height:100%; z-index:0;
            overflow: hidden; border: none; border-radius: 0; background: none;
        }
        
        #view-2d-map {
            width: 100%; height: 100%; position: absolute; top:0; left:0;
            /* FAKE BATHYMETRY GRADIENT */
            background: radial-gradient(circle at 40% 60%, #004B63 0%, #031521 60%, #010408 100%);
            z-index: 1;
        }

        /* GLOWING MAP MARKERS */
        .map-marker {
            width: 14px; height: 14px;
            background: #fff;
            border-radius: 50%;
            cursor: pointer;
            box-shadow: 0 0 10px #4DA8DA, 0 0 20px #4DA8DA;
            position: relative;
        }
        .map-marker::after {
            content: '';
            position: absolute; top: -6px; left: -6px; right: -6px; bottom: -6px;
            border-radius: 50%;
            border: 2px solid rgba(77, 168, 218, 0.5);
            animation: pulse-ring 2s infinite cubic-bezier(0.215, 0.61, 0.355, 1);
        }
        @keyframes pulse-ring {
            0% { transform: scale(0.8); opacity: 1; }
            100% { transform: scale(2.5); opacity: 0; }
        }
        .map-marker-label {
            position: absolute; top: 18px; left: 50%; transform: translateX(-50%);
            font-size: 11px; font-weight: 600; color: #fff; text-shadow: 0 2px 4px rgba(0,0,0,0.8);
            white-space: nowrap; pointer-events: none;
        }

        #ui-layer {
            position: absolute; top:0; left:0; width:100%; height:100%;
            z-index: 10; pointer-events: none;
            display: flex; flex-direction: column;
        }
        #topbar { pointer-events: auto; }
        
        #main {
            flex: 1; display: flex; justify-content: space-between;
            padding: 0 24px 24px 24px; gap: 16px;
        }
        
        .sidebar { pointer-events: auto; width: 280px; display: flex; flex-direction: column; gap: 16px; }
        .pointer-auto { pointer-events: auto; }
        .center-gap { flex: 1; position: relative; pointer-events: none; }
        
        #controls-overlay {
            position: absolute; bottom: 0; left: 50%; transform: translateX(-50%);
            display: flex; gap: 8px; justify-content: center; width: 100%; padding-bottom: 8px;
        }

        /* GLASSMORPHISM */
        .panel {
            background: rgba(14, 20, 26, 0.45);
            backdrop-filter: blur(16px) saturate(180%);
            -webkit-backdrop-filter: blur(16px) saturate(180%);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            padding: 16px;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.5);
        }
'''

# REPLACE CSS inline
html_mod = html.replace('.panel {', '._orig_panel {') # disable old panel
html_mod = html.replace('.sidebar {', '._orig_sidebar {') 
html_mod = html.replace('#main {', '._orig_main {') 
html_mod = html.replace('#canvas-container {', '._orig_canvas-container {')
html_mod = html.replace('#view-2d-map {', '._orig_view-2d-map {')

css_match = re.search(r'<style>(.*?)</style>', html_mod, re.DOTALL)
if css_match:
    updated_css = css_match.group(1) + CSS_NEW
    html_mod = html_mod[:css_match.start(1)] + updated_css + html_mod[css_match.end(1):]

# MAPLIBRE CDN in HEAD
if '<head>' in html_mod and 'maplibre' not in html_mod:
    html_mod = html_mod.replace('<head>', '<head>\n    <script src="https://unpkg.com/maplibre-gl@latest/dist/maplibre-gl.js"></script>\n    <link href="https://unpkg.com/maplibre-gl@latest/dist/maplibre-gl.css" rel="stylesheet" />')

NEW_BODY = f'''<body>
    <!-- MAP & 3D BACKGROUND -->
    <div id="canvas-container">
        <div id="view-2d-map"></div>
        <div id="dive-overlay"></div>
        <div id="view-3d-underwater">
            <div id="annotations"></div>
        </div>
    </div>

    <!-- UI FOREGROUND -->
    <div id="ui-layer">
{topbar_html}
        <div id="main">
{sidebar_left_html}
            <div class="center-gap">
{controls_overlay_html}
            </div>
{sidebar_right_html}
        </div>
    </div>
    
{hidden_func_html}
'''

# We need to replace the entire body except scripts.
body_match = re.search(r'<body>(.*?)<script type="module">', html_mod, re.DOTALL)
if body_match:
    html_mod = html_mod[:body_match.start()] + NEW_BODY + '\n<script type="module">' + html_mod[body_match.end(1) + 21:]

# Now replace JS functions `render2DMap`, `selectZone`, `switchView` using string manipulation or regex
js_replacement = '''
        // ── MAPLIBRE 2D MAP ──────────────────────────────────
        let map;
        let mapMarkers = {};
        
        Object.assign(ZONES.find(z => z.id === 'la-jolla'), {lngLat: [-117.27, 32.85]});
        Object.assign(ZONES.find(z => z.id === 'point-loma'), {lngLat: [-117.24, 32.67]});
        Object.assign(ZONES.find(z => z.id === 'coronado'), {lngLat: [-117.18, 32.68]});
        Object.assign(ZONES.find(z => z.id === 'del-mar'), {lngLat: [-117.27, 32.96]});

        function render2DMap() {
            if (!map) {
                // Fetch the style first so we can modify it
                fetch('https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json')
                  .then(r => r.json())
                  .then(style => {
                      style.layers.forEach(l => {
                          if(l.id.toLowerCase().includes('water') || l.id === 'background') {
                              l.paint['fill-color'] = 'rgba(0,0,0,0)';
                              l.paint['background-color'] = 'rgba(0,0,0,0)';
                          }
                          if(l.id.includes('land') || l.id === 'landcover') {
                              if(l.paint) l.paint['fill-color'] = '#111418';
                          }
                      });
                      
                      map = new maplibregl.Map({
                          container: 'view-2d-map',
                          style: style,
                          center: [-117.22, 32.81],
                          zoom: 10.5,
                          pitch: 20,
                          interactive: true
                      });

                      map.on('load', () => {
                          ZONES.forEach(zone => {
                              const el = document.createElement('div');
                              el.className = `map-marker`;
                              if(zone.id === DashboardState.selectedZone) el.style.boxShadow = '0 0 10px #ff6600, 0 0 20px #ff6600';
                              
                              const label = document.createElement('div');
                              label.className = 'map-marker-label'; label.textContent = zone.name;
                              el.appendChild(label);
                              
                              el.onclick = () => selectZone(zone.id);
                              
                              mapMarkers[zone.id] = new maplibregl.Marker(el)
                                  .setLngLat(zone.lngLat)
                                  .addTo(map);
                          });
                      });
                  }).catch(e => console.error("MapLibre fail", e));
            } else {
                // Update marker styles
                Object.keys(mapMarkers).forEach(id => {
                    const el = mapMarkers[id].getElement();
                    if(id === DashboardState.selectedZone) {
                        el.style.boxShadow = '0 0 10px #ff6600, 0 0 20px #ff6600';
                        el.style.background = '#fff';
                        el.style.zIndex = 10;
                    } else {
                        el.style.boxShadow = '0 0 10px #4DA8DA, 0 0 20px #4DA8DA';
                        el.style.background = '#fff';
                        el.style.zIndex = 1;
                    }
                });
            }
        }
        
        window.selectZone = (zoneId) => {
            if (DashboardState.isTransitioning) return;
            DashboardState.selectedZone = zoneId;
            render2DMap();
            renderZoneList();
            
            const targetPos = ZONES.find(z => z.id === zoneId).lngLat;
            if(map) map.flyTo({center: targetPos, zoom: 12.5, speed: 0.8});
        };

        window.switchView = (mode) => {
            if (DashboardState.viewMode === mode || DashboardState.isTransitioning) return;
            DashboardState.isTransitioning = true;
            DashboardState.viewMode = mode;
            
            document.getElementById('pill-2d').classList.toggle('active', mode === '2d');
            document.getElementById('pill-3d').classList.toggle('active', mode === '3d');
            document.getElementById('pill-bg').style.transform = mode === '3d' ? 'translateX(72px)' : 'translateX(0)';
            document.getElementById('pill-bg').style.width = mode === '3d' ? '120px' : '74px';
            
            const v2d = document.getElementById('view-2d-map');
            const overlay = document.getElementById('dive-overlay');
            const v3d = document.getElementById('view-3d-underwater');

            if (mode === '3d') {
                const targetPos = ZONES.find(z => z.id === DashboardState.selectedZone).lngLat;
                if(map) {
                    map.easeTo({center: targetPos, zoom: 16.5, duration: 1500, pitch: 60});
                }
                
                setTimeout(() => {
                    overlay.classList.add('diving');
                }, 700);
                
                setTimeout(() => {
                    v2d.style.display = 'none';
                    init3D();
                    v3d.classList.add('active');
                    setTimeout(() => {
                        overlay.classList.remove('diving');
                        DashboardState.isTransitioning = false;
                    }, 800);
                }, 1500);
            } else {
                overlay.classList.add('diving');
                
                setTimeout(() => {
                    v3d.classList.remove('active');
                    dispose3D();
                    
                    v2d.style.display = 'block';
                    const targetPos = ZONES.find(z => z.id === DashboardState.selectedZone).lngLat;
                    if(map) map.easeTo({center: targetPos, zoom: 12.5, pitch: 20, duration: 800});
                    
                    setTimeout(() => {
                        overlay.classList.remove('diving');
                        DashboardState.isTransitioning = false;
                    }, 50);
                }, 800);
            }
        };
'''

# The previous old script blocks for render2D map
# We will use regex to replace everything from `function render2DMap()` down to `// ── 3D RENDERER LOGIC`
js_script_match = re.search(r'// ── 2D MAP RENDERING ──.*?// ── 3D RENDERER LOGIC ──.*?\n', html_mod, re.DOTALL)
if js_script_match:
    html_mod = html_mod[:js_script_match.start()] + js_replacement + '\n        // ── 3D RENDERER LOGIC ────────────────────────────────\n' + html_mod[js_script_match.end():]

# Write out the changed HTML
with open('/Users/roycel/Downloads/UCSD/VS Code Stuff/404 Fish Now Found/datahacks/frontend/index.html', 'w', encoding='utf-8') as f:
    f.write(html_mod)
