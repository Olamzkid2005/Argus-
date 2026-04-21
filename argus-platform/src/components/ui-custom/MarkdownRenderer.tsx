"use client";

import React from "react";
import { Shield, Crosshair, AlertTriangle, Wrench, Radio, Lock } from "lucide-react";

interface ParsedBlock {
  type: "heading" | "paragraph" | "list" | "code" | "blockquote" | "divider";
  content: string;
  level?: number;
  items?: string[];
}

function parseMarkdown(text: string): ParsedBlock[] {
  const blocks: ParsedBlock[] = [];
  const lines = text.split("\n");
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      i++;
      continue;
    }

    // Divider
    if (/^---+|===+|\*\*\*+$/.test(trimmed)) {
      blocks.push({ type: "divider", content: "" });
      i++;
      continue;
    }

    // Heading
    const headingMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (headingMatch) {
      blocks.push({
        type: "heading",
        content: headingMatch[2].trim(),
        level: headingMatch[1].length,
      });
      i++;
      continue;
    }

    // Bold heading pattern
    const boldHeadingMatch = trimmed.match(/^\*\*\s*(.+?)\s*\*\*$/);
    if (boldHeadingMatch) {
      blocks.push({
        type: "heading",
        content: boldHeadingMatch[1].trim(),
        level: 2,
      });
      i++;
      continue;
    }

    // Blockquote
    if (trimmed.startsWith(">")) {
      let content = trimmed.slice(1).trim();
      i++;
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        content += "\n" + lines[i].trim().slice(1).trim();
        i++;
      }
      blocks.push({ type: "blockquote", content });
      continue;
    }

    // List
    if (/^[-*•]\s+|^\d+\.\s+/.test(trimmed)) {
      const items: string[] = [];
      while (i < lines.length) {
        const listLine = lines[i].trim();
        if (!listLine) break;
        if (/^[-*•]\s+|^\d+\.\s+/.test(listLine)) {
          items.push(listLine.replace(/^[-*•]\s+|^\d+\.\s+/, ""));
          i++;
        } else if (items.length > 0 && lines[i].startsWith("  ")) {
          items[items.length - 1] += " " + listLine;
          i++;
        } else {
          break;
        }
      }
      blocks.push({ type: "list", content: "", items });
      continue;
    }

    // Code block
    if (trimmed.startsWith("```")) {
      i++;
      let code = "";
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        code += lines[i] + "\n";
        i++;
      }
      blocks.push({ type: "code", content: code.trim() });
      i++;
      continue;
    }

    // Paragraph
    let paragraph = trimmed;
    i++;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].trim().match(/^(#{1,4})\s+|^[-*•]\s+|^\d+\.\s+|^>|^```/)
    ) {
      paragraph += " " + lines[i].trim();
      i++;
    }
    blocks.push({ type: "paragraph", content: paragraph });
  }

  return blocks;
}

function renderInline(text: string): React.ReactNode {
  if (!text) return null;
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i} className="text-text-primary font-semibold">{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*")) {
      return <em key={i} className="italic text-text-secondary">{part.slice(1, -1)}</em>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={i} className="px-1 py-0.5 bg-void border border-structural/60 text-prism-cyan text-[11px] font-mono rounded">
          {part.slice(1, -1)}
        </code>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

// ── Section definitions with icons & colors ──
const SECTION_META: Record<string, { icon: React.ReactNode; label: string; accent: string; border: string; bg: string }> = {
  VULNERABILITY: {
    icon: <AlertTriangle size={13} />,
    label: "VULNERABILITY",
    accent: "text-orange-400",
    border: "border-orange-400/25",
    bg: "bg-orange-400/[0.06]",
  },
  "ATTACK SCENARIO": {
    icon: <Crosshair size={13} />,
    label: "ATTACK SCENARIO",
    accent: "text-red-400",
    border: "border-red-400/25",
    bg: "bg-red-400/[0.06]",
  },
  "BUSINESS IMPACT": {
    icon: <Radio size={13} />,
    label: "BUSINESS IMPACT",
    accent: "text-prism-cream",
    border: "border-prism-cream/25",
    bg: "bg-prism-cream/[0.06]",
  },
  "FIX GUIDANCE": {
    icon: <Wrench size={13} />,
    label: "FIX GUIDANCE",
    accent: "text-green-400",
    border: "border-green-400/25",
    bg: "bg-green-400/[0.06]",
  },
};

function matchSection(title: string) {
  const upper = title.toUpperCase().replace(/[^A-Z\s]/g, "").trim();
  for (const key of Object.keys(SECTION_META)) {
    if (upper.includes(key)) return SECTION_META[key];
  }
  return null;
}

// ── Individual section card ──
function SectionCard({ meta, children }: { meta: typeof SECTION_META[string]; children: React.ReactNode }) {
  return (
    <div className={`border ${meta.border} ${meta.bg} mb-3 overflow-hidden`}>
      <div className={`flex items-center gap-2 px-3 py-2 border-b ${meta.border} ${meta.bg}`}>
        <span className={meta.accent}>{meta.icon}</span>
        <span className={`text-[10px] font-bold font-mono uppercase tracking-widest ${meta.accent}`}>
          {meta.label}
        </span>
      </div>
      <div className="px-3 py-3">
        {children}
      </div>
    </div>
  );
}

export function MarkdownRenderer({ content, variant }: { content: string; variant?: "default" | "chain" }) {
  const blocks = parseMarkdown(content);

  // Group blocks by section heading for card-based layout
  const sections: { meta: typeof SECTION_META[string] | null; blocks: ParsedBlock[] }[] = [];
  let current: typeof sections[0] | null = null;

  for (const block of blocks) {
    if (block.type === "heading" && block.level === 2) {
      const meta = matchSection(block.content);
      if (meta) {
        current = { meta, blocks: [] };
        sections.push(current);
        continue;
      }
    }
    if (current) {
      current.blocks.push(block);
    } else {
      // Ungrouped blocks before first section
      if (sections.length === 0 || sections[sections.length - 1].meta !== null) {
        sections.push({ meta: null, blocks: [] });
      }
      sections[sections.length - 1].blocks.push(block);
    }
  }

  return (
    <div className="space-y-0">
      {sections.map((section, sIdx) => {
        const content = section.blocks.map((block, bIdx) => {
          switch (block.type) {
            case "paragraph":
              return (
                <p key={bIdx} className="text-[13px] text-text-primary leading-[1.7] mb-2 last:mb-0">
                  {renderInline(block.content)}
                </p>
              );
            case "list":
              return (
                <ul key={bIdx} className="space-y-1.5 mt-2">
                  {block.items?.map((item, i) => (
                    <li key={i} className="flex items-start gap-2.5">
                      <span className="w-1 h-1 mt-[9px] shrink-0 bg-text-secondary/40 rotate-45" />
                      <span className="text-[13px] text-text-primary leading-[1.7]">{renderInline(item)}</span>
                    </li>
                  ))}
                </ul>
              );
            case "code":
              return (
                <div key={bIdx} className="border border-structural bg-void/80 overflow-hidden mt-2">
                  <pre className="p-3 text-[11px] font-mono text-text-secondary leading-relaxed overflow-x-auto">
                    <code>{block.content}</code>
                  </pre>
                </div>
              );
            case "blockquote":
              return (
                <div key={bIdx} className="border-l-2 border-prism-cyan/30 pl-3 py-1 mt-2">
                  <p className="text-[12px] text-text-secondary/80 italic leading-[1.6]">
                    {renderInline(block.content)}
                  </p>
                </div>
              );
            case "divider":
              return <hr key={bIdx} className="border-structural/40 my-3" />;
            default:
              return null;
          }
        });

        if (section.meta) {
          return (
            <SectionCard key={sIdx} meta={section.meta}>
              {content}
            </SectionCard>
          );
        }

        return <div key={sIdx}>{content}</div>;
      })}
    </div>
  );
}
