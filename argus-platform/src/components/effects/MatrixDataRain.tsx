"use client";

import { useRef, useEffect } from "react";
import { useTheme } from "next-themes";

export default function MatrixDataRain() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { theme } = useTheme();

  useEffect(() => {
    if (!canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d")!;
    const fontSize = 12; // Reverted to 12px for the original aesthetic

    const resize = () => {
      canvas.width = canvas.offsetWidth;
      canvas.height = canvas.offsetHeight;
    };
    resize();
    window.addEventListener("resize", resize);

    const columns = Math.floor(canvas.width / fontSize);
    const drops = Array(columns).fill(1); // Reverted random initialization so they appear immediately
    let animId: number;

    function drawMatrix() {
      // Use theme-aware transparent clear
      const isLight = document.documentElement.classList.contains('light');
      
      // Clear with slight trail
      ctx.fillStyle = isLight ? "rgba(245, 245, 247, 0.04)" : "rgba(10, 10, 12, 0.04)";
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // Matrix character color
      ctx.fillStyle = isLight ? "rgba(0, 119, 153, 0.4)" : "#E9FFFF";
      ctx.font = `${fontSize}px monospace`;

      for (let i = 0; i < drops.length; i++) {
        const text = String.fromCharCode(0x30A0 + Math.random() * 96);
        const x = i * fontSize;
        const y = drops[i] * fontSize;
        ctx.fillText(text, x, y);

        // Reverted drop reset logic
        if (y > canvas.height && Math.random() > 0.975) {
          drops[i] = 0;
        }
        drops[i]++;
      }
      animId = requestAnimationFrame(drawMatrix);
    }

    drawMatrix();

    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(animId);
    };
  }, [theme]); // Re-run effect when theme toggles to update colors

  return (
    <canvas
      ref={canvasRef}
      // Reverted to absolute positioning to ensure it stays within its container instead of vanishing behind the page
      className="absolute inset-0 w-full h-full opacity-30 pointer-events-none"
    />
  );
}