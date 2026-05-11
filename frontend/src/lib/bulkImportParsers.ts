/**
 * Parsers pour l'import en masse de secrets dans un wallet.
 *
 * Supporte 3 formats avec auto-détection :
 *   - format A : `.env` style (`KEY=VALUE` une par ligne)
 *   - format B : JSON flat ({"KEY": "VALUE", ...})
 *   - format D : JSON harpocrate ({"format": "harpocrate-bulk-import", ...})
 *
 * Auto-détection : essai JSON d'abord. Si parse OK → check "format" pour D
 * sinon traité comme B. Si parse JSON KO → tenté comme .env.
 */

export type BulkImportFormat = "env" | "json-flat" | "harpocrate";

export interface ParsedSecret {
  name: string;
  value: string;
}

export interface ParseSuccess {
  ok: true;
  format: BulkImportFormat;
  secrets: ParsedSecret[];
}

export interface ParseFailure {
  ok: false;
  error: string;
}

export type ParseResult = ParseSuccess | ParseFailure;

// Format Harpocrate : enveloppe explicite reconnue par la clé `format`.
// Permet l'extension future (versioning, métadonnées).
const HARPOCRATE_FORMAT_TAG = "harpocrate-bulk-import";

/**
 * Auto-détecte le format et parse. Retourne `{ok: false, error}` si
 * aucun format ne match (texte vide, JSON invalide ET pas de lignes
 * KEY=VALUE valides).
 */
export function parseBulkImport(input: string): ParseResult {
  const trimmed = input.trim();
  if (!trimmed) {
    return { ok: false, error: "empty input" };
  }

  // 1) Essai JSON
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      const json = JSON.parse(trimmed) as unknown;
      return parseJson(json);
    } catch (e) {
      return { ok: false, error: `invalid JSON: ${(e as Error).message}` };
    }
  }

  // 2) Sinon, format .env
  return parseEnv(trimmed);
}

/**
 * Parse un objet JSON. Détecte format Harpocrate vs flat.
 */
function parseJson(json: unknown): ParseResult {
  if (typeof json !== "object" || json === null || Array.isArray(json)) {
    return {
      ok: false,
      error:
        "JSON must be an object (either flat key/value or Harpocrate format)",
    };
  }
  const obj = json as Record<string, unknown>;

  // Format Harpocrate
  if (obj["format"] === HARPOCRATE_FORMAT_TAG) {
    if (!Array.isArray(obj["secrets"])) {
      return {
        ok: false,
        error: "Harpocrate format: missing or invalid `secrets` array",
      };
    }
    const secrets: ParsedSecret[] = [];
    for (const item of obj["secrets"]) {
      if (typeof item !== "object" || item === null) {
        return {
          ok: false,
          error: "Harpocrate format: each secret must be an object",
        };
      }
      const s = item as Record<string, unknown>;
      const name = typeof s["name"] === "string" ? s["name"] : null;
      const value = typeof s["value"] === "string" ? s["value"] : null;
      if (!name || value === null) {
        return {
          ok: false,
          error:
            "Harpocrate format: each secret needs `name` (string) and `value` (string)",
        };
      }
      secrets.push({ name, value });
    }
    return { ok: true, format: "harpocrate", secrets };
  }

  // Format flat : {key: value, ...}
  const secrets: ParsedSecret[] = [];
  for (const [name, value] of Object.entries(obj)) {
    if (typeof value !== "string") {
      return {
        ok: false,
        error: `flat JSON: value for key "${name}" must be a string (got ${typeof value})`,
      };
    }
    secrets.push({ name, value });
  }
  if (secrets.length === 0) {
    return { ok: false, error: "flat JSON: empty object, nothing to import" };
  }
  return { ok: true, format: "json-flat", secrets };
}

/**
 * Parse un bloc style `.env`.
 * Règles :
 *   - lignes vides ignorées
 *   - lignes commençant par `#` (commentaires) ignorées
 *   - séparateur `=` PRIORITAIRE (format .env standard) ; à défaut `:`
 *     (format "human" type "key: value"). Cette priorité évite de casser
 *     les valeurs qui contiennent un `:` (ex: `URL=postgres://user:p@host`).
 *   - clé et valeur sont trim-ées
 *   - clé normalisée : caractères hors `[a-zA-Z0-9_-]` → `_`,
 *     collapse des `_` consécutifs, trim des `_` aux extrémités.
 *     Permet d'accepter "github token llm" → "github_token_llm".
 *   - guillemets autour de la valeur (`KEY="value"` ou `KEY='value'`) retirés
 *   - lignes qui ne matchent pas sont signalées (erreur de format → fail global)
 */
function parseEnv(text: string): ParseResult {
  const secrets: ParsedSecret[] = [];
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i] ?? "";
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;

    // Choix du séparateur : `=` prioritaire, fallback `:`.
    const eqIdx = line.indexOf("=");
    const colonIdx = line.indexOf(":");
    let sepIdx = -1;
    if (eqIdx > 0) sepIdx = eqIdx;
    else if (colonIdx > 0) sepIdx = colonIdx;

    if (sepIdx <= 0) {
      return {
        ok: false,
        error: `line ${i + 1}: invalid format (expected KEY=VALUE or KEY: VALUE, got "${line}")`,
      };
    }
    const rawName = line.substring(0, sepIdx).trim();
    let value = line.substring(sepIdx + 1).trim();
    // Strip wrapping quotes (mais pas si juste un seul " au début sans fermant).
    if (
      (value.startsWith('"') && value.endsWith('"') && value.length >= 2) ||
      (value.startsWith("'") && value.endsWith("'") && value.length >= 2)
    ) {
      value = value.substring(1, value.length - 1);
    }
    const name = normalizeKey(rawName);
    if (!name) {
      return {
        ok: false,
        error: `line ${i + 1}: empty key after normalization (got "${rawName}")`,
      };
    }
    secrets.push({ name, value });
  }
  if (secrets.length === 0) {
    return { ok: false, error: "no valid KEY=VALUE or KEY: VALUE lines found" };
  }
  return { ok: true, format: "env", secrets };
}

/**
 * Normalise une clé pour qu'elle soit utilisable comme nom de secret :
 *   - tout caractère hors `[a-zA-Z0-9_-]` → `_`
 *   - collapse les `_` consécutifs en un seul
 *   - trim les `_` aux extrémités
 *
 * Exemples :
 *   "github token llm"   → "github_token_llm"
 *   "API key (prod)"     → "API_key_prod"
 *   "  __weird-key__  "  → "weird-key"
 *   "🔑 secret"          → "secret"
 */
export function normalizeKey(raw: string): string {
  return raw
    .replace(/[^a-zA-Z0-9_-]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
}
