# SDK C# / .NET

Client C# zero-knowledge pour Harpocrate Vault. Compatible .NET 8.

Le SDK déchiffre les secrets côté client — le serveur ne voit jamais les valeurs en clair.

## Installation

Télécharger le package NuGet depuis cette page, puis l'ajouter à un projet :

```bash
dotnet add package Harpocrate.Sdk --version 0.2.0 --source ./releases/
```

Ou via `PackageReference` dans le `.csproj` :

```xml
<ItemGroup>
  <PackageReference Include="Harpocrate.Sdk" Version="0.2.0" />
</ItemGroup>
```

## Usage

```csharp
using Harpocrate.Sdk;

var client = await VaultClient.CreateAsync(
    token: "hrpv_1_...",                  // ton API token
    baseUrl: "https://vault.example.com"
);

// Crée un secret
var id = await client.CreateSecretAsync("DB_PASSWORD", "s3cret!");
Console.WriteLine($"id = {id}");

// Récupère et déchiffre côté client
var value = await client.GetSecretAsync("DB_PASSWORD");
Console.WriteLine($"value = {value}");

// Met à jour
var gen = await client.PutSecretAsync("DB_PASSWORD", "n3w-s3cret!");

// Supprime
await client.DeleteSecretAsync("DB_PASSWORD");
```

## Secrets organisés en arborescence (path-style)

```csharp
await client.CreateSecretAsync("/db/prod/password", "s3cret!");
var value = await client.GetSecretAsync("/db/prod/password");
```

Depuis la version 0.2.0, le SDK utilise la résolution `/by-id/<uuid>` pour les
secrets path-style. Cela évite toute dépendance au comportement des reverse
proxies vis-à-vis des `/` URL-encodés (`%2F`).

## Compatibilité

- .NET 8.0 ou plus récent
- Nullable activé, langage `latest`
- Crypto AES-256-GCM via `System.Security.Cryptography.AesGcm`
- HTTP via `HttpClient` standard

## Pour aller plus loin

Voir le [README complet du SDK](https://github.com/gaelgael5/harpocrate/tree/main/sdk-csharp) sur GitHub.
