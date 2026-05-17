"use client";

import { useEffect } from "react";

export default function ServiceWorkerRegister() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;

    const handleLoad = () => {
      navigator.serviceWorker.register("/sw.js").then(
        (registration) => {
          console.log("SW registered: ", registration.scope);
        },
        (err) => {
          console.log("SW registration failed: ", err);
        }
      );
    };

    window.addEventListener("load", handleLoad);
    return () => window.removeEventListener("load", handleLoad);
  }, []);

  return null;
}
