from __future__ import annotations

import argparse
import math
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image

SH_C0 = 0.28209479177387814
FLOOR_Y = -0.42


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build Maya's deterministic national-style courtyard splat."
    )
    parser.add_argument("output", type=Path)
    parser.add_argument("--seed", type=int, default=1125)
    parser.add_argument(
        "--texture",
        type=Path,
        help="Optional front-view courtyard image baked onto visible Gaussians.",
    )
    parser.add_argument("--texture-fov", type=float, default=58)
    return parser.parse_args()


class SplatScene:
    def __init__(self, seed: int) -> None:
        self.rng = np.random.default_rng(seed)
        self.chunks: list[np.ndarray] = []

    @staticmethod
    def _quaternion_from_z(normals: np.ndarray) -> np.ndarray:
        normals = normals / np.linalg.norm(normals, axis=1, keepdims=True)
        quaternions = np.zeros((len(normals), 4), dtype=np.float32)
        dot = normals[:, 2]
        regular = dot > -0.9999
        quaternions[regular, 0] = 1 + dot[regular]
        quaternions[regular, 1] = -normals[regular, 1]
        quaternions[regular, 2] = normals[regular, 0]
        quaternions[~regular, 1] = 1
        quaternions /= np.linalg.norm(quaternions, axis=1, keepdims=True)
        return quaternions

    def add_samples(
        self,
        positions: np.ndarray,
        normals: np.ndarray,
        colors: np.ndarray,
        tangent_scale: float | np.ndarray,
        normal_scale: float = 0.008,
        opacity: float = 0.995,
    ) -> None:
        count = len(positions)
        if count == 0:
            return
        colors = np.broadcast_to(np.asarray(colors, dtype=np.float32), (count, 3))
        colors = np.clip(
            colors + self.rng.normal(0, 0.008, size=colors.shape), 0.01, 0.99
        )
        tangent = np.broadcast_to(np.asarray(tangent_scale, dtype=np.float32), (count,))
        scales = np.column_stack((tangent, tangent, np.full(count, normal_scale)))
        rotations = self._quaternion_from_z(normals.astype(np.float32))
        chunk = np.zeros((count, 17), dtype=np.float32)
        chunk[:, :3] = positions
        chunk[:, 3:6] = normals
        chunk[:, 6:9] = (colors - 0.5) / SH_C0
        chunk[:, 9] = math.log(opacity / (1 - opacity))
        chunk[:, 10:13] = np.log(np.maximum(scales, 0.001))
        chunk[:, 13:17] = rotations
        self.chunks.append(chunk)

    def add_plane(
        self,
        origin: tuple[float, float, float],
        u: tuple[float, float, float],
        v: tuple[float, float, float],
        spacing: float,
        color: tuple[float, float, float]
        | Callable[[np.ndarray, np.ndarray], np.ndarray],
        jitter: float = 0.34,
        normal_scale: float = 0.008,
    ) -> None:
        origin_v = np.asarray(origin, dtype=np.float32)
        u_v = np.asarray(u, dtype=np.float32)
        v_v = np.asarray(v, dtype=np.float32)
        nu = max(2, math.ceil(np.linalg.norm(u_v) / spacing))
        nv = max(2, math.ceil(np.linalg.norm(v_v) / spacing))
        uu, vv = np.meshgrid(
            (np.arange(nu) + 0.5) / nu,
            (np.arange(nv) + 0.5) / nv,
            indexing="xy",
        )
        uu += self.rng.uniform(-jitter, jitter, uu.shape) / nu
        vv += self.rng.uniform(-jitter, jitter, vv.shape) / nv
        positions = origin_v + uu.reshape(-1, 1) * u_v + vv.reshape(-1, 1) * v_v
        normal = np.cross(u_v, v_v)
        normal /= np.linalg.norm(normal)
        normals = np.broadcast_to(normal, positions.shape).copy()
        if callable(color):
            colors = color(uu.ravel(), vv.ravel())
        else:
            colors = np.asarray(color, dtype=np.float32)
        tangent = max(np.linalg.norm(u_v) / nu, np.linalg.norm(v_v) / nv) * 0.72
        self.add_samples(positions, normals, colors, tangent, normal_scale)

    def add_box(
        self,
        center: tuple[float, float, float],
        size: tuple[float, float, float],
        spacing: float,
        color: tuple[float, float, float],
    ) -> None:
        cx, cy, cz = center
        sx, sy, sz = size
        x0, y0, z0 = cx - sx / 2, cy - sy / 2, cz - sz / 2
        self.add_plane((x0, y0, z0), (sx, 0, 0), (0, sy, 0), spacing, color)
        self.add_plane((x0, y0, z0 + sz), (0, sy, 0), (sx, 0, 0), spacing, color)
        self.add_plane((x0, y0, z0), (0, sy, 0), (0, 0, sz), spacing, color)
        self.add_plane((x0 + sx, y0, z0), (0, 0, sz), (0, sy, 0), spacing, color)
        self.add_plane((x0, y0, z0), (0, 0, sz), (sx, 0, 0), spacing, color)
        self.add_plane((x0, y0 + sy, z0), (sx, 0, 0), (0, 0, sz), spacing, color)

    def add_cylinder(
        self,
        center: tuple[float, float, float],
        axis: tuple[float, float, float],
        radius: float,
        length: float,
        spacing: float,
        color: tuple[float, float, float],
    ) -> None:
        axis_v = np.asarray(axis, dtype=np.float32)
        axis_v /= np.linalg.norm(axis_v)
        helper = np.array([0, 1, 0], dtype=np.float32)
        if abs(float(np.dot(helper, axis_v))) > 0.9:
            helper = np.array([1, 0, 0], dtype=np.float32)
        basis_a = np.cross(axis_v, helper)
        basis_a /= np.linalg.norm(basis_a)
        basis_b = np.cross(axis_v, basis_a)
        around = max(12, math.ceil(2 * math.pi * radius / spacing))
        along = max(2, math.ceil(length / spacing))
        theta, along_t = np.meshgrid(
            (np.arange(around) + 0.5) * 2 * math.pi / around,
            (np.arange(along) + 0.5) / along - 0.5,
            indexing="xy",
        )
        radial = (
            np.cos(theta).reshape(-1, 1) * basis_a
            + np.sin(theta).reshape(-1, 1) * basis_b
        )
        positions = (
            np.asarray(center, dtype=np.float32)
            + along_t.reshape(-1, 1) * length * axis_v
            + radius * radial
        )
        self.add_samples(positions, radial, color, spacing * 0.72)

    def add_ellipsoid(
        self,
        center: tuple[float, float, float],
        radii: tuple[float, float, float],
        spacing: float,
        colors: list[tuple[float, float, float]],
    ) -> None:
        rx, ry, rz = radii
        around = max(18, math.ceil(2 * math.pi * max(rx, rz) / spacing))
        vertical = max(10, math.ceil(math.pi * ry / spacing))
        theta, phi = np.meshgrid(
            (np.arange(around) + 0.5) * 2 * math.pi / around,
            (np.arange(vertical) + 0.5) * math.pi / vertical,
            indexing="xy",
        )
        unit = np.column_stack(
            (
                np.sin(phi).ravel() * np.cos(theta).ravel(),
                np.cos(phi).ravel(),
                np.sin(phi).ravel() * np.sin(theta).ravel(),
            )
        )
        positions = np.asarray(center) + unit * np.asarray(radii)
        normals = unit / np.asarray(radii)
        normals /= np.linalg.norm(normals, axis=1, keepdims=True)
        palette = np.asarray(colors, dtype=np.float32)
        selected = palette[self.rng.integers(0, len(palette), len(positions))]
        self.add_samples(positions, normals, selected, spacing * 0.78)

    def project_texture(self, path: Path, vertical_fov: float) -> int:
        """Bake the approved front view onto matching fixed-world surfaces."""
        with Image.open(path) as source:
            pixels = np.asarray(source.convert("RGB"), dtype=np.float32) / 255
        height, width = pixels.shape[:2]
        aspect = width / height
        tangent = math.tan(math.radians(vertical_fov / 2))
        camera = np.array([0, FLOOR_Y + 1.6, -5.4], dtype=np.float32)
        painted = 0

        for chunk in self.chunks:
            relative = chunk[:, :3] - camera
            depth = relative[:, 2]
            visible = depth > 0.2
            safe_depth = np.maximum(depth, 0.2)
            nx = relative[:, 0] / (safe_depth * tangent * aspect)
            ny = relative[:, 1] / (safe_depth * tangent)
            visible &= (np.abs(nx) <= 1) & (np.abs(ny) <= 1)
            if not np.any(visible):
                continue

            px = np.clip(((nx[visible] + 1) * 0.5 * width).astype(int), 0, width - 1)
            py = np.clip(((1 - ny[visible]) * 0.5 * height).astype(int), 0, height - 1)
            colors = pixels[py, px]
            chunk[visible, 6:9] = (colors - 0.5) / SH_C0
            painted += int(np.count_nonzero(visible))
        return painted

    def write(self, output: Path) -> int:
        data = np.concatenate(self.chunks).astype("<f4", copy=False)
        output.parent.mkdir(parents=True, exist_ok=True)
        properties = [
            "x",
            "y",
            "z",
            "nx",
            "ny",
            "nz",
            "f_dc_0",
            "f_dc_1",
            "f_dc_2",
            "opacity",
            "scale_0",
            "scale_1",
            "scale_2",
            "rot_0",
            "rot_1",
            "rot_2",
            "rot_3",
        ]
        header = [
            "ply",
            "format binary_little_endian 1.0",
            f"element vertex {len(data)}",
            *[f"property float {name}" for name in properties],
            "end_header\n",
        ]
        with output.open("wb") as handle:
            handle.write("\n".join(header).encode("ascii"))
            handle.write(data.tobytes())
        return len(data)


def brick_color(width: float, height: float):
    base = np.array([0.41, 0.43, 0.43], dtype=np.float32)

    def color(u: np.ndarray, v: np.ndarray) -> np.ndarray:
        x = u * width
        y = v * height
        row = np.floor(y / 0.28).astype(int)
        shifted = x + (row % 2) * 0.32
        mortar = (np.mod(y, 0.28) < 0.025) | (np.mod(shifted, 0.64) < 0.025)
        shade = 0.035 * np.sin(row * 1.73) + 0.025 * np.sin(np.floor(shifted / 0.64))
        result = base + shade[:, None]
        result[mortar] = np.array([0.27, 0.29, 0.3])
        return result

    return color


def roof_color(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    ribs = np.mod(u * 36, 1)
    rows = np.mod(v * 17, 1)
    base = np.empty((len(u), 3), dtype=np.float32)
    base[:] = (0.23, 0.27, 0.29)
    edge = (ribs < 0.12) | (rows < 0.08)
    base[edge] = (0.14, 0.18, 0.2)
    return base


def lattice_panel(
    scene: SplatScene,
    center_x: float,
    center_y: float,
    z: float,
    width: float,
    height: float,
) -> None:
    wood = (0.24, 0.12, 0.065)
    scene.add_box(
        (center_x, center_y, z), (width, height, 0.09), 0.045, (0.09, 0.075, 0.06)
    )
    for x in np.linspace(center_x - width / 2, center_x + width / 2, 7):
        scene.add_box(
            (float(x), center_y, z - 0.065), (0.055, height, 0.055), 0.035, wood
        )
    for y in np.linspace(center_y - height / 2, center_y + height / 2, 5):
        scene.add_box(
            (center_x, float(y), z - 0.067), (width, 0.05, 0.055), 0.035, wood
        )


def lantern(scene: SplatScene, x: float, y: float, z: float) -> None:
    scene.add_box((x, y, z), (0.34, 0.48, 0.34), 0.035, (0.72, 0.12, 0.055))
    scene.add_box((x, y, z), (0.25, 0.39, 0.355), 0.035, (0.98, 0.55, 0.16))
    scene.add_cylinder(
        (x, y - 0.37, z), (0, 1, 0), 0.045, 0.28, 0.025, (0.7, 0.08, 0.03)
    )


def planter(scene: SplatScene, x: float, z: float, scale: float = 1) -> None:
    scene.add_cylinder(
        (x, FLOOR_Y + 0.34 * scale, z),
        (0, 1, 0),
        0.34 * scale,
        0.58 * scale,
        0.04,
        (0.34, 0.22, 0.14),
    )
    greens = [(0.12, 0.27, 0.1), (0.18, 0.36, 0.13), (0.28, 0.43, 0.17)]
    for dx, dy, dz, radius in [
        (-0.2, 0.84, 0.02, 0.34),
        (0.16, 0.92, -0.03, 0.38),
        (0.02, 1.15, 0.06, 0.33),
    ]:
        scene.add_ellipsoid(
            (x + dx * scale, FLOOR_Y + dy * scale, z + dz * scale),
            (radius * scale, radius * 0.75 * scale, radius * scale),
            0.06,
            greens,
        )


def add_floor(scene: SplatScene) -> None:
    x_edges = np.linspace(-7.4, 7.4, 17)
    z_edges = np.linspace(-8.4, 5.2, 18)
    palette = np.array(
        [[0.52, 0.5, 0.45], [0.58, 0.55, 0.48], [0.47, 0.48, 0.45], [0.62, 0.57, 0.48]]
    )
    for zi in range(len(z_edges) - 1):
        for xi in range(len(x_edges) - 1):
            x0 = x_edges[xi] + 0.025
            z0 = z_edges[zi] + 0.025
            width = x_edges[xi + 1] - x_edges[xi] - 0.05
            depth = z_edges[zi + 1] - z_edges[zi] - 0.05
            color = tuple(palette[(xi * 3 + zi * 5) % len(palette)])
            scene.add_plane(
                (x0, FLOOR_Y, z0),
                (width, 0, 0),
                (0, 0, depth),
                0.065,
                color,
                normal_scale=0.012,
            )


def add_rear_hall(scene: SplatScene) -> None:
    scene.add_plane(
        (-6.3, FLOOR_Y, 5.25),
        (12.6, 0, 0),
        (0, 3.75, 0),
        0.065,
        brick_color(12.6, 3.75),
    )
    scene.add_box((0, 1.3, 5.12), (3.05, 3.05, 0.16), 0.045, (0.19, 0.09, 0.045))
    for x in (-1.0, 0, 1.0):
        scene.add_box((x, 1.28, 5.0), (0.075, 2.68, 0.09), 0.035, (0.31, 0.14, 0.06))
    for y in (0.2, 1.12, 2.05, 2.75):
        scene.add_box((0, y, 4.99), (2.82, 0.065, 0.09), 0.035, (0.31, 0.14, 0.06))
    lattice_panel(scene, -3.55, 1.45, 5.05, 1.75, 1.85)
    lattice_panel(scene, 3.55, 1.45, 5.05, 1.75, 1.85)
    for x in (-5.7, -2.15, 2.15, 5.7):
        scene.add_cylinder(
            (x, 1.45, 4.55), (0, 1, 0), 0.16, 3.75, 0.045, (0.34, 0.16, 0.07)
        )
    scene.add_plane((-6.9, 3.45, 3.8), (13.8, 0, 0), (0, 1.18, 1.72), 0.055, roof_color)
    scene.add_plane(
        (-6.9, 4.63, 5.52), (13.8, 0, 0), (0, -1.18, 1.72), 0.055, roof_color
    )
    scene.add_cylinder(
        (0, 4.64, 5.52), (1, 0, 0), 0.13, 14.1, 0.045, (0.12, 0.15, 0.16)
    )
    for y, z, width in [
        (FLOOR_Y + 0.08, 4.2, 4.4),
        (FLOOR_Y + 0.22, 4.42, 3.8),
        (FLOOR_Y + 0.36, 4.64, 3.2),
    ]:
        scene.add_box((0, y, z), (width, 0.16, 0.46), 0.055, (0.48, 0.46, 0.42))
    lantern(scene, -5.0, 2.15, 4.3)
    lantern(scene, 5.0, 2.15, 4.3)


def add_side_gallery(scene: SplatScene, side: int) -> None:
    wall_x = side * 7.35
    scene.add_plane(
        (wall_x, FLOOR_Y, -8.35 if side > 0 else 5.2),
        (0, 3.7, 0),
        (0, 0, 13.55 if side > 0 else -13.55),
        0.065,
        brick_color(13.55, 3.7),
    )
    column_x = side * 5.85
    for z in (-6.5, -3.8, -1.1, 1.6, 4.3):
        scene.add_cylinder(
            (column_x, 1.38, z), (0, 1, 0), 0.15, 3.6, 0.045, (0.34, 0.16, 0.07)
        )
        if z < 4:
            lantern(scene, column_x - side * 0.16, 2.05, z + 0.7)
    inner_x = side * 5.38
    scene.add_plane(
        (wall_x, 3.35, -8.5),
        (-side * 2.35, 1.05, 0),
        (0, 0, 14.3),
        0.06,
        roof_color,
    )
    scene.add_box((inner_x, 2.88, -1.55), (0.12, 0.16, 13.2), 0.05, (0.26, 0.12, 0.055))


def add_front_wall(scene: SplatScene) -> None:
    scene.add_plane(
        (-7.35, FLOOR_Y, -8.45),
        (14.7, 0, 0),
        (0, 3.7, 0),
        0.065,
        brick_color(14.7, 3.7),
    )
    scene.add_box((0, 1.2, -8.28), (3.5, 2.9, 0.18), 0.045, (0.2, 0.095, 0.045))
    for x in (-5.5, 5.5):
        planter(scene, x, -7.45, 0.9)


def build_scene(seed: int) -> SplatScene:
    scene = SplatScene(seed)
    add_floor(scene)
    add_rear_hall(scene)
    add_side_gallery(scene, -1)
    add_side_gallery(scene, 1)
    add_front_wall(scene)
    for x, z, scale in [
        (-5.0, 3.2, 0.88),
        (5.0, 3.2, 0.88),
        (-5.0, -2.6, 0.75),
        (5.0, -2.6, 0.75),
    ]:
        planter(scene, x, z, scale)
    return scene


def main() -> None:
    args = parse_args()
    scene = build_scene(args.seed)
    if args.texture:
        painted = scene.project_texture(args.texture, args.texture_fov)
        print(f"painted {painted} Gaussians from {args.texture}")
    count = scene.write(args.output)
    print(f"wrote {count} Gaussians to {args.output}")


if __name__ == "__main__":
    main()
