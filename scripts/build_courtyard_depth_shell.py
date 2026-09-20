"""Rasterize a Gaussian PLY into an equirectangular radial-depth texture."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, median_filter


def read_positions(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    data = path.read_bytes()
    marker = b"end_header\n"
    header_end = data.find(marker)
    if header_end < 0:
        raise ValueError("PLY header is missing end_header")
    header = data[:header_end].decode("ascii")
    if "format binary_little_endian 1.0" not in header:
        raise ValueError("Only binary little-endian PLY is supported")
    vertex_match = re.search(r"^element vertex (\d+)$", header, re.MULTILINE)
    if not vertex_match:
        raise ValueError("PLY header is missing the vertex count")
    vertex_count = int(vertex_match.group(1))
    property_count = len(re.findall(r"^property float ", header, re.MULTILINE))
    if property_count < 3:
        raise ValueError("PLY vertices must begin with float x, y, z")
    stride = property_count * 4
    vertices = np.frombuffer(
        data,
        dtype=np.dtype(
            [("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("rest", f"V{stride - 12}")]
        ),
        count=vertex_count,
        offset=header_end + len(marker),
    )
    return vertices["x"], vertices["y"], vertices["z"]


def rasterize_depth(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    *,
    width: int,
    height: int,
    max_depth: float,
) -> np.ndarray:
    # BLUNT cube-face PLY uses image-down Y; the stage and panorama use Y-up.
    y = -y
    radius = np.sqrt(x * x + y * y + z * z)
    valid = np.isfinite(radius) & (radius > 0.05) & (radius <= max_depth)
    x, y, z, radius = x[valid], y[valid], z[valid], radius[valid]

    longitude = np.arctan2(x, z)
    latitude = np.arcsin(np.clip(y / radius, -1, 1))
    pixel_x = np.floor((longitude / (2 * math.pi) + 0.5) * width).astype(np.int32)
    pixel_y = np.floor((0.5 - latitude / math.pi) * height).astype(np.int32)
    pixel_x %= width
    pixel_y = np.clip(pixel_y, 0, height - 1)

    depth = np.full(height * width, np.inf, dtype=np.float32)
    np.minimum.at(depth, pixel_y * width + pixel_x, radius)
    depth = depth.reshape(height, width)
    missing = ~np.isfinite(depth)
    if np.all(missing):
        raise ValueError("No finite depth samples were rasterized")
    nearest = distance_transform_edt(
        missing,
        return_distances=False,
        return_indices=True,
    )
    depth[missing] = depth[tuple(nearest[:, missing])]
    depth = median_filter(depth, size=3, mode="wrap")

    # Every longitude converges at an equirectangular pole. Blending those
    # rows toward one radius prevents the duplicated sphere vertices from
    # forming a visible starburst when the camera tilts toward the floor.
    cap_rows = max(2, height // 32)
    for offset in range(cap_rows):
        weight = (cap_rows - offset) / cap_rows
        for row in (offset, height - 1 - offset):
            median = np.median(depth[row])
            depth[row] = depth[row] * (1 - weight) + median * weight
    return depth


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--max-depth", type=float, default=40.0)
    args = parser.parse_args()
    if args.width < 64 or args.height < 32 or args.max_depth <= 0:
        parser.error("dimensions and max depth must be positive")

    x, y, z = read_positions(args.input)
    depth = rasterize_depth(
        x,
        y,
        z,
        width=args.width,
        height=args.height,
        max_depth=args.max_depth,
    )
    encoded = np.round(np.clip(depth / args.max_depth, 0, 1) * 255).astype(np.uint8)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(encoded, "L").save(args.output, optimize=True)
    metadata = {
        "projection": "equirectangular_radial_depth",
        "width": args.width,
        "height": args.height,
        "max_depth": args.max_depth,
        "source_vertices": len(x),
    }
    args.output.with_suffix(".json").write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output} from {len(x):,} Gaussian centers")


if __name__ == "__main__":
    main()
