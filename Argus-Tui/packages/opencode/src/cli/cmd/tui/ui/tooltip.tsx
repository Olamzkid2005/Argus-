/**
 * Terminal Tooltip component.
 *
 * Shows a hover tooltip with border when the trigger element is hovered or focused.
 * Uses @opentui/solid primitives (box, text) for terminal rendering.
 */
import { type JSX, createSignal, Show } from "solid-js"
import { useTheme } from "@tui/context/theme"

export interface TooltipProps {
  value: JSX.Element
  class?: string
  contentClass?: string
  contentStyle?: JSX.CSSProperties
  inactive?: boolean
  forceOpen?: boolean
  placement?: "top" | "bottom" | "left" | "right"
  gutter?: number
  children: JSX.Element
}

export interface TooltipKeybindProps extends Omit<TooltipProps, "value"> {
  title: string
  keybind: string
}

export function TooltipKeybind(props: TooltipKeybindProps) {
  return (
    <Tooltip {...props} value={<text>{props.title} [{props.keybind}]</text>} />
  )
}

export function Tooltip(props: TooltipProps) {
  const { theme } = useTheme()
  const [open, setOpen] = createSignal(false)

  return (
    <box flexDirection="column">
      <box
        {...({ onPointerEnter: () => setOpen(true), onPointerLeave: () => setOpen(false), onFocus: () => setOpen(true), onBlur: () => setOpen(false) } as any)}
      >
        {props.children}
      </box>
      <Show when={(open() || props.forceOpen) && !props.inactive}>
        <box
          borderStyle="rounded"
          border
          borderColor={theme.textMuted}
          paddingX={1}
          paddingY={1}
          marginTop={1}
          backgroundColor={theme.background}
        >
          {props.value}
        </box>
      </Show>
    </box>
  )
}
