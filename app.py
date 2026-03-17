"""
Industrial Synthetic Data Generation Lab — Gradio UI

Interactive interface for:
1. Load or create a sample USD scene
2. Configure domain randomization parameters
3. Generate N randomized scene variants
4. Preview: 4-panel distribution + variant grid + lighting comparison
5. Export COCO-format dataset annotations
6. View generated USDA and COCO JSON
"""
import gradio as gr
from pathlib import Path
import json

from schema import SDGConfig, RandomizationStrategy, LightingParams, MaterialParams, CameraParams, ObjectPoseParams
from usd_writer import create_sample_battery_scene, parse_usda
from randomizer import generate_variants
from dataset_export import export_coco_dataset, create_dataset_manifest
from preview import render_comparison, render_multi_variant_grid, render_lighting_comparison, render_scene_topdown
from viewer_3d import generate_viewport_html


def ensure_sample_scene() -> str:
    """Create sample scene if it doesn't exist."""
    sample_path = "sample_scenes/battery_module_2x3.usda"
    if not Path(sample_path).exists():
        create_sample_battery_scene(sample_path)
    return sample_path


def process(
    scene_choice: str,
    num_variants: int,
    seed: int,
    light_enabled: bool,
    light_min: float,
    light_max: float,
    mat_enabled: bool,
    mat_hue: float,
    mat_sat_min: float,
    mat_sat_max: float,
    cam_enabled: bool,
    cam_jitter: float,
    cam_fov_min: float,
    cam_fov_max: float,
    pose_enabled: bool,
    pose_jitter: float,
    pose_rot: float,
):
    """
    Full SDG pipeline: configure → randomize → export → visualize.
    Returns 8 outputs for rich display.
    """
    log_lines = []

    # ── Step 1: Scene ──
    log_lines.append("=" * 55)
    log_lines.append("STEP 1: Loading scene...")
    log_lines.append("=" * 55)

    scene_path = ensure_sample_scene()
    log_lines.append(f"  Scene loaded: {scene_path}")

    scene = parse_usda(scene_path)
    from usd_writer import find_prims_by_name
    cells = find_prims_by_name(scene, r"Cell_\d+")
    log_lines.append(f"  Found {len(cells)} battery cells in scene")

    # ── Step 2: Configure ──
    log_lines.append("")
    log_lines.append("=" * 55)
    log_lines.append("STEP 2: Configuring randomization strategy...")
    log_lines.append("=" * 55)

    config = SDGConfig(
        scene_path=scene_path,
        output_dir="outputs",
        num_variants=int(num_variants),
        seed=int(seed) if seed > 0 else None,
        strategy=RandomizationStrategy(
            lighting=LightingParams(
                intensity_min=light_min,
                intensity_max=light_max,
                enabled=light_enabled,
            ),
            materials=MaterialParams(
                hue_shift_range=mat_hue,
                saturation_scale_min=mat_sat_min,
                saturation_scale_max=mat_sat_max,
                enabled=mat_enabled,
            ),
            camera=CameraParams(
                position_jitter=cam_jitter,
                fov_min=cam_fov_min,
                fov_max=cam_fov_max,
                enabled=cam_enabled,
            ),
            object_pose=ObjectPoseParams(
                position_jitter=pose_jitter,
                rotation_jitter=pose_rot,
                enabled=pose_enabled,
            ),
        ),
    )

    enabled = []
    if light_enabled: enabled.append("Lighting")
    if mat_enabled: enabled.append("Materials")
    if cam_enabled: enabled.append("Camera")
    if pose_enabled: enabled.append("Object Pose")
    log_lines.append(f"  Enabled domains: {', '.join(enabled)}")
    log_lines.append(f"  Variants: {num_variants}, Seed: {seed if seed > 0 else 'random'}")

    # ── Step 3: Generate ──
    log_lines.append("")
    log_lines.append("=" * 55)
    log_lines.append(f"STEP 3: Generating {num_variants} randomized variants...")
    log_lines.append("=" * 55)

    try:
        variants = generate_variants(config)
        log_lines.append(f"  Generated {len(variants)} variants")
        for v in variants[:5]:
            log_lines.append(f"    variant_{v.variant_id:04d}: {Path(v.scene_path).name}")
        if len(variants) > 5:
            log_lines.append(f"    ... and {len(variants) - 5} more")
    except Exception as e:
        log_lines.append(f"  Generation failed: {e}")
        return "", "", "", None, None, None, None, "", "\n".join(log_lines)

    # ── Step 4: Export COCO ──
    log_lines.append("")
    log_lines.append("=" * 55)
    log_lines.append("STEP 4: Exporting COCO dataset annotations...")
    log_lines.append("=" * 55)

    coco_json_str = ""
    total_anns = 0
    try:
        ann_path = export_coco_dataset(variants, config.output_dir)
        manifest_path = create_dataset_manifest(variants, config.output_dir)
        log_lines.append(f"  COCO annotations: {ann_path}")
        log_lines.append(f"  Manifest: {manifest_path}")

        with open(ann_path, "r") as f:
            coco_data = json.load(f)
        total_anns = len(coco_data.get("annotations", []))
        log_lines.append(f"  Total annotations: {total_anns}")
        coco_json_str = json.dumps(coco_data, indent=2)
    except Exception as e:
        log_lines.append(f"  Export failed: {e}")

    # ── Step 5: Visualizations ──
    log_lines.append("")
    log_lines.append("=" * 55)
    log_lines.append("STEP 5: Rendering visualizations...")
    log_lines.append("=" * 55)

    # 5a: Distribution comparison
    comparison_path = None
    try:
        comparison_path = render_comparison(variants, f"{config.output_dir}/comparison.png")
        log_lines.append(f"  Distribution plot: OK")
    except Exception as e:
        log_lines.append(f"  Distribution plot failed: {e}")

    # 5b: Multi-variant grid
    grid_path = None
    try:
        grid_path = render_multi_variant_grid(variants, f"{config.output_dir}/variant_grid.png")
        log_lines.append(f"  Variant grid: OK")
    except Exception as e:
        log_lines.append(f"  Variant grid failed: {e}")

    # 5c: Lighting comparison
    lighting_path = None
    try:
        lighting_path = render_lighting_comparison(variants, f"{config.output_dir}/lighting_comparison.png")
        log_lines.append(f"  Lighting comparison: OK")
    except Exception as e:
        log_lines.append(f"  Lighting comparison failed: {e}")

    # 5d: Single variant topdown
    topdown_path = None
    try:
        topdown_path = render_scene_topdown(variants[0], f"{config.output_dir}/topdown_v0.png")
        log_lines.append(f"  Topdown view: OK")
    except Exception as e:
        log_lines.append(f"  Topdown view failed: {e}")

    # 5e: 3D viewport
    viewport_html = ""
    try:
        if variants:
            viewport_html = generate_viewport_html(variants[0].scene_path, height=500)
            log_lines.append(f"  3D viewport: OK")
    except Exception as e:
        log_lines.append(f"  3D viewport failed: {e}")

    # ── Step 6: Read sample USDA ──
    log_lines.append("")
    log_lines.append("=" * 55)
    log_lines.append("STEP 6: Done!")
    log_lines.append("=" * 55)

    usda_content = ""
    if variants:
        try:
            usda_content = Path(variants[0].scene_path).read_text(encoding="utf-8")
        except:
            usda_content = "(could not read variant file)"

    # ── Build summary ──
    summary_parts = [
        f"### Results",
        f"",
        f"**Generated {len(variants)} variants** from `{Path(scene_path).name}`",
        f"",
        f"**Randomization Domains:**",
    ]
    if light_enabled:
        summary_parts.append(f"- Lighting: {light_min:.0f} – {light_max:.0f} lux")
    if mat_enabled:
        summary_parts.append(f"- Materials: ±{mat_hue:.2f} hue shift")
    if cam_enabled:
        summary_parts.append(f"- Camera: ±{cam_jitter*100:.0f}cm jitter, {cam_fov_min:.0f}–{cam_fov_max:.0f}° FOV")
    if pose_enabled:
        summary_parts.append(f"- Object Pose: ±{pose_jitter*1000:.1f}mm / ±{pose_rot:.1f}°")

    summary_parts.append(f"")
    summary_parts.append(f"**Dataset:** {total_anns} COCO annotations exported")
    summary_parts.append(f"")
    summary_parts.append(f"**Output:** `{config.output_dir}/`")

    summary = "\n".join(summary_parts)

    return (
        summary,                # summary_output
        coco_json_str,          # coco_output
        viewport_html,          # viewport_output
        comparison_path,        # dist_output
        grid_path,              # grid_output
        lighting_path,          # lighting_output
        topdown_path,           # topdown_output
        usda_content,           # usda_output
        "\n".join(log_lines),   # log_output
    )


# ── Build Gradio UI ──
with gr.Blocks(
    title="Industrial SDG Lab",
    theme=gr.themes.Soft(
        primary_hue="blue",
        secondary_hue="slate",
    ),
) as demo:
    gr.Markdown(
        """
        # 🏭 Industrial Synthetic Data Generation Lab
        **Domain Randomization → COCO Dataset for Industrial AI**
        
        Load a USD scene → configure randomization → generate variants → export training data
        """
    )

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### ⚙️ Scene & Generation")
            scene_choice = gr.Dropdown(
                choices=["battery_module_2x3 (sample)"],
                value="battery_module_2x3 (sample)",
                label="Scene",
            )
            num_variants = gr.Slider(
                minimum=1, maximum=100, value=10, step=1,
                label="Number of Variants",
            )
            seed = gr.Number(value=42, label="Random Seed (0 = random)", precision=0)

        with gr.Column(scale=1):
            gr.Markdown("### 💡 Lighting Randomization")
            light_enabled = gr.Checkbox(value=True, label="Enable")
            light_min = gr.Slider(100, 5000, value=500, step=100, label="Min Intensity (lux)")
            light_max = gr.Slider(100, 5000, value=3000, step=100, label="Max Intensity (lux)")

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 🎨 Material Randomization")
            mat_enabled = gr.Checkbox(value=True, label="Enable")
            mat_hue = gr.Slider(0.0, 0.3, value=0.08, step=0.01, label="Hue Shift Range")
            mat_sat_min = gr.Slider(0.3, 1.0, value=0.7, step=0.05, label="Saturation Scale Min")
            mat_sat_max = gr.Slider(1.0, 2.0, value=1.3, step=0.05, label="Saturation Scale Max")

        with gr.Column(scale=1):
            gr.Markdown("### 📷 Camera Randomization")
            cam_enabled = gr.Checkbox(value=True, label="Enable")
            cam_jitter = gr.Slider(0.0, 0.5, value=0.10, step=0.01, label="Position Jitter (m)")
            cam_fov_min = gr.Slider(30, 90, value=50, step=5, label="FOV Min (°)")
            cam_fov_max = gr.Slider(30, 120, value=75, step=5, label="FOV Max (°)")

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 🔩 Object Pose Randomization")
            pose_enabled = gr.Checkbox(value=True, label="Enable")
            pose_jitter = gr.Slider(0.0, 0.01, value=0.003, step=0.001, label="Position Jitter (m)")
            pose_rot = gr.Slider(0.0, 10.0, value=2.0, step=0.5, label="Rotation Jitter (°)")

        with gr.Column(scale=1):
            submit_btn = gr.Button(
                "🚀 Generate & Export", variant="primary", size="lg",
            )

    gr.Markdown("---")

    # ── Summary ──
    summary_output = gr.Markdown(label="Summary")

    # ── Visual Outputs in Tabs ──
    with gr.Tabs():
        with gr.Tab("🧊 3D Viewport"):
            gr.Markdown("*Interactive 3D view — drag to rotate, scroll to zoom*")
            viewport_output = gr.HTML(
                label="3D Scene Viewport",
            )

        with gr.Tab("📊 Parameter Distributions"):
            dist_output = gr.Image(
                label="Randomization Parameter Distributions",
                type="filepath",
            )

        with gr.Tab("🔲 Variant Grid"):
            grid_output = gr.Image(
                label="Cell Layout Across Variants",
                type="filepath",
            )

        with gr.Tab("💡 Lighting Comparison"):
            lighting_output = gr.Image(
                label="Lighting Color/Intensity Across Variants",
                type="filepath",
            )

        with gr.Tab("🗺️ Scene Top-Down"):
            topdown_output = gr.Image(
                label="Variant #0 Top-Down View",
                type="filepath",
            )

        with gr.Tab("📝 Generated USDA"):
            usda_output = gr.Code(
                label="Randomized Variant #0 (USDA)",
                language="json",
                lines=25,
            )

        with gr.Tab("📦 COCO Annotations"):
            coco_output = gr.Code(
                label="annotations.json (COCO format)",
                language="json",
                lines=25,
            )

    with gr.Accordion("🔍 Processing Log", open=False):
        log_output = gr.Textbox(
            label="Full Pipeline Log",
            lines=20,
            interactive=False,
        )

    submit_btn.click(
        fn=process,
        inputs=[
            scene_choice, num_variants, seed,
            light_enabled, light_min, light_max,
            mat_enabled, mat_hue, mat_sat_min, mat_sat_max,
            cam_enabled, cam_jitter, cam_fov_min, cam_fov_max,
            pose_enabled, pose_jitter, pose_rot,
        ],
        outputs=[
            summary_output,
            coco_output,
            viewport_output,
            dist_output,
            grid_output,
            lighting_output,
            topdown_output,
            usda_output,
            log_output,
        ],
    )


if __name__ == "__main__":
    ensure_sample_scene()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7862,
        share=False,
    )
