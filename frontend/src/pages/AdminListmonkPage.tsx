/**
 * Paramétrage Listmonk (épic « Cultures et templates Listmonk paramétrés en base »,
 * feature 2).
 *
 * Tout se règle ici, sans éditer le .env de l'hôte : la connexion (feature 3) et l'ID
 * du template de chaque type de mail, pour chaque culture activée. À l'envoi, le
 * serveur prend celui de la culture du destinataire, sinon celui de la culture par
 * défaut.
 */
import {
  Alert,
  Center,
  Loader,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useTranslation } from "react-i18next";

import { ListmonkConnectionCard } from "@/components/ListmonkConnectionCard";
import { ListmonkTemplateRow } from "@/components/ListmonkTemplateRow";
import { useCultures } from "@/hooks/useCultures";
import { useListmonkSettings } from "@/hooks/useListmonk";
import type { Culture } from "@/schemas/cultures";
import type { ListmonkTemplate } from "@/schemas/listmonk";

interface PurposeSectionProps {
  purpose: string;
  cultures: Culture[];
  templates: ListmonkTemplate[];
}

function PurposeSection({ purpose, cultures, templates }: PurposeSectionProps) {
  const { t } = useTranslation();
  const byCulture = new Map(
    templates
      .filter((tpl) => tpl.purpose === purpose)
      .map((tpl) => [tpl.culture_code, tpl.template_id]),
  );
  const defaultCulture = cultures.find((c) => c.is_default);
  const missingDefault =
    defaultCulture !== undefined && !byCulture.has(defaultCulture.code);

  return (
    <Stack gap="xs">
      <Title order={4}>{t(`admin.listmonk.purposes.${purpose}`)}</Title>
      {missingDefault && (
        <Alert color="orange">
          {t("admin.listmonk.missingDefault", {
            name: defaultCulture.english_name,
          })}
        </Alert>
      )}
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t("admin.listmonk.colCulture")}</Table.Th>
            <Table.Th>{t("admin.listmonk.colTemplateId")}</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {cultures.map((c) => {
            const templateId = byCulture.get(c.code) ?? null;
            return (
              <ListmonkTemplateRow
                // La clé suit la valeur serveur : un enregistrement ou une
                // suppression remonte la ligne avec un brouillon neuf.
                key={`${c.code}:${templateId ?? "none"}`}
                purpose={purpose}
                culture={c}
                templateId={templateId}
              />
            );
          })}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

export function AdminListmonkPage() {
  const { t } = useTranslation();
  const settings = useListmonkSettings();
  const cultures = useCultures();

  if (settings.isLoading || cultures.isLoading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }
  const error = settings.error ?? cultures.error;
  if (error || !settings.data || !cultures.data) {
    return (
      <Alert color="red">
        {error instanceof Error ? error.message : t("common.error")}
      </Alert>
    );
  }

  const enabled = cultures.data.items.filter((c) => c.enabled);
  const { connection, purposes, templates } = settings.data;

  return (
    <Stack>
      <Title order={2}>{t("admin.listmonk.title")}</Title>
      <Text size="sm" c="dimmed">
        {t("admin.listmonk.intro")}
      </Text>

      <ListmonkConnectionCard
        // Remontée après chaque enregistrement : brouillon et champ token repartent
        // de la valeur serveur.
        key={connection?.updated_at ?? "none"}
        connection={connection}
      />

      {purposes.map((purpose) => (
        <PurposeSection
          key={purpose}
          purpose={purpose}
          cultures={enabled}
          templates={templates}
        />
      ))}
    </Stack>
  );
}
