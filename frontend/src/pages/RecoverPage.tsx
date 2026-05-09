/**
 * RecoverPage — saisie des 24 mots BIP-39 + nouvelle passphrase (LOT_57).
 *
 * Flow zero-knowledge :
 * 1. GET /v1/auth/recovery/{id} → blobs crypto user (chiffrés avec sym_key)
 * 2. User saisit 24 mots → décodage BIP-39 → seed 32 bytes
 * 3. Argon2id(seed, salt_recovery) → recovery_key
 * 4. AES-GCM décrypte sym_key avec recovery_key
 *    - si KO → POST attempt-failed, on remontre la grille
 *    - si OK → on a sym_key
 * 5. AES-GCM décrypte rsa_private_key avec sym_key (pour vérifier que la chaîne crypto est cohérente)
 * 6. User saisit nouvelle passphrase
 * 7. Argon2id(passphrase, new_salt) → pass_key
 * 8. AES-GCM rechiffre rsa_private_key + sym_key avec pass_key
 * 9. POST complete avec les nouveaux blobs
 */
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Center,
  Stack,
  Title,
  Text,
  TextInput,
  PasswordInput,
  Button,
  Alert,
  Box,
  SimpleGrid,
  Loader,
  Anchor,
  Modal,
  Textarea,
  Group,
} from '@mantine/core'
import { useTranslation } from 'react-i18next'

import { decodeBip39 } from '@/crypto/bip39'
import { deriveKey, deriveKeyFromSeed, type KdfParams, DEFAULT_KDF_PARAMS } from '@/crypto/argon2'
import { aesGcmDecrypt, aesGcmEncrypt } from '@/crypto/aes-gcm'
import { fromBase64, toBase64, randomBytes } from '@/crypto/helpers'

interface RecoveryBlobs {
  session_id: string
  attempts_left: number
  salt_recovery: string
  encrypted_sym_key_by_recovery: string
  // LOT_57 fix : rsa_priv chiffrée avec recovery_key (séparée de la copie
  // chiffrée par pass_key). Permet la récupération zero-knowledge.
  encrypted_rsa_private_key_by_recovery: string
  rsa_public_key: string
  kdf_params: KdfParams
}

type Step = 'loading' | 'words' | 'newPass' | 'submitting' | 'done' | 'error'

/**
 * Extrait jusqu'à 24 mots alphabétiques d'un texte collé. Tolère les formats
 * `01. fatal` / `1) fatal` / `fatal\noutdoor` / `fatal, outdoor`. Renvoie
 * `null` si moins de 24 mots trouvés. La validité BIP-39 n'est PAS vérifiée
 * ici (elle l'est à la vérification finale via decodeBip39).
 */
function parseRecoveryWords(text: string): string[] | null {
  const matches = text.toLowerCase().match(/[a-z]+/g) ?? []
  if (matches.length < 24) return null
  return matches.slice(0, 24)
}

export function RecoverPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { sessionId } = useParams<{ sessionId: string }>()

  const [step, setStep] = useState<Step>('loading')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [blobs, setBlobs] = useState<RecoveryBlobs | null>(null)
  const [words, setWords] = useState<string[]>(Array(24).fill(''))
  const [decryptedSymKey, setDecryptedSymKey] = useState<Uint8Array | null>(null)
  const [decryptedRsaPriv, setDecryptedRsaPriv] = useState<Uint8Array | null>(null)
  const [newPass, setNewPass] = useState('')
  const [newPassConfirm, setNewPassConfirm] = useState('')

  // Modal "Coller mes 24 mots"
  const [pasteOpen, setPasteOpen] = useState(false)
  const [pasteText, setPasteText] = useState('')
  const [pasteError, setPasteError] = useState<string | null>(null)

  // Modal "Refaire un compte" — destruction définitive du compte
  const [destroyOpen, setDestroyOpen] = useState(false)
  const [destroyTyped, setDestroyTyped] = useState('')
  const [destroying, setDestroying] = useState(false)
  const [destroyError, setDestroyError] = useState<string | null>(null)

  // Le user doit taper EXACTEMENT cette chaîne pour que le bouton se débloque.
  // Cohérent avec le contrat backend (body.confirm == DELETE_ACCOUNT_AND_LOSE_ALL_DATA).
  const DESTROY_CONFIRM_LITERAL = 'DELETE_ACCOUNT_AND_LOSE_ALL_DATA'

  function handleApplyPaste() {
    const parsed = parseRecoveryWords(pasteText)
    if (parsed === null) {
      setPasteError(t('recover.pasteParseError'))
      return
    }
    setWords(parsed)
    setPasteOpen(false)
    setPasteText('')
    setPasteError(null)
  }

  // Modal de confirmation de destruction — réutilisable depuis l'étape
  // `words` (l'utilisateur réalise qu'il a perdu ses mots) ou `error`
  // (session déjà cramée). Reset à la fermeture pour ne pas conserver le
  // texte tapé entre deux ouvertures.
  function renderDestroyModal() {
    return (
      <Modal
        opened={destroyOpen}
        onClose={() => {
          setDestroyOpen(false)
          setDestroyTyped('')
          setDestroyError(null)
        }}
        title={t('recover.destroyModalTitle')}
        size="md"
      >
        <Stack gap="sm">
          <Alert color="red" variant="light" title={t('recover.destroyWarningTitle')}>
            {t('recover.destroyWarningBody')}
          </Alert>
          <Text size="sm">
            {t('recover.destroyTypeInstruction')}{' '}
            <Text span fw={700} ff="monospace">
              {DESTROY_CONFIRM_LITERAL}
            </Text>
          </Text>
          <TextInput
            value={destroyTyped}
            onChange={(e) => setDestroyTyped(e.currentTarget.value)}
            placeholder={DESTROY_CONFIRM_LITERAL}
            data-testid="recover-destroy-confirm"
            disabled={destroying}
            autoComplete="off"
            spellCheck={false}
          />
          {destroyError && (
            <Alert color="red" variant="light">
              {destroyError}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => {
                setDestroyOpen(false)
                setDestroyTyped('')
                setDestroyError(null)
              }}
              disabled={destroying}
            >
              {t('common.cancel')}
            </Button>
            <Button
              color="red"
              onClick={() => void handleAbandonAccount()}
              loading={destroying}
              disabled={destroyTyped !== DESTROY_CONFIRM_LITERAL}
            >
              {t('recover.destroyConfirm')}
            </Button>
          </Group>
        </Stack>
      </Modal>
    )
  }

  async function handleAbandonAccount() {
    if (destroyTyped !== DESTROY_CONFIRM_LITERAL) {
      setDestroyError(t('recover.destroyTypeMismatch'))
      return
    }
    setDestroyError(null)
    setDestroying(true)
    try {
      const r = await fetch(`/v1/auth/recovery/${sessionId}/abandon-account`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ confirm: DESTROY_CONFIRM_LITERAL }),
      })
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        const code = body?.detail?.error ?? 'server_error'
        setDestroyError(t(`recover.errors.${code}`, t('errors.serverError')))
        setDestroying(false)
        return
      }
      setDestroyOpen(false)
      setStep('done')
      setErrorMsg(t('recover.destroyDoneNotice'))
    } catch {
      setDestroyError(t('errors.serverError'))
      setDestroying(false)
    }
  }

  // Charge les blobs au montage.
  useEffect(() => {
    if (!sessionId) return
    let cancelled = false
    async function load() {
      try {
        const r = await fetch(`/v1/auth/recovery/${sessionId}`)
        if (cancelled) return
        if (r.status === 410) {
          const body = await r.json().catch(() => ({}))
          const reason = body?.detail?.error ?? 'session_invalid'
          setErrorMsg(t(`recover.errors.${reason}`, t('recover.errors.session_invalid')))
          setStep('error')
          return
        }
        if (r.status === 404) {
          setErrorMsg(t('recover.errors.session_not_found'))
          setStep('error')
          return
        }
        if (!r.ok) {
          setErrorMsg(t('errors.serverError'))
          setStep('error')
          return
        }
        const data = (await r.json()) as RecoveryBlobs
        setBlobs(data)
        setStep('words')
      } catch {
        if (!cancelled) {
          setErrorMsg(t('errors.serverError'))
          setStep('error')
        }
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [sessionId, t])

  async function handleVerifyWords() {
    if (!blobs) return
    if (words.some((w) => !w.trim())) {
      setErrorMsg(t('recover.errors.missing_words'))
      return
    }
    setErrorMsg(null)
    setStep('submitting')

    try {
      // 1. BIP-39 → seed
      let seed: Uint8Array
      try {
        seed = await decodeBip39(words.map((w) => w.trim().toLowerCase()))
      } catch {
        await reportFailedAttempt()
        setErrorMsg(t('recover.errors.invalid_words'))
        setStep('words')
        return
      }

      // 2. Argon2id(seed, salt_recovery) → recovery_key
      const saltRec = fromBase64(blobs.salt_recovery)
      const recoveryKey = await deriveKeyFromSeed(seed, saltRec, blobs.kdf_params)

      // 3. AES-GCM décrypte sym_key avec recovery_key
      let symKey: Uint8Array
      let rsaPriv: Uint8Array
      try {
        const encSym = fromBase64(blobs.encrypted_sym_key_by_recovery)
        symKey = await aesGcmDecrypt(encSym, recoveryKey)
        // 4. AES-GCM décrypte rsa_priv avec recovery_key (LOT_57 fix —
        //    avant la migration 022, rsa_priv n'était chiffrée qu'avec
        //    pass_key et donc inaccessible via les 24 mots).
        const encRsaPrivByRec = fromBase64(blobs.encrypted_rsa_private_key_by_recovery)
        rsaPriv = await aesGcmDecrypt(encRsaPrivByRec, recoveryKey)
      } catch {
        await reportFailedAttempt()
        setErrorMsg(t('recover.errors.invalid_words'))
        setStep('words')
        return
      }

      setDecryptedSymKey(symKey)
      setDecryptedRsaPriv(rsaPriv)
      setStep('newPass')
    } catch {
      setErrorMsg(t('errors.serverError'))
      setStep('words')
    }
  }

  async function reportFailedAttempt() {
    try {
      const r = await fetch(`/v1/auth/recovery/${sessionId}/attempt-failed`, {
        method: 'POST',
      })
      if (r.status === 410) {
        // session passée à 'failed' → plus rien à faire
        setErrorMsg(t('recover.errors.session_failed'))
        setStep('error')
        return
      }
      if (r.ok) {
        const body = (await r.json()) as { attempts_left: number }
        if (blobs) setBlobs({ ...blobs, attempts_left: body.attempts_left })
      }
    } catch {
      // silencieux : si le report échoue, on laisse le user retenter
    }
  }

  async function handleSetNewPassphrase() {
    if (!blobs || !decryptedSymKey || !decryptedRsaPriv) return
    if (newPass.length < 12) {
      setErrorMsg(t('recover.errors.passphrase_too_short'))
      return
    }
    if (newPass !== newPassConfirm) {
      setErrorMsg(t('recover.errors.passphrase_mismatch'))
      return
    }
    setErrorMsg(null)
    setStep('submitting')

    try {
      // 1. Génère nouveau salt + dérive nouvelle pass_key
      const newSalt = randomBytes(16)
      const params = DEFAULT_KDF_PARAMS
      const passKey = await deriveKey(newPass, newSalt, params)

      // 2. Re-chiffre rsa_private_key + sym_key avec la nouvelle pass_key
      const newEncPriv = await aesGcmEncrypt(decryptedRsaPriv, passKey)
      const newEncSymByPass = await aesGcmEncrypt(decryptedSymKey, passKey)

      // 3. POST complete
      const r = await fetch(`/v1/auth/recovery/${blobs.session_id}/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          new_salt_passphrase: toBase64(newSalt),
          new_encrypted_rsa_private_key: toBase64(newEncPriv),
          new_encrypted_sym_key_by_pass: toBase64(newEncSymByPass),
          kdf_memory_kb: params.memory_kb,
          kdf_iterations: params.iterations,
          kdf_parallelism: params.parallelism,
        }),
      })
      if (r.status === 410) {
        setErrorMsg(t('recover.errors.session_invalid'))
        setStep('error')
        return
      }
      if (!r.ok) {
        setErrorMsg(t('errors.serverError'))
        setStep('newPass')
        return
      }
      setStep('done')
    } catch {
      setErrorMsg(t('errors.serverError'))
      setStep('newPass')
    }
  }

  function setWord(idx: number, value: string) {
    const next = [...words]
    next[idx] = value
    setWords(next)
  }

  // ─── Rendu par étape ────────────────────────────────────────────────────────

  if (step === 'loading') {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    )
  }

  if (step === 'error') {
    return (
      <Center h="100vh" style={{ background: 'var(--mantine-color-body)' }}>
        <Stack w={460} gap="md" align="center">
          <Title order={3}>{t('recover.errorTitle')}</Title>
          <Alert color="red" variant="light" w="100%">
            {errorMsg ?? t('errors.serverError')}
          </Alert>
          <Anchor onClick={() => navigate('/recover/start')} style={{ cursor: 'pointer' }}>
            {t('recover.startNewSession')}
          </Anchor>
          <Anchor onClick={() => navigate('/login')} style={{ cursor: 'pointer' }}>
            {t('recover.backToLogin')}
          </Anchor>

          {/* Option de dernier recours : recréer un compte de zéro après
              avoir épuisé toutes les tentatives de récupération. */}
          <Box w="100%" mt="lg" pt="md" style={{ borderTop: '1px solid #eee' }}>
            <Text size="sm" c="dimmed" mb="xs">
              {t('recover.destroyHint')}
            </Text>
            <Button
              variant="outline"
              color="red"
              fullWidth
              onClick={() => setDestroyOpen(true)}
            >
              {t('recover.destroyButton')}
            </Button>
          </Box>

          {renderDestroyModal()}
        </Stack>
      </Center>
    )
  }

  if (step === 'done') {
    return (
      <Center h="100vh" style={{ background: 'var(--mantine-color-body)' }}>
        <Stack w={420} gap="md" align="center">
          <Title order={3}>{t('recover.doneTitle')}</Title>
          <Text size="sm" c="dimmed" ta="center">
            {t('recover.doneBody')}
          </Text>
          <Button color="brand" onClick={() => navigate('/login')}>
            {t('recover.backToLogin')}
          </Button>
        </Stack>
      </Center>
    )
  }

  if (step === 'newPass' || step === 'submitting') {
    return (
      <Center h="100vh" style={{ background: 'var(--mantine-color-body)' }}>
        <Stack w={420} gap="md">
          <Box ta="center">
            <Title order={3}>{t('recover.newPassTitle')}</Title>
            <Text size="sm" c="dimmed" mt="xs">
              {t('recover.newPassSubtitle')}
            </Text>
          </Box>

          {errorMsg && (
            <Alert color="red" variant="light">
              {errorMsg}
            </Alert>
          )}

          <PasswordInput
            label={t('recover.newPassLabel')}
            value={newPass}
            onChange={(e) => setNewPass(e.currentTarget.value)}
            disabled={step === 'submitting'}
            autoFocus
          />
          <PasswordInput
            label={t('recover.newPassConfirmLabel')}
            value={newPassConfirm}
            onChange={(e) => setNewPassConfirm(e.currentTarget.value)}
            disabled={step === 'submitting'}
          />

          <Button
            fullWidth
            color="brand"
            onClick={() => void handleSetNewPassphrase()}
            loading={step === 'submitting'}
            disabled={!newPass || !newPassConfirm}
          >
            {t('recover.confirmReset')}
          </Button>
        </Stack>
      </Center>
    )
  }

  // step === 'words'
  return (
    <Center h="100vh" style={{ background: 'var(--mantine-color-body)' }}>
      <Stack w={620} gap="md">
        <Box ta="center">
          <Title order={3}>{t('recover.wordsTitle')}</Title>
          <Text size="sm" c="dimmed" mt="xs">
            {t('recover.wordsSubtitle')}
          </Text>
          {blobs && (
            <Text size="xs" c="orange" mt="xs">
              {t('recover.attemptsLeft', { count: blobs.attempts_left })}
            </Text>
          )}
        </Box>

        {errorMsg && (
          <Alert color="red" variant="light">
            {errorMsg}
          </Alert>
        )}

        <Group justify="flex-end">
          <Button variant="subtle" size="xs" onClick={() => setPasteOpen(true)}>
            {t('recover.pasteWords')}
          </Button>
        </Group>

        <Modal
          opened={pasteOpen}
          onClose={() => {
            setPasteOpen(false)
            setPasteError(null)
          }}
          title={t('recover.pasteTitle')}
          size="md"
        >
          <Stack gap="sm">
            <Text size="sm" c="dimmed">
              {t('recover.pasteHelp')}
            </Text>
            <Textarea
              autosize
              minRows={6}
              maxRows={12}
              placeholder={'01. fatal\n02. outdoor\n...'}
              value={pasteText}
              onChange={(e) => setPasteText(e.currentTarget.value)}
              data-testid="recover-paste-area"
            />
            {pasteError && (
              <Alert color="red" variant="light">
                {pasteError}
              </Alert>
            )}
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setPasteOpen(false)}>
                {t('common.cancel')}
              </Button>
              <Button color="brand" onClick={handleApplyPaste}>
                {t('recover.pasteApply')}
              </Button>
            </Group>
          </Stack>
        </Modal>

        <SimpleGrid cols={{ base: 2, sm: 3, md: 4 }} spacing="xs">
          {words.map((w, i) => (
            <TextInput
              key={i}
              size="xs"
              label={`${i + 1}`}
              value={w}
              onChange={(e) => setWord(i, e.currentTarget.value)}
              data-testid={`word-${i}`}
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
            />
          ))}
        </SimpleGrid>

        <Button
          fullWidth
          color="brand"
          onClick={() => void handleVerifyWords()}
          disabled={words.some((w) => !w.trim())}
        >
          {t('recover.verifyWords')}
        </Button>

        <Anchor onClick={() => navigate('/login')} ta="center" style={{ cursor: 'pointer' }}>
          {t('recover.backToLogin')}
        </Anchor>

        {/* Échappatoire pour l'utilisateur qui réalise pendant la saisie
            qu'il a définitivement perdu ses 24 mots — sans avoir à attendre
            d'épuiser ses tentatives ou l'expiration de la session. */}
        <Box mt="lg" pt="md" style={{ borderTop: '1px solid #eee' }}>
          <Text size="xs" c="dimmed" mb="xs" ta="center">
            {t('recover.destroyHint')}
          </Text>
          <Button
            variant="outline"
            color="red"
            size="xs"
            fullWidth
            onClick={() => setDestroyOpen(true)}
          >
            {t('recover.destroyButton')}
          </Button>
        </Box>

        {renderDestroyModal()}
      </Stack>
    </Center>
  )
}
