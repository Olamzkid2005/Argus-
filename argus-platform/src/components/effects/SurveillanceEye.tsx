"use client";

import React, { useRef, useState, useMemo } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { shaderMaterial } from "@react-three/drei";
import { easing } from "maath";

/**
 * ── Neural Surveillance Eye ──
 * High-fidelity SOC monitoring visualizer.
 * Note: THREE.Clock is shimmed globally in ClientLayout.tsx via /lib/three-patch.
 */

const IrisShaderMaterial = shaderMaterial(
  { uTime: 0, uColor: new THREE.Color("#FFFDD0") },
  `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  `
    uniform float uTime;
    uniform vec3 uColor;
    varying vec2 vUv;

    void main() {
      vec2 uv = vUv - 0.5;
      float r = length(uv);
      float theta = atan(uv.y, uv.x);

      float wave1 = pow(sin(theta * 12.0 + r * 18.0 - uTime * 2.0) * 0.5 + 0.5, 3.0);
      float wave2 = pow(sin(theta * 8.0 - r * 12.0 + uTime * 1.5) * 0.5 + 0.5, 2.0);
      float wave3 = pow(cos(r * 30.0 + uTime * 3.0) * 0.5 + 0.5, 4.0);

      float pattern = wave1 * 0.5 + wave2 * 0.3 + wave3 * 0.2;

      float innerFade = smoothstep(0.0, 0.05, r);
      float outerFade = 1.0 - smoothstep(0.15, 0.25, r);
      float alpha = pattern * innerFade * outerFade;

      vec3 col = vec3(0.0, 1.0, 1.0);
      float coreGlow = smoothstep(0.0, 0.08, r) * (1.0 - smoothstep(0.08, 0.14, r));
      vec3 coreColor = mix(col, vec3(0.8, 1.0, 1.0), coreGlow);
      float edgeGlow = exp(-r * 10.0) * 2.0;

      gl_FragColor = vec4(coreColor, alpha + edgeGlow);
    }
  `
);

const PupilShaderMaterial = shaderMaterial(
  {},
  `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  `
    varying vec2 vUv;
    void main() {
      float r = length(vUv - 0.5);
      float dist = r * 2.0;
      vec3 color = vec3(0.04, 0.04, 0.06);
      float alpha = smoothstep(0.8, 0.0, dist);
      gl_FragColor = vec4(color, alpha);
    }
  `
);

function Eyeball() {
  return (
    <mesh scale={2.5}>
      <sphereGeometry args={[0.5, 64, 64]} />
      <meshPhysicalMaterial
        transmission={1}
        thickness={0.9}
        roughness={0.0}
        metalness={0.2}
        ior={1.5}
        clearcoat={1}
        clearcoatRoughness={0.0}
        color="#12121A"
        depthWrite
        transparent
        depthTest
        opacity={1}
        reflectivity={0.5}
        iridescence={1}
        iridescenceIOR={1.9}
        iridescenceThicknessRange={[100, 400]}
      />
    </mesh>
  );
}

function IrisMaterial() {
  const material = useMemo(() => new IrisShaderMaterial(), []);

  useFrame((state, dt) => {
    const time = (state.clock as any)?.getElapsedTime?.() || state.clock?.elapsedTime || performance.now() / 1000;
    easing.damp(material, "uTime", time, 0.2, dt);
  });

  return (
    <primitive 
      object={material} 
      attach="material" 
      transparent 
      depthWrite={false} 
      blending={THREE.AdditiveBlending} 
      uColor={new THREE.Color("#FFFDD0")} 
    />
  );
}

function Pupil({ pupilRef }: { pupilRef: React.RefObject<THREE.Mesh | null> }) {
  const material = useMemo(() => new PupilShaderMaterial(), []);

  return (
    <mesh ref={pupilRef as any} scale={1} position={[0, 0, 0.1]} rotation={[Math.PI / 2, 0, 0]}>
      <cylinderGeometry args={[0.4, 0.4, 0.1, 64]} />
      <primitive object={material} attach="material" transparent depthWrite={false} />
    </mesh>
  );
}

function Iris({ pupilRef }: { pupilRef: React.RefObject<THREE.Mesh | null> }) {
  const irisRef = useRef<THREE.Mesh>(null!);

  useFrame(() => {
    if (irisRef.current && pupilRef.current) {
      const pupilPos = pupilRef.current.position;
      const targetQ = new THREE.Quaternion().setFromEuler(
        new THREE.Euler(pupilPos.y, -pupilPos.x, 0)
      );
      irisRef.current.quaternion.slerp(targetQ, 0.1);
    }
  });

  return (
    <mesh ref={irisRef} position={[0, 0, 0.1]} scale={1.5}>
      <cylinderGeometry args={[0.5, 0.5, 0.1, 64]} />
      <IrisMaterial />
      <Pupil pupilRef={pupilRef} />
    </mesh>
  );
}

function Eye({ target }: { target: React.RefObject<THREE.Vector3 | null> }) {
  const groupRef = useRef<THREE.Group>(null!);
  const pupilRef = useRef<THREE.Mesh>(null);
  const [hovered, setHovered] = useState(false);
  const { camera, viewport } = useThree();
  const rotTarget = useRef(new THREE.Euler(0, 0, 0));

  useFrame((_state, dt) => {
    if (!groupRef.current || !target.current || !camera) return;

    const mouse = target.current.clone();
    mouse.project(camera);

    const angle = Math.atan2(mouse.y, mouse.x);
    const distance = Math.min(Math.sqrt(mouse.x ** 2 + mouse.y ** 2), 1);

    const x = Math.cos(angle) * distance * (viewport.width / 2);
    const y = Math.sin(angle) * distance * (viewport.height / 2);

    rotTarget.current.set(y, -x, 0);
    easing.dampE(groupRef.current.rotation, rotTarget.current, 0.05, dt);

    if (pupilRef.current) {
      const targetScale = hovered ? 1.2 : 1.0;
      pupilRef.current.scale.x += (targetScale - pupilRef.current.scale.x) * 0.1;
      pupilRef.current.scale.y += (targetScale - pupilRef.current.scale.y) * 0.1;
      pupilRef.current.scale.z += (targetScale - pupilRef.current.scale.z) * 0.1;
    }
  });

  return (
    <group
      ref={groupRef as any}
      onPointerEnter={() => setHovered(true)}
      onPointerLeave={() => setHovered(false)}
    >
      <Eyeball />
      <Iris pupilRef={pupilRef} />
    </group>
  );
}

export default function SurveillanceEye() {
  const target = useRef(new THREE.Vector3(0, 0, 0));

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    const y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    target.current.set(x, y, 0);
  };

  return (
    <div className="w-full h-full relative" onPointerMove={handlePointerMove}>
      <Canvas
        camera={{ position: [0, 0, 5], fov: 50 }}
        style={{ background: "transparent" }}
        gl={{ alpha: true, antialias: true, failIfMajorPerformanceCaveat: false }}
      >
        <ambientLight intensity={0.3} />
        <pointLight position={[10, 10, 10]} intensity={0.5} />
        <Eye target={target} />
      </Canvas>
    </div>
  );
}