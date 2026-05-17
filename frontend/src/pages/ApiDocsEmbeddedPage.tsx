/**
 * ApiDocsEmbeddedPage — Swagger UI affiché DANS le Layout admin (menu de
 * gauche conservé). Différent d'`ApiDocsPage` qui a son propre layout
 * autonome (utilisé par `/integration/api-docs` pour les visiteurs publics
 * depuis l'IntegrationPage).
 *
 * L'iframe pointe vers `/v1/api-docs` (Swagger UI standalone servi par
 * api_key_openapi.router, qui charge `/v1/openapi-api-key.json` — schema
 * filtré aux endpoints API-key uniquement). Le `/docs` natif FastAPI
 * n'est PAS exposé sous /v1.
 */
import { Box } from "@mantine/core";

export function ApiDocsEmbeddedPage() {
  return (
    <Box
      style={{
        // Le Layout principal a son propre padding ; on prend toute la hauteur
        // restante du panel en retirant la marge de la nav top (~60px).
        height: "calc(100vh - 80px)",
        width: "100%",
      }}
    >
      <iframe
        src="/v1/api-docs"
        title="API Reference"
        style={{
          border: "none",
          width: "100%",
          height: "100%",
          display: "block",
        }}
      />
    </Box>
  );
}
