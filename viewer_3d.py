"""
Three.js 3D viewport generator for USDA scenes.

Converts parsed USDA scene data into an embeddable HTML page
with an interactive Three.js 3D viewer. Supports:
- Battery cells as colored cubes
- Module tray as a transparent box
- Robot arm base as a red cylinder
- Camera marker
- Orbit controls for navigation
- Grid and lighting
"""
import re
import json
from pathlib import Path

from usd_writer import parse_usda, find_prims_by_name, find_prims_by_type, get_attribute


# Cell type → hex color
CELL_COLORS = {
    "LG_E63":   "#4CAF50",
    "HY_50Ah":  "#2196F3",
    "CATL_LFP": "#FF9800",
}
DEFAULT_COLOR = "#9E9E9E"


def _parse_float3(value: str):
    """Parse (x, y, z) from USDA attribute value."""
    m = re.search(r'\((-?\d+\.?\d*),\s*(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\)', value)
    if m:
        return float(m.group(1)), float(m.group(2)), float(m.group(3))
    return 0, 0, 0


def generate_viewport_html(usda_path: str, height: int = 500) -> str:
    """
    Generate an interactive Three.js 3D viewport from a USDA scene file.

    Args:
        usda_path: Path to a .usda file.
        height: Viewport height in pixels.

    Returns:
        HTML string with embedded Three.js scene.
    """
    scene = parse_usda(usda_path)

    # Collect scene objects
    objects_js = []

    # -- Battery cells --
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
        color = CELL_COLORS.get(cell_type, DEFAULT_COLOR)

        objects_js.append({
            "type": "cell",
            "name": cell.name,
            "cellType": cell_type,
            "position": [px, pz, -py],  # USD Z-up → Three.js Y-up
            "scale": [sx * 2, sz * 2, sy * 2],
            "color": color,
        })

    # -- Module tray --
    trays = find_prims_by_name(scene, r"ModuleTray")
    for tray in trays:
        pos_attr = get_attribute(tray, "xformOp:translate")
        scale_attr = get_attribute(tray, "xformOp:scale")
        if pos_attr and scale_attr:
            px, py, pz = _parse_float3(pos_attr.value)
            sx, sy, sz = _parse_float3(scale_attr.value)
            objects_js.append({
                "type": "tray",
                "name": "ModuleTray",
                "position": [px, pz, -py],
                "scale": [sx * 2, sz * 2, sy * 2],
                "color": "#B0BEC5",
            })

    # -- Robot arm base --
    robots = find_prims_by_name(scene, r"RobotArm_.*")
    for robot in robots:
        pos_attr = get_attribute(robot, "xformOp:translate")
        if pos_attr:
            px, py, pz = _parse_float3(pos_attr.value)
            reach_attr = get_attribute(robot, "robot:maxReach")
            reach = float(reach_attr.value) if reach_attr else 1.0
            objects_js.append({
                "type": "robot",
                "name": robot.name,
                "position": [px, pz, -py],
                "reach": reach,
                "color": "#D32F2F",
            })

    # -- Camera --
    cameras = find_prims_by_type(scene, "Camera")
    for cam in cameras:
        pos_attr = get_attribute(cam, "xformOp:translate")
        if pos_attr:
            px, py, pz = _parse_float3(pos_attr.value)
            objects_js.append({
                "type": "camera",
                "name": cam.name,
                "position": [px, pz, -py],
                "color": "#7B1FA2",
            })

    objects_json = json.dumps(objects_js)

    html = f'''
    <div id="viewport-container" style="width:100%; height:{height}px; position:relative; border-radius:8px; overflow:hidden; background:#1a1a2e;">
        <canvas id="three-canvas" style="width:100%; height:100%;"></canvas>
        <div id="info-overlay" style="position:absolute; top:10px; left:10px; color:#fff; font-family:monospace; font-size:11px; background:rgba(0,0,0,0.5); padding:6px 10px; border-radius:4px; pointer-events:none;">
            🔋 {len(cells)} cells | 🤖 {len(robots)} robot | 📷 {len(cameras)} camera | Scroll to zoom, drag to rotate
        </div>
    </div>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <script>
    (function() {{
        const container = document.getElementById('viewport-container');
        const canvas = document.getElementById('three-canvas');

        // Scene setup
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x1a1a2e);
        scene.fog = new THREE.Fog(0x1a1a2e, 3, 8);

        // Camera
        const camera = new THREE.PerspectiveCamera(55, container.clientWidth / container.clientHeight, 0.01, 100);
        camera.position.set(0.8, 0.8, 0.8);
        camera.lookAt(0.3, 0, -0.2);

        // Renderer
        const renderer = new THREE.WebGLRenderer({{ canvas: canvas, antialias: true }});
        renderer.setSize(container.clientWidth, container.clientHeight);
        renderer.setPixelRatio(window.devicePixelRatio);
        renderer.shadowMap.enabled = true;
        renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 1.2;

        // Lights
        const ambientLight = new THREE.AmbientLight(0x404060, 0.6);
        scene.add(ambientLight);

        const keyLight = new THREE.DirectionalLight(0xfff0e0, 1.2);
        keyLight.position.set(2, 3, 1);
        keyLight.castShadow = true;
        keyLight.shadow.mapSize.width = 1024;
        keyLight.shadow.mapSize.height = 1024;
        scene.add(keyLight);

        const fillLight = new THREE.DirectionalLight(0xe0e8ff, 0.4);
        fillLight.position.set(-1, 2, -1);
        scene.add(fillLight);

        const rimLight = new THREE.DirectionalLight(0x8080ff, 0.3);
        rimLight.position.set(0, 1, -2);
        scene.add(rimLight);

        // Grid
        const grid = new THREE.GridHelper(2, 20, 0x444466, 0x333355);
        scene.add(grid);

        // Axes (small)
        const axes = new THREE.AxesHelper(0.15);
        scene.add(axes);

        // Load scene objects
        const objects = {objects_json};

        objects.forEach(obj => {{
            if (obj.type === 'cell') {{
                const geo = new THREE.BoxGeometry(obj.scale[0], obj.scale[1], obj.scale[2]);
                const mat = new THREE.MeshStandardMaterial({{
                    color: obj.color,
                    roughness: 0.4,
                    metalness: 0.2,
                    transparent: false,
                }});
                const mesh = new THREE.Mesh(geo, mat);
                mesh.position.set(obj.position[0], obj.position[1], obj.position[2]);
                mesh.castShadow = true;
                mesh.receiveShadow = true;
                mesh.userData = {{ name: obj.name, cellType: obj.cellType }};
                scene.add(mesh);

                // Edge outline
                const edges = new THREE.EdgesGeometry(geo);
                const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({{ color: 0x000000, opacity: 0.3, transparent: true }}));
                line.position.copy(mesh.position);
                scene.add(line);

            }} else if (obj.type === 'tray') {{
                const geo = new THREE.BoxGeometry(obj.scale[0], obj.scale[1], obj.scale[2]);
                const mat = new THREE.MeshStandardMaterial({{
                    color: obj.color,
                    roughness: 0.6,
                    metalness: 0.1,
                    transparent: true,
                    opacity: 0.3,
                }});
                const mesh = new THREE.Mesh(geo, mat);
                mesh.position.set(obj.position[0], obj.position[1], obj.position[2]);
                mesh.receiveShadow = true;
                scene.add(mesh);

                // Wireframe
                const wire = new THREE.LineSegments(
                    new THREE.EdgesGeometry(geo),
                    new THREE.LineBasicMaterial({{ color: 0x607D8B, opacity: 0.6, transparent: true }})
                );
                wire.position.copy(mesh.position);
                scene.add(wire);

            }} else if (obj.type === 'robot') {{
                // Base cylinder
                const geo = new THREE.CylinderGeometry(0.06, 0.08, 0.15, 16);
                const mat = new THREE.MeshStandardMaterial({{
                    color: obj.color,
                    roughness: 0.3,
                    metalness: 0.5,
                }});
                const mesh = new THREE.Mesh(geo, mat);
                mesh.position.set(obj.position[0], 0.075, obj.position[2]);
                mesh.castShadow = true;
                scene.add(mesh);

                // Reach circle
                const reachGeo = new THREE.RingGeometry(obj.reach - 0.01, obj.reach, 64);
                const reachMat = new THREE.MeshBasicMaterial({{
                    color: 0xFF5252,
                    transparent: true,
                    opacity: 0.15,
                    side: THREE.DoubleSide,
                }});
                const reachMesh = new THREE.Mesh(reachGeo, reachMat);
                reachMesh.rotation.x = -Math.PI / 2;
                reachMesh.position.set(obj.position[0], 0.002, obj.position[2]);
                scene.add(reachMesh);

            }} else if (obj.type === 'camera') {{
                const geo = new THREE.ConeGeometry(0.04, 0.08, 4);
                const mat = new THREE.MeshStandardMaterial({{
                    color: obj.color,
                    roughness: 0.3,
                    metalness: 0.3,
                }});
                const mesh = new THREE.Mesh(geo, mat);
                mesh.position.set(obj.position[0], obj.position[1], obj.position[2]);
                mesh.rotation.x = Math.PI;
                scene.add(mesh);
            }}
        }});

        // Ground plane
        const groundGeo = new THREE.PlaneGeometry(3, 3);
        const groundMat = new THREE.MeshStandardMaterial({{
            color: 0x2a2a3e,
            roughness: 0.9,
        }});
        const ground = new THREE.Mesh(groundGeo, groundMat);
        ground.rotation.x = -Math.PI / 2;
        ground.position.y = -0.001;
        ground.receiveShadow = true;
        scene.add(ground);

        // Simple orbit controls (manual implementation)
        let isDragging = false;
        let prevMouse = {{ x: 0, y: 0 }};
        let spherical = {{ r: 1.2, theta: Math.PI / 4, phi: Math.PI / 4 }};
        const target = new THREE.Vector3(0.2, 0.05, -0.2);

        function updateCamera() {{
            camera.position.x = target.x + spherical.r * Math.sin(spherical.phi) * Math.cos(spherical.theta);
            camera.position.y = target.y + spherical.r * Math.cos(spherical.phi);
            camera.position.z = target.z + spherical.r * Math.sin(spherical.phi) * Math.sin(spherical.theta);
            camera.lookAt(target);
        }}
        updateCamera();

        canvas.addEventListener('mousedown', (e) => {{
            isDragging = true;
            prevMouse = {{ x: e.clientX, y: e.clientY }};
        }});
        canvas.addEventListener('mousemove', (e) => {{
            if (!isDragging) return;
            const dx = e.clientX - prevMouse.x;
            const dy = e.clientY - prevMouse.y;
            spherical.theta -= dx * 0.005;
            spherical.phi = Math.max(0.1, Math.min(Math.PI - 0.1, spherical.phi + dy * 0.005));
            prevMouse = {{ x: e.clientX, y: e.clientY }};
            updateCamera();
        }});
        canvas.addEventListener('mouseup', () => {{ isDragging = false; }});
        canvas.addEventListener('mouseleave', () => {{ isDragging = false; }});
        canvas.addEventListener('wheel', (e) => {{
            spherical.r = Math.max(0.3, Math.min(5, spherical.r + e.deltaY * 0.001));
            updateCamera();
            e.preventDefault();
        }});

        // Animation loop
        function animate() {{
            requestAnimationFrame(animate);
            renderer.render(scene, camera);
        }}
        animate();

        // Resize
        const ro = new ResizeObserver(() => {{
            const w = container.clientWidth;
            const h = container.clientHeight;
            camera.aspect = w / h;
            camera.updateProjectionMatrix();
            renderer.setSize(w, h);
        }});
        ro.observe(container);
    }})();
    </script>
    '''

    return html
