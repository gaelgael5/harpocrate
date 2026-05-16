import { Box, Text, Group } from "@mantine/core";
import { Link } from "react-router-dom";
import { useSessionStore } from "@/stores/session";

export function ApiDocsPage() {
  const user = useSessionStore((s) => s.user);

  return (
    <Box style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      {/* Minimal nav */}
      <Box
        component="nav"
        style={{
          height: 48,
          flexShrink: 0,
          background: "rgba(248,247,244,0.97)",
          backdropFilter: "blur(8px)",
          borderBottom: "1px solid rgba(30,64,175,0.1)",
          padding: "0 5vw",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <Group gap="sm">
          <Link
            to="/integration"
            style={{
              textDecoration: "none",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <Box
              style={{
                width: 24,
                height: 24,
                background: "#1e40af",
                borderRadius: 4,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: "0.55rem",
                color: "#fff",
                letterSpacing: "-0.04em",
                flexShrink: 0,
              }}
            >
              Hp
            </Box>
            <Text
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: "0.65rem",
                color: "rgba(10,10,10,0.5)",
                letterSpacing: "0.04em",
              }}
            >
              ← Integration
            </Text>
          </Link>

          <Text
            style={{
              fontFamily: "'Cormorant Garamond', Georgia, serif",
              fontSize: "1rem",
              color: "#0a0a0a",
            }}
          >
            API Reference
          </Text>
        </Group>

        <Link
          to={user ? "/wallets" : "/login"}
          style={{
            textDecoration: "none",
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: "0.65rem",
            color: "#1e40af",
            letterSpacing: "0.04em",
          }}
        >
          {user ? "← Dashboard" : "Open vault →"}
        </Link>
      </Box>

      {/* Swagger UI iframe */}
      <iframe
        src="/v1/docs"
        title="API Reference"
        style={{ flex: 1, border: "none", width: "100%" }}
      />
    </Box>
  );
}
