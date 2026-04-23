"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  CommandDialog,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandShortcut,
  CommandSeparator,
} from "@/components/ui/command";
import {
  LayoutDashboard,
  Bug,
  Target,
  Settings,
  Plus,
  Square,
  Download,
  Activity,
  ShieldCheck,
} from "lucide-react";
import { useToast } from "@/components/ui/Toast";

interface CommandPaletteProps {
  onNavigate: (path: string) => void;
  onClose: () => void;
  currentEngagementId?: string | null;
}

export function CommandPalette({
  onNavigate,
  onClose,
  currentEngagementId,
}: CommandPaletteProps) {
  const router = useRouter();
  const { showToast } = useToast();

  const runCommand = useCallback(
    (command: () => void) => {
      onClose();
      command();
    },
    [onClose],
  );

  return (
    <CommandDialog
      open={true}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Command Palette"
      description="Search for commands, navigation, and actions..."
    >
      <CommandInput placeholder="Type a command or search..." />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>

        <CommandGroup heading="Navigation">
          <CommandItem
            onSelect={() =>
              runCommand(() => onNavigate("/dashboard"))
            }
          >
            <LayoutDashboard className="mr-2 h-4 w-4" />
            <span>Dashboard</span>
            <CommandShortcut>G D</CommandShortcut>
          </CommandItem>
          <CommandItem
            onSelect={() =>
              runCommand(() => onNavigate("/findings"))
            }
          >
            <Bug className="mr-2 h-4 w-4" />
            <span>Findings</span>
            <CommandShortcut>G F</CommandShortcut>
          </CommandItem>
          <CommandItem
            onSelect={() =>
              runCommand(() => onNavigate("/engagements"))
            }
          >
            <Target className="mr-2 h-4 w-4" />
            <span>Engagements</span>
            <CommandShortcut>G E</CommandShortcut>
          </CommandItem>
          <CommandItem
            onSelect={() =>
              runCommand(() => onNavigate("/settings"))
            }
          >
            <Settings className="mr-2 h-4 w-4" />
            <span>Settings</span>
            <CommandShortcut>G S</CommandShortcut>
          </CommandItem>
        </CommandGroup>

        <CommandSeparator />

        <CommandGroup heading="Actions">
          <CommandItem
            onSelect={() =>
              runCommand(() => onNavigate("/engagements"))
            }
          >
            <Plus className="mr-2 h-4 w-4" />
            <span>New Scan</span>
            <CommandShortcut>⌘N</CommandShortcut>
          </CommandItem>
          {currentEngagementId && (
            <CommandItem
              onSelect={() =>
                runCommand(async () => {
                  try {
                    const response = await fetch(
                      `/api/engagement/${currentEngagementId}/stop`,
                      { method: "POST" },
                    );
                    if (response.ok) {
                      showToast("success", "Scan stopped");
                    }
                  } catch {
                    showToast("error", "Failed to stop scan");
                  }
                })
              }
            >
              <Square className="mr-2 h-4 w-4" />
              <span>Stop Current Scan</span>
            </CommandItem>
          )}
          <CommandItem
            onSelect={() =>
              runCommand(() => {
                showToast("info", "Export feature coming soon");
              })
            }
          >
            <Download className="mr-2 h-4 w-4" />
            <span>Export Report</span>
            <CommandShortcut>⌘E</CommandShortcut>
          </CommandItem>
        </CommandGroup>

        <CommandSeparator />

        <CommandGroup heading="Quick Access">
          <CommandItem
            onSelect={() =>
              runCommand(() => onNavigate("/dashboard?engagement=latest"))
            }
          >
            <Activity className="mr-2 h-4 w-4" />
            <span>Latest Scan Status</span>
          </CommandItem>
          <CommandItem
            onSelect={() =>
              runCommand(() => onNavigate("/findings?verified=false"))
            }
          >
            <ShieldCheck className="mr-2 h-4 w-4" />
            <span>Unverified Findings</span>
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}

// Hook to manage command palette state
function useCommandPalette() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((open) => !open);
      }
    };

    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, []);

  return { open, setOpen };
}

export { useCommandPalette };
