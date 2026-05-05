using System.Security.Cryptography;

namespace Harpocrate.Sdk;

/// <summary>
/// AES-256-GCM encrypt/decrypt — format <c>nonce(12) || ciphertext || tag(16)</c>.
/// </summary>
public static class AesGcmCrypto
{
    private const int NonceLen = 12;
    private const int TagLen = 16;

    public static byte[] Encrypt(byte[] plaintext, byte[] key)
    {
        if (key.Length != 32)
        {
            throw new VaultDecryptionException($"key must be 32 bytes, got {key.Length}");
        }
        var nonce = RandomNumberGenerator.GetBytes(NonceLen);
        var ciphertext = new byte[plaintext.Length];
        var tag = new byte[TagLen];
#pragma warning disable SYSLIB0053 // .NET 8 still ships AesGcm constructor with tagSize
        using var gcm = new AesGcm(key, TagLen);
#pragma warning restore SYSLIB0053
        gcm.Encrypt(nonce, plaintext, ciphertext, tag);

        var blob = new byte[NonceLen + ciphertext.Length + TagLen];
        Buffer.BlockCopy(nonce, 0, blob, 0, NonceLen);
        Buffer.BlockCopy(ciphertext, 0, blob, NonceLen, ciphertext.Length);
        Buffer.BlockCopy(tag, 0, blob, NonceLen + ciphertext.Length, TagLen);
        return blob;
    }

    public static byte[] Decrypt(byte[] blob, byte[] key)
    {
        if (key.Length != 32)
        {
            throw new VaultDecryptionException($"key must be 32 bytes, got {key.Length}");
        }
        if (blob.Length < NonceLen + TagLen)
        {
            throw new VaultDecryptionException($"blob too short: {blob.Length} bytes");
        }
        var nonce = blob.AsSpan(0, NonceLen);
        var ciphertext = blob.AsSpan(NonceLen, blob.Length - NonceLen - TagLen);
        var tag = blob.AsSpan(blob.Length - TagLen, TagLen);
        var plaintext = new byte[ciphertext.Length];
        try
        {
#pragma warning disable SYSLIB0053
            using var gcm = new AesGcm(key, TagLen);
#pragma warning restore SYSLIB0053
            gcm.Decrypt(nonce, ciphertext, tag, plaintext);
        }
        catch (CryptographicException)
        {
            throw new VaultDecryptionException("AES-GCM decryption failed: invalid tag or wrong key");
        }
        return plaintext;
    }
}
