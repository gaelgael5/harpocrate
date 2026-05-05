# Harpocrate SDK — C# / .NET 8

Client zero-knowledge pour [Harpocrate Vault](https://github.com/gaelgael5/harpocrate).

## Installation

```bash
dotnet add package Harpocrate.Sdk
```

## Usage

```csharp
using Harpocrate.Sdk;

using var client = await VaultClient.CreateAsync(
    token: "hrpv_1_...",
    baseUrl: "https://vault.yoops.org");

// Lire un secret
var value = await client.GetSecretAsync("ANTHROPIC_API_KEY");
Console.WriteLine(value);

// Lister
var list = await client.ListSecretsAsync();
foreach (var s in list.Secrets)
{
    Console.WriteLine($"{s.Name} (placeholder={s.IsPlaceholder})");
}

// Créer
var id = await client.CreateSecretAsync("MY_KEY", "secret-value");

// Mettre à jour
var gen = await client.PutSecretAsync("MY_KEY", "new-value");

// Supprimer
await client.DeleteSecretAsync("MY_KEY");
```

## Périmètre v0.1.0

- ✅ Parsing token `hrpv_*` (format identique aux autres SDK)
- ✅ Crypto AES-256-GCM
- ✅ HttpClient + auth Bearer
- ✅ Get / List / Create / Put / Delete secrets
- ✅ Cache wallet_key thread-safe
- ❌ Placeholders + générateurs (futur)
- ❌ Détection rotation auth_error (LOT 22, futur portage C#)

## Build & test

```bash
dotnet test
```

## Publication NuGet

À effectuer manuellement par le mainteneur :

```bash
dotnet pack src/Harpocrate.Sdk -c Release -o ./nupkg
dotnet nuget push ./nupkg/Harpocrate.Sdk.0.1.0.nupkg --api-key <KEY> --source https://api.nuget.org/v3/index.json
```
