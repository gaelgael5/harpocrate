/**
 * FolderTree — arbre de dossiers expandable pour la navigation dans un wallet.
 *
 * Lazy-loading : chaque sous-niveau est fetché à la demande quand l'utilisateur
 * déploie un dossier, via GET /v1/wallets/{wid}/tree?path=...
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Stack, UnstyledButton, Text, Group, Loader } from '@mantine/core'
import { z } from 'zod'

import { api } from '@/lib/api-client'

const FolderSchema = z.object({
  name: z.string(),
  full_path: z.string(),
  secrets_count: z.number(),
  subfolders_count: z.number(),
})

const TreeDataSchema = z.object({
  path: z.string(),
  secrets_at_this_level_count: z.number(),
  folders: z.array(FolderSchema),
})

type Folder = z.infer<typeof FolderSchema>

interface TreeNodeProps {
  walletId: string
  folder: Folder
  currentPath: string
  onSelect: (path: string) => void
  level: number
}

function TreeNode({ walletId, folder, currentPath, onSelect, level }: TreeNodeProps) {
  const [expanded, setExpanded] = useState(false)
  const isCurrent = currentPath === folder.full_path
  const hasChildren = folder.subfolders_count > 0

  const { data, isLoading } = useQuery({
    queryKey: ['wallet-tree-node', walletId, folder.full_path],
    queryFn: async () => {
      const raw = await api.get<unknown>(
        `/wallets/${walletId}/tree?path=${encodeURIComponent(folder.full_path)}`,
      )
      return TreeDataSchema.parse(raw)
    },
    enabled: expanded,
  })

  return (
    <Stack gap={2}>
      <UnstyledButton
        onClick={() => {
          if (hasChildren) setExpanded(!expanded)
          onSelect(folder.full_path)
        }}
        style={{
          paddingLeft: 8 + level * 12,
          paddingRight: 8,
          paddingTop: 4,
          paddingBottom: 4,
          backgroundColor: isCurrent ? 'var(--mantine-color-brand-light)' : undefined,
          borderRadius: 4,
        }}
      >
        <Group gap={4} wrap="nowrap">
          <Text size="xs" w={12}>
            {hasChildren ? (expanded ? '▼' : '▶') : ' '}
          </Text>
          <Text size="xs">📁</Text>
          <Text size="sm" truncate fw={isCurrent ? 600 : 400}>
            {folder.name}
          </Text>
          <Text size="xs" c="dimmed">
            ({folder.secrets_count})
          </Text>
        </Group>
      </UnstyledButton>
      {expanded && (
        <Stack gap={2}>
          {isLoading && <Loader size="xs" ml={level * 12 + 16} />}
          {data?.folders.map((sub) => (
            <TreeNode
              key={sub.full_path}
              walletId={walletId}
              folder={sub}
              currentPath={currentPath}
              onSelect={onSelect}
              level={level + 1}
            />
          ))}
        </Stack>
      )}
    </Stack>
  )
}

export interface FolderTreeProps {
  walletId: string
  currentPath: string
  onSelect: (path: string) => void
}

export function FolderTree({ walletId, currentPath, onSelect }: FolderTreeProps) {
  const isRoot = currentPath === '/'

  const { data, isLoading } = useQuery({
    queryKey: ['wallet-tree-root', walletId],
    queryFn: async () => {
      const raw = await api.get<unknown>(
        `/wallets/${walletId}/tree?path=%2F`,
      )
      return TreeDataSchema.parse(raw)
    },
  })

  return (
    <Stack gap={2} style={{ minWidth: 220, maxWidth: 320 }}>
      <UnstyledButton
        onClick={() => onSelect('/')}
        style={{
          paddingLeft: 8,
          paddingRight: 8,
          paddingTop: 4,
          paddingBottom: 4,
          backgroundColor: isRoot ? 'var(--mantine-color-brand-light)' : undefined,
          borderRadius: 4,
        }}
      >
        <Group gap={4}>
          <Text size="xs">🏠</Text>
          <Text size="sm" fw={isRoot ? 600 : 400}>
            (racine)
          </Text>
        </Group>
      </UnstyledButton>

      {isLoading && <Loader size="xs" />}
      {data?.folders.map((folder) => (
        <TreeNode
          key={folder.full_path}
          walletId={walletId}
          folder={folder}
          currentPath={currentPath}
          onSelect={onSelect}
          level={0}
        />
      ))}
    </Stack>
  )
}
