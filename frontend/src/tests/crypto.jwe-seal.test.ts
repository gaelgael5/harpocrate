// @vitest-environment node
/**
 * Scellement JWE pour l'application (feature 4) — aller-retour :
 * scellé côté navigateur → descellé avec la clé privée éphémère → contenu identique.
 * Environnement node : WebCrypto natif, sans les écarts de royaume de jsdom.
 */
import { describe, it, expect } from "vitest";
import {
  compactDecrypt,
  decodeProtectedHeader,
  exportJWK,
  generateKeyPair,
} from "jose";

import { sealForApplication } from "@/crypto/jwe-seal";
import type { AppPublicJwk } from "@/schemas/connectFlow";

async function appKeyPair() {
  const pair = await generateKeyPair("ECDH-ES", {
    crv: "P-256",
    extractable: true,
  });
  const jwk = await exportJWK(pair.publicKey);
  return { privateKey: pair.privateKey, publicJwk: jwk as AppPublicJwk };
}

const PAYLOAD = {
  token: `hrpv_1_${"a".repeat(26)}_0_01_${"s".repeat(43)}_${"A".repeat(43)}_${"h".repeat(22)}`,
  dkey: "d".repeat(43),
};

describe("sealForApplication", () => {
  it("produit un JWE ECDH-ES / A256GCM que seule la clé privée ouvre", async () => {
    const app = await appKeyPair();

    const jwe = await sealForApplication(PAYLOAD, app.publicJwk);

    const header = decodeProtectedHeader(jwe);
    expect(header.alg).toBe("ECDH-ES");
    expect(header.enc).toBe("A256GCM");
    expect(jwe.split(".")[1]).toBe(""); // accord direct : pas de clé chiffrée
    const { plaintext } = await compactDecrypt(jwe, app.privateKey);
    expect(JSON.parse(new TextDecoder().decode(plaintext))).toEqual(PAYLOAD);
  });

  it("ne s'ouvre pas avec une autre clé privée", async () => {
    const app = await appKeyPair();
    const intruder = await appKeyPair();
    const jwe = await sealForApplication(PAYLOAD, app.publicJwk);
    await expect(compactDecrypt(jwe, intruder.privateKey)).rejects.toThrow();
  });

  it("ne laisse pas la dkey en clair dans le scellé", async () => {
    const app = await appKeyPair();
    const jwe = await sealForApplication(PAYLOAD, app.publicJwk);
    expect(jwe).not.toContain(PAYLOAD.dkey);
  });
});
