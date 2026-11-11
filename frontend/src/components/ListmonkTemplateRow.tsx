/**
 * Une ligne « culture → ID de template Listmonk » de l'écran « Paramétrage Listmonk ».
 */
import { useState } from "react";
import { Badge, Button, Group, NumberInput, Table, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useTranslation } from "react-i18next";

import {
  useDeleteListmonkTemplate,
  useSetListmonkTemplate,
} from "@/hooks/useListmonk";
import { ApiError } from "@/lib/api-client";
import type { Culture } from "@/schemas/cultures";
import { MAX_TEMPLATE_ID } from "@/schemas/listmonk";

interface ListmonkTemplateRowProps {
  purpose: string;
  culture: Culture;
  /** ID enregistré en base, ou null si la culture n'a pas de template. */
  templateId: number | null;
}

export function ListmonkTemplateRow({
  purpose,
  culture,
  templateId,
}: ListmonkTemplateRowProps) {
  const { t } = useTranslation();
  const save = useSetListmonkTemplate();
  const remove = useDeleteListmonkTemplate();
  // Brouillon local, semé une seule fois : le parent remonte la ligne (clé qui
  // inclut l'ID enregistré) quand la valeur serveur change, plutôt que de
  // recopier la prop dans un effet qui écraserait une saisie en cours.
  const [draft, setDraft] = useState<number | string>(templateId ?? "");

  const parsed = typeof draft === "number" ? draft : null;
  const valid = parsed !== null && parsed > 0 && parsed <= MAX_TEMPLATE_ID;
  const pending = save.isPending || remove.isPending;

  const onError = (err: Error) => {
    const disabled = err instanceof ApiError && err.code === "culture_disabled";
    notifications.show({
      color: "red",
      title: t("common.error"),
      message: disabled
        ? t("admin.listmonk.errors.cultureDisabled")
        : err.message,
    });
  };

  return (
    <Table.Tr>
      <Table.Td>
        <Group gap="xs">
          <Text size="sm" fw={500}>
            {culture.english_name}
          </Text>
          <Text size="xs" c="dimmed">
            {culture.code}
          </Text>
          {culture.is_default && (
            <Badge color="blue" size="xs">
              {t("admin.cultures.default")}
            </Badge>
          )}
        </Group>
      </Table.Td>
      <Table.Td>
        <NumberInput
          value={draft}
          onChange={setDraft}
          min={1}
          max={MAX_TEMPLATE_ID}
          allowDecimal={false}
          allowNegative={false}
          placeholder={t("admin.listmonk.noTemplate")}
          aria-label={t("admin.listmonk.templateIdLabel", {
            name: culture.english_name,
          })}
          w={160}
        />
      </Table.Td>
      <Table.Td>
        <Group gap="xs" justify="flex-end">
          <Button
            size="xs"
            disabled={!valid || parsed === templateId || pending}
            onClick={() =>
              parsed !== null &&
              save.mutate(
                { purpose, cultureCode: culture.code, templateId: parsed },
                { onError },
              )
            }
          >
            {t("admin.listmonk.save")}
          </Button>
          {templateId !== null && (
            <Button
              size="xs"
              variant="light"
              color="red"
              disabled={pending}
              onClick={() =>
                remove.mutate(
                  { purpose, cultureCode: culture.code },
                  { onError },
                )
              }
            >
              {t("admin.listmonk.remove")}
            </Button>
          )}
        </Group>
      </Table.Td>
    </Table.Tr>
  );
}
