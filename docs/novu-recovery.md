# Workflow Novu — `passphrase-reset` (LOT_57)

Harpocrate délègue l'envoi d'email à Novu : le backend déclenche un workflow
nommé `passphrase-reset` quand un utilisateur démarre une session de
réinitialisation de passphrase. Côté Harpocrate, aucun template, aucun SMTP.

## Variables d'environnement Harpocrate

```
NOVU_API_URL=https://api.novu.co/v1
NOVU_API_KEY=<ApiKey de l'organisation Novu, sans le préfixe>
HARPOCRATE_PUBLIC_URL=https://vault.yoops.org   # déjà configuré ailleurs
```

Si `NOVU_API_KEY` est vide, le service log `novu_not_configured`
et passe en no-op silencieux. Le flow recovery reste fonctionnel côté UI
(l'admin reçoit toujours `202` après POST `/start`), mais aucun email ne
part — utile pour dev local.

## Payload envoyé à Novu

```http
POST {NOVU_API_URL}/events/trigger
Authorization: ApiKey {NOVU_API_KEY}
Content-Type: application/json

{
  "name": "passphrase-reset",
  "to": {
    "subscriberId": "{user.id (UUID Harpocrate)}",
    "email": "{user.email}"
  },
  "payload": {
    "firstName": "Gaël",
    "resetLink": "https://vault.yoops.org/recover/{session_id}",
    "expiresInMinutes": 30,
    "attemptsAllowed": 3
  }
}
```

`subscriberId = user.id` (UUID Harpocrate). Novu auto-crée le subscriber au
premier trigger, donc rien à pré-créer.

## Workflow Novu à configurer

Côté admin Novu :

1. Créer un workflow nommé exactement **`passphrase-reset`** (sensible à la casse).
2. Ajouter un **email step** consommant les variables :
   - `{{payload.firstName}}` — prénom (peut être vide)
   - `{{payload.resetLink}}` — URL absolue à inclure dans un bouton/lien
   - `{{payload.expiresInMinutes}}` — durée de validité (30)
   - `{{payload.attemptsAllowed}}` — nombre de tentatives autorisées (3)
3. Configurer un provider mail dans Novu (Brevo / Sendgrid / SES…). Pour le
   dev, **Mailtrap** ou similaire suffit pour vérifier l'arrivée du mail
   sans envoyer en vrai.

### Exemple de template (anglais)

> **Subject** : Reset your Harpocrate passphrase
>
> Hi {{payload.firstName}},
>
> We received a request to reset the passphrase of your Harpocrate vault.
> If you initiated this request, click the link below within
> {{payload.expiresInMinutes}} minutes:
>
> [Reset my passphrase]({{payload.resetLink}})
>
> You'll need your 24-word recovery phrase that was shown to you the first
> time you bootstrapped the vault. After {{payload.attemptsAllowed}} failed
> attempts, you must restart a new recovery session.
>
> If you did NOT initiate this request, ignore this email — your passphrase
> is unchanged and the link is single-use.

## Comportement en cas d'échec Novu

- 4xx/5xx HTTP → log `novu_trigger_http_error` côté Harpocrate, pas d'erreur
  remontée au client (anti-énumération).
- Timeout/DNS/connect error → log `novu_trigger_network_error`, idem.
- Le user peut toujours redemander une session après 30 minutes.

## Détection d'attaques

Le service Harpocrate compte les sessions de recovery `failed` ou `expired`
sur 24 heures glissantes. Si ≥5 pour le même email, une row est insérée
dans `identity_anomaly_events` avec :
- `anomaly_type = 'recovery_session_repeated_failures'`
- `severity = 'warning'`
- `metadata = {"unsuccessful_sessions_24h": <count>, "email": "..."}`

Visible dans **Admin → Anomalies** (UI) ou via `GET /v1/admin/anomalies`.
