/**
 * Modale de déclaration / modification d'une application du registre (feature 1).
 *
 * Les URLs de retour se saisissent une par ligne et sont vérifiées avant l'envoi avec les
 * mêmes règles que le backend ; le `client_id` n'est modifiable qu'à la création (les
 * applications l'ont déjà configuré).
 */
import { useState } from "react";
import {
  Alert,
  Button,
  Group,
  Modal,
  Stack,
  TextInput,
  Textarea,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/lib/api-client";
import {
  useCreateConnectClient,
  useUpdateConnectClient,
} from "@/hooks/useConnectClients";
import {
  CLIENT_ID_PATTERN,
  MAX_REDIRECT_URIS,
  parseRedirectUris,
  redirectUriProblem,
  type ConnectClient,
} from "@/schemas/connectClients";

interface ConnectClientFormModalProps {
  opened: boolean;
  onClose: () => void;
  /** Application à modifier ; `null` pour une déclaration. */
  client: ConnectClient | null;
}

interface FormValues {
  client_id: string;
  name: string;
  description: string;
  redirect_uris: string;
}

export function ConnectClientFormModal({
  opened,
  onClose,
  client,
}: ConnectClientFormModalProps) {
  const { t } = useTranslation();
  const createMutation = useCreateConnectClient();
  const updateMutation = useUpdateConnectClient();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const isEdit = client !== null;

  const form = useForm<FormValues>({
    initialValues: {
      client_id: client?.client_id ?? "",
      name: client?.name ?? "",
      description: client?.description ?? "",
      redirect_uris: client?.redirect_uris.join("\n") ?? "",
    },
    validate: {
      client_id: (v) =>
        isEdit || CLIENT_ID_PATTERN.test(v)
          ? null
          : t("admin.connectClients.errors.clientIdFormat"),
      name: (v) =>
        v.trim() ? null : t("admin.connectClients.errors.nameRequired"),
      redirect_uris: (v) => {
        const uris = parseRedirectUris(v);
        if (uris.length === 0)
          return t("admin.connectClients.errors.redirectUrisRequired");
        if (uris.length > MAX_REDIRECT_URIS)
          return t("admin.connectClients.errors.tooManyRedirectUris");
        for (const uri of uris) {
          const problem = redirectUriProblem(uri);
          if (problem)
            return `${t(`admin.connectClients.errors.${problem}`)} : ${uri}`;
        }
        return null;
      },
    },
  });

  async function handleSubmit(values: FormValues) {
    setSubmitError(null);
    const common = {
      name: values.name.trim(),
      description: values.description.trim() || null,
      redirect_uris: parseRedirectUris(values.redirect_uris),
    };
    try {
      if (isEdit) {
        await updateMutation.mutateAsync({ id: client.id, body: common });
      } else {
        await createMutation.mutateAsync({
          client_id: values.client_id,
          ...common,
        });
      }
      onClose();
    } catch (err) {
      if (err instanceof ApiError && err.code === "client_id_taken") {
        form.setFieldError(
          "client_id",
          t("admin.connectClients.errors.clientIdTaken"),
        );
        return;
      }
      setSubmitError(err instanceof Error ? err.message : t("common.error"));
    }
  }

  const pending = createMutation.isPending || updateMutation.isPending;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={
        isEdit
          ? t("admin.connectClients.modalEditTitle")
          : t("admin.connectClients.modalCreateTitle")
      }
      size="lg"
    >
      <form onSubmit={form.onSubmit((v) => void handleSubmit(v))}>
        <Stack>
          <TextInput
            label={t("admin.connectClients.clientId")}
            description={t("admin.connectClients.clientIdHelp")}
            disabled={isEdit}
            required
            {...form.getInputProps("client_id")}
          />
          <TextInput
            label={t("admin.connectClients.name")}
            required
            {...form.getInputProps("name")}
          />
          <Textarea
            label={t("admin.connectClients.description")}
            autosize
            minRows={2}
            {...form.getInputProps("description")}
          />
          <Textarea
            label={t("admin.connectClients.redirectUris")}
            description={t("admin.connectClients.redirectUrisHelp")}
            autosize
            minRows={3}
            required
            {...form.getInputProps("redirect_uris")}
          />
          {submitError && <Alert color="red">{submitError}</Alert>}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t("admin.connectClients.cancel")}
            </Button>
            <Button type="submit" loading={pending}>
              {t("admin.connectClients.save")}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
