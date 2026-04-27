"use client";

import { useEffect } from "react";
import { log } from "@/lib/logger";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    log.error("GlobalError", { message: error.message, digest: error.digest });
  }, [error]);

  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <div className="text-center">
        <h2 className="mb-4 text-2xl font-bold text-red-600">
          Something went wrong!
        </h2>
        <p className="mb-4 text-gray-600">
          {error.message || "An unexpected error occurred"}
        </p>
        <button
          onClick={() => reset()}
          className="rounded bg-blue-600 px-6 py-3 text-white hover:bg-blue-700"
        >
          Try again
        </button>
      </div>
    </div>
  );
}