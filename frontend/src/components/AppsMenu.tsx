/**
 * AppsMenu — hamburger menu listing cross-suite applications.
 *
 * Rendered in the TopBar header. Hidden when loading or when the apps list
 * is empty (so it does not flash on initial load or when apps.json is absent).
 *
 * On click, each entry opens in a new tab with noopener,noreferrer.
 */
import { Menu, ActionIcon, Avatar, Text, Group } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { useApps } from "@/hooks/useApps";
import type { AppEntry } from "@/schemas/apps";

/** Inline SVG grid icon — avoids adding a new icon-package dependency. */
function IconLayoutGrid({ size = 20 }: { size?: number }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="3" width="7" height="7" />
      <rect x="14" y="3" width="7" height="7" />
      <rect x="3" y="14" width="7" height="7" />
      <rect x="14" y="14" width="7" height="7" />
    </svg>
  );
}

function AppMenuItem({ entry }: { entry: AppEntry }) {
  function handleClick() {
    window.open(entry.url, "_blank", "noopener,noreferrer");
  }

  return (
    <Menu.Item onClick={handleClick}>
      <Group gap="xs">
        <Avatar src={entry.icon} size={20} radius="sm" alt={entry.label}>
          {entry.label.charAt(0).toUpperCase()}
        </Avatar>
        <Text size="sm">{entry.label}</Text>
      </Group>
    </Menu.Item>
  );
}

export function AppsMenu() {
  const { t } = useTranslation();
  const { data, isLoading } = useApps();

  const hasApps = !isLoading && (data?.urls.length ?? 0) > 0;

  if (!hasApps) {
    return null;
  }

  return (
    <Menu shadow="md" width={200} position="bottom-end">
      <Menu.Target>
        <ActionIcon
          variant="subtle"
          title={t("topbar.apps_menu")}
          aria-label={t("topbar.apps_menu")}
        >
          <IconLayoutGrid size={20} />
        </ActionIcon>
      </Menu.Target>

      <Menu.Dropdown>
        <Menu.Label>{t("topbar.apps_menu")}</Menu.Label>
        {data?.urls.map((entry) => (
          <AppMenuItem key={entry.key} entry={entry} />
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}
