/**
 * ApiDocsEmbeddedPage — Swagger UI affiché DANS le Layout admin (menu de
 * gauche conservé). Différent d'`ApiDocsPage` qui a son propre layout
 * autonome (utilisé par `/integration/api-docs` pour les visiteurs publics
 * depuis l'IntegrationPage).
 *
 * L'iframe pointe vers `/v1/docs` qui sert le Swagger UI built-in de FastAPI.
 */
import { Box } from '@mantine/core'

export function ApiDocsEmbeddedPage() {
  return (
    <Box
      style={{
        // Le Layout principal a son propre padding ; on prend toute la hauteur
        // restante du panel en retirant la marge de la nav top (~60px).
        height: 'calc(100vh - 80px)',
        width: '100%',
      }}
    >
      <iframe
        src="/v1/docs"
        title="API Reference"
        style={{
          border: 'none',
          width: '100%',
          height: '100%',
          display: 'block',
        }}
      />
    </Box>
  )
}
