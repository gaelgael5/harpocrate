import { createTheme, rem, type MantineColorsTuple } from "@mantine/core";

const brandBlue: MantineColorsTuple = [
  "#eef2ff",
  "#d5dfff",
  "#adc0ff",
  "#809eff",
  "#5577ef",
  "#3358d4",
  "#1e40af",
  "#163088",
  "#0f2268",
  "#08164a",
];

export const theme = createTheme({
  primaryColor: "brand",
  primaryShade: { light: 6, dark: 5 },

  colors: { brand: brandBlue },

  fontFamily: "'Figtree', system-ui, -apple-system, sans-serif",
  fontFamilyMonospace: "'JetBrains Mono', 'Courier New', monospace",

  headings: {
    fontFamily: "'Figtree', system-ui, -apple-system, sans-serif",
    sizes: {
      h1: { fontSize: rem(30), fontWeight: "700", lineHeight: "1.2" },
      h2: { fontSize: rem(24), fontWeight: "600", lineHeight: "1.25" },
      h3: { fontSize: rem(18), fontWeight: "600", lineHeight: "1.3" },
      h4: { fontSize: rem(15), fontWeight: "600", lineHeight: "1.4" },
    },
  },

  defaultRadius: "sm",
  radius: {
    xs: rem(2),
    sm: rem(4),
    md: rem(6),
    lg: rem(8),
    xl: rem(12),
  },

  shadows: {
    xs: "0 1px 3px rgba(10,10,10,0.06)",
    sm: "0 2px 8px rgba(10,10,10,0.08)",
    md: "0 4px 16px rgba(10,10,10,0.09)",
    lg: "0 8px 28px rgba(10,10,10,0.11)",
    xl: "0 20px 48px rgba(10,10,10,0.13)",
  },

  other: {
    fontDisplay: "'Cormorant Garamond', Georgia, serif",
  },

  components: {
    Button: {
      defaultProps: { radius: "sm" },
      styles: { root: { fontWeight: 500, letterSpacing: "0.01em" } },
    },
    Card: {
      defaultProps: { radius: "sm", withBorder: true },
    },
    TextInput: { defaultProps: { radius: "sm" } },
    PasswordInput: { defaultProps: { radius: "sm" } },
    Select: { defaultProps: { radius: "sm" } },
    Textarea: { defaultProps: { radius: "sm" } },
    NumberInput: { defaultProps: { radius: "sm" } },
    Badge: { defaultProps: { radius: "sm" } },
    Alert: { defaultProps: { radius: "sm" } },
    Paper: { defaultProps: { radius: "sm" } },
    Modal: { defaultProps: { radius: "md" } },
    Notification: { defaultProps: { radius: "sm" } },
    NavLink: {
      styles: {
        root: {
          borderRadius: rem(4),
          fontSize: rem(13.5),
          fontWeight: 500,
        },
      },
    },
  },
});
