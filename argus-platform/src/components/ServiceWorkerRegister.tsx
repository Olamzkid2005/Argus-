"use client";

import { useEffect } from "react";

export default function ServiceWorkerRegister() {
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      window.addEventListener("load", () => {
        navigator.serviceWorker.register("/sw.js").then(
          (registration) => {
            console.log("SW registered: ", registration.scope);
          },
          (err) => {
            console.log("SW registration failed: ", err);
          }
        );
      });
    }
  }, []);

  return null;
}
