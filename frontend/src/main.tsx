import React from 'react'
import ReactDOM from 'react-dom/client'
import { MantineProvider } from '@mantine/core'
import { ModalsProvider } from '@mantine/modals'
import { Notifications } from '@mantine/notifications'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@mantine/core/styles.css'
import '@mantine/notifications/styles.css'
import '@mantine/dates/styles.css'

import App from './App'
import './lib/i18n'
import { theme } from './lib/theme'
import './lib/global.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="light">
      <ModalsProvider>
        <Notifications position="top-right" autoClose={6000} zIndex={2000} containerWidth={420} />
        <QueryClientProvider client={queryClient}>
          <App />
        </QueryClientProvider>
      </ModalsProvider>
    </MantineProvider>
  </React.StrictMode>,
)
