"use client";

import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Suspense } from "react";

function AuthErrorContent() {
  const searchParams = useSearchParams();
  const error = searchParams.get("error");

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="max-w-md w-full space-y-8 p-8 bg-white rounded-lg shadow">
        <div>
          <h2 className="text-center text-3xl font-bold text-gray-900">
            Authentication Error
          </h2>
        </div>
        <div className="mt-4">
          <div
            className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded"
            role="alert"
          >
            <p className="font-medium">
              An error occurred during authentication
            </p>
            {error && <p className="text-sm mt-1">{error}</p>}
          </div>
        </div>
        <div className="mt-6">
          <Link
            href="/auth/signin"
            className="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
          >
            Back to Sign In
          </Link>
        </div>
      </div>
    </div>
  );
}

export default function AuthError() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-gray-50">
          <p>Loading...</p>
        </div>
      }
    >
      <AuthErrorContent />
    </Suspense>
  );
}
