/**
 * Cadre des pages du flux « Se connecter avec Harpocrate » (features 2 à 4) : un
 * encadré centré, avec un titre et un contenu (message, demande, consentement).
 */
import type { ReactNode } from "react";
import { Center, Paper, Stack, Text, Title } from "@mantine/core";

interface ConnectStatusCardProps {
  title: string;
  message?: string;
  color?: string;
  children?: ReactNode;
}

export function ConnectStatusCard({
  title,
  message,
  color,
  children,
}: ConnectStatusCardProps) {
  return (
    <Center mih="100vh" p="md">
      <Paper withBorder radius="md" p="xl" w="100%" maw={560}>
        <Stack gap="md">
          <Title order={3} c={color}>
            {title}
          </Title>
          {message && <Text size="sm">{message}</Text>}
          {children}
        </Stack>
      </Paper>
    </Center>
  );
}
