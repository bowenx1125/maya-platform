"use client";

import type { Drawing } from "./drawing";
import type { EggModel } from "../stage3d/egg-model";
import { useEffect, useRef } from "react";
import { eggOrbitYawAfterDrag, eggOrbitYawAfterInertia } from "./egg-orbit";

export function EggCanvas({
  drawing,
  faded,
  playing = false,
  /** Preview-only: horizontal pointer drag spins yaw. Off on the drawing board. */
  orbit = false,
  className = "",
}: {
  drawing?: Drawing | null;
  faded?: ReadonlySet<string>;
  playing?: boolean;
  orbit?: boolean;
  className?: string;
}) {
  const drawingRef = useRef(drawing);
  const fadedRef = useRef(faded);
  const eggRef = useRef<EggModel | null>(null);
  useEffect(() => {
    drawingRef.current = drawing;
    fadedRef.current = faded;
    eggRef.current?.setDrawing(drawing, faded);
  }, [drawing, faded]);
  const host = useRef<HTMLDivElement>(null);
  const playingRef = useRef(playing);
  useEffect(() => {
    playingRef.current = playing;
  }, [playing]);
  const orbitRef = useRef(orbit);
  useEffect(() => {
    orbitRef.current = orbit;
  }, [orbit]);
  useEffect(() => {
    const element = host.current!;
    let active = true,
      cleanup = () => {};
    void Promise.all([
      import("three"),
      import("three/examples/jsm/loaders/GLTFLoader.js"),
      import("three/examples/jsm/environments/RoomEnvironment.js"),
      import("../stage3d/egg-model"),
    ]).then(
      async ([T, { GLTFLoader }, { RoomEnvironment }, { prepareEggModel }]) => {
        if (!active) return;
        const renderer = new T.WebGLRenderer({ alpha: true, antialias: true });
        renderer.setClearColor(0, 0);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        renderer.outputColorSpace = T.SRGBColorSpace;
        renderer.toneMapping = T.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 0.96;
        element.appendChild(renderer.domElement);
        const scene = new T.Scene();
        scene.add(new T.HemisphereLight(0xfff3df, 0x8b7869, 1.4));
        for (const [color, intensity, x, y, z] of [
          [0xffe5c2, 2.6, -3, 5, 4],
          [0xdce9ff, 1.15, 3, 2.6, 3],
          [0xffd2a1, 2.8, 2, 3.8, -2.5],
          [0xb9d9ff, 2, 3, 2.8, -2.5],
          [0xffb75e, 0.8, -3, 2, -2],
        ]) {
          const light = new T.DirectionalLight(color, intensity);
          light.position.set(x, y, z);
          scene.add(light);
        }
        const room = new RoomEnvironment(),
          pmrem = new T.PMREMGenerator(renderer),
          env = pmrem.fromScene(room, 0.05);
        scene.environment = env.texture;
        scene.environmentIntensity = 0.15;
        room.dispose();
        pmrem.dispose();
        const camera = new T.OrthographicCamera(
          -1.72,
          1.72,
          1.72,
          -1.72,
          0.1,
          30,
        );
        camera.position.set(0, 1.35, 9);
        camera.lookAt(0, 1.35, 0);
        const resize = () => {
          const w = element.clientWidth,
            h = element.clientHeight;
          renderer.setSize(w, h);
          camera.left = (-1.56 * w) / h;
          camera.right = (1.56 * w) / h;
          camera.top = 1.56;
          camera.bottom = -1.56;
          camera.updateProjectionMatrix();
        };
        const observer = new ResizeObserver(resize);
        observer.observe(element);
        resize();
        let raf = 0;
        let disposeEgg = () => {};
        const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
        // Preview yaw is session-local; never written to drawing/avatar_config.
        let yaw = 0;
        let velocity = 0;
        let dragging = false;
        let lastX = 0;
        let lastT = 0;
        const onPointerDown = (event: PointerEvent) => {
          if (!orbitRef.current || event.button !== 0) return;
          dragging = true;
          velocity = 0;
          lastX = event.clientX;
          lastT = performance.now();
          element.setPointerCapture(event.pointerId);
          element.dataset.dragging = "true";
        };
        const onPointerMove = (event: PointerEvent) => {
          if (!dragging) return;
          const now = performance.now();
          const dt = Math.max(1, now - lastT) / 1000;
          const dx = event.clientX - lastX;
          yaw = eggOrbitYawAfterDrag(yaw, dx);
          velocity = (-dx / dt) * 0.01;
          lastX = event.clientX;
          lastT = now;
        };
        const onPointerUp = (event: PointerEvent) => {
          if (!dragging) return;
          dragging = false;
          element.releasePointerCapture(event.pointerId);
          delete element.dataset.dragging;
          if (reduced.matches) velocity = 0;
        };
        element.addEventListener("pointerdown", onPointerDown);
        element.addEventListener("pointermove", onPointerMove);
        element.addEventListener("pointerup", onPointerUp);
        element.addEventListener("pointercancel", onPointerUp);
        cleanup = () => {
          cancelAnimationFrame(raf);
          eggRef.current = null;
          disposeEgg();
          observer.disconnect();
          element.removeEventListener("pointerdown", onPointerDown);
          element.removeEventListener("pointermove", onPointerMove);
          element.removeEventListener("pointerup", onPointerUp);
          element.removeEventListener("pointercancel", onPointerUp);
          scene.traverse((o) => {
            if (o instanceof T.Mesh) {
              o.geometry.dispose();
              for (const m of Array.isArray(o.material)
                ? o.material
                : [o.material])
                m.dispose();
            }
          });
          env.dispose();
          renderer.dispose();
          renderer.forceContextLoss();
          renderer.domElement.remove();
        };
        try {
          const gltf = await new GLTFLoader().loadAsync(
            "/avatars/Maya-Egg.glb",
          );
          if (!active) {
            gltf.scene.traverse((o) => {
              if (o instanceof T.Mesh) o.geometry.dispose();
            });
            return;
          }
          const egg = prepareEggModel(gltf.scene, drawingRef.current);
          eggRef.current = egg;
          egg.setDrawing(drawingRef.current, fadedRef.current);
          disposeEgg = egg.dispose;
          scene.add(egg.root);
          let prevMs = 0;
          const frame = (ms: number) => {
            if (!active) return;
            const dt = Math.min(0.05, Math.max(0, (ms - prevMs) / 1000));
            prevMs = ms;
            egg.frame(ms / 1000, playingRef.current, reduced.matches);
            if (orbitRef.current && !dragging) {
              const next = eggOrbitYawAfterInertia(
                yaw,
                velocity,
                dt,
                reduced.matches,
              );
              yaw = next.yaw;
              velocity = next.velocity;
            }
            // egg.frame owns x/z; preview yaw is applied after so speaking
            // wobble and drag never fight.
            egg.root.rotation.y = yaw;
            renderer.render(scene, camera);
            element.dataset.rendered = "true";
            raf = requestAnimationFrame(frame);
          };
          raf = requestAnimationFrame(frame);
        } catch {
          if (active) element.dataset.rendered = "failed";
        }
      },
    );
    return () => {
      active = false;
      cleanup();
    };
  }, []);
  return (
    <div
      ref={host}
      className={`[&_canvas]:block ${orbit ? "cursor-grab touch-none active:cursor-grabbing" : ""} ${className}`}
      style={{ height: "100%", width: "100%" }}
      role="img"
      aria-label="Egg avatar"
    />
  );
}
