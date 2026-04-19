import re

with open('/Users/roycel/Downloads/UCSD/VS Code Stuff/404 Fish Now Found/datahacks/frontend/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

css_match = re.search(r'<style>(.*?)</style>', html, re.DOTALL)
original_css = css_match.group(1) if css_match else ""

css_additions = '''
        /* VIEW TOGGLE */
        .view-toggle-container {
            position: absolute;
            left: 50%;
            transform: translateX(-50%);
            display: flex;
            background: rgba(0,0,0,0.4);
            border: 1px solid var(--panel-border);
            border-radius: 20px;
            padding: 3px;
            z-index: 30;
        }
        .view-pill {
            padding: 6px 18px;
            border-radius: 17px;
            font-size: 11px;
            font-weight: 500;
            color: var(--text-muted);
            cursor: pointer;
            transition: all 0.3s;
            position: relative;
            z-index: 2;
        }
        .view-pill.active {
            color: #000;
            font-weight: 600;
        }
        .view-pill-bg {
            position: absolute;
            top: 3px; left: 3px; bottom: 3px;
            width: 74px;
            background: var(--text-main);
            border-radius: 17px;
            transition: all 0.4s cubic-bezier(0.25, 1, 0.5, 1);
            z-index: 1;
        }
        
        /* 2D MAP SPECIFICS */
        #view-2d-map {
            width: 100%; height: 100%; position: absolute; top:0; left:0;
            background: radial-gradient(circle at center, #0B1A2C 0%, #060B14 100%);
            overflow: hidden;
            display: block;
            transition: transform 0.8s cubic-bezier(0.25, 1, 0.5, 1);
        }
        .map-svg {
            position: absolute; top:0; left:0; width:100%; height:100%;
        }
        .coastline {
            stroke: rgba(77, 168, 218, 0.3);
            stroke-width: 0.5;
            fill: none;
        }
        #map-nodes {
            position: absolute; top:0; left:0; width:100%; height:100%;
        }
        .map-node {
            position: absolute;
            width: 10px; height: 10px;
            background: var(--text-muted);
            border-radius: 50%;
            transform: translate(-50%, -50%);
            cursor: pointer;
            transition: all 0.3s;
            box-shadow: 0 0 0 2px rgba(255,255,255,0.1);
        }
        .map-node:hover { background: #fff; box-shadow: 0 0 8px #fff; }
        .map-node.active { background: var(--primary); box-shadow: 0 0 12px var(--primary); }
        .map-node-label {
            position: absolute; top: 12px; left: 50%; transform: translateX(-50%);
            font-size: 10px; font-weight: 600; color: rgba(255,255,255,0.7);
            white-space: nowrap; pointer-events: none;
        }
        
        /* DIVE OVERLAY */
        #dive-overlay {
            position: absolute; top:0; left:0; width:100%; height:100%;
            background: radial-gradient(circle at center, transparent 0%, #000 100%);
            background-color: rgba(0,0,0,0);
            pointer-events: none;
            z-index: 50;
            opacity: 0;
            transition: opacity 0.8s, background-color 0.8s;
        }
        #dive-overlay.diving {
            opacity: 1;
            background-color: rgba(0,0,10,1);
        }

        #view-3d-underwater {
            width: 100%; height: 100%; position: absolute; top:0; left:0;
            opacity: 0; transition: opacity 0.8s;
            pointer-events: none;
        }
        #view-3d-underwater.active {
            opacity: 1; pointer-events: auto;
        }
'''

new_css = original_css + css_additions

topbar_replacement = '''
    <div id="topbar">
        <div class="title-main">AEGIS OCEAN DASHBOARD <span class="title-v1">V1</span></div>
        
        <div class="view-toggle-container">
            <div class="view-pill-bg" id="pill-bg"></div>
            <div class="view-pill active" onclick="switchView('2d')" id="pill-2d">2D Map</div>
            <div class="view-pill" onclick="switchView('3d')" id="pill-3d">3D Underwater</div>
        </div>

        <div id="topbar-right">
'''

canvas_replacement = '''
        <!-- CENTER MAP / 3D SCENE -->
        <div id="canvas-container">
            <!-- 2D MAP LAYER -->
            <div id="view-2d-map">
                <svg class="map-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
                    <!-- Coastline mockup -->
                    <path d="M45,-10 Q50,20 48,40 T42,70 T48,110" class="coastline" />
                    <path d="M48,40 Q60,45 80,48 T110,50" class="coastline" />
                    <path d="M42,70 Q55,75 70,80 T110,85" class="coastline" />
                </svg>
                <div id="map-nodes"></div>
            </div>

            <div id="dive-overlay"></div>

            <!-- 3D UNDERWATER LAYER -->
            <div id="view-3d-underwater">
                <div id="annotations"></div>
                <div id="controls-overlay" style="display:flex;">
                    <button class="ctrl-btn active" onclick="setMode(this,'heat')">Heat Map</button>
                    <button class="ctrl-btn" onclick="setMode(this,'kelp')">Kelp Health</button>
                    <button class="ctrl-btn" onclick="setMode(this,'urchin')">Urchin Density</button>
                    <button class="ctrl-btn" onclick="setMode(this,'salinity')">Salinity</button>
                </div>
            </div>
            
            <!-- Hidden DOM Elements needed by existing JS -->
'''

js_new = '''
<script type="module">
        import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.module.js';

        // ── STATE MANAGEMENT ──────────────────────────────────
        window.DashboardState = {
            viewMode: '2d',
            selectedZone: 'la-jolla',
            isTransitioning: false
        };

        const ZONES = [
            {
                id: 'la-jolla', name: 'La Jolla Cove',
                pos: new THREE.Vector3(-0.52, 0, -0.22), mapPos: {x: 48, y: 35},
                type: 'kelp', health: 78, urchinDensity: 12, temp: 16.8, depth: '8–30m',
                description: 'Healthy canopy · stable conditions',
                color: '#00ff88', threeColor: new THREE.Color(0x00ff88),
            },
            {
                id: 'point-loma', name: 'Point Loma',
                pos: new THREE.Vector3(0.18, 0, 0.33), mapPos: {x: 42, y: 70},
                type: 'heat', health: 23, urchinDensity: 67, temp: 21.4, depth: '5–25m',
                description: '⚠ Thermal spike — urchins mobilizing',
                color: '#ff6600', threeColor: new THREE.Color(0xff4400),
            },
            {
                id: 'coronado', name: 'Coronado',
                pos: new THREE.Vector3(0.48, 0, 0.02), mapPos: {x: 60, y: 78},
                type: 'urchin', health: 15, urchinDensity: 94, temp: 19.2, depth: '3–18m',
                description: '🚨 Critical barren — dive now',
                color: '#cc44ff', threeColor: new THREE.Color(0xaa22ff),
            },
            {
                id: 'del-mar', name: 'Del Mar',
                pos: new THREE.Vector3(-0.48, 0, 0.38), mapPos: {x: 47, y: 15},
                type: 'normal', health: 65, urchinDensity: 28, temp: 17.1, depth: '10–35m',
                description: 'Recovering · monitoring',
                color: '#0088ff', threeColor: new THREE.Color(0x0088ff),
            },
        ];

        // ── 2D MAP RENDERING ─────────────────────────────────
        function render2DMap() {
            const mapNodes = document.getElementById('map-nodes');
            mapNodes.innerHTML = '';
            ZONES.forEach(zone => {
                const node = document.createElement('div');
                node.className = `map-node ${zone.id === DashboardState.selectedZone ? 'active' : ''}`;
                node.style.left = `${zone.mapPos.x}%`;
                node.style.top = `${zone.mapPos.y}%`;
                
                node.onclick = () => selectZone(zone.id);
                
                const label = document.createElement('div');
                label.className = 'map-node-label';
                label.textContent = zone.name;
                node.appendChild(label);
                
                mapNodes.appendChild(node);
            });
        }
        
        window.selectZone = (zoneId) => {
            if (DashboardState.isTransitioning) return;
            DashboardState.selectedZone = zoneId;
            render2DMap();
            renderZoneList(); // Sync sidebar
        };

        // ── DIVE TRANSITION ──────────────────────────────────
        window.switchView = (mode) => {
            if (DashboardState.viewMode === mode || DashboardState.isTransitioning) return;
            DashboardState.isTransitioning = true;
            DashboardState.viewMode = mode;
            
            // UI Toggle
            document.getElementById('pill-2d').classList.toggle('active', mode === '2d');
            document.getElementById('pill-3d').classList.toggle('active', mode === '3d');
            document.getElementById('pill-bg').style.transform = mode === '3d' ? 'translateX(72px)' : 'translateX(0)';
            document.getElementById('pill-bg').style.width = mode === '3d' ? '120px' : '74px';
            
            const v2d = document.getElementById('view-2d-map');
            const overlay = document.getElementById('dive-overlay');
            const v3d = document.getElementById('view-3d-underwater');

            if (mode === '3d') {
                let targetMapPos = ZONES.find(z => z.id === DashboardState.selectedZone)?.mapPos || {x:50, y:50};
                
                v2d.style.transformOrigin = `${targetMapPos.x}% ${targetMapPos.y}%`;
                v2d.style.transform = 'scale(5)';
                overlay.classList.add('diving');
                
                setTimeout(() => {
                    v2d.style.display = 'none';
                    init3D();
                    v3d.classList.add('active');
                    setTimeout(() => {
                        overlay.classList.remove('diving');
                        DashboardState.isTransitioning = false;
                    }, 800);
                }, 800);
                
            } else {
                overlay.classList.add('diving');
                
                setTimeout(() => {
                    v3d.classList.remove('active');
                    dispose3D();
                    
                    v2d.style.display = 'block';
                    v2d.style.transform = 'scale(1.5)';
                    
                    setTimeout(() => {
                        v2d.style.transform = 'scale(1)';
                        overlay.classList.remove('diving');
                        DashboardState.isTransitioning = false;
                    }, 50);
                }, 800);
            }
        };

        // ── 3D RENDERER LOGIC ────────────────────────────────
        const container3d = document.getElementById('view-3d-underwater');
        let scene, camera, renderer, clock, oceanParticles, oceanMat;
        let autoRotate = true, theta = 0.05, phi = 1.08, radius = 2.9, drag = false, prevMouse;

        window.setMode = (btn, mode) => {
            const modeMap = { heat: 0, kelp: 1, urchin: 2, salinity: 3 };
            document.querySelectorAll('.ctrl-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            if (oceanMat) oceanMat.uniforms.uMode.value = modeMap[mode] || 0;
        };

        function init3D() {
            if (renderer) return;

            scene = new THREE.Scene();
            scene.background = new THREE.Color(0x083d5c);
            scene.fog = new THREE.FogExp2(0x0a4f6e, 0.085);

            camera = new THREE.PerspectiveCamera(52, container3d.clientWidth / container3d.clientHeight, 0.01, 50);
            camera.position.set(0, 1.5, 2.9);
            camera.lookAt(0, -0.15, 0);

            renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
            renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
            renderer.setSize(container3d.clientWidth, container3d.clientHeight);
            container3d.appendChild(renderer.domElement);
            
            renderer.domElement.addEventListener('mousedown', e => { drag = true; autoRotate = false; prevMouse = { x: e.clientX, y: e.clientY }; });
            renderer.domElement.addEventListener('mouseup', () => { drag = false; });
            renderer.domElement.addEventListener('mousemove', e => {
                if (!drag) return;
                theta -= (e.clientX - prevMouse.x) * 0.005;
                phi -= (e.clientY - prevMouse.y) * 0.005;
                phi = Math.max(0.28, Math.min(1.52, phi));
                prevMouse = { x: e.clientX, y: e.clientY };
            });

            const oceanVert = `
              attribute float aAnomaly; attribute float aTemp; attribute float aSal;
              uniform float uTime; uniform float uTemperature; uniform int uMode;
              varying float vAnomaly; varying float vTemp; varying float vSal;
              void main() { vAnomaly = aAnomaly; vTemp = aTemp; vSal = aSal; gl_PointSize = 3.2; 
              gl_Position = projectionMatrix * modelViewMatrix * vec4(position + vec3(0, sin(position.x*4.2+uTime*0.75)*0.035, 0), 1.0); }
            `;
            const oceanFrag = `
              varying float vAnomaly; uniform float uTime; uniform float uAlert; uniform int uMode;
              void main() { 
                  if (dot(gl_PointCoord-0.5, gl_PointCoord-0.5) > 0.25) discard;
                  vec3 col;
                  if (uMode == 0) col = mix(vec3(0.0,0.5,0.7), vec3(1.0,0.0,0.0), clamp(vAnomaly*0.5+0.5, 0.0, 1.0));
                  else if (uMode == 1) col = vec3(0.0, 0.8, 0.3);
                  else col = vec3(0.8, 0.1, 0.8);
                  if(uAlert > 0.5) col += vec3(abs(sin(uTime*3.0)),0,0);
                  gl_FragColor = vec4(col, 0.9); 
              }
            `;
            
            oceanMat = new THREE.ShaderMaterial({
                vertexShader: oceanVert, fragmentShader: oceanFrag,
                uniforms: { uTime: { value: 0 }, uTemperature: { value: 0.35 }, uAlert: { value: 0 }, uMode: { value: 0 } },
                transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
            });

            // Fetch Logic
            const targetJson = `${DashboardState.selectedZone}_v2.json`;
            fetch(targetJson)
                .then(r => { if(!r.ok) throw new Error('Not found'); return r.json(); })
                .catch(() => fetch('./splats.json').then(r => r.json()))
                .then(buildOceanFromArray)
                .catch(() => {
                    const N=3000, arr=[];
                    for(let i=0; i<N; i++) arr.push({x:(Math.random()-0.5)*1.4, y:(Math.random()-0.5)*1.4, z:-Math.random(), anomaly:(Math.random()-0.5)*2});
                    buildOceanFromArray(arr);
                });

            const annotationsEl = document.getElementById('annotations');
            annotationsEl.innerHTML = '';
            ZONES.forEach((zone) => {
                const disc = new THREE.Mesh(new THREE.CircleGeometry(0.022, 32), new THREE.MeshBasicMaterial({ color: zone.threeColor, transparent: true, opacity: 0.95 }));
                disc.rotation.x = -Math.PI / 2; disc.position.set(zone.pos.x, -0.99, zone.pos.z);
                scene.add(disc);
                
                const div = document.createElement('div');
                div.className = 'zone-annotation'; div.id = `ann-3d-${zone.id}`;
                div.innerHTML = `
                    <div class="ann-bubble">
                      <div class="ann-name">${zone.name}</div>
                      <div class="ann-info">Average: <span class="ann-val">${zone.temp}°C</span></div>
                      <div class="ann-info">Kelp Health: <span class="ann-val" style="color: #4DA8DA;">${zone.health}%</span></div>
                    </div>
                `;
                annotationsEl.appendChild(div);
            });

            clock = new THREE.Clock();
            renderer.setAnimationLoop(() => {
                if(!renderer) return;
                const t = clock.getElapsedTime();
                if (autoRotate) theta += 0.0018;
                camera.position.x = radius * Math.sin(phi) * Math.sin(theta);
                camera.position.y = radius * Math.cos(phi);
                camera.position.z = radius * Math.sin(phi) * Math.cos(theta);
                camera.lookAt(0, -0.2, 0);

                if (oceanMat) oceanMat.uniforms.uTime.value = t;

                ZONES.forEach(zone => {
                    const p3 = zone.pos.clone(); p3.y += 0.04;
                    const proj = p3.project(camera);
                    const el = document.getElementById(`ann-3d-${zone.id}`);
                    if (el) {
                        if (proj.z < 1) { 
                            el.style.left = (proj.x * 0.5 + 0.5) * container3d.clientWidth + 'px'; 
                            el.style.top = (-proj.y * 0.5 + 0.5) * container3d.clientHeight + 'px'; 
                            el.style.opacity = '1'; 
                        } else el.style.opacity = '0';
                    }
                });

                renderer.render(scene, camera);
            });
        }
        
        function buildOceanFromArray(pts) {
            const N = Math.min(pts.length, 6000);
            const pos = new Float32Array(N * 3), anom = new Float32Array(N);
            for(let i=0; i<N; i++) {
                pos[i*3] = (pts[i].x || 0)*1.4; pos[i*3+1] = pts[i].z || 0; pos[i*3+2] = (pts[i].y || 0)*1.4;
                anom[i] = pts[i].anomaly || 0;
            }
            const geo = new THREE.BufferGeometry();
            geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
            geo.setAttribute('aAnomaly', new THREE.BufferAttribute(anom, 1));
            oceanParticles = new THREE.Points(geo, oceanMat);
            scene.add(oceanParticles);
        }

        function dispose3D() {
            if (!renderer) return;
            renderer.setAnimationLoop(null);
            renderer.domElement.remove();
            renderer.dispose();
            renderer = null; scene = null; camera = null; oceanParticles = null; oceanMat = null;
        }

        // ── SYNC SIDEBAR ─────────────────────────────────────
        function renderZoneList() {
            const zoneListEl = document.getElementById('zone-list');
            zoneListEl.innerHTML = '';
            ZONES.forEach(zone => {
                const isActive = zone.id === DashboardState.selectedZone;
                const isNominal = zone.health > 50;
                const dotColor = isActive ? '#fff' : (isNominal ? '#4DA8DA' : '#8B9AB0');
                
                const card = document.createElement('div');
                card.className = `zone-list-item`;
                card.style.cursor = 'pointer';
                if(isActive) card.style.background = 'rgba(77, 168, 218, 0.15)';
                card.onclick = () => selectZone(zone.id);

                card.innerHTML = `
                    <div class="zone-list-left" style="${isActive ? 'color:#fff; font-weight:600;' : ''}">
                        <div class="zone-dot" style="background: ${dotColor};"></div>
                        <span class="zone-name">${zone.name}</span>
                    </div>
                    <div class="zone-status-pill">${isNominal ? 'Normal' : 'Alert'}</div>
                `;
                zoneListEl.appendChild(card);
            });
        }

        // ── INIT ─────────────────────────────────────────────
        render2DMap();
        renderZoneList();
    </script>
'''

html_mod = re.sub(r'<div id="topbar">.*?<div id="topbar-right">', topbar_replacement, html, flags=re.DOTALL)
html_mod = re.sub(r'<!-- CENTER MAP / 3D SCENE -->.*?<!-- Hidden DOM Elements needed by existing JS -->', canvas_replacement, html_mod, flags=re.DOTALL)
html_mod = re.sub(r'<style>.*?</style>', f'<style>{new_css}</style>', html_mod, flags=re.DOTALL)
html_mod = re.sub(r'<script type="module">.*?</script>', js_new, html_mod, flags=re.DOTALL)

with open('/Users/roycel/Downloads/UCSD/VS Code Stuff/404 Fish Now Found/datahacks/frontend/index.html', 'w', encoding='utf-8') as f:
    f.write(html_mod)

