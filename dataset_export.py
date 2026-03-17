"""
COCO-format dataset exporter for the Industrial SDG Lab.

Converts domain-randomized scene variants into a standard COCO dataset
that can be used directly with object detection frameworks like
YOLOv8, Detectron2, or MMDetection.

The bounding boxes are computed by projecting 3D object positions
through the camera's perspective projection. This is a simplified
pinhole camera model — sufficient for synthetic data generation
where we have exact 3D coordinates.
"""
import json
import math
import re
from pathlib import Path
from datetime import datetime
from dataclasses import asdict

from schema import SDGConfig, BoundingBox, DatasetSample
from randomizer import VariantRecord
from usd_writer import (
    parse_usda,
    find_prims_by_name,
    find_prims_by_type,
    get_attribute,
)
from config import COCO, IMAGE_WIDTH, IMAGE_HEIGHT


def _parse_float3(value: str) -> tuple[float, float, float]:
    """Parse a USDA float3 value like '(0.15, 0.30, 0.1)'."""
    match = re.search(
        r'\((-?\d+\.?\d*),\s*(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\)',
        value,
    )
    if match:
        return float(match.group(1)), float(match.group(2)), float(match.group(3))
    return 0.0, 0.0, 0.0


def _project_to_image(
    world_pos: tuple[float, float, float],
    cam_pos: tuple[float, float, float],
    cam_look_at: tuple[float, float, float],
    focal_length: float,
    image_w: int = IMAGE_WIDTH,
    image_h: int = IMAGE_HEIGHT,
    sensor_w: float = 36.0,
) -> tuple[float, float]:
    """
    Project a 3D world position to 2D image coordinates using
    a simplified pinhole camera model.

    Returns:
        (u, v) pixel coordinates.
    """
    # Camera direction vector
    dx = cam_look_at[0] - cam_pos[0]
    dy = cam_look_at[1] - cam_pos[1]
    dz = cam_look_at[2] - cam_pos[2]
    dist = math.sqrt(dx*dx + dy*dy + dz*dz)
    if dist < 1e-6:
        return image_w / 2, image_h / 2

    # Forward vector (camera Z)
    fwd = (dx / dist, dy / dist, dz / dist)

    # Right vector (camera X) = fwd × up
    up = (0, 0, 1)
    right = (
        fwd[1] * up[2] - fwd[2] * up[1],
        fwd[2] * up[0] - fwd[0] * up[2],
        fwd[0] * up[1] - fwd[1] * up[0],
    )
    r_len = math.sqrt(right[0]**2 + right[1]**2 + right[2]**2)
    if r_len < 1e-6:
        return image_w / 2, image_h / 2
    right = (right[0] / r_len, right[1] / r_len, right[2] / r_len)

    # Recalculate up = right × fwd
    cam_up = (
        right[1] * fwd[2] - right[2] * fwd[1],
        right[2] * fwd[0] - right[0] * fwd[2],
        right[0] * fwd[1] - right[1] * fwd[0],
    )

    # Vector from camera to point
    to_point = (
        world_pos[0] - cam_pos[0],
        world_pos[1] - cam_pos[1],
        world_pos[2] - cam_pos[2],
    )

    # Project onto camera axes
    z = to_point[0] * fwd[0] + to_point[1] * fwd[1] + to_point[2] * fwd[2]
    if z <= 0:
        return -1, -1  # Behind camera

    x = to_point[0] * right[0] + to_point[1] * right[1] + to_point[2] * right[2]
    y = to_point[0] * cam_up[0] + to_point[1] * cam_up[1] + to_point[2] * cam_up[2]

    # Pinhole projection
    px_per_mm = image_w / sensor_w
    u = image_w / 2 + (x / z) * focal_length * px_per_mm
    v = image_h / 2 - (y / z) * focal_length * px_per_mm

    return u, v


def generate_annotations(variant: VariantRecord) -> list[BoundingBox]:
    """
    Generate bounding box annotations for a single scene variant.

    Reads the variant's USDA file and projects cell/tray/robot positions
    through the camera to produce 2D bounding boxes.

    Returns:
        List of BoundingBox annotations.
    """
    scene = parse_usda(variant.scene_path)
    annotations = []

    # Find camera
    cameras = find_prims_by_type(scene, "Camera")
    if not cameras:
        return annotations

    cam = cameras[0]
    cam_pos_attr = get_attribute(cam, "xformOp:translate")
    cam_look_attr = get_attribute(cam, "camera:lookAt")
    focal_attr = get_attribute(cam, "focalLength")

    if not (cam_pos_attr and cam_look_attr and focal_attr):
        return annotations

    cam_pos = _parse_float3(cam_pos_attr.value)
    cam_look = _parse_float3(cam_look_attr.value)
    focal = float(focal_attr.value)

    # -- Battery cells (category_id=1) --
    cells = find_prims_by_name(scene, r"Cell_\d+")
    for cell in cells:
        pos_attr = get_attribute(cell, "xformOp:translate")
        scale_attr = get_attribute(cell, "xformOp:scale")
        if not (pos_attr and scale_attr):
            continue

        pos = _parse_float3(pos_attr.value)
        scale = _parse_float3(scale_attr.value)

        # Project center and corners to get bbox
        u, v = _project_to_image(pos, cam_pos, cam_look, focal)
        if u < 0 or v < 0:
            continue

        # Approximate bbox size from scale
        half_w = scale[0]
        half_d = scale[1]
        corner1 = (pos[0] - half_w, pos[1] - half_d, pos[2])
        corner2 = (pos[0] + half_w, pos[1] + half_d, pos[2])

        u1, v1 = _project_to_image(corner1, cam_pos, cam_look, focal)
        u2, v2 = _project_to_image(corner2, cam_pos, cam_look, focal)

        if u1 < 0 or u2 < 0:
            continue

        x_min = max(0, min(u1, u2))
        y_min = max(0, min(v1, v2))
        x_max = min(IMAGE_WIDTH, max(u1, u2))
        y_max = min(IMAGE_HEIGHT, max(v1, v2))

        box_w = x_max - x_min
        box_h = y_max - y_min

        if box_w > 2 and box_h > 2:
            annotations.append(BoundingBox(
                x=round(x_min, 1),
                y=round(y_min, 1),
                width=round(box_w, 1),
                height=round(box_h, 1),
                category_id=1,
                object_name=cell.name,
            ))

    # -- Module tray (category_id=3) --
    trays = find_prims_by_name(scene, r"ModuleTray")
    for tray in trays:
        pos_attr = get_attribute(tray, "xformOp:translate")
        scale_attr = get_attribute(tray, "xformOp:scale")
        if not (pos_attr and scale_attr):
            continue

        pos = _parse_float3(pos_attr.value)
        scale = _parse_float3(scale_attr.value)

        u, v = _project_to_image(pos, cam_pos, cam_look, focal)
        if u < 0:
            continue

        corner1 = (pos[0] - scale[0], pos[1] - scale[1], pos[2])
        corner2 = (pos[0] + scale[0], pos[1] + scale[1], pos[2])
        u1, v1 = _project_to_image(corner1, cam_pos, cam_look, focal)
        u2, v2 = _project_to_image(corner2, cam_pos, cam_look, focal)

        if u1 >= 0 and u2 >= 0:
            annotations.append(BoundingBox(
                x=round(min(u1, u2), 1),
                y=round(min(v1, v2), 1),
                width=round(abs(u2 - u1), 1),
                height=round(abs(v2 - v1), 1),
                category_id=3,
                object_name="ModuleTray",
            ))

    return annotations


def export_coco_dataset(
    variants: list[VariantRecord],
    output_dir: str = "outputs",
) -> str:
    """
    Export all variant annotations as a single COCO-format JSON dataset.

    Args:
        variants: List of generated variant records.
        output_dir: Directory to write the annotations.json.

    Returns:
        Path to the annotations.json file.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    coco = {
        "info": {
            **COCO["info"],
            "date_created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
        "licenses": [],
        "categories": COCO["categories"],
        "images": [],
        "annotations": [],
    }

    ann_id = 1

    for variant in variants:
        image_id = variant.variant_id + 1
        image_filename = f"variant_{variant.variant_id:04d}.png"

        coco["images"].append({
            "id": image_id,
            "file_name": image_filename,
            "width": IMAGE_WIDTH,
            "height": IMAGE_HEIGHT,
            "usda_path": variant.scene_path,
        })

        # Generate annotations
        bboxes = generate_annotations(variant)

        for bbox in bboxes:
            coco["annotations"].append({
                "id": ann_id,
                "image_id": image_id,
                "category_id": bbox.category_id,
                "bbox": [bbox.x, bbox.y, bbox.width, bbox.height],
                "area": round(bbox.width * bbox.height, 1),
                "iscrowd": 0,
                "object_name": bbox.object_name,
            })
            ann_id += 1

    # Write
    annotations_path = out_dir / "annotations.json"
    annotations_path.write_text(
        json.dumps(coco, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return str(annotations_path.resolve())


def create_dataset_manifest(
    variants: list[VariantRecord],
    output_dir: str = "outputs",
) -> str:
    """
    Create a manifest file listing all variants and their metadata.

    Returns:
        Path to the manifest.json file.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_variants": len(variants),
        "variants": [],
    }

    for v in variants:
        manifest["variants"].append({
            "id": v.variant_id,
            "scene_path": v.scene_path,
            "randomization": {
                "lighting": v.lighting,
                "materials": v.materials,
                "camera": v.camera,
                "object_poses": v.object_poses,
            },
        })

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return str(manifest_path.resolve())
