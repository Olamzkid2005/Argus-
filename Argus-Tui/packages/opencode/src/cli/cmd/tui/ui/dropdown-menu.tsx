/**
 * Terminal DropdownMenu component.
 *
 * Renders a trigger element and a selectable list of items in a bordered panel.
 * Uses @opentui/solid primitives (box, text) for terminal rendering.
 *
 * Supports: Trigger, Portal, Content, Group, GroupLabel, Item, ItemLabel,
 * RadioItem, RadioGroup.
 */
import { createSignal, createContext, useContext, type JSX, type ParentProps, For, Show } from "solid-js"
import { useTheme } from "@tui/context/theme"

// ── Context ───────────────────────────────────────────────────────────

interface DropdownContextValue {
  open: boolean
  setOpen: (v: boolean) => void
  onOpenChange?: (open: boolean) => void
  selectedValue?: string
  setSelectedValue?: (v: string) => void
}

const DropdownCtx = createContext<DropdownContextValue>()

function useDropdownCtx(): DropdownContextValue {
  const ctx = useContext(DropdownCtx)
  if (!ctx) throw new Error("DropdownMenu components must be used within <DropdownMenu>")
  return ctx
}

// ── Props ─────────────────────────────────────────────────────────────

export interface DropdownMenuProps {
  children: JSX.Element
  onOpenChange?: (open: boolean) => void
}

export interface DropdownMenuTriggerProps extends ParentProps {
  class?: string
}

export interface DropdownMenuPortalProps {
  children: JSX.Element
}

export interface DropdownMenuContentProps extends ParentProps {
  class?: string
}

export interface DropdownMenuGroupProps extends ParentProps {
  class?: string
}

export interface DropdownMenuGroupLabelProps extends ParentProps {
  class?: string
}

export interface DropdownMenuItemProps extends ParentProps {
  class?: string
  onSelect?: () => void
}

export interface DropdownMenuItemLabelProps extends ParentProps {
  class?: string
}

export interface DropdownMenuRadioItemProps extends ParentProps {
  value: string
  class?: string
  onSelect?: () => void
}

export interface DropdownMenuRadioGroupProps extends ParentProps {
  value?: string
  class?: string
}

// ── Root ──────────────────────────────────────────────────────────────

function DropdownMenuRoot(props: DropdownMenuProps) {
  const [open, setOpen] = createSignal(false)

  return (
    <DropdownCtx.Provider
      value={{
        get open() { return open() },
        setOpen: (v: boolean) => {
          setOpen(v)
          props.onOpenChange?.(v)
        },
      }}
    >
      {props.children}
    </DropdownCtx.Provider>
  )
}

// ── Trigger ───────────────────────────────────────────────────────────

function DropdownMenuTrigger(props: ParentProps<DropdownMenuTriggerProps>) {
  const ctx = useDropdownCtx()
  const { theme } = useTheme()

  return (
    <box
      {...({ onClick: () => ctx.setOpen(!ctx.open), cursorPointer: true } as any)}
    >
      {props.children}
    </box>
  )
}

// ── Portal ────────────────────────────────────────────────────────────

function DropdownMenuPortal(props: DropdownMenuPortalProps) {
  return <>{props.children}</>
}

// ── Content ───────────────────────────────────────────────────────────

function DropdownMenuContent(props: ParentProps<DropdownMenuContentProps>) {
  const ctx = useDropdownCtx()
  const { theme } = useTheme()

  return (
    <Show when={ctx.open}>
      <box
        borderStyle="rounded"
        border
        borderColor={theme.textMuted}
        paddingX={1}
        paddingY={1}
        marginTop={1}
        backgroundColor={theme.backgroundPanel}
        flexDirection="column"
        gap={1}
      >
        {props.children}
      </box>
    </Show>
  )
}

// ── Group ─────────────────────────────────────────────────────────────

function DropdownMenuGroup(props: ParentProps<DropdownMenuGroupProps>) {
  return (
    <box flexDirection="column" gap={1}>
      {props.children}
    </box>
  )
}

// ── GroupLabel ────────────────────────────────────────────────────────

function DropdownMenuGroupLabel(props: ParentProps<DropdownMenuGroupLabelProps>) {
  const { theme } = useTheme()
  return <text fg={theme.textMuted}>{props.children}</text>
}

// ── Item ──────────────────────────────────────────────────────────────

function DropdownMenuItem(props: ParentProps<DropdownMenuItemProps>) {
  const { theme } = useTheme()

  return (
    <box
      {...({ onClick: () => props.onSelect?.(), cursorPointer: true } as any)}
      paddingX={1}
    >
      <text fg={theme.text}>{props.children}</text>
    </box>
  )
}

// ── ItemLabel ─────────────────────────────────────────────────────────

function DropdownMenuItemLabel(props: ParentProps<DropdownMenuItemLabelProps>) {
  const { theme } = useTheme()
  return <text fg={theme.text}>{props.children}</text>
}

// ── RadioGroup ────────────────────────────────────────────────────────

function DropdownMenuRadioGroup(props: ParentProps<DropdownMenuRadioGroupProps>) {
  return (
    <box flexDirection="column" gap={1}>
      {props.children}
    </box>
  )
}

// ── RadioItem ─────────────────────────────────────────────────────────

function DropdownMenuRadioItem(props: ParentProps<DropdownMenuRadioItemProps>) {
  const ctx = useDropdownCtx()
  const { theme } = useTheme()

  return (
    <box
      {...({ onClick: () => { ctx.setOpen(false); props.onSelect?.() }, cursorPointer: true } as any)}
      paddingX={1}
    >
      <text fg={theme.primary}>○ {props.children}</text>
    </box>
  )
}

// ── ItemIndicator ─────────────────────────────────────────────────────

function DropdownMenuItemIndicator(props: ParentProps) {
  return <text>{props.children}</text>
}

// ── Exports ───────────────────────────────────────────────────────────

export const DropdownMenu = Object.assign(DropdownMenuRoot, {
  Trigger: DropdownMenuTrigger,
  Portal: DropdownMenuPortal,
  Content: DropdownMenuContent,
  Group: DropdownMenuGroup,
  GroupLabel: DropdownMenuGroupLabel,
  Item: DropdownMenuItem,
  ItemLabel: DropdownMenuItemLabel,
  RadioGroup: DropdownMenuRadioGroup,
  RadioItem: DropdownMenuRadioItem,
  ItemIndicator: DropdownMenuItemIndicator,
})
