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
  ShieldAlert,
  ChevronDown,
  Activity,
  Menu,
  X,
  Code2,
  MessageSquare,
  Image as ImageIcon,
  Building2,
  Server,
  Network,
  Clock,
  Star,
  BookOpen,
  ChevronRight,
  Fingerprint,
  Radio,
  Terminal,
  Database,
  LayoutDashboard,
  UserPlus,
} from "lucide-react";
import { signIn, useSession } from "next-auth/react";
import { motion, useScroll, useTransform } from "framer-motion";
import SurveillanceEye from "@/components/effects/SurveillanceEye";
import { ScrollReveal } from "@/components/animations/ScrollReveal";
import { StaggerContainer, StaggerItem } from "@/components/animations/StaggerContainer";

// ── Animation Variants ──

const fadeInUp = {
  hidden: { opacity: 0, y: 24 },
  visible: (delay: number = 0) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.6, delay, ease: "easeOut" as const },
  }),
};

const fadeIn = {
  hidden: { opacity: 0 },
  visible: (delay: number = 0) => ({
    opacity: 1,
    transition: { duration: 0.6, delay },
  }),
};

const staggerContainer = {
  hidden: {},
  visible: {
    transition: { staggerChildren: 0.1 },
  },
};

// ── Section Components ──

function Navbar({ session }: { session: any }) {
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const navLinks = [
    { label: "Platform", href: "#platform" },
    { label: "Models", href: "#models" },
    { label: "Developers", href: "#developers" },
    { label: "Pricing", href: "#pricing" },
  ];

  return (
    <nav
      className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
        scrolled
          ? "bg-surface/80 backdrop-blur-xl border-b border-outline/20 shadow-sm"
          : "bg-transparent"
      }`}
    >
      <div className="max-w-7xl mx-auto px-6 lg:px-8">
        <div className="flex items-center justify-between h-16 lg:h-20">
          {/* Brand */}
          <Link href="/" className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
              <ShieldCheck size={18} className="text-white" />
            </div>
            <span className="font-headline text-xl font-bold text-on-surface tracking-tight">
              Argus
            </span>
          </Link>

          {/* Desktop Nav */}
          <div className="hidden md:flex items-center gap-8">
            {navLinks.map((link) => (
              <a
                key={link.label}
                href={link.href}
                className="text-sm font-body text-on-surface-variant hover:text-on-surface transition-colors duration-300"
              >
                {link.label}
              </a>
            ))}
          </div>

          {/* Desktop Actions */}
          <div className="hidden md:flex items-center gap-4">
            <Link
              href="/auth/signin"
              className="text-sm font-body font-medium text-on-surface-variant hover:text-on-surface transition-colors duration-300"
            >
              Login
            </Link>
            <Link
              href="/auth/signup"
              className="px-5 py-2.5 rounded-xl primary-gradient text-white text-sm font-semibold shadow-glow hover:shadow-glow-strong transition-all duration-300"
            >
              Get Started
            </Link>
          </div>

          {/* Mobile Toggle */}
          <button
            onClick={() => setMobileOpen(!mobileOpen)}
            className="md:hidden p-2 rounded-lg hover:bg-surface-container transition-colors"
          >
            {mobileOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
      </div>

      {/* Mobile Menu */}
      {mobileOpen && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="md:hidden bg-surface/95 backdrop-blur-xl border-b border-outline/20 px-6 pb-6 pt-2"
        >
          <div className="flex flex-col gap-4">
            {navLinks.map((link) => (
              <a
                key={link.label}
                href={link.href}
                onClick={() => setMobileOpen(false)}
                className="text-sm font-body text-on-surface-variant hover:text-on-surface transition-colors"
              >
                {link.label}
              </a>
            ))}
            <hr className="border-outline/20" />
            <Link
              href="/auth/signin"
              className="text-sm font-body font-medium text-on-surface-variant"
              onClick={() => setMobileOpen(false)}
            >
              Login
            </Link>
            <Link
              href="/auth/signup"
              className="px-5 py-2.5 rounded-xl primary-gradient text-white text-sm font-semibold text-center"
              onClick={() => setMobileOpen(false)}
            >
              Get Started
            </Link>
          </div>
        </motion.div>
      )}
    </nav>
  );
}

function FeatureCard({
  icon: Icon,
  title,
  desc,
  delay,
}: {
  icon: any;
  title: string;
  desc: string;
  delay: number;
}) {
  return (
    <motion.div
      custom={delay}
      variants={fadeInUp}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-50px" }}
      className="group relative p-6 lg:p-8 rounded-2xl bg-surface border border-outline/20 hover:border-primary/30 hover:shadow-glow transition-all duration-300"
    >
      <div className="w-11 h-11 flex items-center justify-center rounded-xl bg-surface-container mb-5 group-hover:bg-primary/10 transition-colors duration-300">
        <Icon size={22} className="text-primary" />
      </div>
      <h3 className="text-base font-headline font-semibold text-on-surface mb-2">
        {title}
      </h3>
      <p className="text-sm font-body text-on-surface-variant leading-relaxed">
        {desc}
      </p>
    </motion.div>
  );
}

function ModelCard({
  name,
  provider,
  latency,
  description,
  delay,
}: {
  name: string;
  provider: string;
  latency: string;
  description: string;
  delay: number;
}) {
  return (
    <motion.div
      custom={delay}
      variants={fadeInUp}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-50px" }}
      className="group relative p-6 rounded-2xl bg-surface border border-outline/20 hover:border-primary/30 hover:shadow-glow transition-all duration-300"
    >
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs font-label font-medium px-2.5 py-1 rounded-full bg-surface-container text-on-surface-variant">
          {provider}
        </span>
        <span className="flex items-center gap-1 text-xs font-label text-emerald-600 dark:text-emerald-400">
          <Clock size={12} />
          {latency}
        </span>
      </div>
      <h3 className="text-base font-headline font-semibold text-on-surface mb-2">
        {name}
      </h3>
      <p className="text-sm font-body text-on-surface-variant leading-relaxed">
        {description}
      </p>
    </motion.div>
  );
}

function TestimonialCard({
  quote,
  author,
  role,
  delay,
}: {
  quote: string;
  author: string;
  role: string;
  delay: number;
}) {
  return (
    <motion.div
      custom={delay}
      variants={fadeInUp}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-50px" }}
      className="p-8 rounded-2xl bg-surface border border-outline/20"
    >
      <div className="flex gap-1 mb-4">
        {[...Array(5)].map((_, i) => (
          <Star key={i} size={14} className="text-primary fill-primary" />
        ))}
      </div>
      <p className="text-base font-body text-on-surface leading-relaxed mb-6">
        &ldquo;{quote}&rdquo;
      </p>
      <div>
        <p className="text-sm font-headline font-semibold text-on-surface">
          {author}
        </p>
        <p className="text-xs font-body text-on-surface-variant">{role}</p>
      </div>
    </motion.div>
  );
}

function BlogCard({
  title,
  excerpt,
  tag,
  delay,
}: {
  title: string;
  excerpt: string;
  tag: string;
  delay: number;
}) {
  return (
    <motion.article
      custom={delay}
      variants={fadeInUp}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-50px" }}
      className="group cursor-pointer"
    >
      <div className="aspect-[16/10] rounded-2xl bg-surface-container mb-4 overflow-hidden border border-outline/20">
        <div className="w-full h-full bg-surface-container-high group-hover:scale-105 transition-transform duration-500 flex items-center justify-center">
          <BookOpen size={32} className="text-outline" />
        </div>
      </div>
      <span className="text-xs font-label font-medium px-2.5 py-1 rounded-full bg-surface-container text-on-surface-variant mb-3 inline-block">
        {tag}
      </span>
      <h3 className="text-base font-headline font-semibold text-on-surface mb-2 group-hover:text-primary transition-colors duration-300">
        {title}
      </h3>
      <p className="text-sm font-body text-on-surface-variant leading-relaxed">
        {excerpt}
      </p>
    </motion.article>
  );
}

// ── Main Page Content ──

function LandingContent({ session }: { session: any }) {
  const heroRef = useRef(null);
  const { scrollYProgress } = useScroll();

  const eyeOpacity = useTransform(scrollYProgress, [0, 0.2], [1, 0.1]);
  const heroScale = useTransform(scrollYProgress, [0, 0.2], [1, 0.98]);

  return (
    <div className="min-h-screen bg-surface text-on-surface selection:bg-primary selection:text-white overflow-x-hidden relative">
      {/* ── Background Layer ── */}
      <div className="fixed inset-0 z-0 bg-gradient-to-b from-transparent via-surface/50 to-surface pointer-events-none" />

      {/* ── Navigation ── */}
      <Navbar session={session} />

      {/* ── Hero Section ── */}
      <section
        ref={heroRef}
        className="relative min-h-screen flex flex-col justify-center px-6 md:px-12 lg:px-24 pt-20 overflow-hidden hero-mesh"
      >
        <motion.div
          style={{ scale: heroScale }}
          className="relative z-10 grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16 items-center max-w-7xl mx-auto w-full"
        >
          <div className="space-y-8 lg:space-y-10">
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.6 }}
              className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-outline/30 bg-surface/60 backdrop-blur-sm text-xs font-label font-semibold text-primary uppercase tracking-wider"
            >
              <Activity size={14} className="animate-pulse" />
              Autonomous Security Platform
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 30 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1, duration: 0.6 }}
            >
              <h1 className="text-5xl md:text-7xl lg:text-8xl font-headline font-bold tracking-tight leading-[0.95] text-on-surface">
                Build. Tune.{" "}
                <span className="bg-gradient-to-r from-primary to-violet-400 bg-clip-text text-transparent">
                  Scale.
                </span>
              </h1>
            </motion.div>

            <motion.p
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2, duration: 0.6 }}
              className="text-base md:text-lg text-on-surface-variant max-w-xl leading-relaxed font-body"
            >
              The infrastructure for intelligence. Deploy AI-powered security
              operations at scale with unified observability, automated
              triage, and real-time threat neutralization.
            </motion.p>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3, duration: 0.6 }}
              className="flex flex-wrap items-center gap-4 pt-2"
            >
              <Link
                href="/auth/signup"
                className="group flex items-center gap-2 px-7 py-3.5 rounded-xl primary-gradient text-white font-semibold text-sm shadow-glow hover:shadow-glow-strong transition-all duration-300"
              >
                Get Started Free
                <ArrowRight
                  size={18}
                  className="group-hover:translate-x-1 transition-transform duration-300"
                />
              </Link>

              <Link
                href="#contact"
                className="flex items-center gap-2 px-7 py-3.5 rounded-xl border border-outline/40 text-on-surface font-semibold text-sm hover:bg-surface-container transition-all duration-300"
              >
                Talk to our team
              </Link>
            </motion.div>
          </div>

          <motion.div
            style={{ opacity: eyeOpacity }}
            className="hidden lg:block relative h-[500px] xl:h-[600px] group"
          >
            <div className="absolute inset-0 z-0">
              <SurveillanceEye />
            </div>
            <div className="absolute inset-0 border border-outline/20 rounded-3xl pointer-events-none group-hover:border-primary/20 transition-colors duration-700" />
            <div className="absolute top-6 right-6 flex items-center gap-2 px-3 py-1.5 rounded-full bg-surface/80 backdrop-blur-sm border border-outline/20">
              <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <div className="text-[10px] font-label font-semibold text-on-surface-variant uppercase tracking-wider">
                Active Monitor
              </div>
            </div>
            <div className="absolute bottom-6 left-6 text-[11px] font-body text-on-surface-variant/60 uppercase tracking-[0.2em]">
              Vanguard SOC Visualizer :: Threat Level Low
            </div>
          </motion.div>
        </motion.div>

        <div className="absolute bottom-12 left-1/2 -translate-x-1/2 animate-bounce opacity-30 text-on-surface-variant">
          <ChevronDown size={28} />
        </div>
      </section>

      {/* ── Logo Marquee ── */}
      <ScrollReveal direction="up" delay={0.1}>
        <section className="relative py-16 border-y border-outline/10 bg-surface-container/50">
          <div className="max-w-7xl mx-auto px-6 lg:px-8 text-center">
            <motion.p
              custom={0}
              variants={fadeIn}
              initial="hidden"
              whileInView="visible"
              viewport={{ once: true }}
              className="text-xs font-label font-semibold text-on-surface-variant uppercase tracking-[0.2em] mb-10"
            >
              Trusted by the most innovative teams
            </motion.p>
            <motion.div
              variants={staggerContainer}
              initial="hidden"
              whileInView="visible"
              viewport={{ once: true }}
              className="flex flex-wrap justify-center items-center gap-x-12 gap-y-6"
            >
            {["Vanguard", "Nexus Corp", "CyberDyne", "OmniSec", "Fortress"].map(
              (name, i) => (
                <motion.div
                  key={name}
                  custom={i * 0.1}
                  variants={fadeIn}
                  className="text-lg font-headline font-bold text-on-surface-variant/40 hover:text-on-surface-variant/70 transition-colors duration-300"
                >
                  {name}
                </motion.div>
              )
            )}
          </motion.div>
        </div>
      </section>
      </ScrollReveal>

      {/* ── Capabilities Bento Grid ── */}
      <ScrollReveal direction="up" delay={0.1}>
        <section id="platform" className="relative py-24 lg:py-32 px-6 md:px-12 lg:px-24">
          <div className="max-w-7xl mx-auto">
            <div className="mb-16 text-center space-y-4">
              <motion.h2
                custom={0}
                variants={fadeInUp}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true }}
                className="text-xs font-label font-bold text-primary uppercase tracking-[0.2em]"
              >
                Platform Capabilities
              </motion.h2>
            <motion.p
              custom={0.1}
              variants={fadeInUp}
              initial="hidden"
              whileInView="visible"
              viewport={{ once: true }}
              className="text-3xl md:text-4xl font-headline font-bold text-on-surface tracking-tight"
            >
              Everything you need to secure AI infrastructure
            </motion.p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
            <FeatureCard
              icon={Code2}
              title="Code Assistance"
              desc="AI-powered code review and vulnerability detection integrated directly into your development pipeline."
              delay={0.1}
            />
            <FeatureCard
              icon={MessageSquare}
              title="Conversational AI"
              desc="Natural language interface for querying security posture and orchestrating response playbooks."
              delay={0.2}
            />
            <FeatureCard
              icon={ImageIcon}
              title="Multimodal"
              desc="Process and analyze visual threat intelligence, diagrams, and unstructured security data."
              delay={0.3}
            />
            <FeatureCard
              icon={Building2}
              title="Enterprise RAG"
              desc="Retrieval-augmented generation grounded in your security documentation and incident history."
              delay={0.4}
            />
          </div>
        </div>
      </section>
      </ScrollReveal>

      {/* ── Model Library ── */}
      <ScrollReveal direction="up" delay={0.1}>
        <section
          id="models"
          className="relative py-24 lg:py-32 px-6 md:px-12 lg:px-24 bg-surface-container/30"
        >
          <div className="max-w-7xl mx-auto">
            <div className="mb-16 text-center space-y-4">
              <motion.h2
                custom={0}
                variants={fadeInUp}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true }}
                className="text-xs font-label font-bold text-primary uppercase tracking-[0.2em]"
              >
                Model Library
              </motion.h2>
            <motion.p
              custom={0.1}
              variants={fadeInUp}
              initial="hidden"
              whileInView="visible"
              viewport={{ once: true }}
              className="text-3xl md:text-4xl font-headline font-bold text-on-surface tracking-tight"
            >
              State-of-the-art security, at the touch of a button
            </motion.p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            <ModelCard
              name="DeepSeek V3"
              provider="DeepSeek"
              latency="45ms"
              description="Advanced reasoning model optimized for security analysis and threat attribution."
              delay={0.1}
            />
            <ModelCard
              name="Mistral Large"
              provider="Mistral AI"
              latency="62ms"
              description="High-performance multilingual model with strong code and log analysis capabilities."
              delay={0.2}
            />
            <ModelCard
              name="Gemma 2"
              provider="Google"
              latency="38ms"
              description="Efficient open model delivering excellent results for real-time classification tasks."
              delay={0.3}
            />
            <ModelCard
              name="Llama 3.1 405B"
              provider="Meta"
              latency="89ms"
              description="Frontier open-weight model with unmatched depth for complex investigation workflows."
              delay={0.4}
            />
          </div>
        </div>
      </section>
      </ScrollReveal>

      {/* ── Infrastructure ── */}
      <ScrollReveal direction="up" delay={0.1}>
        <section className="relative py-24 lg:py-32 px-6 md:px-12 lg:px-24">
          <div className="max-w-7xl mx-auto">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-20 items-center">
              <motion.div
                custom={0}
                variants={fadeInUp}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true }}
                className="space-y-8"
              >
                <div>
                  <h2 className="text-xs font-label font-bold text-primary uppercase tracking-[0.2em] mb-4">
                    Global Infrastructure
                  </h2>
                <p className="text-3xl md:text-4xl font-headline font-bold text-on-surface tracking-tight mb-6">
                  Built for scale, designed for security
                </p>
                <p className="text-base font-body text-on-surface-variant leading-relaxed">
                  Argus runs on a globally distributed edge network with
                  enterprise-grade compliance and zero-trust architecture at
                  every layer.
                </p>
              </div>

              <div className="space-y-6">
                {[
                  {
                    icon: Globe,
                    title: "Global Distribution",
                    desc: "Deploy workloads across 40+ regions with automatic failover and sub-50ms latency.",
                  },
                  {
                    icon: Lock,
                    title: "Enterprise Security",
                    desc: "SOC 2 Type II, ISO 27001, and GDPR compliant with end-to-end encryption.",
                  },
                  {
                    icon: Server,
                    title: "Dedicated Compute",
                    desc: "Isolated tenant environments with dedicated GPUs and encrypted storage.",
                  },
                ].map((item, i) => (
                  <motion.div
                    key={item.title}
                    custom={0.2 + i * 0.1}
                    variants={fadeInUp}
                    initial="hidden"
                    whileInView="visible"
                    viewport={{ once: true }}
                    className="flex gap-4"
                  >
                    <div className="w-10 h-10 rounded-xl bg-surface-container flex items-center justify-center shrink-0">
                      <item.icon size={20} className="text-primary" />
                    </div>
                    <div>
                      <h3 className="text-sm font-headline font-semibold text-on-surface mb-1">
                        {item.title}
                      </h3>
                      <p className="text-sm font-body text-on-surface-variant leading-relaxed">
                        {item.desc}
                      </p>
                    </div>
                  </motion.div>
                ))}
              </div>
            </motion.div>

            <motion.div
              custom={0.3}
              variants={fadeInUp}
              initial="hidden"
              whileInView="visible"
              viewport={{ once: true }}
              className="relative aspect-square rounded-3xl bg-surface-container border border-outline/20 overflow-hidden"
            >
              <div className="absolute inset-0 matrix-grid" />
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="relative w-48 h-48">
                  <div className="absolute inset-0 rounded-full border border-primary/20 animate-[spin-slow_20s_linear_infinite]" />
                  <div className="absolute inset-4 rounded-full border border-primary/15 animate-[spin-slow_15s_linear_infinite_reverse]" />
                  <div className="absolute inset-8 rounded-full border border-primary/10 animate-[spin-slow_10s_linear_infinite]" />
                  <div className="absolute inset-0 flex items-center justify-center">
                    <Network size={40} className="text-primary" />
                  </div>
                </div>
              </div>
            </motion.div>
          </div>
        </div>
      </section>
      </ScrollReveal>

      {/* ── Testimonials ── */}
      <ScrollReveal direction="up" delay={0.1}>
        <section className="relative py-24 lg:py-32 px-6 md:px-12 lg:px-24 bg-surface-container/30">
          <div className="max-w-7xl mx-auto">
            <div className="mb-16 text-center space-y-4">
              <motion.h2
                custom={0}
                variants={fadeInUp}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true }}
                className="text-xs font-label font-bold text-primary uppercase tracking-[0.2em]"
              >
                Customer Stories
              </motion.h2>
            <motion.p
              custom={0.1}
              variants={fadeInUp}
              initial="hidden"
              whileInView="visible"
              viewport={{ once: true }}
              className="text-3xl md:text-4xl font-headline font-bold text-on-surface tracking-tight"
            >
              Loved by security teams worldwide
            </motion.p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-4xl mx-auto">
            <TestimonialCard
              quote="Argus reduced our mean time to detect by 73%. The autonomous triage capabilities are genuinely transformative for our SOC workflow."
              author="Sarah Chen"
              role="CISO, Nexus Corporation"
              delay={0.1}
            />
            <TestimonialCard
              quote="We evaluated every major platform. Argus was the only one that combined real-time intelligence with actual automated response."
              author="Marcus Webb"
              role="Head of Security, OmniSec"
              delay={0.2}
            />
          </div>
        </div>
      </section>
      </ScrollReveal>

      {/* ── Blog Section ── */}
      <ScrollReveal direction="up" delay={0.1}>
        <section className="relative py-24 lg:py-32 px-6 md:px-12 lg:px-24">
          <div className="max-w-7xl mx-auto">
            <div className="mb-16 text-center space-y-4">
              <motion.h2
                custom={0}
                variants={fadeInUp}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true }}
                className="text-xs font-label font-bold text-primary uppercase tracking-[0.2em]"
              >
                From the Blog
              </motion.h2>
            <motion.p
              custom={0.1}
              variants={fadeInUp}
              initial="hidden"
              whileInView="visible"
              viewport={{ once: true }}
              className="text-3xl md:text-4xl font-headline font-bold text-on-surface tracking-tight"
            >
              Latest insights on AI security
            </motion.p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            <BlogCard
              title="The Future of Autonomous SOC Operations"
              excerpt="How large language models are reshaping incident response and what it means for enterprise security teams."
              tag="Research"
              delay={0.1}
            />
            <BlogCard
              title="Deploying DeepSeek for Threat Attribution"
              excerpt="A technical deep dive into leveraging reasoning models for faster and more accurate attack path analysis."
              tag="Engineering"
              delay={0.2}
            />
            <BlogCard
              title="Zero-Trust Architecture in 2026"
              excerpt="Why perimeter-based security is dead and how identity-centric models are becoming the new standard."
              tag="Strategy"
              delay={0.3}
            />
          </div>
        </div>
      </section>
      </ScrollReveal>

      {/* ── Final CTA ── */}
      <ScrollReveal direction="up" delay={0.1}>
        <section className="relative py-24 lg:py-32 px-6 md:px-12 lg:px-24">
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.7 }}
            className="max-w-5xl mx-auto"
          >
          <div className="relative overflow-hidden rounded-[2rem] primary-gradient p-10 md:p-16 text-center">
            <div className="absolute top-0 left-0 w-full h-full opacity-10">
              <div className="absolute -top-24 -right-24 w-64 h-64 rounded-full bg-white blur-3xl" />
              <div className="absolute -bottom-24 -left-24 w-64 h-64 rounded-full bg-white blur-3xl" />
            </div>
            <div className="relative z-10 space-y-8">
              <h2 className="text-3xl md:text-5xl font-headline font-bold text-white tracking-tight">
                Start building today
              </h2>
              <p className="text-base md:text-lg text-white/80 max-w-xl mx-auto font-body">
                Join thousands of teams using Argus to secure their AI
                infrastructure. Free tier available.
              </p>
              <div className="flex flex-wrap items-center justify-center gap-4">
                <Link
                  href="/auth/signup"
                  className="px-8 py-3.5 rounded-xl bg-white text-primary font-semibold text-sm shadow-lg hover:shadow-xl transition-all duration-300"
                >
                  Get Started Free
                </Link>
                <Link
                  href="#contact"
                  className="px-8 py-3.5 rounded-xl border border-white/30 text-white font-semibold text-sm hover:bg-white/10 transition-all duration-300"
                >
                  Talk to Sales
                </Link>
              </div>
            </div>
          </div>
        </motion.div>
      </section>
      </ScrollReveal>

      {/* ── Footer ── */}
      <ScrollReveal direction="up" delay={0.1}>
        <footer className="relative py-16 px-6 md:px-12 lg:px-24 border-t border-outline/10 bg-surface">
          <div className="max-w-7xl mx-auto">
            <StaggerContainer className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-10 mb-12" staggerDelay={0.06}>
              <StaggerItem className="col-span-2 md:col-span-4 lg:col-span-1">
                <Link href="/" className="flex items-center gap-2.5 mb-4">
                  <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
                    <ShieldCheck size={18} className="text-white" />
                  </div>
                  <span className="font-headline text-lg font-bold text-on-surface">
                    Argus
                  </span>
                </Link>
                <p className="text-sm font-body text-on-surface-variant leading-relaxed">
                  Infrastructure for intelligence. Secure AI at scale.
                </p>
              </StaggerItem>

              <StaggerItem>
                <h4 className="text-xs font-label font-semibold text-on-surface uppercase tracking-wider mb-4">
                  Product
                </h4>
                <ul className="space-y-3">
                  {["Platform", "Models", "Pricing", "Changelog"].map((item) => (
                    <li key={item}>
                      <a
                        href="#"
                        className="text-sm font-body text-on-surface-variant hover:text-on-surface transition-colors duration-300"
                      >
                        {item}
                      </a>
                    </li>
                  ))}
                </ul>
              </StaggerItem>

              <StaggerItem>
                <h4 className="text-xs font-label font-semibold text-on-surface uppercase tracking-wider mb-4">
                  Developers
                </h4>
                <ul className="space-y-3">
                  {["Documentation", "API Reference", "SDKs", "Status"].map(
                    (item) => (
                      <li key={item}>
                        <a
                          href="#"
                          className="text-sm font-body text-on-surface-variant hover:text-on-surface transition-colors duration-300"
                        >
                          {item}
                        </a>
                      </li>
                    )
                  )}
                </ul>
              </StaggerItem>

              <StaggerItem>
                <h4 className="text-xs font-label font-semibold text-on-surface uppercase tracking-wider mb-4">
                  Company
                </h4>
                <ul className="space-y-3">
                  {["About", "Blog", "Careers", "Contact"].map((item) => (
                    <li key={item}>
                      <a
                        href="#"
                        className="text-sm font-body text-on-surface-variant hover:text-on-surface transition-colors duration-300"
                      >
                        {item}
                      </a>
                    </li>
                  ))}
                </ul>
              </StaggerItem>

              <StaggerItem>
                <h4 className="text-xs font-label font-semibold text-on-surface uppercase tracking-wider mb-4">
                  Legal
                </h4>
                <ul className="space-y-3">
                  {["Privacy", "Terms", "Security"].map((item) => (
                    <li key={item}>
                      <a
                        href="#"
                        className="text-sm font-body text-on-surface-variant hover:text-on-surface transition-colors duration-300"
                      >
                        {item}
                      </a>
                    </li>
                  ))}
                </ul>
              </StaggerItem>
            </StaggerContainer>

            <div className="pt-8 border-t border-outline/10 flex flex-col md:flex-row justify-between items-center gap-4">
              <span className="text-xs font-body text-on-surface-variant/60">
                © 2026 Argus Systems. All rights reserved.
              </span>
              <div className="flex items-center gap-6">
                <a
                  href="#"
                  className="text-xs font-body text-on-surface-variant/60 hover:text-on-surface-variant transition-colors"
                >
                  Directives
                </a>
                <a
                  href="#"
                  className="text-xs font-body text-on-surface-variant/60 hover:text-on-surface-variant transition-colors"
                >
                  SOC Docs
                </a>
                <a
                  href="#"
                  className="text-xs font-body text-on-surface-variant/60 hover:text-on-surface-variant transition-colors"
                >
                  Encrypted Support
                </a>
              </div>
            </div>
          </div>
        </footer>
      </ScrollReveal>
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
      <div className="flex items-center justify-center min-h-screen bg-surface text-primary">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return <LandingContent session={session} />;
}
