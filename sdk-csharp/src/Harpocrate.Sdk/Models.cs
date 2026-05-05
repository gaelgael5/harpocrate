using System.Text.Json.Serialization;

namespace Harpocrate.Sdk;

public sealed record SecretInfo
{
    [JsonPropertyName("id")] public Guid Id { get; init; }
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("description")] public string? Description { get; init; }
    [JsonPropertyName("tags")] public List<string> Tags { get; init; } = [];
    [JsonPropertyName("is_placeholder")] public bool IsPlaceholder { get; init; }
    [JsonPropertyName("generation_version")] public long GenerationVersion { get; init; }
}

public sealed record SecretListResponse
{
    [JsonPropertyName("secrets")] public List<SecretInfo> Secrets { get; init; } = [];
    [JsonPropertyName("next_cursor")] public string? NextCursor { get; init; }
}

public sealed record WalletInfo
{
    [JsonPropertyName("id")] public Guid Id { get; init; }
    [JsonPropertyName("name")] public string Name { get; init; } = "";
    [JsonPropertyName("description")] public string? Description { get; init; }
}

public sealed record ApiKeyInfo(Guid ApiKeyId, Guid WalletId, byte Permissions, long Exp);

internal sealed record WalletIdResp([property: JsonPropertyName("wallet_id")] string WalletId);

internal sealed record GrantResp(
    [property: JsonPropertyName("encrypted_wallet_key")] string EncryptedWalletKey);

internal sealed record SecretResp(
    [property: JsonPropertyName("encrypted_value")] string EncryptedValue);

internal sealed record CreateSecretResp(
    [property: JsonPropertyName("secret_id")] string SecretId);

internal sealed record PutSecretResp(
    [property: JsonPropertyName("generation_version")] long GenerationVersion);
