# Changelog

## 0.7.0 — 2026-05-17

### Security — split-token client-side

**La `decryption_key` ne transite plus jamais sur le canal HTTP.**

Le `VaultHttpClient` tronque maintenant le token API key à l'instanciation :
le segment `dkey` (43 chars base64url) est remplacé par un placeholder constant
avant la première requête. La vraie `dkey` reste en RAM côté client, parsée par
`VaultClient` pour le déchiffrement local des `encrypted_wallet_key`.

Le HMAC du token ne couvre pas le segment `dkey` (cf.
`backend/app/core/api_key_token.py:103-112`), donc la troncature est
transparente pour la validation serveur.

- **Avant 0.7.0** : le SDK envoyait le token complet `hrpv_1_id_exp_perms_auth_dkey_hmac`
  dans le header `Authorization`. La dkey transitait sur TLS et était parsée
  côté serveur (jamais utilisée par un handler, mais présente en mémoire).
- **À partir de 0.7.0** : le SDK envoie `hrpv_1_id_exp_perms_auth_<placeholder43>_hmac`.
  Un serveur compromis qui logue le header `Authorization` ne récupère plus la dkey.

### Nouvelles API publiques

- `harpocrate.token.truncate_token_for_transport(token: str) -> str` —
  helper exposé pour les intégrations qui construisent leurs propres clients
  HTTP. Lève `InvalidTokenError` si le token est mal formé.

### Breaking changes

- `VaultHttpClient(base_url, token=...)` **valide maintenant le format du
  token au boot**. Un token de fixtures de test sans le format `hrpv_*`
  complet (8 segments, longueurs fixes) lève `InvalidTokenError`. Mettez à
  jour vos fixtures de test pour utiliser un token réel ou utilisez
  `unittest.mock.patch("harpocrate.client.parse_token")` + `patch("harpocrate.client.VaultHttpClient")`
  pour tester un client mocké de bout en bout (cf. `tests/test_rotation.py`).

### Tests

- Suite de tests `tests/unit/test_http_split_token.py` qui intercepte
  `httpx.request` et vérifie que la `dkey` n'apparaît jamais dans le header
  `Authorization` envoyé (GET, POST, PUT, PATCH, DELETE).
- 8 nouveaux tests unitaires pour `truncate_token_for_transport`.
- Suite totale : 140 tests verts.

### Migration depuis 0.6.x

Pour les utilisateurs du SDK :
- **Aucun changement de code requis** : `VaultClient(token=..., base_url=...)`
  fonctionne à l'identique. Le token complet est toujours accepté en entrée,
  la troncature est interne.
- Si vous instanciez directement `VaultHttpClient` avec un token de test
  (`"hrpv_test"`, `"hrpv_x"`...), remplacez-le par un token au bon format
  (cf. `tests/unit/test_http_split_token.py` pour un exemple).

Les autres SDK officiels (TypeScript, JavaScript, Go, Rust, C#) n'ont **pas
encore** ce changement — ils enverront toujours le token complet jusqu'à leur
prochaine version.

---

## 0.6.0 — antérieur

(historique non documenté dans ce CHANGELOG ; voir `git log` pour les détails).
