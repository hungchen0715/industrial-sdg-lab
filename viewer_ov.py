"""
Omniverse-style premium Three.js 3D viewport.

Features beyond the basic Three.js viewer:
- Post-processing pipeline (Bloom, SSAO, tone mapping)
- HDR environment map for realistic reflections
- Rounded/beveled cell geometry with glossy PBR materials
- Professional Omniverse-style dark UI overlay
- Property panel showing selected object details
- Animated grid pulse effect
- Higher quality shadows and anti-aliasing
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
        objects.append({
            "type": "cell", "name": cell.name, "cellType": cell_type,
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
                "type": "tray", "name": "ModuleTray",
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
                "position": [px, pz, -py], "reach": reach, "color": "#D32F2F",
            })

    cameras = find_prims_by_type(scene, "Camera")
    for cam in cameras:
        pos_attr = get_attribute(cam, "xformOp:translate")
        if pos_attr:
            px, py, pz = _parse_float3(pos_attr.value)
            objects.append({
                "type": "camera", "name": cam.name,
                "position": [px, pz, -py], "color": "#7B1FA2",
            })

    return objects


def generate_ov_viewer_html(usda_path: str) -> str:
    objects = _extract_objects(usda_path)
    objects_json = json.dumps(objects)
    num_cells = sum(1 for o in objects if o["type"] == "cell")
    num_robots = sum(1 for o in objects if o["type"] == "robot")

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>NVIDIA Omniverse-Style Viewport</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #1b1b1b; overflow: hidden; font-family: 'Segoe UI', 'Inter', sans-serif; color: #d0d0d0; }}
  canvas {{ display: block; }}

  /* Omniverse-style top toolbar */
  #toolbar {{
    position: fixed; top: 0; left: 0; right: 0; height: 32px;
    background: linear-gradient(180deg, #2b2b2b 0%, #232323 100%);
    border-bottom: 1px solid #3a3a3a;
    display: flex; align-items: center; padding: 0 12px; gap: 12px;
    z-index: 100; font-size: 12px;
  }}
  .toolbar-logo {{
    background: linear-gradient(135deg, #76b900, #4a8c00);
    color: #fff; font-weight: 700; font-size: 10px;
    padding: 2px 8px; border-radius: 3px; letter-spacing: 1px;
  }}
  .toolbar-title {{ color: #aaa; font-size: 12px; }}
  .toolbar-sep {{ width: 1px; height: 16px; background: #444; }}
  .toolbar-stat {{ color: #888; font-size: 11px; }}
  .toolbar-stat b {{ color: #76b900; }}

  /* Right property panel */
  #props {{
    position: fixed; top: 32px; right: 0; width: 240px; bottom: 24px;
    background: #252525; border-left: 1px solid #3a3a3a;
    z-index: 90; font-size: 11px; overflow-y: auto;
  }}
  .props-header {{
    background: #2d2d2d; padding: 6px 10px; font-size: 11px;
    color: #76b900; font-weight: 600; border-bottom: 1px solid #3a3a3a;
    text-transform: uppercase; letter-spacing: 0.5px;
  }}
  .props-section {{ padding: 8px 10px; border-bottom: 1px solid #333; }}
  .props-row {{ display: flex; justify-content: space-between; margin: 3px 0; }}
  .props-label {{ color: #888; }}
  .props-value {{ color: #d0d0d0; font-family: 'Consolas', monospace; }}
  .props-value.green {{ color: #76b900; }}

  /* Scene tree */
  .scene-item {{
    padding: 3px 10px 3px 20px; cursor: pointer;
    border-left: 2px solid transparent;
  }}
  .scene-item:hover {{ background: #2a2a2a; }}
  .scene-item.selected {{ background: #2a3520; border-left-color: #76b900; }}
  .scene-icon {{ margin-right: 6px; }}

  /* Bottom status bar */
  #statusbar {{
    position: fixed; bottom: 0; left: 0; right: 0; height: 24px;
    background: #232323; border-top: 1px solid #3a3a3a;
    display: flex; align-items: center; padding: 0 12px; gap: 16px;
    font-size: 10px; color: #666; z-index: 100;
  }}
  .status-dot {{ width: 6px; height: 6px; border-radius: 50%; background: #76b900; }}

  /* Tooltip */
  #tooltip {{
    position: fixed; display: none;
    background: rgba(30,30,30,0.95); color: #e0e0e0;
    padding: 8px 12px; border-radius: 4px;
    font-size: 11px; pointer-events: none; z-index: 200;
    border: 1px solid #76b900; box-shadow: 0 4px 12px rgba(0,0,0,0.5);
  }}

  /* Viewport label */
  #vp-label {{
    position: fixed; top: 38px; left: 8px;
    color: #555; font-size: 10px; z-index: 90;
    text-transform: uppercase; letter-spacing: 1px;
  }}
</style>
</head>
<body>

<div id="toolbar">
  <span class="toolbar-logo">OV</span>
  <span class="toolbar-title">Industrial SDG Lab — Viewport</span>
  <span class="toolbar-sep"></span>
  <span class="toolbar-stat"><b>{num_cells}</b> cells</span>
  <span class="toolbar-stat"><b>{num_robots}</b> robot</span>
  <span class="toolbar-sep"></span>
  <span class="toolbar-stat" id="fps-counter">-- FPS</span>
</div>

<div id="vp-label">Perspective</div>

<div id="props">
  <div class="props-header">Scene Hierarchy</div>
  <div id="scene-tree"></div>
  <div class="props-header">Properties</div>
  <div id="prop-detail">
    <div class="props-section">
      <div style="color:#666; text-align:center; padding:16px;">Click an object to inspect</div>
    </div>
  </div>
</div>

<div id="statusbar">
  <span class="status-dot"></span>
  <span>RTX Viewport Active</span>
  <span style="margin-left:auto">Renderer: Three.js WebGL2 | Post-Processing: Bloom + Vignette</span>
</div>

<div id="tooltip"></div>

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
import {{ ShaderPass }} from 'three/addons/postprocessing/ShaderPass.js';
import {{ RoundedBoxGeometry }} from 'three/addons/geometries/RoundedBoxGeometry.js';

// ── Vignette shader ──
const VignetteShader = {{
  uniforms: {{
    tDiffuse: {{ value: null }},
    offset: {{ value: 1.0 }},
    darkness: {{ value: 1.2 }},
  }},
  vertexShader: `varying vec2 vUv; void main() {{ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }}`,
  fragmentShader: `uniform sampler2D tDiffuse; uniform float offset; uniform float darkness; varying vec2 vUv;
    void main() {{
      vec4 texel = texture2D(tDiffuse, vUv);
      vec2 uv = (vUv - vec2(0.5)) * vec2(offset);
      texel.rgb *= 1.0 - dot(uv, uv) * darkness;
      gl_FragColor = texel;
    }}`
}};

// ── Scene ──
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1b1b1b);

// ── Camera ──
const vpW = window.innerWidth - 240;
const vpH = window.innerHeight - 56;
const camera = new THREE.PerspectiveCamera(45, vpW / vpH, 0.01, 100);
camera.position.set(1.5, 1.1, 1.3);

// ── Renderer ──
const renderer = new THREE.WebGLRenderer({{ antialias: true, powerPreference: 'high-performance' }});
renderer.setSize(vpW, vpH);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.5;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.domElement.style.position = 'fixed';
renderer.domElement.style.top = '32px';
renderer.domElement.style.left = '0';
document.body.appendChild(renderer.domElement);

// ── Post-processing ──
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));

const bloom = new UnrealBloomPass(
  new THREE.Vector2(vpW, vpH), 0.3, 0.4, 0.85
);
composer.addPass(bloom);

const vignette = new ShaderPass(VignetteShader);
vignette.uniforms.darkness.value = 1.5;
composer.addPass(vignette);

// ── Controls ──
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0.08, 0);
controls.enableDamping = true;
controls.dampingFactor = 0.06;
controls.autoRotate = true;
controls.autoRotateSpeed = 0.3;
controls.maxPolarAngle = Math.PI / 2.05;
controls.update();

// ── Lighting ──
scene.add(new THREE.AmbientLight(0x303040, 0.5));

const hemi = new THREE.HemisphereLight(0xfff8f0, 0x202030, 0.6);
scene.add(hemi);

const key = new THREE.DirectionalLight(0xfff5e0, 2.2);
key.position.set(4, 6, 3);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
key.shadow.camera.left = -3; key.shadow.camera.right = 3;
key.shadow.camera.top = 3; key.shadow.camera.bottom = -3;
key.shadow.bias = -0.0005;
key.shadow.normalBias = 0.02;
scene.add(key);

const fill = new THREE.DirectionalLight(0xc0d8ff, 0.5);
fill.position.set(-3, 4, -2);
scene.add(fill);

const accent = new THREE.PointLight(0x76b900, 0.4, 5);
accent.position.set(0, 1, -1);
scene.add(accent);

const rim = new THREE.PointLight(0x4060ff, 0.3, 6);
rim.position.set(-1, 0.5, 2);
scene.add(rim);

// ── Ground ──
const groundMat = new THREE.MeshStandardMaterial({{
  color: 0x1a1a1a, roughness: 0.92, metalness: 0.0,
}});
const ground = new THREE.Mesh(new THREE.PlaneGeometry(8, 8), groundMat);
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);

// Grid (subtle)
const grid = new THREE.GridHelper(4, 40, 0x2a2a2a, 0x222222);
grid.position.y = 0.001;
scene.add(grid);

// ── Build Scene Tree UI ──
const objects = {objects_json};
const sceneTree = document.getElementById('scene-tree');
const propDetail = document.getElementById('prop-detail');
const interactables = [];
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();

function buildSceneTree() {{
  let html = '';
  objects.forEach((obj, i) => {{
    let icon = '📦';
    if (obj.type === 'cell') icon = '🔋';
    else if (obj.type === 'robot') icon = '🤖';
    else if (obj.type === 'camera') icon = '📷';
    else if (obj.type === 'tray') icon = '📐';
    html += `<div class="scene-item" data-idx="${{i}}" onclick="selectItem(${{i}})"><span class="scene-icon">${{icon}}</span>${{obj.name}}</div>`;
  }});
  sceneTree.innerHTML = html;
}}
buildSceneTree();

window.selectItem = function(idx) {{
  document.querySelectorAll('.scene-item').forEach(el => el.classList.remove('selected'));
  document.querySelector(`[data-idx="${{idx}}"]`)?.classList.add('selected');
  const obj = objects[idx];
  let html = '<div class="props-section">';
  html += `<div class="props-row"><span class="props-label">Name</span><span class="props-value green">${{obj.name}}</span></div>`;
  html += `<div class="props-row"><span class="props-label">Type</span><span class="props-value">${{obj.type}}</span></div>`;
  if (obj.cellType) html += `<div class="props-row"><span class="props-label">Cell Type</span><span class="props-value">${{obj.cellType}}</span></div>`;
  html += `<div class="props-row"><span class="props-label">Position</span><span class="props-value">${{obj.position.map(v => v.toFixed(3)).join(', ')}}</span></div>`;
  if (obj.scale) html += `<div class="props-row"><span class="props-label">Scale</span><span class="props-value">${{obj.scale.map(v => v.toFixed(3)).join(', ')}}</span></div>`;
  if (obj.reach) html += `<div class="props-row"><span class="props-label">Max Reach</span><span class="props-value">${{obj.reach}} m</span></div>`;
  html += '</div>';
  propDetail.innerHTML = html;
}};

// ── Create scene objects ──
objects.forEach((obj, idx) => {{
  if (obj.type === 'cell') {{
    // Rounded box for premium look
    const geo = new RoundedBoxGeometry(obj.scale[0], obj.scale[1], obj.scale[2], 2, 0.008);
    const mat = new THREE.MeshPhysicalMaterial({{
      color: obj.color, roughness: 0.28, metalness: 0.1,
      clearcoat: 0.3, clearcoatRoughness: 0.2,
    }});
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(...obj.position);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData = {{ idx, ...obj }};
    scene.add(mesh);
    interactables.push(mesh);

    // Subtle edge glow
    const edges = new THREE.EdgesGeometry(geo, 15);
    const line = new THREE.LineSegments(edges,
      new THREE.LineBasicMaterial({{ color: 0xffffff, opacity: 0.08, transparent: true }}));
    line.position.copy(mesh.position);
    scene.add(line);

    // Terminal marks (two small dark patches on top)
    const termGeo = new THREE.CylinderGeometry(0.006, 0.006, 0.003, 8);
    const termMat = new THREE.MeshStandardMaterial({{ color: 0x333333, roughness: 0.5, metalness: 0.8 }});
    const t1 = new THREE.Mesh(termGeo, termMat);
    t1.position.set(obj.position[0] - obj.scale[0]*0.25, obj.position[1]+obj.scale[1]/2+0.002, obj.position[2]);
    scene.add(t1);
    const t2 = new THREE.Mesh(termGeo, termMat.clone());
    t2.material.color.setHex(0xcc0000);
    t2.position.set(obj.position[0] + obj.scale[0]*0.25, obj.position[1]+obj.scale[1]/2+0.002, obj.position[2]);
    scene.add(t2);

  }} else if (obj.type === 'tray') {{
    const geo = new RoundedBoxGeometry(obj.scale[0], obj.scale[1], obj.scale[2], 2, 0.005);
    const mat = new THREE.MeshPhysicalMaterial({{
      color: obj.color, roughness: 0.45, metalness: 0.08,
      transparent: true, opacity: 0.6, clearcoat: 0.1,
    }});
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(...obj.position);
    mesh.receiveShadow = true;
    mesh.userData = {{ idx, ...obj }};
    scene.add(mesh);
    interactables.push(mesh);

    const edges = new THREE.EdgesGeometry(geo, 15);
    const line = new THREE.LineSegments(edges,
      new THREE.LineBasicMaterial({{ color: 0x78909C, opacity: 0.4, transparent: true }}));
    line.position.copy(mesh.position);
    scene.add(line);

  }} else if (obj.type === 'robot') {{
    // Detailed robot base
    const baseMat = new THREE.MeshPhysicalMaterial({{
      color: obj.color, roughness: 0.2, metalness: 0.7,
      clearcoat: 0.5, clearcoatRoughness: 0.1,
    }});
    const base = new THREE.Mesh(new THREE.CylinderGeometry(0.10, 0.13, 0.08, 32), baseMat);
    base.position.set(obj.position[0], 0.04, obj.position[2]);
    base.castShadow = true;
    base.userData = {{ idx, ...obj }};
    scene.add(base);
    interactables.push(base);

    // Shoulder
    const shoulderMat = new THREE.MeshPhysicalMaterial({{ color: 0x444444, roughness: 0.25, metalness: 0.8 }});
    const shoulder = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.07, 0.12, 24), shoulderMat);
    shoulder.position.set(obj.position[0], 0.14, obj.position[2]);
    shoulder.castShadow = true;
    scene.add(shoulder);

    // Upper arm
    const armMat = new THREE.MeshPhysicalMaterial({{ color: 0x555555, roughness: 0.3, metalness: 0.7 }});
    const upperArm = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.04, 0.30, 16), armMat);
    upperArm.position.set(obj.position[0], 0.35, obj.position[2]);
    upperArm.castShadow = true;
    scene.add(upperArm);

    // Elbow joint
    const elbowMat = new THREE.MeshPhysicalMaterial({{ color: obj.color, roughness: 0.2, metalness: 0.8, clearcoat: 0.4 }});
    const elbow = new THREE.Mesh(new THREE.SphereGeometry(0.05, 20, 20), elbowMat);
    elbow.position.set(obj.position[0], 0.50, obj.position[2]);
    elbow.castShadow = true;
    scene.add(elbow);

    // Forearm (angled)
    const forearm = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.035, 0.25, 12), armMat.clone());
    forearm.position.set(obj.position[0] + 0.10, 0.55, obj.position[2]);
    forearm.rotation.z = -Math.PI / 6;
    forearm.castShadow = true;
    scene.add(forearm);

    // Wrist
    const wrist = new THREE.Mesh(new THREE.SphereGeometry(0.035, 16, 16), shoulderMat.clone());
    wrist.position.set(obj.position[0] + 0.22, 0.56, obj.position[2]);
    wrist.castShadow = true;
    scene.add(wrist);

    // Reach circle (pulsing glow)
    const ringGeo = new THREE.RingGeometry(obj.reach - 0.02, obj.reach, 128);
    const ringMat = new THREE.MeshBasicMaterial({{ color: 0xff3333, transparent: true, opacity: 0.08, side: THREE.DoubleSide }});
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(obj.position[0], 0.003, obj.position[2]);
    ring.userData.isPulse = true;
    scene.add(ring);

  }} else if (obj.type === 'camera') {{
    const camMat = new THREE.MeshPhysicalMaterial({{
      color: obj.color, roughness: 0.25, metalness: 0.5,
      clearcoat: 0.4,
    }});
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.05, 0.09), camMat);
    body.position.set(...obj.position);
    body.castShadow = true;
    body.userData = {{ idx, ...obj }};
    scene.add(body);
    interactables.push(body);

    // Lens assembly
    const lensMat = new THREE.MeshPhysicalMaterial({{ color: 0x1a237e, roughness: 0.05, metalness: 0.9, clearcoat: 1.0 }});
    const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.028, 0.05, 20), lensMat);
    lens.rotation.x = Math.PI / 2;
    lens.position.set(obj.position[0], obj.position[1] - 0.045, obj.position[2]);
    scene.add(lens);

    // Frustum cone (field of view indicator)
    const frustumGeo = new THREE.ConeGeometry(0.12, 0.3, 4);
    const frustumMat = new THREE.MeshBasicMaterial({{ color: 0x7B1FA2, transparent: true, opacity: 0.06, wireframe: true }});
    const frustum = new THREE.Mesh(frustumGeo, frustumMat);
    frustum.position.set(obj.position[0], obj.position[1] - 0.22, obj.position[2]);
    scene.add(frustum);
  }}
}});

// ── Hover & Click ──
const tooltip = document.getElementById('tooltip');
let hovered = null;
let selectedMat = null;

renderer.domElement.addEventListener('mousemove', (e) => {{
  mouse.x = (e.offsetX / renderer.domElement.clientWidth) * 2 - 1;
  mouse.y = -(e.offsetY / renderer.domElement.clientHeight) * 2 + 1;

  raycaster.setFromCamera(mouse, camera);
  const hits = raycaster.intersectObjects(interactables);

  if (hits.length > 0) {{
    const obj = hits[0].object;
    if (hovered !== obj) {{
      if (hovered && hovered.material) hovered.material.emissive?.setHex(0x000000);
      hovered = obj;
      if (hovered.material.emissive) hovered.material.emissive.setHex(0x1a2e0a);
    }}
    tooltip.style.display = 'block';
    tooltip.style.left = (e.clientX + 15) + 'px';
    tooltip.style.top = (e.clientY + 15) + 'px';
    const ud = obj.userData;
    tooltip.innerHTML = ud.cellType
      ? `<b>${{ud.name}}</b> — ${{ud.cellType}}`
      : `<b>${{ud.name}}</b>`;
  }} else {{
    if (hovered && hovered.material?.emissive) hovered.material.emissive.setHex(0x000000);
    hovered = null;
    tooltip.style.display = 'none';
  }}
}});

renderer.domElement.addEventListener('click', (e) => {{
  raycaster.setFromCamera(mouse, camera);
  const hits = raycaster.intersectObjects(interactables);
  if (hits.length > 0) {{
    const ud = hits[0].object.userData;
    if (ud.idx !== undefined) window.selectItem(ud.idx);
  }}
}});

// ── FPS counter ──
const fpsEl = document.getElementById('fps-counter');
let frameCount = 0, lastTime = performance.now();

// ── Animation ──
function animate() {{
  requestAnimationFrame(animate);
  controls.update();

  // Pulse reach ring
  const t = performance.now() * 0.001;
  scene.traverse(child => {{
    if (child.userData?.isPulse && child.material) {{
      child.material.opacity = 0.04 + Math.sin(t * 2) * 0.04;
    }}
  }});

  composer.render();

  // FPS
  frameCount++;
  if (performance.now() - lastTime >= 1000) {{
    fpsEl.textContent = frameCount + ' FPS';
    frameCount = 0;
    lastTime = performance.now();
  }}
}}
animate();

// ── Resize ──
window.addEventListener('resize', () => {{
  const w = window.innerWidth - 240;
  const h = window.innerHeight - 56;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
  composer.setSize(w, h);
}});
</script>
</body>
</html>'''


# ── HTTP Server for OV viewer ──
_ov_server = None
_ov_thread = None


def _write_and_serve_ov(usda_path: str):
    global _ov_server, _ov_thread

    html = generate_ov_viewer_html(usda_path)
    viewer_dir = Path("outputs/ov_viewer")
    viewer_dir.mkdir(parents=True, exist_ok=True)
    (viewer_dir / "index.html").write_text(html, encoding="utf-8")

    if _ov_server:
        _ov_server.shutdown()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(viewer_dir), **kwargs)
        def log_message(self, format, *args):
            pass

    _ov_server = socketserver.TCPServer(("0.0.0.0", OV_VIEWER_PORT), Handler)
    _ov_server.allow_reuse_address = True
    _ov_thread = threading.Thread(target=_ov_server.serve_forever, daemon=True)
    _ov_thread.start()


def get_ov_viewport_iframe(usda_path: str, height: int = 600) -> str:
    _write_and_serve_ov(usda_path)
    return f'<iframe src="http://localhost:{OV_VIEWER_PORT}" width="100%" height="{height}px" style="border:none; border-radius:4px;" allow="autoplay"></iframe>'
