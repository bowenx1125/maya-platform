"""Render consistent perspective view sets from one courtyard panorama."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

VIEW_SETS = (
    ("eye", 0.0, 58.0),
    ("up", 12.0, 58.0),
    ("down", -12.0, 58.0),
    ("wide", 0.0, 82.0),
)


def render_view(
    panorama: np.ndarray,
    *,
    yaw_degrees: float,
    pitch_degrees: float,
    vertical_fov_degrees: float,
    width: int,
    height: int,
) -> Image.Image:
    """Project an equirectangular panorama into one rectilinear camera view."""
    half_height = math.tan(math.radians(vertical_fov_degrees) / 2)
    xs = np.linspace(-1, 1, width, dtype=np.float32)
    ys = np.linspace(1, -1, height, dtype=np.float32)
    xx, yy = np.meshgrid(xs, ys)
    rays = np.stack(
        (
            xx * (width / height) * half_height,
            yy * half_height,
            np.ones_like(xx),
        ),
        axis=-1,
    )
    rays /= np.linalg.norm(rays, axis=-1, keepdims=True)

    pitch = math.radians(pitch_degrees)
    yaw = math.radians(yaw_degrees)
    x_camera = rays[..., 0]
    y_camera = rays[..., 1]
    z_camera = rays[..., 2]
    y_pitched = y_camera * math.cos(pitch) + z_camera * math.sin(pitch)
    z_pitched = -y_camera * math.sin(pitch) + z_camera * math.cos(pitch)
    x_world = x_camera * math.cos(yaw) + z_pitched * math.sin(yaw)
    z_world = -x_camera * math.sin(yaw) + z_pitched * math.cos(yaw)

    longitude = np.arctan2(x_world, z_world)
    latitude = np.arcsin(np.clip(y_pitched, -1, 1))
    source_height, source_width = panorama.shape[:2]
    source_x = ((longitude / (2 * math.pi) + 0.5) * source_width) % source_width
    source_y = np.clip(
        (0.5 - latitude / math.pi) * (source_height - 1),
        0,
        source_height - 1,
    )

    x0 = np.floor(source_x).astype(np.int32)
    y0 = np.floor(source_y).astype(np.int32)
    x1 = (x0 + 1) % source_width
    y1 = np.minimum(y0 + 1, source_height - 1)
    wx = (source_x - x0)[..., None]
    wy = (source_y - y0)[..., None]
    pixels = (
        panorama[y0, x0] * (1 - wx) * (1 - wy)
        + panorama[y0, x1] * wx * (1 - wy)
        + panorama[y1, x0] * (1 - wx) * wy
        + panorama[y1, x1] * wx * wy
    )
    return Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), "RGB")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("panorama", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--views", type=int, default=24)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    args = parser.parse_args()
    if args.views < 4 or args.width < 64 or args.height < 64:
        parser.error("views must be >= 4 and dimensions must be >= 64")

    panorama = np.asarray(Image.open(args.panorama).convert("RGB"))
    args.output.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "source": str(args.panorama),
        "projection": "equirectangular",
        "camera_centers": 1,
        "note": (
            "Rotational views from one camera center; suitable for review and "
            "environment coverage, not translated multi-view photogrammetry."
        ),
        "sets": [],
    }
    sets = manifest["sets"]
    assert isinstance(sets, list)
    for set_name, pitch, fov in VIEW_SETS:
        set_directory = args.output / set_name
        set_directory.mkdir(exist_ok=True)
        files = []
        for index in range(args.views):
            yaw = index * 360 / args.views
            filename = f"{index + 1:03d}-yaw-{yaw:05.1f}.jpg"
            render_view(
                panorama,
                yaw_degrees=yaw,
                pitch_degrees=pitch,
                vertical_fov_degrees=fov,
                width=args.width,
                height=args.height,
            ).save(set_directory / filename, quality=92, subsampling=0)
            files.append(str(Path(set_name) / filename))
        sets.append(
            {
                "name": set_name,
                "pitch_degrees": pitch,
                "vertical_fov_degrees": fov,
                "files": files,
            }
        )

    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Rendered {len(VIEW_SETS) * args.views} views to {args.output}")


if __name__ == "__main__":
    main()
