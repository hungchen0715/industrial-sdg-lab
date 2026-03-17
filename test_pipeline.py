"""
Pipeline integration test for the Industrial SDG Lab.
Tests all core modules: schema, usd_writer, randomizer, dataset_export.
"""
import sys
import json
from pathlib import Path

def run_tests():
    passed = 0
    failed = 0
    
    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            print(f"  ✅ {name}")
            passed += 1
        else:
            print(f"  ❌ {name}: {detail}")
            failed += 1
    
    # ── Test 1: Schema ──
    print("\n" + "=" * 50)
    print("TEST 1: Schema Models")
    print("=" * 50)
    
    from schema import SDGConfig, RandomizationStrategy, LightingParams, BoundingBox
    
    config = SDGConfig(scene_path="test.usda", num_variants=5, seed=42)
    check("SDGConfig creation", config.num_variants == 5)
    check("SDGConfig defaults", config.strategy.lighting.enabled == True)
    check("SDGConfig JSON", '"scene_path"' in config.model_dump_json())
    
    bbox = BoundingBox(x=10, y=20, width=100, height=50, category_id=1, object_name="Cell_01")
    check("BoundingBox creation", bbox.width == 100)
    
    # ── Test 2: USD Writer ──
    print("\n" + "=" * 50)
    print("TEST 2: USD Writer")
    print("=" * 50)
    
    from usd_writer import create_sample_battery_scene, parse_usda, find_prims_by_name, find_prims_by_type, get_attribute, modify_attribute, write_usda
    
    # Create sample scene
    scene_path = create_sample_battery_scene("test_outputs/test_scene.usda")
    check("Sample scene created", Path(scene_path).exists())
    
    # Parse
    scene = parse_usda(scene_path)
    check("Scene parsed", scene.root is not None)
    check("Root is World", scene.root.name == "World")
    
    # Find cells
    cells = find_prims_by_name(scene, r"Cell_\d+")
    check("Found 6 cells", len(cells) == 6, f"found {len(cells)}")
    
    # Find lights
    lights = find_prims_by_type(scene, "DomeLight")
    check("Found DomeLight", len(lights) == 1, f"found {len(lights)}")
    
    # Find camera
    cameras = find_prims_by_type(scene, "Camera")
    check("Found Camera", len(cameras) == 1, f"found {len(cameras)}")
    
    # Get attribute
    if cells:
        cell_type = get_attribute(cells[0], "battery:cellType")
        check("Cell type attr", cell_type is not None and "LG_E63" in cell_type.value)
    
    # Modify attribute
    if lights:
        ok = modify_attribute(scene, lights[0], "inputs:intensity", "999")
        check("Modify attribute", ok)
        updated = get_attribute(lights[0], "inputs:intensity")
        check("Attribute updated", updated.value == "999")
    
    # Write back
    out_path = write_usda(scene, "test_outputs/modified_scene.usda")
    check("Write USDA", Path(out_path).exists())
    
    # Round-trip: re-parse
    scene2 = parse_usda(out_path)
    lights2 = find_prims_by_type(scene2, "DomeLight")
    if lights2:
        intensity2 = get_attribute(lights2[0], "inputs:intensity")
        check("Round-trip preserved", intensity2 is not None and intensity2.value == "999")
    
    # ── Test 3: Randomizer ──
    print("\n" + "=" * 50)
    print("TEST 3: Domain Randomization")
    print("=" * 50)
    
    from randomizer import generate_variants
    
    config = SDGConfig(
        scene_path=scene_path,
        output_dir="test_outputs",
        num_variants=5,
        seed=42,
    )
    
    variants = generate_variants(config)
    check("Generated 5 variants", len(variants) == 5)
    check("Variant files exist", all(Path(v.scene_path).exists() for v in variants))
    check("Lighting randomized", len(variants[0].lighting) > 0)
    check("Materials randomized", len(variants[0].materials) > 0)
    check("Camera randomized", len(variants[0].camera) > 0)
    check("Poses randomized", len(variants[0].object_poses) > 0)
    
    # Check variants are different
    if len(variants) >= 2:
        v0_light = variants[0].lighting
        v1_light = variants[1].lighting
        are_different = str(v0_light) != str(v1_light)
        check("Variants differ", are_different)
    
    # ── Test 4: COCO Export ──
    print("\n" + "=" * 50)
    print("TEST 4: COCO Dataset Export")
    print("=" * 50)
    
    from dataset_export import export_coco_dataset, create_dataset_manifest
    
    ann_path = export_coco_dataset(variants, "test_outputs")
    check("Annotations created", Path(ann_path).exists())
    
    with open(ann_path) as f:
        coco = json.load(f)
    
    check("COCO has images", len(coco["images"]) == 5)
    check("COCO has categories", len(coco["categories"]) >= 1)
    check("COCO has annotations", len(coco["annotations"]) > 0)
    check("Annotation has bbox", "bbox" in coco["annotations"][0])
    check("Bbox has 4 values", len(coco["annotations"][0]["bbox"]) == 4)
    
    manifest_path = create_dataset_manifest(variants, "test_outputs")
    check("Manifest created", Path(manifest_path).exists())
    
    # ── Test 5: Preview ──
    print("\n" + "=" * 50)
    print("TEST 5: Visualization")
    print("=" * 50)
    
    from preview import render_comparison
    
    comparison_path = render_comparison(variants, "test_outputs/comparison.png")
    check("Comparison plot created", Path(comparison_path).exists())
    
    # ── Summary ──
    print("\n" + "=" * 50)
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print("=" * 50)
    
    # Cleanup
    import shutil
    shutil.rmtree("test_outputs", ignore_errors=True)
    
    return failed == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
