"""
Pure-text USDA scene reader/writer for the Industrial SDG Lab.

Design decision: We avoid the pxr (OpenUSD) Python SDK because it requires
a platform-specific build from NVIDIA/Pixar. Instead, we parse and modify
.usda files as structured text. This is sufficient for domain randomization
(modifying attribute values) and produces files that any USD reader can load.

Limitations:
- Only handles flat-hierarchy USDA (no deep nesting beyond World/Prim)
- Attribute modification is regex-based on known patterns
- Not suitable for complex scene graph operations
"""
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class UsdAttribute:
    """A single USD attribute with its type, name, and value."""
    attr_type: str          # e.g. "float", "color3f[]", "float3"
    name: str               # e.g. "inputs:intensity", "xformOp:translate"
    value: str              # Raw string value, e.g. "1000", "(0.3, 0.5, 0.7)"
    is_custom: bool = False # Whether it uses the "custom" keyword
    line_number: int = 0


@dataclass
class UsdPrim:
    """A single USD prim (def block) with its type, name, and attributes."""
    prim_type: str          # e.g. "Cube", "Xform", "Camera", "DomeLight"
    name: str               # e.g. "Cell_01", "World", "InspectionCamera"
    path: str               # e.g. "/World/Cell_01"
    attributes: list[UsdAttribute] = field(default_factory=list)
    children: list['UsdPrim'] = field(default_factory=list)
    start_line: int = 0
    end_line: int = 0


@dataclass
class UsdScene:
    """Parsed representation of a USDA file."""
    header: str             # Everything before the first 'def' block
    root: Optional[UsdPrim] = None
    raw_lines: list[str] = field(default_factory=list)
    source_path: str = ""


# ── Regex patterns ──
_DEF_PATTERN = re.compile(
    r'^\s*def\s+(\w+)\s+"([^"]+)"', re.MULTILINE
)
_ATTR_PATTERN = re.compile(
    r'^\s*(custom\s+)?(\w[\w\[\]]*)\s+([\w:\.]+)\s*=\s*(.+)$'
)
_BRACE_OPEN = re.compile(r'\{')
_BRACE_CLOSE = re.compile(r'\}')


def parse_usda(filepath: str) -> UsdScene:
    """
    Parse a .usda file into a UsdScene structure.

    Args:
        filepath: Path to the .usda file.

    Returns:
        Parsed UsdScene with prims and attributes.
    """
    path = Path(filepath)
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    scene = UsdScene(
        header="",
        raw_lines=lines,
        source_path=str(path.resolve()),
    )

    # Find first 'def' to separate header
    first_def = -1
    for i, line in enumerate(lines):
        if _DEF_PATTERN.match(line):
            first_def = i
            break

    if first_def == -1:
        scene.header = content
        return scene

    scene.header = "\n".join(lines[:first_def])

    # Parse prim tree
    scene.root = _parse_prim_block(lines, first_def, "/")

    return scene


def _parse_prim_block(
    lines: list[str], start: int, parent_path: str
) -> Optional[UsdPrim]:
    """Recursively parse a def block and its children."""
    if start >= len(lines):
        return None

    match = _DEF_PATTERN.match(lines[start])
    if not match:
        return None

    prim = UsdPrim(
        prim_type=match.group(1),
        name=match.group(2),
        path=f"{parent_path}{match.group(2)}",
        start_line=start,
    )

    # Find matching braces
    depth = 0
    i = start
    found_open = False

    while i < len(lines):
        line = lines[i]
        for ch in line:
            if ch == '{':
                depth += 1
                found_open = True
            elif ch == '}':
                depth -= 1
                if found_open and depth == 0:
                    prim.end_line = i
                    break
        if found_open and depth == 0:
            break
        i += 1

    # Parse contents (attributes and child prims)
    j = start + 1
    while j < prim.end_line:
        line = lines[j].strip()

        # Check for child def
        child_match = _DEF_PATTERN.match(lines[j])
        if child_match:
            child = _parse_prim_block(lines, j, f"{prim.path}/")
            if child:
                prim.children.append(child)
                j = child.end_line + 1
                continue

        # Check for attribute
        attr = _parse_attribute(lines[j], j)
        if attr:
            prim.attributes.append(attr)

        j += 1

    return prim


def _parse_attribute(line: str, line_num: int) -> Optional[UsdAttribute]:
    """Parse a single attribute line."""
    stripped = line.strip()
    if not stripped or stripped.startswith('#') or stripped.startswith('('):
        return None

    match = _ATTR_PATTERN.match(stripped)
    if match:
        is_custom = match.group(1) is not None
        return UsdAttribute(
            attr_type=match.group(2),
            name=match.group(3),
            value=match.group(4).strip(),
            is_custom=is_custom,
            line_number=line_num,
        )
    return None


def find_prims_by_type(scene: UsdScene, prim_type: str) -> list[UsdPrim]:
    """Find all prims of a given type in the scene."""
    results = []
    if scene.root:
        _collect_prims(scene.root, prim_type, results)
    return results


def _collect_prims(prim: UsdPrim, prim_type: str, results: list):
    """Recursively collect prims matching a type."""
    if prim.prim_type == prim_type:
        results.append(prim)
    for child in prim.children:
        _collect_prims(child, prim_type, results)


def find_prims_by_name(scene: UsdScene, name_pattern: str) -> list[UsdPrim]:
    """Find all prims whose name matches a regex pattern."""
    results = []
    pattern = re.compile(name_pattern)
    if scene.root:
        _collect_prims_by_name(scene.root, pattern, results)
    return results


def _collect_prims_by_name(prim: UsdPrim, pattern, results: list):
    """Recursively collect prims matching a name pattern."""
    if pattern.search(prim.name):
        results.append(prim)
    for child in prim.children:
        _collect_prims_by_name(child, pattern, results)


def get_attribute(prim: UsdPrim, attr_name: str) -> Optional[UsdAttribute]:
    """Get an attribute from a prim by name."""
    for attr in prim.attributes:
        if attr.name == attr_name:
            return attr
    return None


def modify_attribute(
    scene: UsdScene,
    prim: UsdPrim,
    attr_name: str,
    new_value: str,
) -> bool:
    """
    Modify an attribute value in the scene's raw lines.

    Args:
        scene: The parsed UsdScene.
        prim: The prim containing the attribute.
        attr_name: Name of the attribute to modify.
        new_value: New value string.

    Returns:
        True if the attribute was found and modified.
    """
    attr = get_attribute(prim, attr_name)
    if attr is None:
        return False

    line = scene.raw_lines[attr.line_number]

    # Replace the value part after "= "
    eq_pos = line.find("= ")
    if eq_pos == -1:
        eq_pos = line.find("=")
        if eq_pos == -1:
            return False
        scene.raw_lines[attr.line_number] = line[:eq_pos + 1] + " " + new_value
    else:
        scene.raw_lines[attr.line_number] = line[:eq_pos + 2] + new_value

    # Update the parsed attribute too
    attr.value = new_value

    return True


def write_usda(scene: UsdScene, output_path: str) -> str:
    """
    Write a UsdScene back to a .usda file.

    Args:
        scene: The (possibly modified) UsdScene.
        output_path: Where to write the file.

    Returns:
        Absolute path to the written file.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(scene.raw_lines), encoding="utf-8")
    return str(out.resolve())


def create_sample_battery_scene(output_path: str = "sample_scenes/battery_module_2x3.usda") -> str:
    """
    Create a sample battery module assembly scene in USDA format.
    This serves as a demo scene for the SDG pipeline.

    Returns:
        Absolute path to the created .usda file.
    """
    usda = '''#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 1.0
    upAxis = "Z"
    doc = "Sample battery module: 2x3 LG E63 cells with UR10e robot"
)

def Xform "World"
{
    def DomeLight "AmbientLight"
    {
        float inputs:intensity = 1000
        color3f inputs:color = (1.0, 0.98, 0.95)
    }

    def DistantLight "KeyLight"
    {
        float inputs:intensity = 2500
        color3f inputs:color = (1.0, 0.96, 0.90)
        float3 xformOp:rotateXYZ = (315, 45, 0)
        uniform token[] xformOpOrder = ["xformOp:rotateXYZ"]
    }

    def Mesh "GroundPlane"
    {
        int[] faceVertexCounts = [4]
        int[] faceVertexIndices = [0, 1, 2, 3]
        point3f[] points = [(-5, -5, 0), (5, -5, 0), (5, 5, 0), (-5, 5, 0)]
        color3f[] primvars:displayColor = [(0.75, 0.78, 0.80)]
    }

    def Cube "ModuleTray"
    {
        float3 xformOp:translate = (0.4, 0.3, -0.01)
        float3 xformOp:scale = (0.4, 0.3, 0.01)
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]
        color3f[] primvars:displayColor = [(0.78, 0.80, 0.82)]
    }

    def Cube "Cell_01"
    {
        float3 xformOp:translate = (0.15, 0.15, 0.1)
        float3 xformOp:scale = (0.025, 0.06, 0.1)
        float xformOp:rotateY = 0.0
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateY", "xformOp:scale"]
        color3f[] primvars:displayColor = [(0.30, 0.69, 0.31)]
        custom string battery:cellType = "LG_E63"
        custom string battery:cellId = "Cell_01"
    }

    def Cube "Cell_02"
    {
        float3 xformOp:translate = (0.21, 0.15, 0.1)
        float3 xformOp:scale = (0.025, 0.06, 0.1)
        float xformOp:rotateY = 0.0
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateY", "xformOp:scale"]
        color3f[] primvars:displayColor = [(0.30, 0.69, 0.31)]
        custom string battery:cellType = "LG_E63"
        custom string battery:cellId = "Cell_02"
    }

    def Cube "Cell_03"
    {
        float3 xformOp:translate = (0.27, 0.15, 0.1)
        float3 xformOp:scale = (0.025, 0.06, 0.1)
        float xformOp:rotateY = 180.0
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateY", "xformOp:scale"]
        color3f[] primvars:displayColor = [(0.30, 0.69, 0.31)]
        custom string battery:cellType = "LG_E63"
        custom string battery:cellId = "Cell_03"
    }

    def Cube "Cell_04"
    {
        float3 xformOp:translate = (0.15, 0.30, 0.1)
        float3 xformOp:scale = (0.025, 0.06, 0.1)
        float xformOp:rotateY = 0.0
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateY", "xformOp:scale"]
        color3f[] primvars:displayColor = [(0.30, 0.69, 0.31)]
        custom string battery:cellType = "LG_E63"
        custom string battery:cellId = "Cell_04"
    }

    def Cube "Cell_05"
    {
        float3 xformOp:translate = (0.21, 0.30, 0.1)
        float3 xformOp:scale = (0.025, 0.06, 0.1)
        float xformOp:rotateY = 0.0
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateY", "xformOp:scale"]
        color3f[] primvars:displayColor = [(0.30, 0.69, 0.31)]
        custom string battery:cellType = "LG_E63"
        custom string battery:cellId = "Cell_05"
    }

    def Cube "Cell_06"
    {
        float3 xformOp:translate = (0.27, 0.30, 0.1)
        float3 xformOp:scale = (0.025, 0.06, 0.1)
        float xformOp:rotateY = 180.0
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateY", "xformOp:scale"]
        color3f[] primvars:displayColor = [(0.30, 0.69, 0.31)]
        custom string battery:cellType = "LG_E63"
        custom string battery:cellId = "Cell_06"
    }

    def Xform "RobotArm_UR10e"
    {
        float3 xformOp:translate = (0.0, 0.0, 0.0)
        uniform token[] xformOpOrder = ["xformOp:translate"]

        def Cylinder "Base"
        {
            float3 xformOp:scale = (0.08, 0.08, 0.15)
            float3 xformOp:translate = (0, 0, 0.075)
            uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]
            color3f[] primvars:displayColor = [(0.85, 0.20, 0.15)]
        }

        custom string robot:model = "UR10e"
        custom string robot:gripper = "Vacuum_Gripper_V1"
        custom double robot:maxReach = 1.30
        custom double robot:deadZone = 0.18
        custom double robot:payload = 12.5
    }

    def Camera "InspectionCamera"
    {
        float3 xformOp:translate = (0.4, 0.3, 1.2)
        uniform token[] xformOpOrder = ["xformOp:translate"]
        float focalLength = 35.0
        float horizontalAperture = 36
        custom float3 camera:lookAt = (0.4, 0.3, 0.0)
    }
}
'''
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(usda, encoding="utf-8")
    return str(out.resolve())
