"""
Three.js 3D Viewport Server

Generates a standalone HTML page with a premium Three.js scene,
and serves it on a separate port. The Gradio app embeds it via iframe.

Features:
- PBR materials (metalness, roughness)
- Soft shadows + ambient occlusion
- Edge outlines on geometry
- OrbitControls for navigation
- Hover tooltips showing cell info
- Subtle auto-rotation
- Responsive resize
"""
import json
import re
import threading
import http.server
import socketserver
from pathlib import Path

from usd_writer import parse_usda, find_prims_by_name, find_prims_by_type, get_attribute

VIEWER_PORT = 7863

# Cell type → hex color
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


def _extract_scene_objects(usda_path: str) -> list[dict]:
    """Extract scene objects from a USDA file as JSON-serializable dicts."""
    scene = parse_usda(usda_path)
    objects = []

    # Battery cells
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
            "position": [px, pz, -py],  # USD Z-up → Three.js Y-up
            "scale": [sx * 2, sz * 2, sy * 2],
            "color": CELL_COLORS.get(cell_type, DEFAULT_COLOR),
        })

    # Module tray
    trays = find_prims_by_name(scene, r"ModuleTray")
    for tray in trays:
        pos_attr = get_attribute(tray, "xformOp:translate")
        scale_attr = get_attribute(tray, "xformOp:scale")
        if pos_attr and scale_attr:
            px, py, pz = _parse_float3(pos_attr.value)
            sx, sy, sz = _parse_float3(scale_attr.value)
            objects.append({
                "type": "tray", "name": "ModuleTray",
                "position": [px, pz, -py],
                "scale": [sx * 2, sz * 2, sy * 2],
                "color": "#B0BEC5",
            })

    # Robot arm
    robots = find_prims_by_name(scene, r"RobotArm_.*")
    for robot in robots:
        pos_attr = get_attribute(robot, "xformOp:translate")
        if pos_attr:
            px, py, pz = _parse_float3(pos_attr.value)
            reach_attr = get_attribute(robot, "robot:maxReach")
            reach = float(reach_attr.value) if reach_attr else 1.0
            objects.append({
                "type": "robot", "name": robot.name,
                "position": [px, pz, -py],
                "reach": reach, "color": "#D32F2F",
            })

    # Camera
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


def generate_viewer_html(usda_path: str) -> str:
    """Generate a complete standalone HTML page with Three.js scene."""
    objects = _extract_scene_objects(usda_path)
    objects_json = json.dumps(objects)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Industrial SDG Lab — 3D Viewport</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0d1117; overflow: hidden; font-family: 'Segoe UI', sans-serif; }}
  canvas {{ display: block; }}
  #info {{
    position: fixed; top: 12px; left: 12px;
    color: #c9d1d9; font-size: 12px;
    background: rgba(13,17,23,0.85); padding: 8px 14px;
    border-radius: 6px; border: 1px solid #30363d;
    pointer-events: none; z-index: 10;
  }}
  #info h3 {{ color: #58a6ff; margin-bottom: 4px; font-size: 13px; }}
  #tooltip {{
    position: fixed; display: none;
    background: rgba(13,17,23,0.92); color: #e6edf3;
    padding: 8px 12px; border-radius: 6px;
    font-size: 12px; pointer-events: none; z-index: 20;
    border: 1px solid #58a6ff;
  }}
  #legend {{
    position: fixed; bottom: 12px; left: 12px;
    color: #c9d1d9; font-size: 11px;
    background: rgba(13,17,23,0.85); padding: 8px 14px;
    border-radius: 6px; border: 1px solid #30363d;
    z-index: 10;
  }}
  .legend-item {{ display: flex; align-items: center; gap: 8px; margin: 3px 0; }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 2px; }}
</style>
</head>
<body>

<div id="info">
  <h3>🏭 Battery Module 2×3</h3>
  <span>Drag to rotate · Scroll to zoom · Right-click to pan</span>
</div>

<div id="tooltip"></div>

<div id="legend">
  <div class="legend-item"><div class="legend-dot" style="background:#4CAF50"></div>LG E63</div>
  <div class="legend-item"><div class="legend-dot" style="background:#2196F3"></div>HY 50Ah</div>
  <div class="legend-item"><div class="legend-dot" style="background:#FF9800"></div>CATL LFP</div>
  <div class="legend-item"><div class="legend-dot" style="background:#D32F2F"></div>Robot Base</div>
  <div class="legend-item"><div class="legend-dot" style="background:#7B1FA2"></div>Camera</div>
</div>

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

// ── Scene ──
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0d1117);

// ── Camera ──
const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.01, 100);
camera.position.set(1.2, 0.9, 1.0);

// ── Renderer ──
const renderer = new THREE.WebGLRenderer({{ antialias: true }});
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.4;
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);

// ── Controls ──
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0.08, 0);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.autoRotate = true;
controls.autoRotateSpeed = 0.5;
controls.maxPolarAngle = Math.PI / 2.05;
controls.update();

// ── Lighting ──
const ambient = new THREE.AmbientLight(0x404060, 0.8);
scene.add(ambient);

const hemi = new THREE.HemisphereLight(0xfff0e8, 0x303050, 0.6);
scene.add(hemi);

const key = new THREE.DirectionalLight(0xfff5e8, 1.8);
key.position.set(3, 5, 2);
key.castShadow = true;
key.shadow.mapSize.width = 2048;
key.shadow.mapSize.height = 2048;
key.shadow.camera.near = 0.1;
key.shadow.camera.far = 20;
key.shadow.camera.left = -3;
key.shadow.camera.right = 3;
key.shadow.camera.top = 3;
key.shadow.camera.bottom = -3;
key.shadow.bias = -0.001;
scene.add(key);

const fill = new THREE.DirectionalLight(0xd0e0ff, 0.5);
fill.position.set(-2, 3, -1);
scene.add(fill);

const rim = new THREE.PointLight(0x6088ff, 0.4, 10);
rim.position.set(0, 2, -2);
scene.add(rim);

// ── Ground ──
const groundGeo = new THREE.PlaneGeometry(6, 6);
const groundMat = new THREE.MeshStandardMaterial({{
  color: 0x161b22, roughness: 0.95, metalness: 0.0,
}});
const ground = new THREE.Mesh(groundGeo, groundMat);
ground.rotation.x = -Math.PI / 2;
ground.position.y = -0.001;
ground.receiveShadow = true;
scene.add(ground);

// Grid
const grid = new THREE.GridHelper(4, 40, 0x21262d, 0x1a1f26);
grid.position.y = 0.001;
scene.add(grid);

// ── Scene Objects ──
const objects = {objects_json};
const interactables = [];
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();

objects.forEach(obj => {{
  if (obj.type === 'cell') {{
    const geo = new THREE.BoxGeometry(obj.scale[0], obj.scale[1], obj.scale[2]);
    const mat = new THREE.MeshStandardMaterial({{
      color: obj.color, roughness: 0.35, metalness: 0.15,
    }});
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(obj.position[0], obj.position[1], obj.position[2]);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData = {{ name: obj.name, cellType: obj.cellType, type: 'cell' }};
    scene.add(mesh);
    interactables.push(mesh);

    // Edge outline
    const edges = new THREE.EdgesGeometry(geo);
    const lineMat = new THREE.LineBasicMaterial({{ color: 0x000000, opacity: 0.2, transparent: true }});
    const line = new THREE.LineSegments(edges, lineMat);
    line.position.copy(mesh.position);
    scene.add(line);

    // Top label bar (thin strip on top)
    const labelGeo = new THREE.BoxGeometry(obj.scale[0] * 0.9, 0.003, obj.scale[2] * 0.4);
    const labelMat = new THREE.MeshStandardMaterial({{
      color: 0xffffff, roughness: 0.6, metalness: 0.0, opacity: 0.3, transparent: true,
    }});
    const label = new THREE.Mesh(labelGeo, labelMat);
    label.position.set(obj.position[0], obj.position[1] + obj.scale[1] / 2 + 0.002, obj.position[2]);
    scene.add(label);

  }} else if (obj.type === 'tray') {{
    const geo = new THREE.BoxGeometry(obj.scale[0], obj.scale[1], obj.scale[2]);
    const mat = new THREE.MeshStandardMaterial({{
      color: obj.color, roughness: 0.5, metalness: 0.05,
      transparent: true, opacity: 0.5,
    }});
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(obj.position[0], obj.position[1], obj.position[2]);
    mesh.receiveShadow = true;
    scene.add(mesh);

    const edges = new THREE.EdgesGeometry(geo);
    const line = new THREE.LineSegments(edges,
      new THREE.LineBasicMaterial({{ color: 0x607D8B, opacity: 0.5, transparent: true }}));
    line.position.copy(mesh.position);
    scene.add(line);

  }} else if (obj.type === 'robot') {{
    // Base
    const baseGeo = new THREE.CylinderGeometry(0.08, 0.10, 0.20, 24);
    const baseMat = new THREE.MeshStandardMaterial({{
      color: obj.color, roughness: 0.25, metalness: 0.6,
    }});
    const base = new THREE.Mesh(baseGeo, baseMat);
    base.position.set(obj.position[0], 0.10, obj.position[2]);
    base.castShadow = true;
    base.userData = {{ name: obj.name, type: 'robot' }};
    scene.add(base);
    interactables.push(base);

    // Arm stub
    const armGeo = new THREE.CylinderGeometry(0.03, 0.04, 0.35, 12);
    const armMat = new THREE.MeshStandardMaterial({{
      color: 0x424242, roughness: 0.3, metalness: 0.7,
    }});
    const arm = new THREE.Mesh(armGeo, armMat);
    arm.position.set(obj.position[0], 0.375, obj.position[2]);
    arm.castShadow = true;
    scene.add(arm);

    // Joint sphere
    const jointGeo = new THREE.SphereGeometry(0.045, 16, 16);
    const jointMat = new THREE.MeshStandardMaterial({{
      color: 0x616161, roughness: 0.3, metalness: 0.6,
    }});
    const joint = new THREE.Mesh(jointGeo, jointMat);
    joint.position.set(obj.position[0], 0.55, obj.position[2]);
    joint.castShadow = true;
    scene.add(joint);

    // Reach ring
    const ringGeo = new THREE.RingGeometry(obj.reach - 0.015, obj.reach, 64);
    const ringMat = new THREE.MeshBasicMaterial({{
      color: 0xFF5252, transparent: true, opacity: 0.12, side: THREE.DoubleSide,
    }});
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(obj.position[0], 0.003, obj.position[2]);
    scene.add(ring);

  }} else if (obj.type === 'camera') {{
    // Camera body
    const bodyGeo = new THREE.BoxGeometry(0.06, 0.04, 0.08);
    const bodyMat = new THREE.MeshStandardMaterial({{
      color: obj.color, roughness: 0.3, metalness: 0.4,
    }});
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    body.position.set(obj.position[0], obj.position[1], obj.position[2]);
    body.castShadow = true;
    body.userData = {{ name: obj.name, type: 'camera' }};
    scene.add(body);
    interactables.push(body);

    // Lens
    const lensGeo = new THREE.CylinderGeometry(0.02, 0.025, 0.04, 16);
    const lensMat = new THREE.MeshStandardMaterial({{
      color: 0x263238, roughness: 0.1, metalness: 0.8,
    }});
    const lens = new THREE.Mesh(lensGeo, lensMat);
    lens.rotation.x = Math.PI / 2;
    lens.position.set(obj.position[0], obj.position[1] - 0.035, obj.position[2]);
    scene.add(lens);
  }}
}});

// ── Tooltip ──
const tooltip = document.getElementById('tooltip');
let hovered = null;

window.addEventListener('mousemove', (e) => {{
  mouse.x = (e.clientX / window.innerWidth) * 2 - 1;
  mouse.y = -(e.clientY / window.innerHeight) * 2 + 1;

  raycaster.setFromCamera(mouse, camera);
  const intersects = raycaster.intersectObjects(interactables);

  if (intersects.length > 0) {{
    const obj = intersects[0].object;
    if (hovered !== obj) {{
      if (hovered) hovered.material.emissive.setHex(0x000000);
      hovered = obj;
      hovered.material.emissive.setHex(0x222244);
    }}
    tooltip.style.display = 'block';
    tooltip.style.left = e.clientX + 15 + 'px';
    tooltip.style.top = e.clientY + 15 + 'px';
    const ud = obj.userData;
    if (ud.type === 'cell') {{
      tooltip.innerHTML = `<b>${{ud.name}}</b><br>Type: ${{ud.cellType}}`;
    }} else {{
      tooltip.innerHTML = `<b>${{ud.name}}</b>`;
    }}
  }} else {{
    if (hovered) {{ hovered.material.emissive.setHex(0x000000); hovered = null; }}
    tooltip.style.display = 'none';
  }}
}});

// ── Animation ──
function animate() {{
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}}
animate();

// ── Resize ──
window.addEventListener('resize', () => {{
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
}});
</script>
</body>
</html>'''


# ── HTTP Server ──
_server = None
_server_thread = None


def _write_and_serve(usda_path: str):
    """Write the viewer HTML and start/restart the HTTP server."""
    global _server, _server_thread

    # Generate HTML
    html = generate_viewer_html(usda_path)
    viewer_dir = Path("outputs/viewer")
    viewer_dir.mkdir(parents=True, exist_ok=True)
    (viewer_dir / "index.html").write_text(html, encoding="utf-8")

    # Stop existing server
    if _server:
        _server.shutdown()

    # Start new server
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(viewer_dir), **kwargs)
        def log_message(self, format, *args):
            pass  # Suppress logs

    _server = socketserver.TCPServer(("0.0.0.0", VIEWER_PORT), Handler)
    _server.allow_reuse_address = True
    _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _server_thread.start()


def get_viewer_iframe(usda_path: str, height: int = 550) -> str:
    """
    Generate the 3D viewer and return an iframe HTML string
    that Gradio can display.
    """
    _write_and_serve(usda_path)
    return f'<iframe src="http://localhost:{VIEWER_PORT}" width="100%" height="{height}px" style="border:none; border-radius:8px;" allow="autoplay"></iframe>'
