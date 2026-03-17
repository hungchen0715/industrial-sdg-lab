"""
Visualization module for the Industrial SDG Lab.

Generates comparison plots showing randomization effects:
1. Before/after attribute comparison
2. Parameter distribution across variants
3. Scene top-down view with cell positions
"""
import matplotlib
matplotlib.use('Agg')

import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
import re
from pathlib import Path

from randomizer import VariantRecord
from config import PREVIEW_DPI


def render_comparison(
    records: list[VariantRecord],
    output_path: str = "outputs/comparison.png",
) -> str:
    """
    Render a multi-panel comparison showing how randomization
    changed key parameters across variants.
    """
    if not records:
        return ""

    fig, axes = plt.subplots(2, 2, figsize=(14, 6))
    fig.suptitle(
        f"Domain Randomization — {len(records)} Variants",
        fontsize=14, fontweight="bold",
    )

    # ── Panel 1: Lighting Intensity ──
    ax = axes[0, 0]
    intensities = []
    for r in records:
        for light_name, params in r.lighting.items():
            intensities.append(params.get("intensity", 0))
    if intensities:
        ax.hist(intensities, bins=min(20, len(intensities)),
                color="#FF9800", edgecolor="white", alpha=0.85)
        ax.axvline(np.mean(intensities), color="#E65100", linestyle="--",
                   label=f"Mean: {np.mean(intensities):.0f}")
        ax.legend(fontsize=8)
    ax.set_title("Light Intensity Distribution", fontsize=10, fontweight="bold")
    ax.set_xlabel("Intensity (lux)")
    ax.set_ylabel("Count")

    # ── Panel 2: Material Color Shifts ──
    ax = axes[0, 1]
    hue_deltas = []
    for r in records:
        for cell_name, params in r.materials.items():
            orig = params.get("original", [0, 0, 0])
            rand = params.get("randomized", [0, 0, 0])
            delta = sum((a - b) ** 2 for a, b in zip(orig, rand)) ** 0.5
            hue_deltas.append(delta)
    if hue_deltas:
        ax.hist(hue_deltas, bins=min(20, len(hue_deltas)),
                color="#4CAF50", edgecolor="white", alpha=0.85)
        ax.axvline(np.mean(hue_deltas), color="#1B5E20", linestyle="--",
                   label=f"Mean delta: {np.mean(hue_deltas):.4f}")
        ax.legend(fontsize=8)
    ax.set_title("Material Color Shift Magnitude", fontsize=10, fontweight="bold")
    ax.set_xlabel("RGB Distance")
    ax.set_ylabel("Count")

    # ── Panel 3: Camera Position Jitter ──
    ax = axes[1, 0]
    cam_x_offsets = []
    cam_y_offsets = []
    for r in records:
        cam = r.camera
        if "position" in cam:
            orig = cam["position"]["original"]
            rand = cam["position"]["randomized"]
            cam_x_offsets.append(rand[0] - orig[0])
            cam_y_offsets.append(rand[1] - orig[1])
    if cam_x_offsets:
        ax.scatter(cam_x_offsets, cam_y_offsets,
                   c="#2196F3", alpha=0.6, edgecolors="white", s=40)
        ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")
        ax.axvline(0, color="gray", linewidth=0.5, linestyle="--")
    ax.set_title("Camera Position Jitter (XY)", fontsize=10, fontweight="bold")
    ax.set_xlabel("dX (meters)")
    ax.set_ylabel("dY (meters)")
    ax.set_aspect("equal")

    # ── Panel 4: Object Pose Perturbation ──
    ax = axes[1, 1]
    pos_deltas = []
    rot_deltas = []
    for r in records:
        for cell_name, params in r.object_poses.items():
            pd = params.get("position_delta", [0, 0, 0])
            pos_deltas.append((pd[0] ** 2 + pd[1] ** 2) ** 0.5 * 1000)
            if "rotation_delta" in params:
                rot_deltas.append(abs(params["rotation_delta"]))

    if pos_deltas:
        ax.hist(pos_deltas, bins=min(20, len(pos_deltas)),
                color="#9C27B0", edgecolor="white", alpha=0.85,
                label="Position (mm)")
    if rot_deltas:
        ax2 = ax.twinx()
        ax2.hist(rot_deltas, bins=min(20, len(rot_deltas)),
                 color="#F44336", edgecolor="white", alpha=0.4,
                 label="Rotation (deg)")
        ax2.set_ylabel("Rotation Count", fontsize=8, color="#F44336")
        ax2.legend(fontsize=7, loc="upper left")
    ax.set_title("Object Pose Perturbation", fontsize=10, fontweight="bold")
    ax.set_xlabel("Magnitude")
    ax.set_ylabel("Position Count")
    if pos_deltas:
        ax.legend(fontsize=7, loc="upper right")

    plt.tight_layout()

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out), dpi=PREVIEW_DPI, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)

    return str(out.resolve())


def render_scene_topdown(
    variant: VariantRecord,
    output_path: str = "outputs/topdown.png",
) -> str:
    """
    Render a top-down view of a single variant showing cell positions.
    """
    from usd_writer import parse_usda, find_prims_by_name, find_prims_by_type, get_attribute

    scene = parse_usda(variant.scene_path)
    cells = find_prims_by_name(scene, r"Cell_\d+")

    fig, ax = plt.subplots(1, 1, figsize=(8, 6))
    ax.set_title(
        f"Variant #{variant.variant_id:04d} — Top-Down View",
        fontsize=12, fontweight="bold",
    )

    colors = plt.cm.Set2(np.linspace(0, 1, max(len(cells), 1)))

    for idx, cell in enumerate(cells):
        pos_attr = get_attribute(cell, "xformOp:translate")
        scale_attr = get_attribute(cell, "xformOp:scale")
        if not (pos_attr and scale_attr):
            continue

        pos_match = re.search(
            r'\((-?\d+\.?\d*),\s*(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\)',
            pos_attr.value,
        )
        scale_match = re.search(
            r'\((-?\d+\.?\d*),\s*(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\)',
            scale_attr.value,
        )
        if not (pos_match and scale_match):
            continue

        px = float(pos_match.group(1))
        py = float(pos_match.group(2))
        sw = float(scale_match.group(1))
        sd = float(scale_match.group(2))

        rect = patches.Rectangle(
            (px - sw, py - sd), sw * 2, sd * 2,
            linewidth=1.5, edgecolor="black",
            facecolor=colors[idx], alpha=0.75,
        )
        ax.add_patch(rect)
        ax.annotate(
            cell.name.replace("Cell_", "C"),
            xy=(px, py), ha="center", va="center",
            fontsize=7, fontweight="bold",
        )

    # Draw tray
    trays = find_prims_by_name(scene, r"ModuleTray")
    for tray in trays:
        pos_attr = get_attribute(tray, "xformOp:translate")
        scale_attr = get_attribute(tray, "xformOp:scale")
        if pos_attr and scale_attr:
            pos_m = re.search(r'\((-?\d+\.?\d*),\s*(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\)', pos_attr.value)
            scl_m = re.search(r'\((-?\d+\.?\d*),\s*(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\)', scale_attr.value)
            if pos_m and scl_m:
                tx, ty = float(pos_m.group(1)), float(pos_m.group(2))
                tsx, tsy = float(scl_m.group(1)), float(scl_m.group(2))
                tray_rect = patches.Rectangle(
                    (tx - tsx, ty - tsy), tsx * 2, tsy * 2,
                    linewidth=2, edgecolor="#37474F", facecolor="#ECEFF1",
                    alpha=0.3, linestyle="--", label="Module Tray",
                )
                ax.add_patch(tray_rect)

    ax.set_xlabel("X (meters)")
    ax.set_ylabel("Y (meters)")
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.2)
    ax.legend(fontsize=8)
    ax.autoscale()

    plt.tight_layout()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out), dpi=PREVIEW_DPI, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)

    return str(out.resolve())


def render_multi_variant_grid(
    variants: list[VariantRecord],
    output_path: str = "outputs/variant_grid.png",
    max_show: int = 6,
) -> str:
    """
    Render a grid showing multiple variants' cell layouts side by side.
    Demonstrates visual diversity from randomization.
    """
    from usd_writer import parse_usda, find_prims_by_name, get_attribute

    n = min(len(variants), max_show)
    cols = min(3, n)
    rows = (n + cols - 1) // cols

    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 4 * rows))
    fig.suptitle(
        f"Cell Layout Across {n} Variants (showing pose jitter)",
        fontsize=13, fontweight="bold",
    )

    if n == 1:
        axes = np.array([axes])
    axes = np.atleast_2d(axes)

    cell_colors = {
        "LG_E63": "#4CAF50",
        "HY_50Ah": "#2196F3",
        "CATL_LFP": "#FF9800",
    }

    for idx in range(n):
        row, col = divmod(idx, cols)
        ax = axes[row, col]
        v = variants[idx]

        scene = parse_usda(v.scene_path)
        cells = find_prims_by_name(scene, r"Cell_\d+")

        for cell in cells:
            pos_attr = get_attribute(cell, "xformOp:translate")
            scale_attr = get_attribute(cell, "xformOp:scale")
            type_attr = get_attribute(cell, "battery:cellType")
            if not (pos_attr and scale_attr):
                continue

            pos_m = re.search(r'\((-?\d+\.?\d*),\s*(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\)', pos_attr.value)
            scl_m = re.search(r'\((-?\d+\.?\d*),\s*(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\)', scale_attr.value)
            if not (pos_m and scl_m):
                continue

            px, py = float(pos_m.group(1)), float(pos_m.group(2))
            sw, sd = float(scl_m.group(1)), float(scl_m.group(2))

            ctype = type_attr.value.strip('"') if type_attr else "unknown"
            color = cell_colors.get(ctype, "#9E9E9E")

            rect = patches.Rectangle(
                (px - sw, py - sd), sw * 2, sd * 2,
                linewidth=1, edgecolor="#263238",
                facecolor=color, alpha=0.8,
            )
            ax.add_patch(rect)
            ax.annotate(
                cell.name.replace("Cell_", "C"),
                xy=(px, py), ha="center", va="center",
                fontsize=6, fontweight="bold", color="white",
            )

        ax.set_title(f"Variant #{v.variant_id:04d}", fontsize=9)
        ax.set_xlim(0.05, 0.40)
        ax.set_ylim(0.05, 0.45)
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.15)

    # Hide empty subplots
    for idx in range(n, rows * cols):
        row, col = divmod(idx, cols)
        axes[row, col].set_visible(False)

    plt.tight_layout()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out), dpi=PREVIEW_DPI, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)

    return str(out.resolve())


def render_lighting_comparison(
    variants: list[VariantRecord],
    output_path: str = "outputs/lighting_comparison.png",
    max_show: int = 8,
) -> str:
    """
    Render colored squares showing how light color varies across variants.
    Simulates what different lighting conditions would look like.
    """
    n = min(len(variants), max_show)

    fig, axes = plt.subplots(1, n, figsize=(2 * n, 3))
    fig.suptitle("Lighting Color Across Variants", fontsize=12, fontweight="bold")

    if n == 1:
        axes = [axes]

    for i in range(n):
        ax = axes[i]
        v = variants[i]

        # Get the first light's color
        color = [1.0, 0.98, 0.95]  # default
        intensity = 1000
        for light_name, params in v.lighting.items():
            color = params.get("color", color)
            intensity = params.get("intensity", intensity)
            break

        # Adjust brightness by intensity (normalized to 0-1 range)
        brightness = min(1.0, intensity / 3000.0)
        display_color = [c * brightness for c in color]

        ax.fill([0, 1, 1, 0], [0, 0, 1, 1], color=display_color)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(f"#{i}\n{intensity:.0f} lux", fontsize=7)
        ax.set_aspect("equal")

    plt.tight_layout()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(out), dpi=PREVIEW_DPI, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)

    return str(out.resolve())
