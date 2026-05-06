using Xunit;

namespace Harpocrate.Sdk.Tests;

public class TokenParserTests
{
    [Fact]
    public void Rejects_invalid_prefix()
    {
        Assert.Throws<InvalidTokenException>(() => TokenParser.Parse("foo_bar"));
    }

    [Fact]
    public void Rejects_too_short()
    {
        Assert.Throws<InvalidTokenException>(() => TokenParser.Parse("hrpv_1_short"));
    }

    [Fact]
    public void Rejects_null_or_empty()
    {
        Assert.Throws<InvalidTokenException>(() => TokenParser.Parse(""));
    }
}
