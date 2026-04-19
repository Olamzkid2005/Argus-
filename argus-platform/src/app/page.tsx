"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  Zap,
  ShieldCheck,
  Cpu,
  Network,
  ArrowRight,
  Loader2,
} from "lucide-react";
import { signIn, signOut, useSession } from "next-auth/react";

export default function Home() {
  const router = useRouter();
  const { data: session, status } = useSession();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Wait for session to load
    if (status === "loading") {
      return;
    }
    setLoading(false);

    // If not logged in, show landing page with sign-in prompt
    // If logged in, redirect to dashboard
    if (session) {
      router.push("/dashboard");
    }
  }, [session, status, router]);

  if (loading || status === "loading") {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center py-20 px-6">
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.5 }}
        className="w-full max-w-5xl"
      >
        <div className="prism-glass p-12 rounded-[2rem] relative overflow-hidden text-center">
          {/* Background Scanner Visual */}
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 opacity-20 pointer-events-none">
            <div className="prism-scanner w-[500px] h-[500px]" />
          </div>

          <div className="relative z-10">
            <motion.div
              initial={{ y: 20, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{ delay: 0.2 }}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-primary/10 border border-primary/20 text-primary text-xs font-bold uppercase tracking-widest mb-8"
            >
              <Zap className="h-4 w-4" />
              Autonomous Engine v2.0 Active
            </motion.div>

            <h1 className="text-6xl md:text-8xl font-extrabold tracking-tighter mb-6 bg-gradient-to-br from-foreground to-muted-foreground bg-clip-text text-transparent">
              Security at the <br />
              <span className="text-primary italic">Speed of Thought</span>
            </h1>

            <p className="text-lg md:text-xl text-muted-foreground max-w-2xl mx-auto mb-10 text-balance">
              Argus transforms passive scanning into autonomous intelligence.
              Our AI orchestrates complex attack chains to identify critical
              risks before they exist.
            </p>

            <div className="flex flex-col sm:flex-row gap-4 justify-center">
              <button
                onClick={() => signIn()}
                className="inline-flex items-center justify-center gap-2 px-8 py-4 bg-primary text-primary-foreground rounded-2xl font-bold text-lg hover:shadow-[0_0_30px_rgba(59,130,246,0.5)] transition-all hover:-translate-y-1"
              >
                <ShieldCheck className="h-5 w-5" />
                Sign In to Launch
                <ArrowRight className="h-5 w-5" />
              </button>
              <a
                href="/docs"
                className="inline-flex items-center justify-center gap-2 px-8 py-4 bg-secondary text-secondary-foreground rounded-2xl font-bold text-lg border border-border hover:bg-muted transition-all"
              >
                Documentation
              </a>
            </div>

            <div className="mt-20 grid grid-cols-1 md:grid-cols-3 gap-8">
              {[
                {
                  icon: ShieldCheck,
                  title: "Autonomous Recon",
                  desc: "Passive and active enumeration discovery at scale.",
                },
                {
                  icon: Cpu,
                  title: "AI Intelligence",
                  desc: "Gathers findings and chains them into exploit paths.",
                },
                {
                  icon: Network,
                  title: "Attack Graphs",
                  desc: "Visualizes the blast radius of every vulnerability.",
                },
              ].map((item, i) => (
                <div
                  key={i}
                  className="flex flex-col items-center text-center p-6"
                >
                  <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center mb-4 border border-primary/10">
                    <item.icon className="h-6 w-6 text-primary" />
                  </div>
                  <h3 className="font-bold text-lg mb-2">{item.title}</h3>
                  <p className="text-sm text-muted-foreground">{item.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
