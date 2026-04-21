"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { 
  Zap, 
  ShieldCheck, 
  ArrowRight, 
  Loader2,
  Globe,
  Lock,
  Cpu,
  Fingerprint,
  Radio,
  Eye as EyeIcon,
  ShieldAlert,
  ChevronDown,
  Activity,
  Terminal,
  Database,
  LayoutDashboard,
  UserPlus
} from "lucide-react";
import { signIn, useSession } from "next-auth/react";
import { motion, useScroll, useTransform, useInView } from "framer-motion";
import MatrixDataRain from "@/components/effects/MatrixDataRain";
import SurveillanceEye from "@/components/effects/SurveillanceEye";
import ScannerReveal from "@/components/effects/ScannerReveal";

// ── Sections Components ──

function FeatureCard({ icon: Icon, title, desc, delay }: { icon: any, title: string, desc: string, delay: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      whileInView={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay }}
      viewport={{ once: true }}
      className="group relative p-8 border border-structural bg-surface/30 backdrop-blur-sm hover:border-prism-cream/30 transition-all duration-500"
    >
      <div className="absolute top-0 right-0 p-4 opacity-0 group-hover:opacity-100 transition-opacity">
        <Zap size={14} className="text-prism-cream animate-pulse" />
      </div>
      <div className="w-12 h-12 flex items-center justify-center border border-structural mb-6 group-hover:bg-prism-cream/5 transition-colors">
        <Icon size={24} className="text-text-primary group-hover:text-prism-cream transition-colors" />
      </div>
      <h3 className="text-lg font-bold text-text-primary uppercase tracking-widest mb-3 font-mono">
        {title}
      </h3>
      <p className="text-sm text-text-secondary leading-relaxed font-mono opacity-80">
        {desc}
      </p>
    </motion.div>
  );
}

function StatItem({ value, label }: { value: string, label: string }) {
  return (
    <div className="space-y-1">
      <div className="text-3xl font-mono text-text-primary tracking-tighter">{value}</div>
      <div className="text-[10px] font-bold text-text-secondary uppercase tracking-[0.2em]">{label}</div>
    </div>
  );
}

// ── Main Page Content ──

function LandingContent({ session }: { session: any }) {
  const heroRef = useRef(null);
  const { scrollYProgress } = useScroll();
  
  const eyeOpacity = useTransform(scrollYProgress, [0, 0.2], [1, 0.1]);
  const heroScale = useTransform(scrollYProgress, [0, 0.2], [1, 0.95]);

  return (
    <div className="dark min-h-screen bg-void text-text-primary selection:bg-prism-cream selection:text-void overflow-x-hidden relative">
      {/* ── Background Layer ── */}
      <div className="fixed inset-0 z-0 opacity-20 pointer-events-none">
        <MatrixDataRain />
      </div>
      <div className="fixed inset-0 z-0 bg-gradient-to-b from-transparent via-void/50 to-void pointer-events-none" />

      {/* ── Hero Section ── */}
      <section ref={heroRef} className="relative min-h-screen flex flex-col justify-center px-12 md:px-24 overflow-hidden">
        <motion.div style={{ scale: heroScale }} className="relative z-10 grid grid-cols-1 lg:grid-cols-2 gap-16 items-center pt-20">
          <div className="space-y-12">
            <motion.div 
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              className="inline-flex items-center gap-2 px-4 py-1.5 border border-structural bg-surface/10 text-[10px] font-bold text-prism-cream uppercase tracking-[0.3em]"
            >
              <Activity size={14} className="animate-pulse" />
              Autonomous Security Terminal
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 30 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
            >
              <h1 className="text-8xl md:text-[11rem] font-semibold tracking-tighter leading-[0.8] font-mono italic text-text-primary">
                ARGUS
              </h1>
              <div className="mt-4 flex items-center gap-4">
                <div className="h-[1px] w-12 bg-prism-cream/40" />
                <p className="text-xl md:text-2xl text-prism-cream font-mono uppercase tracking-[0.4em] opacity-80">
                  SOC Defense Platform
                </p>
              </div>
            </motion.div>

            <motion.p 
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              className="text-lg text-text-secondary max-w-xl leading-relaxed font-mono uppercase tracking-tight text-[14px] opacity-80"
            >
              Advanced adversarial simulation and SOC orchestration. 
              Monitor, detect, and neutralize threats with machine intelligence.
            </motion.p>

            <motion.div 
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
              className="flex flex-wrap items-center gap-6 pt-4"
            >
              <Link 
                href="/auth/signin"
                className="group relative flex items-center gap-4 px-10 py-5 bg-prism-cream text-void font-bold text-sm tracking-[0.2em] uppercase hover:bg-white transition-all shadow-glow-cream"
              >
                {session ? "Enter Terminal" : "Initialize Node"}
                <ArrowRight size={20} className="group-hover:translate-x-1 transition-transform duration-300" />
              </Link>
              
              {!session && (
                <Link 
                  href="/auth/signup"
                  className="flex items-center gap-3 px-8 py-5 border border-structural text-text-primary font-bold text-xs tracking-widest uppercase hover:bg-surface/20 transition-all font-mono"
                >
                  <UserPlus size={16} />
                  Provision Access
                </Link>
              )}
            </motion.div>
          </div>

          <motion.div 
            style={{ opacity: eyeOpacity }}
            className="hidden lg:block relative h-[700px] group"
          >
            <div className="absolute inset-0 z-0">
              <SurveillanceEye />
            </div>
            <div className="absolute inset-0 border border-structural pointer-events-none group-hover:border-text-secondary/20 transition-colors duration-700" />
            <div className="absolute top-8 right-8 flex gap-3">
              <div className="w-1.5 h-1.5 rounded-full bg-prism-cyan animate-ping" />
              <div className="text-[10px] font-mono text-prism-cyan uppercase tracking-widest">Active Monitor</div>
            </div>
            <div className="absolute bottom-8 left-8 text-[11px] font-mono text-text-secondary opacity-40 uppercase tracking-[0.3em]">
              Vanguard SOC Visualizer :: Threat Level Low
            </div>
          </motion.div>
        </motion.div>

        <div className="absolute bottom-12 left-1/2 -translate-x-1/2 animate-bounce opacity-20 text-text-primary">
          <ChevronDown size={32} />
        </div>
      </section>

      {/* ── Capabilities Section ── */}
      <section className="relative py-32 px-12 md:px-24 border-t border-structural bg-surface/5">
        <div className="max-w-7xl mx-auto">
          <div className="mb-20 text-center space-y-4">
            <h2 className="text-[11px] font-bold text-prism-cyan uppercase tracking-[0.5em]">System Protocols</h2>
            <div className="text-4xl font-mono uppercase italic text-text-primary tracking-tighter">Defense Capabilities</div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <FeatureCard 
              icon={Globe} 
              title="Infrastructure Scan" 
              desc="Total visibility into internal and external network dependencies." 
              delay={0.1}
            />
            <FeatureCard 
              icon={ShieldAlert} 
              title="Automated Triage" 
              desc="Intelligent prioritization of vulnerabilities based on real-world risk." 
              delay={0.2}
            />
            <FeatureCard 
              icon={Cpu} 
              title="Response Logic" 
              desc="Automated playbooks for rapid threat containment and mitigation." 
              delay={0.3}
            />
            <FeatureCard 
              icon={Lock} 
              title="Identity Guard" 
              desc="Advanced monitoring of authentication flows and lateral movement." 
              delay={0.4}
            />
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="relative py-12 px-12 md:px-24 border-t border-structural flex flex-col md:flex-row justify-between items-center gap-8">
        <div className="flex items-center gap-4">
          <div className="p-2 border border-prism-cream/20 bg-surface/10">
            <ShieldCheck size={18} className="text-prism-cream" />
          </div>
          <span className="text-xs font-bold text-text-primary uppercase tracking-[0.4em]">ARGUS :: SOC</span>
        </div>
        
        <div className="flex gap-12 items-center">
          <a href="#" className="text-[10px] font-bold text-text-secondary uppercase tracking-widest hover:text-prism-cream transition-colors">Directives</a>
          <a href="#" className="text-[10px] font-bold text-text-secondary uppercase tracking-widest hover:text-prism-cream transition-colors">SOC Docs</a>
          <a href="#" className="text-[10px] font-bold text-text-secondary uppercase tracking-widest hover:text-prism-cream transition-colors">Encrypted Support</a>
        </div>

        <div className="text-[9px] font-mono text-text-secondary/40 uppercase tracking-[0.2em]">
          © 2026 Argus Systems. SOC-Operational.
        </div>
      </footer>
    </div>
  );
}

export default function Home() {
  const { data: session, status } = useSession();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (status === "loading") return;
    setLoading(false);
  }, [status]);

  if (loading || status === "loading") {
    return (
      <div className="flex items-center justify-center min-h-screen bg-void text-prism-cream">
        <Loader2 className="h-8 w-8 animate-spin text-prism-cream" />
      </div>
    );
  }

  return <LandingContent session={session} />;
}
