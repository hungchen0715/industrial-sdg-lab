"""
Example: Basic Domain Randomization Pipeline

This script demonstrates the full SDG workflow:
1. Create or load a USD scene
2. Configure randomization strategy
3. Generate randomized variants
4. Export COCO-format annotations
5. Visualize randomization distributions
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schema import SDGConfig, RandomizationStrategy, LightingParams, MaterialParams
from usd_writer import create_sample_battery_scene
from randomizer import generate_variants
from dataset_export import export_coco_dataset, create_dataset_manifest
from preview import render_comparison


def main():
    # ── Step 1: Create a sample scene ──
    print("=" * 50)
    print("Step 1: Creating sample battery module scene...")
    scene_path = create_sample_battery_scene("sample_scenes/battery_module_2x3.usda")
    print(f"  ✅ Scene: {scene_path}")

    # ── Step 2: Configure randomization ──
    print("\nStep 2: Configuring domain randomization...")
    config = SDGConfig(
        scene_path=scene_path,
        output_dir="example_output",
        num_variants=20,
        seed=42,                  # Reproducible results
        strategy=RandomizationStrategy(
            lighting=LightingParams(
                intensity_min=800,
                intensity_max=2500,
            ),
            materials=MaterialParams(
                hue_shift_range=0.05,       # Conservative color shift
                saturation_scale_min=0.8,
                saturation_scale_max=1.2,
            ),
        ),
    )
    print(f"  ✅ {config.num_variants} variants, seed={config.seed}")
    print(f"  Domains: lighting, materials, camera, object_pose")

    # ── Step 3: Generate variants ──
    print(f"\nStep 3: Generating {config.num_variants} variants...")
    variants = generate_variants(config)
    print(f"  ✅ Generated {len(variants)} scene variants")

    for v in variants[:3]:
        print(f"    variant_{v.variant_id:04d}: "
              f"light={list(v.lighting.values())[0].get('intensity', '?') if v.lighting else '?'} lux, "
              f"cells_shifted={len(v.object_poses)}")

    # ── Step 4: Export COCO dataset ──
    print("\nStep 4: Exporting COCO annotations...")
    ann_path = export_coco_dataset(variants, config.output_dir)
    manifest_path = create_dataset_manifest(variants, config.output_dir)
    print(f"  ✅ Annotations: {ann_path}")
    print(f"  ✅ Manifest: {manifest_path}")

    # ── Step 5: Visualize ──
    print("\nStep 5: Rendering comparison plot...")
    plot_path = render_comparison(variants, f"{config.output_dir}/comparison.png")
    print(f"  ✅ Plot: {plot_path}")

    print("\n" + "=" * 50)
    print("✅ Pipeline complete!")
    print(f"   Output directory: {config.output_dir}/")
    print("=" * 50)


if __name__ == "__main__":
    main()
