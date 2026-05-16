import { Menu, Button } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { setLocale, type SupportedLocale } from "@/lib/i18n";
import { useSessionStore } from "@/stores/session";

const LOCALES: { code: SupportedLocale; label: string; flag: string }[] = [
  { code: "en", label: "English", flag: "🇬🇧" },
  { code: "fr", label: "Français", flag: "🇫🇷" },
];

export function LocaleSwitcher() {
  const { i18n } = useTranslation();
  const user = useSessionStore((s) => s.user);
  const current =
    LOCALES.find((l) => i18n.language?.startsWith(l.code)) ?? LOCALES[0]!;

  const patchMut = useMutation({
    mutationFn: (locale: SupportedLocale) =>
      api.patch<void>("/me/preferences", { preferred_locale: locale }),
  });

  function switchTo(locale: SupportedLocale) {
    setLocale(locale);
    if (user) {
      patchMut.mutate(locale);
    }
  }

  return (
    <Menu shadow="md" width={140}>
      <Menu.Target>
        <Button variant="subtle" size="xs" px="xs">
          {current.flag} {current.label}
        </Button>
      </Menu.Target>
      <Menu.Dropdown>
        {LOCALES.map((l) => (
          <Menu.Item
            key={l.code}
            onClick={() => switchTo(l.code)}
            style={{
              fontWeight: i18n.language?.startsWith(l.code) ? 700 : 400,
            }}
          >
            {l.flag} {l.label}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}
