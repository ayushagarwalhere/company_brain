import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

/* Hero 3D scene: a shaded planet with an atmosphere, and the context graph in orbit around it.
   Nodes are typed (message, ticket, requirement, PR, doc); one red "drift" link pulses between a
   message and the ticket it never reached. Pure three.js shaders, no external models. */

const PLANET_R = 22;
const PLANET_POS = new THREE.Vector3(8, -26.3, -18);

const NOISE = /* glsl */ `
  vec3 hash3(vec3 p){ p = vec3(dot(p,vec3(127.1,311.7,74.7)), dot(p,vec3(269.5,183.3,246.1)), dot(p,vec3(113.5,271.9,124.6)));
    return -1.0 + 2.0*fract(sin(p)*43758.5453123); }
  float noise(vec3 p){ vec3 i=floor(p); vec3 f=fract(p); vec3 u=f*f*(3.0-2.0*f);
    return mix(mix(mix(dot(hash3(i+vec3(0,0,0)),f-vec3(0,0,0)), dot(hash3(i+vec3(1,0,0)),f-vec3(1,0,0)),u.x),
                   mix(dot(hash3(i+vec3(0,1,0)),f-vec3(0,1,0)), dot(hash3(i+vec3(1,1,0)),f-vec3(1,1,0)),u.x),u.y),
               mix(mix(dot(hash3(i+vec3(0,0,1)),f-vec3(0,0,1)), dot(hash3(i+vec3(1,0,1)),f-vec3(1,0,1)),u.x),
                   mix(dot(hash3(i+vec3(0,1,1)),f-vec3(0,1,1)), dot(hash3(i+vec3(1,1,1)),f-vec3(1,1,1)),u.x),u.y),u.z); }
  float fbm(vec3 p){ float v=0.0, a=0.5; for(int i=0;i<5;i++){ v+=a*noise(p); p*=2.03; a*=0.5; } return v; }
`;

function Planet({ light, reduced }: { light: boolean; reduced: boolean }) {
  const mat = useRef<THREE.ShaderMaterial>(null);
  const mesh = useRef<THREE.Mesh>(null);
  const { pointer } = useThree();
  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uLight: { value: new THREE.Vector3(0.35, 0.9, 0.45).normalize() },
    uDeep: { value: new THREE.Color(light ? "#9a82e3" : "#120b33") },
    uMid: { value: new THREE.Color(light ? "#c2b0f5" : "#2a1b66") },
    uHigh: { value: new THREE.Color(light ? "#e9e1ff" : "#6d4fd6") },
    uRim: { value: new THREE.Color(light ? "#ffffff" : "#e6dcff") },
    uAmbient: { value: light ? 0.5 : 0.18 },
  }), [light]);
  useFrame((_, dt) => {
    if (mat.current) mat.current.uniforms.uTime.value += dt;
    if (!mesh.current) return;
    mesh.current.rotation.y += dt * 0.012;
    if (!reduced) {  // the planet leans slightly toward the cursor, damped
      mesh.current.position.x += (PLANET_POS.x + pointer.x * 0.9 - mesh.current.position.x) * 0.03;
      mesh.current.position.y += (PLANET_POS.y + pointer.y * 0.5 - mesh.current.position.y) * 0.03;
    }
  });
  return (
    <mesh ref={mesh} position={PLANET_POS}>
      <sphereGeometry args={[PLANET_R, 192, 192]} />
      <shaderMaterial ref={mat} uniforms={uniforms}
        vertexShader={/* glsl */ `
          varying vec3 vN; varying vec3 vP; varying vec3 vView;
          void main(){ vN = normalize(normalMatrix * normal); vP = position;
            vec4 mv = modelViewMatrix * vec4(position,1.0); vView = normalize(-mv.xyz); gl_Position = projectionMatrix * mv; }`}
        fragmentShader={/* glsl */ `
          uniform float uTime, uAmbient; uniform vec3 uLight, uDeep, uMid, uHigh, uRim;
          varying vec3 vN; varying vec3 vP; varying vec3 vView;
          ${NOISE}
          void main(){
            vec3 p = normalize(vP);
            float bands = fbm(vec3(p.x*2.2, p.y*7.0 + uTime*0.01, p.z*2.2)) * 0.6 + fbm(p*5.0) * 0.4;
            vec3 base = mix(uDeep, uMid, smoothstep(-0.35, 0.45, bands));
            base = mix(base, uHigh, smoothstep(0.32, 0.75, bands) * 0.55);
            float diff = clamp(dot(vN, uLight), 0.0, 1.0);
            float fres = pow(1.0 - clamp(dot(vN, vView), 0.0, 1.0), 2.6);
            vec3 col = base * (uAmbient + 0.95 * diff) + uRim * fres * (0.35 + 0.9 * diff);
            gl_FragColor = vec4(col, 1.0);
          }`} />
    </mesh>
  );
}

function Atmosphere({ light }: { light: boolean }) {
  const uniforms = useMemo(() => ({
    uColorA: { value: new THREE.Color(light ? "#a78bfa" : "#8b5cf6") },
    uColorB: { value: new THREE.Color("#ffffff") },
  }), [light]);
  return (
    <mesh position={PLANET_POS} scale={1.028}>
      <sphereGeometry args={[PLANET_R, 96, 96]} />
      <shaderMaterial uniforms={uniforms} transparent depthWrite={false} blending={THREE.AdditiveBlending} side={THREE.BackSide}
        vertexShader={/* glsl */ `
          varying vec3 vN; varying vec3 vView;
          void main(){ vN = normalize(normalMatrix * normal); vec4 mv = modelViewMatrix * vec4(position,1.0); vView = normalize(-mv.xyz); gl_Position = projectionMatrix * mv; }`}
        fragmentShader={/* glsl */ `
          uniform vec3 uColorA, uColorB; varying vec3 vN; varying vec3 vView;
          void main(){ float i = pow(clamp(0.66 - dot(vN, vView), 0.0, 1.0), 2.4);
            vec3 c = mix(uColorA, uColorB, smoothstep(0.25, 0.9, i));
            gl_FragColor = vec4(c, 1.0) * i * 1.5; }`} />
    </mesh>
  );
}

function Stars({ count = 1600 }: { count?: number }) {
  const ref = useRef<THREE.Points>(null);
  const geo = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const pos = new Float32Array(count * 3), size = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      const r = 40 + Math.random() * 40, th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
      pos.set([r * Math.sin(ph) * Math.cos(th), r * Math.cos(ph) * 0.6 + 6, -Math.abs(r * Math.sin(ph) * Math.sin(th))], i * 3);
      size[i] = Math.random() * 1.6 + 0.4;
    }
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("aSize", new THREE.BufferAttribute(size, 1));
    return g;
  }, [count]);
  useFrame((_, dt) => { if (ref.current) ref.current.rotation.y += dt * 0.004; });
  return (
    <points ref={ref} geometry={geo}>
      <shaderMaterial transparent depthWrite={false}
        vertexShader={`attribute float aSize; void main(){ vec4 mv = modelViewMatrix*vec4(position,1.0); gl_PointSize = aSize * (90.0 / -mv.z); gl_Position = projectionMatrix*mv; }`}
        fragmentShader={`void main(){ float d = length(gl_PointCoord-0.5); gl_FragColor = vec4(vec3(0.92,0.9,1.0), smoothstep(0.5,0.0,d)*0.8); }`} />
    </points>
  );
}

type NodeSpec = { color: string; radius: number; tilt: [number, number]; speed: number; phase: number; size: number };
const ORBITS: { radius: number; tilt: [number, number] }[] = [
  { radius: PLANET_R + 2.6, tilt: [1.18, 0.34] },
  { radius: PLANET_R + 4.6, tilt: [1.05, 0.22] },
  { radius: PLANET_R + 7.0, tilt: [0.95, 0.12] },
];
const C = { msg: "#fcd34d", ticket: "#7dd3fc", req: "#c4b5fd", pr: "#86efac", doc: "#f0abfc" };

function orbitPoint(radius: number, tilt: [number, number], angle: number, out = new THREE.Vector3()) {
  out.set(Math.cos(angle) * radius, 0, Math.sin(angle) * radius);
  out.applyEuler(new THREE.Euler(tilt[0], 0, tilt[1]));
  return out.add(PLANET_POS);
}

function OrbitRing({ radius, tilt }: { radius: number; tilt: [number, number] }) {
  const line = useMemo(() => {
    const pts = Array.from({ length: 241 }, (_, i) => orbitPoint(radius, tilt, (i / 240) * Math.PI * 2));
    const g = new THREE.BufferGeometry().setFromPoints(pts);
    const m = new THREE.LineDashedMaterial({ color: "#8b7fd1", dashSize: 0.12, gapSize: 0.22, transparent: true, opacity: 0.35 });
    const l = new THREE.Line(g, m);
    l.computeLineDistances();
    return l;
  }, [radius, tilt]);
  return <primitive object={line} />;
}

function Graph({ reduced }: { reduced: boolean }) {
  const nodes = useMemo<NodeSpec[]>(() => {
    const spec: [string, number, number, number][] = [ // color, orbit, phase, size
      [C.msg, 0, 1.2, 0.11], [C.msg, 0, 2.3, 0.09], [C.msg, 0, 4.1, 0.08], [C.req, 0, 5.2, 0.13],
      [C.ticket, 1, 1.75, 0.15], [C.ticket, 1, 3.3, 0.12], [C.req, 1, 4.6, 0.12], [C.doc, 1, 0.4, 0.11],
      [C.pr, 2, 1.45, 0.14], [C.pr, 2, 2.9, 0.12], [C.doc, 2, 4.0, 0.12], [C.ticket, 2, 5.4, 0.1],
    ];
    return spec.map(([color, o, phase, size], i) => ({ color, radius: ORBITS[o].radius, tilt: ORBITS[o].tilt, speed: [0.016, 0.012, 0.009][o] * (i % 2 ? 1 : 1.1), phase, size: size * 3.2 }));
  }, []);
  // edges: [from, to, drift?]
  const edges: [number, number, boolean][] = [[0, 4, true], [1, 3, false], [3, 5, false], [4, 8, false], [5, 9, false], [6, 7, false], [7, 10, false], [2, 6, false], [11, 9, false]];

  const meshes = useRef<(THREE.Mesh | null)[]>([]);
  const halos = useRef<(THREE.Sprite | null)[]>([]);
  // faint spokes from every node down to the planet: everything is anchored in one graph
  const spokeGeo = useMemo(() => new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(new Float32Array(nodes.length * 6), 3)), [nodes.length]);
  const HOT = 5;  // the node that periodically flares orange: "a drift being detected"
  const hotColor = useMemo(() => ({ base: new THREE.Color(nodes[HOT].color), drift: new THREE.Color("#ff5a36"), cur: new THREE.Color() }), [nodes]);
  const lineGeo = useMemo(() => new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(new Float32Array(edges.length * 6), 3)), [edges.length]);
  const lineCol = useMemo(() => {
    const col = new Float32Array(edges.length * 6);
    edges.forEach(([, , d], i) => { const c = new THREE.Color(d ? "#ff5a36" : "#a99cf0"); col.set([c.r, c.g, c.b, c.r, c.g, c.b], i * 6); });
    lineGeo.setAttribute("color", new THREE.BufferAttribute(col, 3));
    return col;
  }, [edges, lineGeo]);
  const lineMat = useRef<THREE.LineBasicMaterial>(null);
  const driftSprite = useRef<THREE.Sprite>(null);
  const glowTex = useMemo(() => {
    const c = document.createElement("canvas"); c.width = c.height = 64;
    const g = c.getContext("2d")!; const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grd.addColorStop(0, "rgba(255,255,255,1)"); grd.addColorStop(0.25, "rgba(255,255,255,.55)"); grd.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = grd; g.fillRect(0, 0, 64, 64);
    return new THREE.CanvasTexture(c);
  }, []);
  void lineCol;

  const tmp = useMemo(() => nodes.map(() => new THREE.Vector3()), [nodes]);
  useFrame(({ clock }) => {
    const t = reduced ? 0 : clock.getElapsedTime();
    nodes.forEach((n, i) => {
      orbitPoint(n.radius, n.tilt, n.phase + t * n.speed, tmp[i]);
      meshes.current[i]?.position.copy(tmp[i]);
      halos.current[i]?.position.copy(tmp[i]);
    });
    const sp = spokeGeo.attributes.position.array as Float32Array, dir = new THREE.Vector3();
    tmp.forEach((v, i) => {
      dir.copy(v).sub(PLANET_POS).normalize().multiplyScalar(PLANET_R).add(PLANET_POS);
      sp.set([v.x, v.y, v.z, dir.x, dir.y, dir.z], i * 6);
    });
    spokeGeo.attributes.position.needsUpdate = true;
    // every ~5 s the hot node flares orange for a moment, then cools back
    const phase = reduced ? 0 : (t % 5) / 5, flare = phase < 0.3 ? Math.sin((phase / 0.3) * Math.PI) : 0;
    hotColor.cur.copy(hotColor.base).lerp(hotColor.drift, flare);
    const hm = meshes.current[HOT]?.material as THREE.MeshBasicMaterial | undefined;
    if (hm) hm.color.copy(hotColor.cur);
    const hh = halos.current[HOT];
    if (hh) { (hh.material as THREE.SpriteMaterial).color.copy(hotColor.cur); const k = nodes[HOT].size * 7 * (1 + flare * 1.6); hh.scale.set(k, k, 1); }
    const arr = lineGeo.attributes.position.array as Float32Array;
    edges.forEach(([a, b], i) => { arr.set([tmp[a].x, tmp[a].y, tmp[a].z, tmp[b].x, tmp[b].y, tmp[b].z], i * 6); });
    lineGeo.attributes.position.needsUpdate = true;
    if (lineMat.current) lineMat.current.opacity = 0.55;
    if (driftSprite.current) {
      // a pulse travelling along the drift edge
      const k = (t * 0.45) % 1;
      driftSprite.current.position.lerpVectors(tmp[0], tmp[4], k);
      const s = 0.55 + Math.sin(t * 6) * 0.08;
      driftSprite.current.scale.set(s, s, s);
    }
  });

  return (
    <group>
      {ORBITS.map((o, i) => <OrbitRing key={i} radius={o.radius} tilt={o.tilt} />)}
      <lineSegments geometry={spokeGeo}>
        <lineBasicMaterial color="#8b7fd1" transparent opacity={0.12} depthWrite={false} blending={THREE.AdditiveBlending} />
      </lineSegments>
      <lineSegments geometry={lineGeo}>
        <lineBasicMaterial ref={lineMat} vertexColors transparent opacity={0.55} depthWrite={false} blending={THREE.AdditiveBlending} />
      </lineSegments>
      {nodes.map((n, i) => (
        <group key={i}>
          <mesh ref={(m) => { meshes.current[i] = m; }}>
            <sphereGeometry args={[n.size, 24, 24]} />
            <meshBasicMaterial color={n.color} />
          </mesh>
          <sprite ref={(s) => { halos.current[i] = s; }} scale={[n.size * 7, n.size * 7, 1]}>
            <spriteMaterial map={glowTex} color={n.color} transparent opacity={0.55} depthWrite={false} blending={THREE.AdditiveBlending} />
          </sprite>
        </group>
      ))}
      <sprite ref={driftSprite}>
        <spriteMaterial map={glowTex} color="#ff5a36" transparent opacity={0.95} depthWrite={false} blending={THREE.AdditiveBlending} />
      </sprite>
    </group>
  );
}

function Rig({ scroll, reduced }: { scroll: React.MutableRefObject<number>; reduced: boolean }) {
  const { camera, pointer } = useThree();
  useFrame(() => {
    if (reduced) { camera.lookAt(0, -0.6, -2); return; }  // no camera moves under reduced motion
    const tx = pointer.x * 0.6, ty = 0.4 + pointer.y * 0.3 - scroll.current * 1.6;
    camera.position.x += (tx - camera.position.x) * 0.04;
    camera.position.y += (ty - camera.position.y) * 0.04;
    camera.lookAt(0, -0.6 - scroll.current * 1.2, -2);
  });
  return null;
}

export default function Planet3D({ light }: { light: boolean }) {
  const wrap = useRef<HTMLDivElement>(null);
  const scroll = useRef(0);
  const [visible, setVisible] = useState(true);
  const reduced = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  useEffect(() => {
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting));
    if (wrap.current) io.observe(wrap.current);
    const onScroll = () => { scroll.current = Math.min(1, window.scrollY / window.innerHeight); };
    addEventListener("scroll", onScroll, { passive: true });
    return () => { io.disconnect(); removeEventListener("scroll", onScroll); };
  }, []);
  return (
    <div ref={wrap} className="planet3d" aria-hidden>
      <Canvas dpr={[1, 1.5]} frameloop={reduced ? "demand" : visible ? "always" : "never"} camera={{ position: [0, 0.4, 10], fov: 38, near: 0.1, far: 200 }}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}>
        <Stars />
        <Planet light={light} reduced={reduced} />
        <Atmosphere light={light} />
        <Graph reduced={reduced} />
        <Rig scroll={scroll} reduced={reduced} />
      </Canvas>
    </div>
  );
}
