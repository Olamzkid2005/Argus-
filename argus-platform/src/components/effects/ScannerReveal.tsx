import { useRef, useState, useEffect } from "react";
import Image from "next/image";
import gsap from "gsap";

interface ScannerRevealProps {
  icon: string;
  text: string;
  scannedText: string;
  className?: string;
  glowColor?: string;
}

export default function ScannerReveal({
  icon,
  text,
  scannedText,
  className = "",
  glowColor = "#FFFDD0",
}: ScannerRevealProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const [isHovered, setIsHovered] = useState(false);
  const [isScanned, setIsScanned] = useState(false);
  const [isRevealed, setIsRevealed] = useState(false);
  const tlRef = useRef<gsap.core.Timeline | null>(null);

  useEffect(() => {
    if (!isHovered || isScanned || !cardRef.current || !containerRef.current) return;

    const tl = gsap.timeline({ paused: true });
    tlRef.current = tl;

    // Phase 1: Hover Glow (0%)
    tl.to(cardRef.current, {
      borderColor: `rgba(${hexToRgb(glowColor)}, 0.5)`,
      boxShadow: `0 0 15px ${glowColor}33`,
      duration: 0.2,
      ease: "power1.out",
    }, 0);

    // Light Sweep (0%)
    tl.to(
      containerRef.current.querySelector(".card-shine"),
      { opacity: 0.8, x: "100%", duration: 0.6, ease: "power1.inOut" },
      0
    );

    // Phase 2: Scanner Entry (10%)
    tl.to(
      containerRef.current.querySelector(".scanner-blade"),
      { opacity: 1, x: "100%", duration: 0.2, ease: "power1.in" },
      0.1
    );

    // Phase 3: Surface Peel (30%)
    tl.to(
      containerRef.current.querySelector(".surface-layer"),
      {
        rotationX: 120,
        transformOrigin: "top center",
        duration: 0.8,
        ease: "power2.inOut",
        filter: "brightness(1.2)",
        onComplete: () => setIsRevealed(true),
      },
      0.3
    );

    // Sync Scanner with Peel (30%)
    tl.to(
      containerRef.current.querySelector(".scanner-blade"),
      {
        duration: 0.8,
        ease: "none",
        top: "100%",
        filter: "brightness(2)",
        boxShadow: `0 0 30px ${glowColor}, 0 0 60px rgba(233,255,255,0.8)`,
      },
      0.3
    );

    // Phase 4: Lock In & Fly Away (50%)
    tl.to(
      containerRef.current.querySelector(".scanner-blade"),
      { x: "200%", duration: 0.4, ease: "power1.in" },
      0.5
    );
    tl.to(
      containerRef.current.querySelector(".surface-layer"),
      { y: "-40%", rotationZ: -5, opacity: 0, duration: 0.4, ease: "power1.in" },
      "<"
    );
    tl.to(
      cardRef.current,
      {
        borderColor: "rgba(233,255,255,0.5)",
        boxShadow: "0 0 20px rgba(233,255,255,0.3)",
        duration: 0.2,
      },
      "<"
    );

    // Phase 5: Reset (60%)
    tl.call(() => setIsScanned(true), [], 0.6);
    tl.set(
      containerRef.current.querySelector(".surface-layer"),
      { display: "none" },
      0.6
    );
    tl.set(
      containerRef.current.querySelector(".scanner-blade"),
      { opacity: 0, x: "-100%", top: "0%" },
      0.6
    );
    tl.set(
      containerRef.current.querySelector(".card-shine"),
      { opacity: 0, x: "-100%" },
      0.6
    );

    tl.call(
      () => {
        tl.kill();
        setIsHovered(false);
      },
      [],
      1.0
    );

    tl.play();

    return () => {
      tl.kill();
    };
  }, [isHovered, isScanned, glowColor]);

  return (
    <div
      ref={(el) => {
        containerRef.current = el;
        if (el) cardRef.current = el;
      }}
      className={`scanner-reveal-container relative overflow-hidden border border-white/10 bg-[#12121A] group ${className}`}
    >
      {/* Revealed Content Layer */}
      <div className="absolute inset-0 flex items-center justify-center bg-[#0A0A0C] z-0">
        {isRevealed && (
          <Image
            src={icon}
            alt="Icon"
            width={48}
            height={48}
            unoptimized
            className="w-12 h-12 object-contain drop-shadow-[0_0_10px_rgba(233,255,255,0.5)]"
          />
        )}
        {isRevealed && (
          <span className="ml-3 text-[#E9FFFF] font-mono text-lg tracking-widest uppercase">
            {scannedText}
          </span>
        )}
      </div>

      {/* Surface Layer */}
      <div
        className="surface-layer absolute inset-0 z-10 flex flex-col items-center justify-center bg-[#1A1A24] cursor-pointer"
        onMouseEnter={() => !isScanned && setIsHovered(true)}
        onMouseLeave={() => {
          if (!isScanned) {
            tlRef.current?.kill();
            setIsHovered(false);
          }
        }}
      >
        <span className="text-[#F0F0F5] font-mono text-sm tracking-wide">{text}</span>
        <div className="hidden">{icon}</div>
      </div>

      {/* Scanner Blade */}
      <div
        className="scanner-blade absolute top-0 left-0 w-[120%] h-[20px] z-20 -translate-x-full opacity-0"
        style={{
          background: glowColor,
          boxShadow: `0 0 15px ${glowColor}, 0 0 30px rgba(233,255,255,0.5)`,
        }}
      />

      {/* Shine Overlay */}
      <div className="card-shine absolute inset-0 z-30 pointer-events-none opacity-0 bg-gradient-to-r from-transparent via-white/20 to-transparent -translate-x-full" />
    </div>
  );
}

function hexToRgb(hex: string): string {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return result
    ? `${parseInt(result[1], 16)}, ${parseInt(result[2], 16)}, ${parseInt(result[3], 16)}`
    : "255, 253, 208";
}