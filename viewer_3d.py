"""
GLB scene exporter for Gradio's Model3D component.

Converts parsed USDA scene data into a GLB (binary glTF) file
that Gradio's gr.Model3D can display with full 3D orbit controls.

Uses trimesh to create colored box/cylinder meshes programmatically.
"""
import re
import numpy as np
import trimesh
from pathlib import Path

from usd_writer import parse_usda, find_prims_by_name, find_prims_by_type, get_attribute


# Cell type → RGBA color (0-255)
CELL_COLORS = {
    "LG_E63":   [76, 175, 80, 255],     # Green
    "HY_50Ah":  [33, 150, 243, 255],     # Blue
    "CATL_LFP": [255, 152, 0, 255],      # Orange
}
DEFAULT_COLOR = [158, 158, 158, 255]

TRAY_COLOR = [176, 190, 197, 100]        # Light gray, semi-transparent
ROBOT_COLOR = [211, 47, 47, 255]         # Red
GROUND_COLOR = [60, 60, 80, 255]         # Dark blue-gray
CAMERA_COLOR = [123, 31, 162, 255]       # Purple


def _parse_float3(value: str):
    """Parse (x, y, z) from USDA attribute value."""
    m = re.search(r'\((-?\d+\.?\d*),\s*(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\)', value)
    if m:
        return float(m.group(1)), float(m.group(2)), float(m.group(3))
    return 0, 0, 0


def _create_colored_box(size, position, color_rgba):
    """Create a box mesh with a uniform color."""
    box = trimesh.creation.box(extents=size)
    box.apply_translation(position)
    # Set vertex colors
    box.visual.vertex_colors = color_rgba
    return box


def _create_colored_cylinder(radius, height, position, color_rgba, segments=16):
    """Create a cylinder mesh with a uniform color."""
    cyl = trimesh.creation.cylinder(radius=radius, height=height, sections=segments)
    cyl.apply_translation(position)
    cyl.visual.vertex_colors = color_rgba
    return cyl


def _create_colored_cone(radius, height, position, color_rgba):
    """Create a cone mesh with uniform color."""
    cone = trimesh.creation.cone(radius=radius, height=height)
    cone.apply_translation(position)
    cone.visual.vertex_colors = color_rgba
    return cone


def usda_to_glb(usda_path: str, output_path: str = "outputs/scene.glb") -> str:
    """
    Convert a USDA scene file to GLB for Gradio's Model3D viewer.

    Parses the USDA, extracts object positions/sizes/colors,
    creates trimesh geometry, and exports as GLB.

    Args:
        usda_path: Path to a .usda file.
        output_path: Where to save the .glb file.

    Returns:
        Absolute path to the GLB file.
    """
    scene = parse_usda(usda_path)
    meshes = []

    # -- Ground plane --
    ground = _create_colored_box(
        size=[2.0, 0.005, 2.0],
        position=[0.4, -0.005, 0.3],
        color_rgba=GROUND_COLOR,
    )
    meshes.append(ground)

    # -- Module tray --
    trays = find_prims_by_name(scene, r"ModuleTray")
    for tray in trays:
        pos_attr = get_attribute(tray, "xformOp:translate")
        scale_attr = get_attribute(tray, "xformOp:scale")
        if pos_attr and scale_attr:
            px, py, pz = _parse_float3(pos_attr.value)
            sx, sy, sz = _parse_float3(scale_attr.value)
            # USD Z-up → GLB Y-up: swap Y and Z
            tray_mesh = _create_colored_box(
                size=[sx * 2, sz * 2, sy * 2],
                position=[px, pz, py],
                color_rgba=TRAY_COLOR,
            )
            meshes.append(tray_mesh)

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

        # USD Z-up → GLB Y-up: swap Y and Z
        cell_mesh = _create_colored_box(
            size=[sx * 2, sz * 2, sy * 2],
            position=[px, pz, py],
            color_rgba=color,
        )
        meshes.append(cell_mesh)

    # -- Robot arm base --
    robots = find_prims_by_name(scene, r"RobotArm_.*")
    for robot in robots:
        pos_attr = get_attribute(robot, "xformOp:translate")
        if pos_attr:
            px, py, pz = _parse_float3(pos_attr.value)

            # Base cylinder
            base = _create_colored_cylinder(
                radius=0.06,
                height=0.15,
                position=[px, 0.075, py],
                color_rgba=ROBOT_COLOR,
            )
            meshes.append(base)

            # Reach ring (thin large cylinder)
            reach_attr = get_attribute(robot, "robot:maxReach")
            if reach_attr:
                reach = float(reach_attr.value)
                # Create a thin ring using annulus approximation
                ring_outer = trimesh.creation.cylinder(radius=reach, height=0.003, sections=64)
                ring_inner = trimesh.creation.cylinder(radius=reach - 0.01, height=0.006, sections=64)
                try:
                    ring = trimesh.boolean.difference([ring_outer, ring_inner], engine="blender")
                except:
                    # Fallback: just use the outer cylinder as transparent indicator
                    ring = trimesh.creation.cylinder(radius=reach, height=0.002, sections=64)
                ring.apply_translation([px, 0.001, py])
                ring.visual.vertex_colors = [255, 82, 82, 40]
                meshes.append(ring)

    # -- Camera --
    cameras = find_prims_by_type(scene, "Camera")
    for cam in cameras:
        pos_attr = get_attribute(cam, "xformOp:translate")
        if pos_attr:
            px, py, pz = _parse_float3(pos_attr.value)
            # Small cone pointing down
            cam_mesh = _create_colored_cone(
                radius=0.03,
                height=0.06,
                position=[px, pz, py],
                color_rgba=CAMERA_COLOR,
            )
            meshes.append(cam_mesh)

    # -- Combine and export --
    if not meshes:
        # Create a dummy cube if nothing found
        meshes = [_create_colored_box([0.1, 0.1, 0.1], [0, 0, 0], [200, 200, 200, 255])]

    combined = trimesh.util.concatenate(meshes)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    combined.export(str(out), file_type="glb")

    return str(out.resolve())
