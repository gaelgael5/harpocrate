/**
 * Cultures activables (épic « Cultures et templates Listmonk paramétrés en base », feature 1).
 *
 * Une culture activée peut recevoir des contenus paramétrés (templates de mails) ; la
 * culture par défaut sert de repli. Activer une culture ne traduit PAS l'interface :
 * l'UI reste en français et en anglais (décision de cadrage du 2026-11-11).
 */
import { useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Center,
  Code,
  Group,
  Loader,
  SegmentedControl,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useTranslation } from "react-i18next";

import { useCultures, useUpdateCulture } from "@/hooks/useCultures";
import { ApiError } from "@/lib/api-client";
import type { Culture, CultureUpdateBody } from "@/schemas/cultures";

type Filter = "all" | "enabled";

// Refus métier du backend dont le message est traduit ; les autres erreurs
// affichent le message brut de l'API.
const KNOWN_ERRORS = new Set([
  "default_culture_cannot_be_disabled",
  "culture_disabled",
]);

function matches(culture: Culture, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return [culture.code, culture.english_name, culture.native_name ?? ""].some(
    (v) => v.toLowerCase().includes(q),
  );
}

interface CultureRowProps {
  culture: Culture;
  onUpdate: (code: string, body: CultureUpdateBody) => void;
  pending: boolean;
}

function CultureRow({ culture, onUpdate, pending }: CultureRowProps) {
  const { t } = useTranslation();
  return (
    <Table.Tr>
      <Table.Td>
        <Code>{culture.code}</Code>
      </Table.Td>
      <Table.Td>
        <Text size="sm" fw={500}>
          {culture.english_name}
        </Text>
        {culture.native_name &&
          culture.native_name !== culture.english_name && (
            <Text size="xs" c="dimmed">
              {culture.native_name}
            </Text>
          )}
      </Table.Td>
      <Table.Td>
        <Switch
          checked={culture.enabled}
          // La culture par défaut ne se désactive pas : le backend le refuse,
          // l'interrupteur grisé l'annonce avant le clic.
          disabled={culture.is_default || pending}
          aria-label={t("admin.cultures.toggleLabel", {
            name: culture.english_name,
          })}
          onChange={(e) =>
            onUpdate(culture.code, { enabled: e.currentTarget.checked })
          }
        />
      </Table.Td>
      <Table.Td>
        {culture.is_default ? (
          <Badge color="blue" size="sm">
            {t("admin.cultures.default")}
          </Badge>
        ) : (
          culture.enabled && (
            <Button
              size="xs"
              variant="default"
              disabled={pending}
              onClick={() => onUpdate(culture.code, { is_default: true })}
            >
              {t("admin.cultures.makeDefault")}
            </Button>
          )
        )}
      </Table.Td>
    </Table.Tr>
  );
}

export function AdminCulturesPage() {
  const { t } = useTranslation();
  const { data, isLoading, error } = useCultures();
  const update = useUpdateCulture();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("enabled");

  const visible = useMemo(
    () =>
      (data?.items ?? []).filter(
        (c) => (filter === "all" || c.enabled) && matches(c, query.trim()),
      ),
    [data, filter, query],
  );

  const onUpdate = (code: string, body: CultureUpdateBody) => {
    update.mutate(
      { code, body },
      {
        onError: (err) => {
          const known = err instanceof ApiError && KNOWN_ERRORS.has(err.code);
          notifications.show({
            color: "red",
            title: t("common.error"),
            message: known
              ? t(`admin.cultures.errors.${(err as ApiError).code}`)
              : err.message,
          });
        },
      },
    );
  };

  if (isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }
  if (error) {
    return (
      <Alert color="red">
        {error instanceof Error ? error.message : t("common.error")}
      </Alert>
    );
  }

  return (
    <Stack>
      <Title order={2}>{t("admin.cultures.title")}</Title>
      <Text size="sm" c="dimmed">
        {t("admin.cultures.intro")}
      </Text>
      <Group>
        <TextInput
          placeholder={t("admin.cultures.search")}
          value={query}
          onChange={(e) => setQuery(e.currentTarget.value)}
          style={{ flex: 1 }}
        />
        <SegmentedControl
          value={filter}
          onChange={(v) => setFilter(v as Filter)}
          data={[
            { value: "enabled", label: t("admin.cultures.filterEnabled") },
            { value: "all", label: t("admin.cultures.filterAll") },
          ]}
        />
      </Group>

      {visible.length === 0 ? (
        <Text c="dimmed">{t("admin.cultures.empty")}</Text>
      ) : (
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("admin.cultures.colCode")}</Table.Th>
              <Table.Th>{t("admin.cultures.colName")}</Table.Th>
              <Table.Th>{t("admin.cultures.colEnabled")}</Table.Th>
              <Table.Th>{t("admin.cultures.colDefault")}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {visible.map((c) => (
              <CultureRow
                key={c.code}
                culture={c}
                onUpdate={onUpdate}
                pending={update.isPending}
              />
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}
