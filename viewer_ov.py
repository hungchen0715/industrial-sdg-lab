"""
Omniverse-style premium Three.js 3D viewport — V2.
Closely matches NVIDIA Omniverse USD Composer visual style.

Key features matching the Omniverse reference:
- CSS2DRenderer for 3D labels floating on objects
- ViewCube in top-right corner
- Left toolbar (Select/Translate/Rotate/Scale)
- Omniverse menu bar (File/Edit/View/Assets)
- Transform panel (X/Y/Z in mm)
- Gradient background (dark navy)
- Bright isometric lighting
- Bottom toolbar (View Cube/Grid/Measure/Shading)
- Scene hierarchy with expandable tree
"""
import json
import re
import threading
import http.server
import socketserver
from pathlib import Path

from usd_writer import parse_usda, find_prims_by_name, find_prims_by_type, get_attribute

OV_VIEWER_PORT = 7864

CELL_COLORS = {
    "LG_E63":   "#4CAF50",
    "HY_50Ah":  "#2196F3",
    "CATL_LFP": "#FF9800",
}
DEFAULT_COLOR = "#9E9E9E"


def _parse_float3(value: str):
    m = re.search(r'\((-?\d+\.?\d*),\s*(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\)', value)
    if m:
        return float(m.group(1)), float(m.group(2)), float(m.group(3))
    return 0, 0, 0


def _extract_objects(usda_path: str) -> list[dict]:
    scene = parse_usda(usda_path)
    objects = []
    # Track counts per type for G1,G2.../B1/O1 labels
    type_counters = {"LG_E63": 0, "HY_50Ah": 0, "CATL_LFP": 0}
    type_prefix = {"LG_E63": "G", "HY_50Ah": "B", "CATL_LFP": "O"}
    cells = find_prims_by_name(scene, r"Cell_\d+")
    for cell in cells:
        pos_attr = get_attribute(cell, "xformOp:translate")
        scale_attr = get_attribute(cell, "xformOp:scale")
        type_attr = get_attribute(cell, "battery:cellType")
        if not (pos_attr and scale_attr):
            continue
        px, py, pz = _parse_float3(pos_attr.value)
        sx, sy, sz = _parse_float3(scale_attr.value)
        cell_type = type_attr.value.strip('"') if type_attr else "unknown"
        type_counters[cell_type] = type_counters.get(cell_type, 0) + 1
        prefix = type_prefix.get(cell_type, "C")
        short = f"{prefix}{type_counters[cell_type]}"
        objects.append({
            "type": "cell", "name": cell.name, "label": short,
            "cellType": cell_type,
            "position": [px, pz, -py], "scale": [sx * 2, sz * 2, sy * 2],
            "color": CELL_COLORS.get(cell_type, DEFAULT_COLOR),
        })

    trays = find_prims_by_name(scene, r"ModuleTray")
    for tray in trays:
        pos_attr = get_attribute(tray, "xformOp:translate")
        scale_attr = get_attribute(tray, "xformOp:scale")
        if pos_attr and scale_attr:
            px, py, pz = _parse_float3(pos_attr.value)
            sx, sy, sz = _parse_float3(scale_attr.value)
            objects.append({
                "type": "tray", "name": "ModuleTray", "label": "2x3 Battery\\nTray",
                "position": [px, pz, -py], "scale": [sx * 2, sz * 2, sy * 2],
                "color": "#B0BEC5",
            })

    robots = find_prims_by_name(scene, r"RobotArm_.*")
    for robot in robots:
        pos_attr = get_attribute(robot, "xformOp:translate")
        if pos_attr:
            px, py, pz = _parse_float3(pos_attr.value)
            reach_attr = get_attribute(robot, "robot:maxReach")
            reach = float(reach_attr.value) if reach_attr else 1.0
            objects.append({
                "type": "robot", "name": robot.name,
                "label": "KUKA\\nKR 10 R1100",
                "position": [px, pz, -py], "reach": reach, "color": "#D32F2F",
            })

    cameras = find_prims_by_type(scene, "Camera")
    for cam in cameras:
        pos_attr = get_attribute(cam, "xformOp:translate")
        if pos_attr:
            px, py, pz = _parse_float3(pos_attr.value)
            objects.append({
                "type": "camera", "name": cam.name, "label": "Cam",
                "position": [px, pz, -py], "color": "#7B1FA2",
            })

    return objects


def generate_ov_viewer_html(usda_path: str) -> str:
    objects = _extract_objects(usda_path)
    objects_json = json.dumps(objects)
    num_cells = sum(1 for o in objects if o["type"] == "cell")
    green_cells = sum(1 for o in objects if o.get("cellType") == "LG_E63")
    blue_cells = sum(1 for o in objects if o.get("cellType") == "HY_50Ah")
    orange_cells = sum(1 for o in objects if o.get("cellType") == "CATL_LFP")

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Omniverse-Style Viewport</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #1a1d23; overflow: hidden; font-family: 'Segoe UI', sans-serif; color: #d0d0d0; }}
  canvas {{ display: block; }}

  /* ── Omniverse top menu bar ── */
  #menu-bar {{
    position: fixed; top: 0; left: 0; right: 0; height: 28px;
    background: #2b2d30; border-bottom: 1px solid #3c3e42;
    display: flex; align-items: center; padding: 0 8px; z-index: 200;
  }}
  .ov-logo {{
    width: 22px; height: 22px; background: linear-gradient(135deg, #76b900, #4a7a00);
    border-radius: 4px; display: flex; align-items: center; justify-content: center;
    margin-right: 10px; font-weight: 800; font-size: 10px; color: #fff;
  }}
  .menu-item {{
    padding: 4px 10px; font-size: 12px; color: #aaa; cursor: pointer;
  }}
  .menu-item:hover {{ color: #fff; background: #3c3e42; border-radius: 3px; }}

  /* ── Title bar under menu ── */
  #title-bar {{
    position: fixed; top: 28px; left: 40px; right: 260px; height: 26px;
    background: #25272b; border-bottom: 1px solid #3c3e42;
    display: flex; align-items: center; padding: 0 10px; z-index: 190;
    font-size: 11px; color: #888; gap: 10px;
  }}
  .title-scene {{ color: #76b900; font-weight: 600; }}
  .title-stat {{ color: #666; font-size: 10px; }}

  /* ── Left toolbar ── */
  #left-toolbar {{
    position: fixed; top: 54px; left: 0; width: 40px; bottom: 32px;
    background: #2b2d30; border-right: 1px solid #3c3e42;
    display: flex; flex-direction: column; align-items: center;
    padding: 8px 0; gap: 2px; z-index: 190;
  }}
  .tool-btn {{
    width: 32px; height: 32px; display: flex; align-items: center; justify-content: center;
    border-radius: 4px; cursor: pointer; font-size: 14px; color: #888;
    border: 1px solid transparent;
  }}
  .tool-btn:hover {{ background: #3c3e42; color: #ccc; }}
  .tool-btn.active {{ background: #3a5a1a; color: #76b900; border-color: #76b900; }}
  .tool-sep {{ width: 24px; height: 1px; background: #3c3e42; margin: 4px 0; }}

  /* ── Right panel ── */
  #right-panel {{
    position: fixed; top: 28px; right: 0; width: 260px; bottom: 32px;
    background: #25272b; border-left: 1px solid #3c3e42;
    z-index: 190; font-size: 11px; overflow-y: auto;
  }}
  .panel-header {{
    background: #2b2d30; padding: 5px 10px; font-size: 11px;
    color: #76b900; font-weight: 600; border-bottom: 1px solid #3c3e42;
    text-transform: uppercase; letter-spacing: 0.8px;
  }}
  .tree-item {{
    padding: 3px 8px 3px 16px; cursor: pointer; display: flex;
    align-items: center; gap: 6px; border-left: 2px solid transparent;
    font-size: 11px;
  }}
  .tree-item:hover {{ background: #2e3035; }}
  .tree-item.selected {{ background: #2a3520; border-left-color: #76b900; }}
  .tree-dot {{ width: 8px; height: 8px; border-radius: 2px; flex-shrink: 0; }}
  .tree-expand {{ color: #666; font-size: 8px; margin-right: 2px; }}

  .prop-section {{ padding: 8px 10px; border-bottom: 1px solid #333; }}
  .prop-title {{ color: #76b900; font-weight: 600; margin-bottom: 6px; text-transform: uppercase; font-size: 10px; letter-spacing: 0.5px; }}
  .prop-row {{ display: flex; justify-content: space-between; margin: 3px 0; align-items: center; }}
  .prop-label {{ color: #888; font-size: 11px; }}
  .prop-val {{ color: #d0d0d0; font-family: 'Consolas', monospace; font-size: 11px; }}
  .prop-val.x {{ color: #e74c3c; }}
  .prop-val.y {{ color: #76b900; }}
  .prop-val.z {{ color: #3498db; }}

  /* ── Bottom toolbar ── */
  #bottom-bar {{
    position: fixed; bottom: 0; left: 0; right: 0; height: 32px;
    background: #2b2d30; border-top: 1px solid #3c3e42;
    display: flex; align-items: center; padding: 0 8px; gap: 4px; z-index: 200;
  }}
  .bottom-btn {{
    padding: 4px 10px; font-size: 11px; color: #888; cursor: pointer;
    border-radius: 3px; display: flex; align-items: center; gap: 5px;
  }}
  .bottom-btn:hover {{ background: #3c3e42; color: #ccc; }}
  .bottom-btn.active {{ color: #76b900; }}
  .bottom-sep {{ width: 1px; height: 18px; background: #3c3e42; margin: 0 4px; }}

  /* ── Viewport nav (Orbit/Pan/Zoom) ── */
  #nav-controls {{
    position: fixed; right: 268px; top: 60px;
    display: flex; flex-direction: column; gap: 3px; z-index: 180;
    font-size: 10px; color: #888;
  }}
  .nav-row {{ display: flex; align-items: center; gap: 6px; justify-content: flex-end; }}
  .nav-circle {{ width: 16px; height: 16px; border-radius: 50%; border: 1px solid #555; display: flex; align-items: center; justify-content: center; font-size: 8px; }}
  .nav-circle.active {{ border-color: #76b900; color: #76b900; }}

  /* ── 3D Label overlay (CSS2D style) ── */
  .label-3d {{
    position: absolute; pointer-events: none;
    color: #fff; font-size: 10px; font-weight: 600;
    text-shadow: 0 0 4px rgba(0,0,0,0.8), 0 1px 2px rgba(0,0,0,0.9);
    white-space: pre; text-align: center; line-height: 1.3;
    transform: translate(-50%, -50%);
  }}
  .label-3d.desc {{
    font-size: 9px; font-weight: 400; color: #aaa;
    font-style: italic;
  }}
  .label-3d.dim {{
    font-size: 9px; font-weight: 400; color: #ff6666;
    font-style: italic;
  }}

  /* ── Viewport perspective label ── */
  #vp-perspective {{
    position: fixed; top: 58px; left: 48px;
    color: #555; font-size: 9px; text-transform: uppercase;
    letter-spacing: 1.5px; z-index: 180;
  }}

  /* ── View Cube ── */
  #view-cube {{
    position: fixed; top: 60px; right: 270px; width: 60px; height: 60px;
    z-index: 180;
  }}

  /* ── Axes indicator ── */
  #axes-indicator {{
    position: fixed; bottom: 40px; left: 48px;
    z-index: 180;
  }}

  /* Tooltip */
  #tooltip {{
    position: fixed; display: none;
    background: rgba(30,30,30,0.95); color: #e0e0e0;
    padding: 6px 10px; border-radius: 3px;
    font-size: 11px; pointer-events: none; z-index: 300;
    border: 1px solid #76b900; box-shadow: 0 4px 12px rgba(0,0,0,0.6);
  }}
</style>
</head>
<body>

<!-- Menu Bar -->
<div id="menu-bar">
  <div class="ov-logo">⬡</div>
  <span class="menu-item">File</span>
  <span class="menu-item">Edit</span>
  <span class="menu-item">View</span>
  <span class="menu-item">Assets</span>
</div>

<!-- Title Bar -->
<div id="title-bar">
  <span class="title-scene">BATTERY ASSEMBLY_VIEW (Isometric)</span>
  <span>|</span>
  <span class="title-stat">3D V0.84</span>
</div>

<!-- Left Toolbar -->
<div id="left-toolbar">
  <div class="tool-btn active" title="Select">🔍</div>
  <div class="tool-btn" title="Translate">↔</div>
  <div class="tool-btn" title="Rotate">⟳</div>
  <div class="tool-btn" title="Scale">⤡</div>
  <div class="tool-sep"></div>
  <div class="tool-btn" title="Rebake">♻</div>
</div>

<div id="vp-perspective">PERSPECTIVE</div>

<!-- Nav Controls -->
<div id="nav-controls">
  <div class="nav-row"><span>Orbit</span> <div class="nav-circle active">⟳</div></div>
  <div class="nav-row"><span>Pan</span> <div class="nav-circle">✥</div></div>
  <div class="nav-row"><span>Zoom</span> <div class="nav-circle">⊕</div></div>
</div>

<!-- Right Panel -->
<div id="right-panel">
  <div class="panel-header">Scene Hierarchy</div>
  <div id="scene-tree">
    <div class="tree-item"><span class="tree-expand">▼</span> 📁 All</div>
    <div class="tree-item" style="padding-left:28px"><span class="tree-expand">▼</span> 📁 Assets</div>
    <div class="tree-item" style="padding-left:40px"><span class="tree-expand">▼</span> 🔋 Battery...</div>
  </div>
  <div id="scene-items"></div>

  <div class="panel-header" style="margin-top:4px">Properties</div>
  <div id="prop-detail">
    <div class="prop-section" style="text-align:center;color:#555;padding:20px">
      Click an object to inspect
    </div>
  </div>

  <div class="panel-header">Transform</div>
  <div id="transform-panel">
    <div class="prop-section">
      <div class="prop-row"><span class="prop-label">X</span><span class="prop-val x" id="tx">0.000</span><span class="prop-label">mm</span></div>
      <div class="prop-row"><span class="prop-label">Y</span><span class="prop-val y" id="ty">0.000</span><span class="prop-label">mm</span></div>
      <div class="prop-row"><span class="prop-label">Z</span><span class="prop-val z" id="tz">0.000</span><span class="prop-label">mm</span></div>
    </div>
  </div>
</div>

<!-- Bottom Bar -->
<div id="bottom-bar">
  <span class="bottom-btn">⚙</span>
  <span class="bottom-sep"></span>
  <span class="bottom-btn active">🧊 View Cube</span>
  <span class="bottom-btn active">⊞ Grid</span>
  <span class="bottom-btn">📏 Measure</span>
  <span class="bottom-btn active">🎨 Shading</span>
  <span style="flex:1"></span>
  <span class="bottom-btn" id="fps-display" style="color:#76b900">-- FPS</span>
</div>

<!-- Axes Indicator -->
<svg id="axes-indicator" width="40" height="40" viewBox="0 0 40 40">
  <line x1="20" y1="20" x2="38" y2="20" stroke="#e74c3c" stroke-width="2"/>
  <text x="38" y="16" fill="#e74c3c" font-size="9" font-weight="bold">X</text>
  <line x1="20" y1="20" x2="20" y2="2" stroke="#76b900" stroke-width="2"/>
  <text x="14" y="8" fill="#76b900" font-size="9" font-weight="bold">Y</text>
  <line x1="20" y1="20" x2="8" y2="32" stroke="#3498db" stroke-width="2"/>
  <text x="2" y="36" fill="#3498db" font-size="9" font-weight="bold">Z</text>
</svg>

<div id="tooltip"></div>
<div id="labels-container" style="position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:150;overflow:hidden;"></div>

<!-- View Cube (mini) -->
<canvas id="view-cube" width="60" height="60"></canvas>

<script type="importmap">
{{
  "imports": {{
    "three": "https://cdn.jsdelivr.net/npm/three@0.164.0/build/three.module.js",
    "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.164.0/examples/jsm/"
  }}
}}
</script>

<script type="module">
import * as THREE from 'three';
import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';
import {{ EffectComposer }} from 'three/addons/postprocessing/EffectComposer.js';
import {{ RenderPass }} from 'three/addons/postprocessing/RenderPass.js';
import {{ UnrealBloomPass }} from 'three/addons/postprocessing/UnrealBloomPass.js';
import {{ RoundedBoxGeometry }} from 'three/addons/geometries/RoundedBoxGeometry.js';

// ── Scene ──
const scene = new THREE.Scene();
// Gradient background like Omniverse
const bgCanvas = document.createElement('canvas');
bgCanvas.width = 2; bgCanvas.height = 512;
const bgCtx = bgCanvas.getContext('2d');
const grad = bgCtx.createLinearGradient(0, 0, 0, 512);
grad.addColorStop(0, '#1a2035');
grad.addColorStop(0.5, '#1a1d25');
grad.addColorStop(1, '#141820');
bgCtx.fillStyle = grad;
bgCtx.fillRect(0, 0, 2, 512);
const bgTexture = new THREE.CanvasTexture(bgCanvas);
scene.background = bgTexture;

// ── Camera - Isometric-ish ──
const vpW = window.innerWidth - 300;
const vpH = window.innerHeight - 60;
const camera = new THREE.PerspectiveCamera(35, vpW / vpH, 0.01, 100);
camera.position.set(1.0, 0.9, 1.2);

// ── Renderer ──
const renderer = new THREE.WebGLRenderer({{ antialias: true, powerPreference: 'high-performance' }});
renderer.setSize(vpW, vpH);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 2.0;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.domElement.style.position = 'fixed';
renderer.domElement.style.top = '54px';
renderer.domElement.style.left = '40px';
document.body.appendChild(renderer.domElement);

// ── Post-processing ──
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(vpW, vpH), 0.15, 0.3, 0.9);
composer.addPass(bloom);

// ── Controls ──
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0.08, 0);
controls.enableDamping = true;
controls.dampingFactor = 0.06;
controls.autoRotate = false;
controls.maxPolarAngle = Math.PI / 2.05;
controls.update();

// ── Bright Omniverse-style lighting ──
scene.add(new THREE.AmbientLight(0x404060, 1.0));
const hemi = new THREE.HemisphereLight(0xfff8f0, 0x302820, 0.8);
scene.add(hemi);

const key = new THREE.DirectionalLight(0xfff5e0, 3.0);
key.position.set(3, 5, 4);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
key.shadow.camera.left = -3; key.shadow.camera.right = 3;
key.shadow.camera.top = 3; key.shadow.camera.bottom = -3;
key.shadow.bias = -0.0003;
key.shadow.normalBias = 0.02;
scene.add(key);

const fill = new THREE.DirectionalLight(0xc8d8ff, 1.0);
fill.position.set(-3, 3, -2);
scene.add(fill);

const back = new THREE.DirectionalLight(0xffe0c0, 0.6);
back.position.set(0, 2, -4);
scene.add(back);

const accent = new THREE.PointLight(0x76b900, 0.3, 5);
accent.position.set(0, 1, 0);
scene.add(accent);

// ── Ground ──
const groundMat = new THREE.MeshStandardMaterial({{ color: 0x252830, roughness: 0.85 }});
const ground = new THREE.Mesh(new THREE.PlaneGeometry(10, 10), groundMat);
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);

// Subtle grid
const grid = new THREE.GridHelper(4, 40, 0x353840, 0x2a2d32);
grid.position.y = 0.001;
scene.add(grid);

// ── Scene Data ──
const objects = {objects_json};
const interactables = [];
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();
const labelData = []; // {{element, mesh}} for 3D labels
const labelsContainer = document.getElementById('labels-container');

// ── Build Scene Tree ──
const sceneItems = document.getElementById('scene-items');
objects.forEach((obj, i) => {{
  const dot = obj.type === 'cell' ? obj.color : obj.type === 'robot' ? '#D32F2F' : obj.type === 'camera' ? '#7B1FA2' : '#B0BEC5';
  const icon = obj.type === 'cell' ? '🔋' : obj.type === 'robot' ? '🤖' : obj.type === 'camera' ? '📷' : '📐';
  sceneItems.innerHTML += `<div class="tree-item" style="padding-left:52px" data-idx="${{i}}" onclick="window.selectObj(${{i}})">
    <div class="tree-dot" style="background:${{dot}}"></div>
    <span>${{icon}} ${{obj.name}}</span>
  </div>`;
}});

function createLabel(text, className = '') {{
  const el = document.createElement('div');
  el.className = 'label-3d ' + className;
  el.textContent = text;
  labelsContainer.appendChild(el);
  return el;
}}

// ── Create Objects ──
const cellObjs = objects.filter(o => o.type === 'cell');
objects.forEach((obj, idx) => {{
  if (obj.type === 'cell') {{
    const geo = new RoundedBoxGeometry(obj.scale[0], obj.scale[1], obj.scale[2], 3, 0.004);
    const mat = new THREE.MeshPhysicalMaterial({{
      color: obj.color, roughness: 0.25, metalness: 0.12,
      clearcoat: 0.4, clearcoatRoughness: 0.15,
    }});
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(...obj.position);
    mesh.castShadow = true; mesh.receiveShadow = true;
    mesh.userData = {{ idx, ...obj }};
    scene.add(mesh); interactables.push(mesh);

    // Cell label on top
    const label = createLabel(obj.label);
    labelData.push({{ el: label, pos: new THREE.Vector3(obj.position[0], obj.position[1] + obj.scale[1]/2 + 0.025, obj.position[2]) }});

    // Cell ID printed on front face using canvas texture
    const idCanvas = document.createElement('canvas');
    idCanvas.width = 64; idCanvas.height = 64;
    const ctx = idCanvas.getContext('2d');
    ctx.fillStyle = 'rgba(0,0,0,0.3)';
    ctx.fillRect(0, 0, 64, 64);
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 32px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(obj.label, 32, 32);
    const idTexture = new THREE.CanvasTexture(idCanvas);
    const idMat = new THREE.MeshBasicMaterial({{ map: idTexture, transparent: true }});
    const idPlane = new THREE.Mesh(new THREE.PlaneGeometry(obj.scale[0]*0.8, obj.scale[1]*0.35), idMat);
    idPlane.position.set(obj.position[0], obj.position[1], obj.position[2] + obj.scale[2]/2 + 0.001);
    scene.add(idPlane);

    // Edges
    const edges = new THREE.EdgesGeometry(geo, 20);
    const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({{ color: 0xffffff, opacity: 0.06, transparent: true }}));
    line.position.copy(mesh.position);
    scene.add(line);

    // Terminal connectors on top (larger copper tabs)
    const tabW = obj.scale[0] * 0.35;
    const tabD = obj.scale[2] * 0.20;
    const tabH = 0.008;
    const tabGeo = new THREE.BoxGeometry(tabW, tabH, tabD);
    const topY = obj.position[1] + obj.scale[1]/2 + tabH/2;

    // Positive terminal (copper/red)
    const posTab = new THREE.Mesh(tabGeo, new THREE.MeshPhysicalMaterial({{ color: 0xcc4444, roughness: 0.3, metalness: 0.8 }}));
    posTab.position.set(obj.position[0] + obj.scale[0]*0.25, topY, obj.position[2]);
    posTab.castShadow = true; scene.add(posTab);

    // Negative terminal (dark)
    const negTab = new THREE.Mesh(tabGeo, new THREE.MeshPhysicalMaterial({{ color: 0x333333, roughness: 0.3, metalness: 0.8 }}));
    negTab.position.set(obj.position[0] - obj.scale[0]*0.25, topY, obj.position[2]);
    negTab.castShadow = true; scene.add(negTab);

  }} else if (obj.type === 'tray') {{
    // Main tray body
    const geo = new RoundedBoxGeometry(obj.scale[0], obj.scale[1], obj.scale[2], 2, 0.004);
    const mat = new THREE.MeshPhysicalMaterial({{
      color: 0x8a9196, roughness: 0.35, metalness: 0.15,
      clearcoat: 0.2,
    }});
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(...obj.position);
    mesh.receiveShadow = true;
    mesh.userData = {{ idx, ...obj }};
    scene.add(mesh); interactables.push(mesh);

    // Raised tray lip/border (4 walls)
    const lipH = 0.04;
    const lipT = 0.008;
    const lipMat = new THREE.MeshPhysicalMaterial({{ color: 0x6d7276, roughness: 0.4, metalness: 0.2 }});
    const hw = obj.scale[0]/2;
    const hd = obj.scale[2]/2;
    const lipY = lipH/2;

    // Front wall
    const fw = new THREE.Mesh(new THREE.BoxGeometry(obj.scale[0], lipH, lipT), lipMat);
    fw.position.set(obj.position[0], lipY, obj.position[2] + hd); scene.add(fw);
    // Back wall
    const bw = new THREE.Mesh(new THREE.BoxGeometry(obj.scale[0], lipH, lipT), lipMat);
    bw.position.set(obj.position[0], lipY, obj.position[2] - hd); scene.add(bw);
    // Left wall
    const lw = new THREE.Mesh(new THREE.BoxGeometry(lipT, lipH, obj.scale[2]), lipMat);
    lw.position.set(obj.position[0] - hw, lipY, obj.position[2]); scene.add(lw);
    // Right wall
    const rw = new THREE.Mesh(new THREE.BoxGeometry(lipT, lipH, obj.scale[2]), lipMat);
    rw.position.set(obj.position[0] + hw, lipY, obj.position[2]); scene.add(rw);

    // Divider walls between cell columns (based on cell positions)
    const divMat = new THREE.MeshPhysicalMaterial({{ color: 0x7a7e82, roughness: 0.5, metalness: 0.1 }});
    const cellPositionsX = [...new Set(cellObjs.map(c => c.position[0]))].sort((a,b) => a-b);
    for (let i = 0; i < cellPositionsX.length - 1; i++) {{
      const midX = (cellPositionsX[i] + cellPositionsX[i+1]) / 2;
      const divider = new THREE.Mesh(new THREE.BoxGeometry(0.005, lipH * 0.8, obj.scale[2] * 0.9), divMat);
      divider.position.set(midX, lipH * 0.4, obj.position[2]);
      scene.add(divider);
    }}
    // Divider wall between rows
    const cellPositionsZ = [...new Set(cellObjs.map(c => c.position[2]))].sort((a,b) => a-b);
    if (cellPositionsZ.length > 1) {{
      const midZ = (cellPositionsZ[0] + cellPositionsZ[cellPositionsZ.length-1]) / 2;
      const rowDiv = new THREE.Mesh(new THREE.BoxGeometry(obj.scale[0] * 0.9, lipH * 0.8, 0.005), divMat);
      rowDiv.position.set(obj.position[0], lipH * 0.4, midZ);
      scene.add(rowDiv);
    }}

    // Tray label
    const label = createLabel("2x3 Battery\\nTray", "desc");
    labelData.push({{ el: label, pos: new THREE.Vector3(obj.position[0]+0.35, obj.position[1]+0.02, obj.position[2]+0.25) }});

  }} else if (obj.type === 'robot') {{
    // ── Black square base pad ──
    const padMat = new THREE.MeshPhysicalMaterial({{ color: 0x222222, roughness: 0.6, metalness: 0.3 }});
    const pad = new THREE.Mesh(new THREE.BoxGeometry(0.30, 0.04, 0.30), padMat);
    pad.position.set(obj.position[0], 0.02, obj.position[2]);
    pad.castShadow = true; pad.receiveShadow = true;
    scene.add(pad);

    // ── Red cylinder (robot base) ──
    const baseMat = new THREE.MeshPhysicalMaterial({{ color: obj.color, roughness: 0.15, metalness: 0.7, clearcoat: 0.6 }});
    const base = new THREE.Mesh(new THREE.CylinderGeometry(0.10, 0.12, 0.30, 32), baseMat);
    base.position.set(obj.position[0], 0.19, obj.position[2]);
    base.castShadow = true;
    base.userData = {{ idx, ...obj }};
    scene.add(base); interactables.push(base);

    // ── Red Robot Base label ──
    const robotLabel = createLabel("Red Robot Base");
    labelData.push({{ el: robotLabel, pos: new THREE.Vector3(obj.position[0]-0.15, 0.40, obj.position[2]) }});
    const descLabel = createLabel("KUKA\\nKR 10 R1100", "desc");
    labelData.push({{ el: descLabel, pos: new THREE.Vector3(obj.position[0]-0.2, 0.15, obj.position[2]+0.15) }});

    // Reach ring (pulsing, filled semi-transparent)
    const ringFillGeo = new THREE.CircleGeometry(obj.reach, 128);
    const ringFillMat = new THREE.MeshBasicMaterial({{ color: 0xff3333, transparent: true, opacity: 0.04, side: THREE.DoubleSide }});
    const ringFill = new THREE.Mesh(ringFillGeo, ringFillMat);
    ringFill.rotation.x = -Math.PI / 2; ringFill.position.set(obj.position[0], 0.002, obj.position[2]);
    scene.add(ringFill);

    // Reach ring outline
    const ringGeo = new THREE.RingGeometry(obj.reach - 0.015, obj.reach, 128);
    const ringMat = new THREE.MeshBasicMaterial({{ color: 0xff3333, transparent: true, opacity: 0.15, side: THREE.DoubleSide }});
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.rotation.x = -Math.PI / 2; ring.position.set(obj.position[0], 0.003, obj.position[2]);
    ring.userData.pulse = true;
    scene.add(ring);

    // Reach label
    const reachLabel = createLabel((obj.reach * 1000).toFixed(0) + " mm", "dim");
    labelData.push({{ el: reachLabel, pos: new THREE.Vector3(obj.position[0]+obj.reach*0.5, 0.01, obj.position[2]+obj.reach*0.5) }});
    const envLabel = createLabel("Reach Envelope", "desc");
    labelData.push({{ el: envLabel, pos: new THREE.Vector3(obj.position[0], 0.01, obj.position[2]+obj.reach*0.8) }});

  }} else if (obj.type === 'camera') {{
    const camMat = new THREE.MeshPhysicalMaterial({{ color: obj.color, roughness: 0.2, metalness: 0.5, clearcoat: 0.5 }});
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.05, 0.09), camMat);
    body.position.set(...obj.position);
    body.castShadow = true;
    body.userData = {{ idx, ...obj }};
    scene.add(body); interactables.push(body);

    const lensMat = new THREE.MeshPhysicalMaterial({{ color: 0x1a237e, roughness: 0.05, metalness: 0.9, clearcoat: 1.0 }});
    const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.028, 0.05, 20), lensMat);
    lens.rotation.x = Math.PI / 2;
    lens.position.set(obj.position[0], obj.position[1]-0.045, obj.position[2]);
    scene.add(lens);

    // FOV cone
    const fCone = new THREE.Mesh(new THREE.ConeGeometry(0.15, 0.35, 4),
      new THREE.MeshBasicMaterial({{ color: 0x7B1FA2, transparent: true, opacity: 0.04, wireframe: true }}));
    fCone.position.set(obj.position[0], obj.position[1]-0.25, obj.position[2]);
    scene.add(fCone);
  }}
}});

// ── White base frame under cells ──
if (cellObjs.length) {{
  // Compute bounding box of all cells
  const minX = Math.min(...cellObjs.map(c => c.position[0] - c.scale[0]/2)) - 0.02;
  const maxX = Math.max(...cellObjs.map(c => c.position[0] + c.scale[0]/2)) + 0.02;
  const minZ = Math.min(...cellObjs.map(c => c.position[2] - c.scale[2]/2)) - 0.02;
  const maxZ = Math.max(...cellObjs.map(c => c.position[2] + c.scale[2]/2)) + 0.02;
  const bw = maxX - minX;
  const bd = maxZ - minZ;
  const bcx = (minX + maxX) / 2;
  const bcz = (minZ + maxZ) / 2;

  // White base platform
  const whiteMat = new THREE.MeshPhysicalMaterial({{ color: 0xeeeeee, roughness: 0.4, metalness: 0.05 }});
  const whitePlat = new THREE.Mesh(new RoundedBoxGeometry(bw, 0.015, bd, 2, 0.003), whiteMat);
  whitePlat.position.set(bcx, 0.008, bcz);
  whitePlat.receiveShadow = true;
  scene.add(whitePlat);

  // Side rails (left & right)
  const railMat = new THREE.MeshPhysicalMaterial({{ color: 0xdddddd, roughness: 0.35, metalness: 0.1 }});
  const railH = 0.04;
  const lRail = new THREE.Mesh(new THREE.BoxGeometry(0.008, railH, bd), railMat);
  lRail.position.set(minX - 0.004, railH/2, bcz);
  scene.add(lRail);
  const rRail = new THREE.Mesh(new THREE.BoxGeometry(0.008, railH, bd), railMat);
  rRail.position.set(maxX + 0.004, railH/2, bcz);
  scene.add(rRail);
}}

// ── Bus bars (wires between cell tops) ──
const wireMat = new THREE.MeshPhysicalMaterial({{ color: 0xcc6600, roughness: 0.4, metalness: 0.7 }});
for (let i = 0; i < cellObjs.length - 1; i++) {{
  const a = cellObjs[i], b = cellObjs[i+1];
  // Only connect cells in same row (similar Z)
  if (Math.abs(a.position[2] - b.position[2]) < 0.05) {{
    const midX = (a.position[0] + b.position[0]) / 2;
    const topY = a.position[1] + a.scale[1] / 2 + 0.005;
    const dist = Math.abs(a.position[0] - b.position[0]);
    const wire = new THREE.Mesh(new THREE.BoxGeometry(dist, 0.004, 0.015), wireMat);
    wire.position.set(midX, topY, a.position[2]);
    wire.castShadow = true;
    scene.add(wire);
  }}
}}

// ── Welding spots on cell tops ──
const weldMat = new THREE.MeshStandardMaterial({{ color: 0xaaaaaa, roughness: 0.2, metalness: 0.9 }});
const weldGeo = new THREE.CylinderGeometry(0.004, 0.004, 0.002, 8);
cellObjs.forEach(c => {{
  const topY = c.position[1] + c.scale[1] / 2 + 0.002;
  [-0.25, 0.25].forEach(xOff => {{
    const w = new THREE.Mesh(weldGeo, weldMat);
    w.position.set(c.position[0] + c.scale[0] * xOff, topY, c.position[2]);
    scene.add(w);
  }});
}});

// Description labels for cell types
const greenCells = objects.filter(o => o.cellType === 'LG_E63');
const blueCells = objects.filter(o => o.cellType === 'HY_50Ah');
const orangeCells = objects.filter(o => o.cellType === 'CATL_LFP');
if (greenCells.length) {{
  const gl = createLabel("Green Cells", "desc");
  const avgX = greenCells.reduce((s,c) => s+c.position[0], 0) / greenCells.length;
  const maxY = Math.max(...greenCells.map(c => c.position[1] + c.scale[1]));
  labelData.push({{ el: gl, pos: new THREE.Vector3(avgX, maxY + 0.06, greenCells[0].position[2]) }});
}}
if (blueCells.length) {{
  const bl = createLabel("Blue Cell", "desc");
  labelData.push({{ el: bl, pos: new THREE.Vector3(blueCells[0].position[0], blueCells[0].position[1]+blueCells[0].scale[1]+0.04, blueCells[0].position[2]) }});
}}
if (orangeCells.length) {{
  const ol = createLabel("Orange Cell", "desc");
  labelData.push({{ el: ol, pos: new THREE.Vector3(orangeCells[0].position[0]+0.12, orangeCells[0].position[1]+orangeCells[0].scale[1]+0.04, orangeCells[0].position[2]) }});
}}

// ── Selection ──
let selectedIdx = -1;
window.selectObj = function(idx) {{
  selectedIdx = idx;
  document.querySelectorAll('.tree-item[data-idx]').forEach(el => el.classList.remove('selected'));
  document.querySelector(`[data-idx="${{idx}}"]`)?.classList.add('selected');
  const obj = objects[idx];
  let html = '<div class="prop-section">';
  html += `<div class="prop-row"><span class="prop-label">Name</span><span class="prop-val" style="color:#76b900">${{obj.name}}</span></div>`;
  if (obj.cellType) html += `<div class="prop-row"><span class="prop-label">Cell Type</span><span class="prop-val">${{obj.cellType}}</span></div>`;
  html += `<div class="prop-row"><span class="prop-label">Material</span><span class="prop-val">Aluminum</span></div>`;
  html += '</div>';
  document.getElementById('prop-detail').innerHTML = html;

  // Update transform
  document.getElementById('tx').textContent = (obj.position[0] * 1000).toFixed(3);
  document.getElementById('ty').textContent = ((obj.position[1] || 0) * 1000).toFixed(3);
  document.getElementById('tz').textContent = (obj.position[2] * 1000).toFixed(3);

  // Highlight mesh
  interactables.forEach(m => {{ if (m.material.emissive) m.material.emissive.setHex(0x000000); }});
  const mesh = interactables.find(m => m.userData.idx === idx);
  if (mesh && mesh.material.emissive) mesh.material.emissive.setHex(0x1a2e0a);
}};

// ── Hover ──
const tooltip = document.getElementById('tooltip');
let hovered = null;
renderer.domElement.addEventListener('mousemove', (e) => {{
  mouse.x = (e.offsetX / renderer.domElement.clientWidth) * 2 - 1;
  mouse.y = -(e.offsetY / renderer.domElement.clientHeight) * 2 + 1;
  raycaster.setFromCamera(mouse, camera);
  const hits = raycaster.intersectObjects(interactables);
  if (hits.length > 0) {{
    const o = hits[0].object;
    if (hovered !== o) {{
      if (hovered?.material?.emissive && hovered.userData.idx !== selectedIdx) hovered.material.emissive.setHex(0x000000);
      hovered = o;
      if (hovered.material.emissive) hovered.material.emissive.setHex(0x151f0a);
    }}
    tooltip.style.display = 'block';
    tooltip.style.left = (e.clientX + 15) + 'px';
    tooltip.style.top = (e.clientY + 15) + 'px';
    const ud = o.userData;
    tooltip.innerHTML = ud.cellType ? `<b>${{ud.name}}</b> — ${{ud.cellType}}` : `<b>${{ud.name}}</b>`;
  }} else {{
    if (hovered?.material?.emissive && hovered.userData.idx !== selectedIdx) hovered.material.emissive.setHex(0x000000);
    hovered = null;
    tooltip.style.display = 'none';
  }}
}});

renderer.domElement.addEventListener('click', () => {{
  raycaster.setFromCamera(mouse, camera);
  const hits = raycaster.intersectObjects(interactables);
  if (hits.length > 0 && hits[0].object.userData.idx !== undefined) window.selectObj(hits[0].object.userData.idx);
}});

// ── Update 3D Labels ──
function updateLabels() {{
  labelData.forEach(ld => {{
    const projected = ld.pos.clone().project(camera);
    const x = (projected.x * 0.5 + 0.5) * vpW + 40;
    const y = (-projected.y * 0.5 + 0.5) * vpH + 54;
    const visible = projected.z < 1;
    ld.el.style.display = visible ? 'block' : 'none';
    ld.el.style.left = x + 'px';
    ld.el.style.top = y + 'px';
  }});
}}

// ── View Cube ──
const vcCanvas = document.getElementById('view-cube');
const vcCtx = vcCanvas.getContext('2d');
function drawViewCube() {{
  vcCtx.clearRect(0, 0, 60, 60);
  vcCtx.strokeStyle = '#555'; vcCtx.lineWidth = 1;
  vcCtx.strokeRect(10, 10, 40, 40);
  vcCtx.strokeStyle = '#666';
  vcCtx.beginPath(); vcCtx.moveTo(30, 10); vcCtx.lineTo(45, 5); vcCtx.lineTo(55, 15); vcCtx.lineTo(50, 50); vcCtx.stroke();
  vcCtx.beginPath(); vcCtx.moveTo(50, 10); vcCtx.lineTo(50, 50); vcCtx.stroke();
  vcCtx.fillStyle = '#888'; vcCtx.font = '8px sans-serif';
  vcCtx.fillText('FRONT', 15, 35);
}}
drawViewCube();

// ── FPS ──
const fpsEl = document.getElementById('fps-display');
let fc = 0, lt = performance.now();

// ── Animate ──
function animate() {{
  requestAnimationFrame(animate);
  controls.update();
  const t = performance.now() * 0.001;
  scene.traverse(c => {{ if (c.userData?.pulse && c.material) c.material.opacity = 0.06 + Math.sin(t*2)*0.04; }});
  composer.render();
  updateLabels();
  fc++;
  if (performance.now() - lt >= 1000) {{ fpsEl.textContent = fc + ' FPS'; fc = 0; lt = performance.now(); }}
}}
animate();

// ── Resize ──
window.addEventListener('resize', () => {{
  const w = window.innerWidth - 300;
  const h = window.innerHeight - 60;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
  composer.setSize(w, h);
}});
</script>
</body>
</html>'''


# ── HTTP Server ──
_ov_server = None
_ov_thread = None

def _write_and_serve_ov(usda_path: str):
    global _ov_server, _ov_thread
    html = generate_ov_viewer_html(usda_path)
    viewer_dir = Path("outputs/ov_viewer")
    viewer_dir.mkdir(parents=True, exist_ok=True)
    (viewer_dir / "index.html").write_text(html, encoding="utf-8")

    if _ov_server:
        try: _ov_server.shutdown()
        except: pass

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(viewer_dir), **kwargs)
        def log_message(self, format, *args):
            pass

    try:
        _ov_server = socketserver.TCPServer(("0.0.0.0", OV_VIEWER_PORT), Handler)
        _ov_server.allow_reuse_address = True
        _ov_thread = threading.Thread(target=_ov_server.serve_forever, daemon=True)
        _ov_thread.start()
    except OSError:
        pass  # Port already in use from previous run


def get_ov_viewport_iframe(usda_path: str, height: int = 600) -> str:
    _write_and_serve_ov(usda_path)
    return f'<iframe src="http://localhost:{OV_VIEWER_PORT}" width="100%" height="{height}px" style="border:none; border-radius:4px;" allow="autoplay"></iframe>'
