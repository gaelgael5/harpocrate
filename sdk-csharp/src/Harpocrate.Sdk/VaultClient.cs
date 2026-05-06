using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Harpocrate.Sdk;

/// <summary>
/// Client haut-niveau Harpocrate Vault.
/// Le SDK déchiffre côté client — le serveur ne voit jamais les valeurs en clair.
/// </summary>
public sealed class VaultClient : IDisposable
{
    private readonly ParsedToken _parsed;
    private readonly HttpClient _http;
    private readonly string _baseUrl;
    private readonly object _wkLock = new();
    private byte[]? _walletKey;

    public Guid WalletId { get; private set; }

    private VaultClient(ParsedToken parsed, HttpClient http, string baseUrl)
    {
        _parsed = parsed;
        _http = http;
        _baseUrl = baseUrl.TrimEnd('/');
    }

    public static async Task<VaultClient> CreateAsync(
        string token,
        string baseUrl,
        HttpClient? httpClient = null,
        TimeSpan? timeout = null,
        CancellationToken cancellationToken = default)
    {
        var parsed = TokenParser.Parse(token);
        var http = httpClient ?? new HttpClient();
        if (httpClient is null && timeout is not null)
        {
            http.Timeout = timeout.Value;
        }
        http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);

        var client = new VaultClient(parsed, http, baseUrl);
        var widResp = await client.GetJsonAsync<WalletIdResp>(
            $"/v1/api-keys/{parsed.ApiKeyId}/wallet-id", cancellationToken);
        client.WalletId = Guid.Parse(widResp.WalletId);
        return client;
    }

    public ApiKeyInfo Whoami() => new(_parsed.ApiKeyId, WalletId, _parsed.Permissions, _parsed.Exp);

    public Task<WalletInfo> GetWalletInfoAsync(CancellationToken ct = default) =>
        GetJsonAsync<WalletInfo>($"/v1/wallets/{WalletId}", ct);

    public Task<SecretListResponse> ListSecretsAsync(CancellationToken ct = default) =>
        GetJsonAsync<SecretListResponse>($"/v1/wallets/{WalletId}/secrets", ct);

    public async Task<string> GetSecretAsync(string name, CancellationToken ct = default)
    {
        var url = SecretUrl(name);
        var resp = await GetJsonAsync<SecretResp>(url, ct);
        var wk = await GetWalletKeyAsync(ct);
        var enc = Convert.FromBase64String(resp.EncryptedValue);
        var plain = AesGcmCrypto.Decrypt(enc, wk);
        return System.Text.Encoding.UTF8.GetString(plain);
    }

    public async Task<Guid> CreateSecretAsync(string name, string value, CancellationToken ct = default)
    {
        var wk = await GetWalletKeyAsync(ct);
        var enc = AesGcmCrypto.Encrypt(System.Text.Encoding.UTF8.GetBytes(value), wk);
        var body = new { name, encrypted_value = Convert.ToBase64String(enc) };
        var url = $"/v1/wallets/{WalletId}/secrets";
        var resp = await PostJsonAsync<CreateSecretResp>(url, body, ct);
        return Guid.Parse(resp.SecretId);
    }

    public async Task<long> PutSecretAsync(string name, string value, CancellationToken ct = default)
    {
        var wk = await GetWalletKeyAsync(ct);
        var enc = AesGcmCrypto.Encrypt(System.Text.Encoding.UTF8.GetBytes(value), wk);
        var body = new { encrypted_value = Convert.ToBase64String(enc) };
        var url = SecretUrl(name);
        var resp = await PutJsonAsync<PutSecretResp>(url, body, ct);
        return resp.GenerationVersion;
    }

    public async Task DeleteSecretAsync(string name, CancellationToken ct = default)
    {
        var r = await _http.DeleteAsync(_baseUrl + SecretUrl(name), ct);
        await EnsureSuccessOrThrow(r, name);
    }

    private async Task<byte[]> GetWalletKeyAsync(CancellationToken ct)
    {
        lock (_wkLock)
        {
            if (_walletKey is not null) return _walletKey;
        }
        var grant = await GetJsonAsync<GrantResp>(
            $"/v1/wallets/{WalletId}/my-api-key-grant", ct);
        var enc = Convert.FromBase64String(grant.EncryptedWalletKey);
        var wk = AesGcmCrypto.Decrypt(enc, _parsed.DecryptionKey);
        if (wk.Length != 32)
        {
            throw new VaultDecryptionException("wallet_key not 32 bytes");
        }
        lock (_wkLock)
        {
            _walletKey ??= wk;
            return _walletKey;
        }
    }

    private string SecretUrl(string name)
    {
        var normalized = name.Contains('/') && !name.StartsWith('/') ? "/" + name : name;
        var encoded = Uri.EscapeDataString(normalized);
        return $"/v1/wallets/{WalletId}/secrets/{encoded}";
    }

    // ─── HTTP helpers ────────────────────────────────────────────────────────

    private async Task<T> GetJsonAsync<T>(string path, CancellationToken ct)
    {
        var r = await _http.GetAsync(_baseUrl + path, ct);
        await EnsureSuccessOrThrow(r, path);
        return (await r.Content.ReadFromJsonAsync<T>(JsonOpts, ct))
               ?? throw new HarpocrateException($"empty body for {path}");
    }

    private async Task<T> PostJsonAsync<T>(string path, object body, CancellationToken ct)
    {
        var r = await _http.PostAsJsonAsync(_baseUrl + path, body, JsonOpts, ct);
        await EnsureSuccessOrThrow(r, path);
        return (await r.Content.ReadFromJsonAsync<T>(JsonOpts, ct))
               ?? throw new HarpocrateException($"empty body for {path}");
    }

    private async Task<T> PutJsonAsync<T>(string path, object body, CancellationToken ct)
    {
        var r = await _http.PutAsJsonAsync(_baseUrl + path, body, JsonOpts, ct);
        await EnsureSuccessOrThrow(r, path);
        return (await r.Content.ReadFromJsonAsync<T>(JsonOpts, ct))
               ?? throw new HarpocrateException($"empty body for {path}");
    }

    private static async Task EnsureSuccessOrThrow(HttpResponseMessage r, string ctx)
    {
        if (r.IsSuccessStatusCode) return;
        var body = await r.Content.ReadAsStringAsync();
        if (r.StatusCode == HttpStatusCode.NotFound)
        {
            throw new SecretNotFoundException(ctx);
        }
        throw new VaultHttpException((int)r.StatusCode, body);
    }

    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = null,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    public void Dispose()
    {
        _http.Dispose();
    }
}
