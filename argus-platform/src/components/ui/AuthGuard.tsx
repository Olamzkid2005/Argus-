"use client";

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { signOut, useSession } from "next-auth/react";
import { signIn } from "next-auth/react";
import { Loader2 } from "lucide-react";

export function AuthGuard({
  children,
  required = true,
}: {
  children: React.ReactNode;
  required?: boolean;
}) {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    if (status === "loading") {
      return;
    }
    setIsReady(true);

    if (required && !session) {
      signIn();
    }
  }, [session, status, required]);

  if (!isReady || status === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (required && !session) {
    return null;
  }

  return <>{children}</>;
}

export { useSession, signIn, signOut };
