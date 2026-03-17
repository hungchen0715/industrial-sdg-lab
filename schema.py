"""
Pydantic data models for the Industrial Synthetic Data Generation Lab.

Defines the structured configuration for domain randomization strategies,
scene parameters, and dataset output formats.
"""
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


# ── Randomization target categories ──
class RandomizationTarget(str, Enum):
    LIGHTING = "lighting"
    MATERIALS = "materials"
    CAMERA = "camera"
    OBJECT_POSE = "object_pose"


# ── Lighting parameter ranges ──
class LightingParams(BaseModel):
    intensity_min: float = Field(default=500.0, ge=0, description="Min light intensity (lux)")
    intensity_max: float = Field(default=3000.0, ge=0, description="Max light intensity (lux)")
    color_temp_min: float = Field(default=3200.0, description="Min color temperature (K)")
    color_temp_max: float = Field(default=6500.0, description="Max color temperature (K)")
    enabled: bool = Field(default=True, description="Whether to randomize lighting")


# ── Material parameter ranges ──
class MaterialParams(BaseModel):
    hue_shift_range: float = Field(default=0.08, ge=0, le=0.5, description="Max hue shift fraction")
    saturation_scale_min: float = Field(default=0.7, ge=0, description="Min saturation multiplier")
    saturation_scale_max: float = Field(default=1.3, ge=0, description="Max saturation multiplier")
    roughness_min: float = Field(default=0.2, ge=0, le=1.0, description="Min surface roughness")
    roughness_max: float = Field(default=0.9, ge=0, le=1.0, description="Max surface roughness")
    enabled: bool = Field(default=True, description="Whether to randomize materials")


# ── Camera parameter ranges ──
class CameraParams(BaseModel):
    position_jitter: float = Field(default=0.10, ge=0, description="Max camera position offset (m)")
    rotation_jitter: float = Field(default=3.0, ge=0, description="Max camera rotation offset (deg)")
    fov_min: float = Field(default=50.0, ge=10, le=120, description="Min field of view (deg)")
    fov_max: float = Field(default=75.0, ge=10, le=120, description="Max field of view (deg)")
    enabled: bool = Field(default=True, description="Whether to randomize camera")


# ── Object pose parameter ranges ──
class ObjectPoseParams(BaseModel):
    position_jitter: float = Field(default=0.003, ge=0, description="Max object position offset (m)")
    rotation_jitter: float = Field(default=2.0, ge=0, description="Max object rotation offset (deg)")
    enabled: bool = Field(default=True, description="Whether to randomize object poses")


# ── Complete randomization strategy ──
class RandomizationStrategy(BaseModel):
    lighting: LightingParams = Field(default_factory=LightingParams)
    materials: MaterialParams = Field(default_factory=MaterialParams)
    camera: CameraParams = Field(default_factory=CameraParams)
    object_pose: ObjectPoseParams = Field(default_factory=ObjectPoseParams)


# ── Top-level SDG configuration ──
class SDGConfig(BaseModel):
    scene_path: str = Field(
        ...,
        description="Path to the input .usda scene file"
    )
    output_dir: str = Field(
        default="outputs",
        description="Directory for generated dataset"
    )
    num_variants: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="Number of randomized variants to generate"
    )
    strategy: RandomizationStrategy = Field(
        default_factory=RandomizationStrategy,
        description="Randomization strategy configuration"
    )
    seed: Optional[int] = Field(
        default=None,
        description="Random seed for reproducibility (None = random each run)"
    )
    export_coco: bool = Field(
        default=True,
        description="Whether to export COCO-format annotations"
    )


# ── Single dataset sample ──
class BoundingBox(BaseModel):
    x: float = Field(..., description="Top-left x (pixels)")
    y: float = Field(..., description="Top-left y (pixels)")
    width: float = Field(..., description="Box width (pixels)")
    height: float = Field(..., description="Box height (pixels)")
    category_id: int = Field(..., description="COCO category ID")
    object_name: str = Field(..., description="Source prim name")


class DatasetSample(BaseModel):
    variant_id: int = Field(..., description="Variant index")
    scene_path: str = Field(..., description="Path to the randomized .usda file")
    annotations: list[BoundingBox] = Field(default_factory=list, description="Object annotations")
    metadata: dict = Field(default_factory=dict, description="Randomization params applied")
