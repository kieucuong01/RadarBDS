param(
    [Parameter(Mandatory = $true)]
    [string] $Url,
    [string] $ExpectedCanonical,
    [string] $HeadingContains,
    [string] $SitemapUrl = "https://radarbds.vn/sitemap.xml",
    [switch] $RequireInSitemap = $true,
    [switch] $RequireWatchlistIntent
)

$ErrorActionPreference = "Stop"

if (-not $ExpectedCanonical) {
    $ExpectedCanonical = $Url
}

$page = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 30
$html = $page.Content

if ($page.StatusCode -ne 200) {
    throw "Unexpected status code for ${Url}: $($page.StatusCode)"
}

$canonicalMatch = [regex]::Match($html, '<link rel="canonical" href="([^"]+)"')
if (-not $canonicalMatch.Success) {
    throw "Canonical tag missing on $Url"
}
if ($canonicalMatch.Groups[1].Value -ne $ExpectedCanonical) {
    throw "Canonical mismatch on $Url. Expected $ExpectedCanonical but got $($canonicalMatch.Groups[1].Value)"
}

if ($HeadingContains -and $html -notmatch [regex]::Escape($HeadingContains)) {
    throw "Heading marker not found on ${Url}: $HeadingContains"
}

if ($RequireWatchlistIntent -and $html -notmatch [regex]::Escape('/?tab=signals&amp;intent=watchlist')) {
    throw "Watchlist funnel CTA missing on $Url"
}

$inSitemap = $false
if ($RequireInSitemap) {
    $sitemap = Invoke-WebRequest -UseBasicParsing -Uri $SitemapUrl -TimeoutSec 30
    if ($sitemap.StatusCode -ne 200) {
        throw "Unexpected sitemap status code for ${SitemapUrl}: $($sitemap.StatusCode)"
    }
    $inSitemap = $sitemap.Content -match [regex]::Escape($ExpectedCanonical)
    if (-not $inSitemap) {
        throw "Article URL missing from sitemap: $ExpectedCanonical"
    }
}

[pscustomobject]@{
    Url = $Url
    StatusCode = [int]$page.StatusCode
    Canonical = $canonicalMatch.Groups[1].Value
    HeadingContains = $HeadingContains
    RequireWatchlistIntent = [bool]$RequireWatchlistIntent
    InSitemap = [bool]$inSitemap
} | Format-List
