using System.Globalization;

namespace Harpocrate.Sdk;

/// <summary>
/// Parsing du token <c>hrpv_v_id_exp_perms_auth_dkey_hmac</c> (format identique au SDK Python).
/// </summary>
public sealed record ParsedToken(
    string Version,
    Guid ApiKeyId,
    long Exp,
    byte Permissions,
    string AuthSecretB64,
    byte[] DecryptionKey,
    string DkeyB64,
    string HmacB64);

public static class TokenParser
{
    private const string Prefix = "hrpv";
    private const string Version = "1";
    private const int IdB32Len = 26;
    private const int AuthSecretLen = 43;
    private const int DkeyLen = 43;
    private const int HmacLen = 22;

    public static ParsedToken Parse(string token)
    {
        if (string.IsNullOrEmpty(token) || !token.StartsWith($"{Prefix}_"))
        {
            throw new InvalidTokenException("invalid_prefix", "Token must start with 'hrpv_'");
        }

        var suffixLen = AuthSecretLen + 1 + DkeyLen + 1 + HmacLen;
        var minLen = Prefix.Length + 1 + Version.Length + 1 + IdB32Len + 1 + 1 + 1 + 2 + 1 + suffixLen;
        if (token.Length < minLen)
        {
            throw new InvalidTokenException("invalid_format", "Token is too short");
        }

        var total = token.Length;
        var hmacB64 = token[(total - HmacLen)..];
        if (token[total - HmacLen - 1] != '_')
        {
            throw new InvalidTokenException("invalid_format", "Malformed token structure");
        }

        var dkeyEnd = HmacLen + 1 + DkeyLen;
        var dkeyB64 = token[(total - dkeyEnd)..(total - HmacLen - 1)];
        if (token[total - dkeyEnd - 1] != '_')
        {
            throw new InvalidTokenException("invalid_format", "Malformed token structure");
        }

        var authEnd = dkeyEnd + 1 + AuthSecretLen;
        var authSecretB64 = token[(total - authEnd)..(total - dkeyEnd - 1)];
        if (token[total - authEnd - 1] != '_')
        {
            throw new InvalidTokenException("invalid_format", "Malformed token structure");
        }

        var prefixPart = token[..(total - suffixLen - 1)];
        var parts = prefixPart.Split('_');
        if (parts.Length != 5)
        {
            throw new InvalidTokenException("invalid_format", "Malformed token structure (prefix)");
        }
        var (prefix, version, idB32, expB36, permsHex) = (parts[0], parts[1], parts[2], parts[3], parts[4]);

        if (prefix != Prefix)
        {
            throw new InvalidTokenException("invalid_prefix", "Token must start with 'hrpv_'");
        }
        if (version != Version)
        {
            throw new InvalidTokenException("unsupported_version", $"Unsupported token version: {version}");
        }
        if (idB32.Length != IdB32Len)
        {
            throw new InvalidTokenException("invalid_id_encoding", "Invalid API key ID encoding");
        }

        var apiKeyId = DecodeBase32Uuid(idB32);
        if (!long.TryParse(expB36, NumberStyles.None, CultureInfo.InvariantCulture, out _))
        {
            // base 36 - parse manuel
        }
        var exp = ParseBase36(expB36);
        if (!byte.TryParse(permsHex, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var perms))
        {
            throw new InvalidTokenException("invalid_perms_encoding", "Cannot decode permissions");
        }
        if (perms > 0x3F)
        {
            throw new InvalidTokenException("invalid_perms_value", $"Permissions out of range: {perms}");
        }

        var dkeyBytes = Base64UrlDecode(dkeyB64);
        if (dkeyBytes.Length != 32)
        {
            throw new InvalidTokenException("invalid_dkey_length",
                $"Decryption key must be 32 bytes, got {dkeyBytes.Length}");
        }

        if (exp != 0 && exp < DateTimeOffset.UtcNow.ToUnixTimeSeconds())
        {
            throw new TokenExpiredException();
        }

        return new ParsedToken(version, apiKeyId, exp, perms, authSecretB64, dkeyBytes, dkeyB64, hmacB64);
    }

    private static Guid DecodeBase32Uuid(string b32)
    {
        // base32 RFC 4648 lowercase 26 chars → 16 bytes UUID
        var padded = (b32.ToUpperInvariant() + "======")[..32];
        try
        {
            var bytes = Base32Decode(padded);
            return new Guid(bytes);
        }
        catch
        {
            throw new InvalidTokenException("invalid_id_encoding", "Cannot decode API key ID");
        }
    }

    private static byte[] Base32Decode(string s)
    {
        const string Alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
        var clean = s.TrimEnd('=');
        var output = new List<byte>(clean.Length * 5 / 8);
        var buffer = 0;
        var bitsLeft = 0;
        foreach (var c in clean)
        {
            var idx = Alphabet.IndexOf(c);
            if (idx < 0) throw new FormatException($"Invalid base32 char: {c}");
            buffer = (buffer << 5) | idx;
            bitsLeft += 5;
            if (bitsLeft >= 8)
            {
                bitsLeft -= 8;
                output.Add((byte)((buffer >> bitsLeft) & 0xFF));
            }
        }
        return [.. output];
    }

    private static long ParseBase36(string s)
    {
        long result = 0;
        foreach (var c in s.ToLowerInvariant())
        {
            int digit;
            if (c >= '0' && c <= '9') digit = c - '0';
            else if (c >= 'a' && c <= 'z') digit = c - 'a' + 10;
            else throw new InvalidTokenException("invalid_exp_encoding", $"Bad base36 char: {c}");
            result = result * 36 + digit;
        }
        return result;
    }

    private static byte[] Base64UrlDecode(string s)
    {
        var padded = s.Replace('-', '+').Replace('_', '/');
        switch (padded.Length % 4)
        {
            case 2: padded += "=="; break;
            case 3: padded += "="; break;
        }
        try
        {
            return Convert.FromBase64String(padded);
        }
        catch
        {
            throw new InvalidTokenException("invalid_dkey_encoding", "Cannot decode decryption key");
        }
    }
}
