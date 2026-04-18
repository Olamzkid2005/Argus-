import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/ThemeProvider";
import { ThemeToggle } from "@/components/ThemeToggle";
import { ShieldCheck } from "lucide-react";

const plusJakartaSans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-plus-jakarta",
});

export const metadata: Metadata = {
  title: "Argus Pentest Platform",
  description: "AI-Powered Autonomous Penetration Testing Platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${plusJakartaSans.variable} font-sans antialiased`}>
        <ThemeProvider
          attribute="data-theme"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          <div className="relative min-h-screen">
            <nav className="sticky top-0 z-50 h-16 border-b border-border bg-background/70 backdrop-blur-xl flex items-center justify-between px-10">
              <div className="flex items-center gap-3">
                <ShieldCheck className="h-6 w-6 text-primary" />
                <span className="text-xl font-extrabold tracking-tight bg-gradient-to-br from-accent to-primary bg-clip-text text-transparent uppercase">
                  Argus :: Prism
                </span>
              </div>
              
              <div className="flex items-center gap-6">
                <div className="hidden md:flex items-center gap-6 text-sm font-medium text-muted-foreground">
                  <a href="/dashboard" className="transition-colors hover:text-primary">Dashboard</a>
                  <a href="/engagements" className="transition-colors hover:text-primary">Engagements</a>
                  <a href="/findings" className="transition-colors hover:text-primary">Findings</a>
                </div>
                <div className="h-6 w-px bg-border mx-2" />
                <ThemeToggle />
              </div>
            </nav>
            <main>{children}</main>
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
