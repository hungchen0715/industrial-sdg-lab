"""
Domain Randomization engine for the Industrial SDG Lab.

Applies controlled randomization to USD scene attributes to generate
diverse training data that bridges the Sim-to-Real gap. Each variant
records its exact randomization parameters as ground-truth metadata.

Randomization domains:
1. Lighting — intensity, color temperature
2. Materials — hue shift, saturation, roughness
3. Camera — position jitter, FOV variation
4. Object Pose — position/rotation micro-perturbations
"""
import random
import copy
import colorsys
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from schema import (
    SDGConfig,
    RandomizationStrategy,
    DatasetSample,
    BoundingBox,
)
from usd_writer import (
    UsdScene,
    UsdPrim,
    parse_usda,
    write_usda,
    find_prims_by_type,
    find_prims_by_name,
    get_attribute,
    modify_attribute,
)
from config import CELL_BASE_COLORS


@dataclass
class VariantRecord:
    """Records what was randomized in a single variant."""
    variant_id: int
    scene_path: str
    lighting: dict = field(default_factory=dict)
    materials: dict = field(default_factory=dict)
    camera: dict = field(default_factory=dict)
    object_poses: dict = field(default_factory=dict)


# ── Randomization Functions ──

def randomize_lighting(
    scene: UsdScene,
    intensity_min: float = 500.0,
    intensity_max: float = 3000.0,
    color_r_range: tuple = (0.85, 1.0),
    color_g_range: tuple = (0.80, 1.0),
    color_b_range: tuple = (0.75, 1.0),
) -> dict:
    """
    Randomize all light sources in the scene.

    Returns:
        Dict of light_name → {intensity, color} applied.
    """
    record = {}

    # Find DomeLight and DistantLight prims
    light_types = ["DomeLight", "DistantLight", "SphereLight", "RectLight"]
    for lt in light_types:
        lights = find_prims_by_type(scene, lt)
        for light in lights:
            new_intensity = round(random.uniform(intensity_min, intensity_max), 1)
            new_r = round(random.uniform(*color_r_range), 3)
            new_g = round(random.uniform(*color_g_range), 3)
            new_b = round(random.uniform(*color_b_range), 3)

            modify_attribute(scene, light, "inputs:intensity", str(new_intensity))
            modify_attribute(scene, light, "inputs:color", f"({new_r}, {new_g}, {new_b})")

            record[light.name] = {
                "intensity": new_intensity,
                "color": [new_r, new_g, new_b],
            }

    return record


def randomize_materials(
    scene: UsdScene,
    hue_shift_range: float = 0.08,
    saturation_scale_min: float = 0.7,
    saturation_scale_max: float = 1.3,
    value_scale_min: float = 0.6,
    value_scale_max: float = 1.2,
) -> dict:
    """
    Randomize material colors on all cell prims (identified by battery:cellType).

    Perturbs colors in HSV space for realistic variation.

    Returns:
        Dict of cell_name → {original_color, new_color} applied.
    """
    record = {}

    cells = find_prims_by_name(scene, r"Cell_\d+")
    for cell in cells:
        color_attr = get_attribute(cell, "primvars:displayColor")
        if not color_attr:
            continue

        # Parse the current color: [(r, g, b)]
        color_match = re.search(
            r'\((\d+\.?\d*),\s*(\d+\.?\d*),\s*(\d+\.?\d*)\)',
            color_attr.value,
        )
        if not color_match:
            continue

        orig_r = float(color_match.group(1))
        orig_g = float(color_match.group(2))
        orig_b = float(color_match.group(3))

        # Convert to HSV, perturb, convert back
        h, s, v = colorsys.rgb_to_hsv(orig_r, orig_g, orig_b)

        new_h = (h + random.uniform(-hue_shift_range, hue_shift_range)) % 1.0
        new_s = max(0.0, min(1.0, s * random.uniform(saturation_scale_min, saturation_scale_max)))
        new_v = max(0.0, min(1.0, v * random.uniform(value_scale_min, value_scale_max)))

        new_r, new_g, new_b = colorsys.hsv_to_rgb(new_h, new_s, new_v)
        new_r = round(new_r, 3)
        new_g = round(new_g, 3)
        new_b = round(new_b, 3)

        new_value = f"[({new_r}, {new_g}, {new_b})]"
        modify_attribute(scene, cell, "primvars:displayColor", new_value)

        record[cell.name] = {
            "original": [orig_r, orig_g, orig_b],
            "randomized": [new_r, new_g, new_b],
        }

    return record


def randomize_camera(
    scene: UsdScene,
    position_jitter: float = 0.10,
    fov_min: float = 50.0,
    fov_max: float = 75.0,
) -> dict:
    """
    Apply random perturbation to camera position and FOV.

    Returns:
        Dict with original and new camera parameters.
    """
    record = {}

    cameras = find_prims_by_type(scene, "Camera")
    for cam in cameras:
        pos_attr = get_attribute(cam, "xformOp:translate")
        focal_attr = get_attribute(cam, "focalLength")

        if pos_attr:
            # Parse position: (x, y, z)
            pos_match = re.search(
                r'\((-?\d+\.?\d*),\s*(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\)',
                pos_attr.value,
            )
            if pos_match:
                ox, oy, oz = float(pos_match.group(1)), float(pos_match.group(2)), float(pos_match.group(3))
                nx = round(ox + random.uniform(-position_jitter, position_jitter), 4)
                ny = round(oy + random.uniform(-position_jitter, position_jitter), 4)
                nz = round(oz + random.uniform(-position_jitter * 0.5, position_jitter * 0.5), 4)  # Less Z jitter
                modify_attribute(scene, cam, "xformOp:translate", f"({nx}, {ny}, {nz})")
                record["position"] = {
                    "original": [ox, oy, oz],
                    "randomized": [nx, ny, nz],
                }

        if focal_attr:
            # Randomize FOV by changing focal length
            import math
            new_fov = random.uniform(fov_min, fov_max)
            new_focal = round(36.0 / (2.0 * math.tan(math.radians(new_fov / 2))), 2)
            modify_attribute(scene, cam, "focalLength", str(new_focal))
            record["fov"] = round(new_fov, 1)
            record["focal_length"] = new_focal

    return record


def randomize_object_poses(
    scene: UsdScene,
    position_jitter: float = 0.003,
    rotation_jitter: float = 2.0,
) -> dict:
    """
    Apply micro-perturbations to battery cell positions and rotations.

    Small position jitter simulates real-world placement inaccuracies.
    Rotation jitter simulates slight misalignment within tolerance.

    Returns:
        Dict of cell_name → {position_delta, rotation_delta}.
    """
    record = {}

    cells = find_prims_by_name(scene, r"Cell_\d+")
    for cell in cells:
        pos_attr = get_attribute(cell, "xformOp:translate")
        rot_attr = get_attribute(cell, "xformOp:rotateY")

        if pos_attr:
            pos_match = re.search(
                r'\((-?\d+\.?\d*),\s*(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\)',
                pos_attr.value,
            )
            if pos_match:
                ox, oy, oz = float(pos_match.group(1)), float(pos_match.group(2)), float(pos_match.group(3))
                dx = round(random.uniform(-position_jitter, position_jitter), 5)
                dy = round(random.uniform(-position_jitter, position_jitter), 5)
                nx = round(ox + dx, 5)
                ny = round(oy + dy, 5)
                modify_attribute(scene, cell, "xformOp:translate", f"({nx}, {ny}, {oz})")

                cell_record = {"position_delta": [dx, dy, 0]}
            else:
                cell_record = {}
        else:
            cell_record = {}

        if rot_attr:
            try:
                orig_rot = float(rot_attr.value)
                d_rot = round(random.uniform(-rotation_jitter, rotation_jitter), 2)
                new_rot = round(orig_rot + d_rot, 2)
                modify_attribute(scene, cell, "xformOp:rotateY", str(new_rot))
                cell_record["rotation_delta"] = d_rot
            except ValueError:
                pass

        if cell_record:
            record[cell.name] = cell_record

    return record


# ── Main Variant Generation Pipeline ──

def generate_variants(config: SDGConfig) -> list[VariantRecord]:
    """
    Generate N randomized scene variants from a base USDA scene.

    For each variant:
    1. Load the original scene fresh
    2. Apply all enabled randomizations
    3. Write the modified scene to output_dir/variant_XXXX.usda
    4. Record the exact randomization parameters

    Args:
        config: SDG configuration with scene path, strategy, and output settings.

    Returns:
        List of VariantRecord objects describing each variant.
    """
    if config.seed is not None:
        random.seed(config.seed)

    strategy = config.strategy
    output_dir = Path(config.output_dir) / "scenes"
    output_dir.mkdir(parents=True, exist_ok=True)

    records = []

    for i in range(config.num_variants):
        # Fresh parse each time (modifications affect raw_lines in-place)
        scene = parse_usda(config.scene_path)

        record = VariantRecord(
            variant_id=i,
            scene_path="",
        )

        # Apply randomizations
        if strategy.lighting.enabled:
            record.lighting = randomize_lighting(
                scene,
                intensity_min=strategy.lighting.intensity_min,
                intensity_max=strategy.lighting.intensity_max,
            )

        if strategy.materials.enabled:
            record.materials = randomize_materials(
                scene,
                hue_shift_range=strategy.materials.hue_shift_range,
                saturation_scale_min=strategy.materials.saturation_scale_min,
                saturation_scale_max=strategy.materials.saturation_scale_max,
            )

        if strategy.camera.enabled:
            record.camera = randomize_camera(
                scene,
                position_jitter=strategy.camera.position_jitter,
                fov_min=strategy.camera.fov_min,
                fov_max=strategy.camera.fov_max,
            )

        if strategy.object_pose.enabled:
            record.object_poses = randomize_object_poses(
                scene,
                position_jitter=strategy.object_pose.position_jitter,
                rotation_jitter=strategy.object_pose.rotation_jitter,
            )

        # Write variant
        variant_filename = f"variant_{i:04d}.usda"
        variant_path = write_usda(scene, str(output_dir / variant_filename))
        record.scene_path = variant_path

        records.append(record)

    return records
