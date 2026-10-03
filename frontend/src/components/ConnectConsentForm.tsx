/**
 * Écran de consentement « Se connecter avec Harpocrate » (feature 3).
 *
 * L'utilisateur choisit un wallet sur lequel il a [share], ou en crée un ; les permissions
 * et la durée sont pré-remplies avec la demande et ne peuvent qu'être réduites (D3).
 * Refuser renvoie `access_denied` à l'application sans créer de clé (invariant 6).
 */
import { useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Group,
  NumberInput,
  Select,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { useTranslation } from "react-i18next";

import { ConnectExistingKeys } from "@/components/ConnectExistingKeys";
import { useShareableWallets } from "@/hooks/useConnectFlow";
import {
  NEW_WALLET,
  WALLET_NAME_MAX,
  grantablePermissions,
  isTtlAllowed,
  maxTtlDays,
} from "@/lib/connectConsent";
import type {
  ConnectDecision,
  ConnectRequestView,
} from "@/schemas/connectFlow";
import { PERMISSION_KEYS } from "@/schemas/grants";

interface ConnectConsentFormProps {
  request: ConnectRequestView;
  onApprove: (decision: ConnectDecision) => void;
  onDeny: () => void;
  approving: boolean;
  denying: boolean;
  error: string | null;
}

export function ConnectConsentForm({
  request,
  onApprove,
  onDeny,
  approving,
  denying,
  error,
}: ConnectConsentFormProps) {
  const { t } = useTranslation();
  const wallets = useShareableWallets(true);
  const [walletChoice, setWalletChoice] = useState<string>(NEW_WALLET);
  const [newName, setNewName] = useState(request.client.name);
  const [permissions, setPermissions] = useState(
    grantablePermissions(request.requested_permissions, null),
  );
  const [ttlDays, setTtlDays] = useState<number | null>(
    request.requested_ttl_days,
  );

  const chosen = (wallets.data ?? []).find((w) => w.id === walletChoice);
  const grantable = grantablePermissions(
    request.requested_permissions,
    chosen ? chosen.my_permissions : null,
  );

  function chooseWallet(value: string | null) {
    const next = value ?? NEW_WALLET;
    setWalletChoice(next);
    const wallet = (wallets.data ?? []).find((w) => w.id === next);
    // Changer de wallet remet les permissions au maximum accordable sur celui-ci.
    setPermissions(
      grantablePermissions(
        request.requested_permissions,
        wallet ? wallet.my_permissions : null,
      ),
    );
  }

  const name = newName.trim();
  const nameOk =
    walletChoice !== NEW_WALLET ||
    (name.length > 0 && name.length <= WALLET_NAME_MAX);
  const effective = permissions & grantable;
  const canApprove =
    nameOk &&
    effective !== 0 &&
    isTtlAllowed(ttlDays, request.requested_ttl_days) &&
    !wallets.isLoading;

  function approve() {
    onApprove({
      wallet:
        walletChoice === NEW_WALLET
          ? { kind: "new", name }
          : { kind: "existing", walletId: walletChoice },
      permissions: effective,
      ttlDays,
    });
  }

  const walletOptions = [
    { value: NEW_WALLET, label: t("connect.newWallet") },
    ...(wallets.data ?? []).map((w) => ({ value: w.id, label: w.name })),
  ];

  return (
    <Stack gap="md">
      <Select
        label={t("connect.walletLabel")}
        data={walletOptions}
        value={walletChoice}
        onChange={chooseWallet}
        allowDeselect={false}
        disabled={approving}
      />
      {walletChoice === NEW_WALLET && (
        <TextInput
          label={t("connect.newWalletName")}
          value={newName}
          maxLength={WALLET_NAME_MAX}
          onChange={(e) => setNewName(e.currentTarget.value)}
          error={nameOk ? null : t("connect.newWalletNameRequired")}
          disabled={approving}
        />
      )}
      {chosen && (
        <ConnectExistingKeys
          walletId={chosen.id}
          clientId={request.client.client_id}
        />
      )}
      <Stack gap={4}>
        <Text size="sm" fw={500}>
          {t("connect.grantedPermissions")}
        </Text>
        {PERMISSION_KEYS.filter(
          ({ bit }) => (request.requested_permissions & bit) !== 0,
        ).map(({ bit, key }) => (
          <Checkbox
            key={key}
            label={t(`permissions.${key}`)}
            checked={(effective & bit) !== 0}
            disabled={(grantable & bit) === 0 || approving}
            onChange={() => setPermissions(permissions ^ bit)}
          />
        ))}
      </Stack>
      <NumberInput
        label={t("connect.ttlLabel")}
        description={
          request.requested_ttl_days === null
            ? t("connect.ttlHelpNone")
            : t("connect.ttlHelpMax", { count: request.requested_ttl_days })
        }
        value={ttlDays ?? ""}
        min={1}
        max={maxTtlDays(request.requested_ttl_days)}
        allowDecimal={false}
        onChange={(v) => setTtlDays(typeof v === "number" ? v : null)}
        error={
          isTtlAllowed(ttlDays, request.requested_ttl_days)
            ? null
            : t("connect.ttlInvalid")
        }
        disabled={approving}
      />
      {error && <Alert color="red">{error}</Alert>}
      <Group justify="flex-end">
        <Button
          variant="default"
          onClick={onDeny}
          loading={denying}
          disabled={approving}
        >
          {t("connect.deny")}
        </Button>
        <Button
          onClick={approve}
          loading={approving}
          disabled={!canApprove || denying}
        >
          {t("connect.approve")}
        </Button>
      </Group>
    </Stack>
  );
}
