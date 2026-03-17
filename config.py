"""
Configuration for the Industrial Synthetic Data Generation Lab.

Defines randomization parameter ranges, output formats, and
default settings for the domain randomization pipeline.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Output Settings ──
OUTPUT_DIR = os.getenv("SDG_OUTPUT_DIR", "outputs")
DEFAULT_NUM_VARIANTS = 10
IMAGE_WIDTH = 1024
IMAGE_HEIGHT = 768

# ── Lighting Randomization Ranges ──
LIGHTING = {
    "intensity_range": (500.0, 3000.0),       # lux
    "color_temp_range": (3200.0, 6500.0),      # Kelvin (warm tungsten → daylight)
    "color_r_range": (0.85, 1.0),
    "color_g_range": (0.80, 1.0),
    "color_b_range": (0.75, 1.0),
}

# ── Material Randomization Ranges ──
MATERIALS = {
    "color_hue_shift": (-0.08, 0.08),          # Fraction of hue wheel
    "color_saturation_scale": (0.7, 1.3),
    "color_value_scale": (0.6, 1.2),
    "roughness_range": (0.2, 0.9),
    "metallic_range": (0.0, 0.5),
}

# ── Camera Randomization Ranges ──
CAMERA = {
    "position_jitter": (-0.10, 0.10),          # meters per axis
    "rotation_jitter": (-3.0, 3.0),            # degrees per axis
    "fov_range": (50.0, 75.0),                 # degrees
}

# ── Object Pose Randomization ──
OBJECT_POSE = {
    "position_jitter": (-0.003, 0.003),        # meters (±3mm)
    "rotation_jitter": (-2.0, 2.0),            # degrees
}

# ── Battery Cell Visual Properties ──
# Base colors for randomization (will be perturbed per variant)
CELL_BASE_COLORS = {
    "LG_E63":   (0.30, 0.69, 0.31),     # Green
    "HY_50Ah":  (0.13, 0.59, 0.95),     # Blue
    "CATL_LFP": (1.00, 0.60, 0.00),     # Orange
}

# ── COCO Dataset Settings ──
COCO = {
    "info": {
        "description": "Industrial Battery Module Assembly — Synthetic Dataset",
        "version": "1.0",
        "contributor": "industrial-sdg-lab",
    },
    "categories": [
        {"id": 1, "name": "battery_cell", "supercategory": "component"},
        {"id": 2, "name": "robot_arm", "supercategory": "equipment"},
        {"id": 3, "name": "module_tray", "supercategory": "fixture"},
    ],
}

# ── Preview Settings ──
PREVIEW_DPI = 120
PREVIEW_FIGSIZE = (14, 6)
