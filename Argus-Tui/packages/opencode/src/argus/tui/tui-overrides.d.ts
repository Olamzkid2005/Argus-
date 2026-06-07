/**
 * Type augmentations for @opentui/solid JSX elements.
 *
 * The TUI framework supports these props at runtime but the type definitions
 * in @opentui/solid are incomplete. This file adds the missing props used
 * throughout the Argus TUI codebase.
 */
import "solid-js"

declare module "solid-js" {
  namespace JSX {
    interface TextProps {
      /** Make text bold */
      bold?: boolean
      /** Click handler */
      onClick?: () => void
      /** Text wrapping mode */
      wrap?: string
      /** Foreground color — accepts RGBA objects from theme */
      fg?: string | RGBA
    }

    interface BoxProps {
      /** Click handler */
      onClick?: () => void
    }

    interface RGBA {
      r: number
      g: number
      b: number
      a?: number
    }

    interface BorderSide {
      type?: string
      fg?: string | RGBA
      char?: string
    }

    interface BorderSides {
      type?: string
      fg?: string | RGBA
      char?: string
    }
  }
}
