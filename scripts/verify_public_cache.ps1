param(
    [string] $BaseUrl = "https://radarbds.vn",
    [string] $ExpectedDatasetVersion = "",
    [switch] $RequireCdn = $false
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$BaseUrl = $BaseUrl.TrimEnd("/")
$ProbePaths = @(
    "/",
    "/api/signals?page=1&limit=20",
    "/api/listings?date_range=3m&sort_by=date&sort_dir=desc&page=1&limit=50",
    "/api/counts",
    "/api/dashboard"
)
$SensitiveKeys = @(
    "phone",
    "phone_number",
    "source_url",
    "original_url",
    "contact_phone"
)
$CookieValue = "cache-bypass-probe-$([guid]::NewGuid().ToString('N'))"
$CookieHeaderContract = "radar_session=cache-bypass-probe"
$AuthorizationValue = "Bearer cache-bypass-probe"
$CdnPublicStatuses = @("HIT", "MISS", "EXPIRED", "STALE", "UPDATING", "REVALIDATED")
$CdnHotStatuses = @("HIT", "STALE", "UPDATING", "REVALIDATED")
$OriginPublicStatuses = @("HIT", "MISS", "STALE", "UPDATING")

function Get-HeaderValue {
    param($Response, [string] $Name)
    $value = $Response.Headers[$Name]
    if ($null -eq $value) { return "" }
    if ($value -is [System.Array]) { return ($value -join ", ") }
    return [string] $value
}

function Invoke-CacheRequest {
    param(
        [string] $Url,
        [hashtable] $Headers = @{},
        $WebSession = $null
    )
    $params = @{
        Uri = $Url
        Method = "GET"
        UseBasicParsing = $true
        Headers = $Headers
        TimeoutSec = 30
    }
    if ($null -ne $WebSession) { $params.WebSession = $WebSession }
    $response = Invoke-WebRequest @params
    if ([int] $response.StatusCode -ne 200) {
        throw "Expected 200 from $Url, got $($response.StatusCode)"
    }
    return $response
}

function Assert-NoSensitiveJson {
    param($Value, [string] $Path = "$")
    if ($null -eq $Value) { return }

    if ($Value -is [System.Collections.IDictionary]) {
        foreach ($key in $Value.Keys) {
            $name = [string] $key
            $child = $Value[$key]
            if ($SensitiveKeys -contains $name.ToLowerInvariant()) {
                if ($null -ne $child -and -not [string]::IsNullOrWhiteSpace([string] $child)) {
                    throw "Sensitive JSON field is non-null at $Path.$name"
                }
            }
            Assert-NoSensitiveJson -Value $child -Path "$Path.$name"
        }
        return
    }

    if ($Value -is [pscustomobject]) {
        foreach ($property in $Value.PSObject.Properties) {
            $name = [string] $property.Name
            $child = $property.Value
            if ($SensitiveKeys -contains $name.ToLowerInvariant()) {
                if ($null -ne $child -and -not [string]::IsNullOrWhiteSpace([string] $child)) {
                    throw "Sensitive JSON field is non-null at $Path.$name"
                }
            }
            Assert-NoSensitiveJson -Value $child -Path "$Path.$name"
        }
        return
    }

    if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
        $index = 0
        foreach ($item in $Value) {
            Assert-NoSensitiveJson -Value $item -Path "$Path[$index]"
            $index++
        }
    }
}

function Assert-PrivateBypass {
    param([string] $Url, [string] $Kind)
    $headers = @{}
    $session = $null
    if ($Kind -eq "cookie") {
        $session = [Microsoft.PowerShell.Commands.WebRequestSession]::new()
        $uri = [uri] $Url
        $cookie = [System.Net.Cookie]::new("radar_session", $CookieValue, "/", $uri.Host)
        $session.Cookies.Add($cookie)
    } elseif ($Kind -eq "authorization") {
        $headers.Authorization = $AuthorizationValue
    } else {
        throw "Unknown bypass kind: $Kind"
    }

    $response = Invoke-CacheRequest -Url $Url -Headers $headers -WebSession $session
    $edge = (Get-HeaderValue $response "X-Radar-Edge-Cache").ToUpperInvariant()
    if ($edge -eq "HIT") { throw "$Kind request unexpectedly reported edge HIT for $Url" }
    if ($edge -and $edge -ne "BYPASS") {
        throw "$Kind request has unexpected edge cache status '$edge' for $Url"
    }
    $cacheControl = Get-HeaderValue $response "Cache-Control"
    if ($cacheControl -notmatch "(?i)private" -or $cacheControl -notmatch "(?i)no-store") {
        throw "$Kind request is missing private, no-store for $Url"
    }
    if ($RequireCdn) {
        if (-not (Get-HeaderValue $response "CF-Ray")) {
            throw "$Kind request is missing CF-Ray for $Url"
        }
        $cdn = (Get-HeaderValue $response "CF-Cache-Status").ToUpperInvariant()
        if (@("BYPASS", "DYNAMIC") -notcontains $cdn) {
            throw "$Kind request has unsafe Cloudflare cache status '$cdn' for $Url"
        }
    }
}

$results = @()
foreach ($path in $ProbePaths) {
    $url = "$BaseUrl$path"
    $guest = Invoke-CacheRequest -Url $url
    if (Get-HeaderValue $guest "Set-Cookie") {
        throw "Guest response contains Set-Cookie for $url"
    }
    if (Get-HeaderValue $guest "X-Radar-Public-Cache") {
        throw "Internal X-Radar-Public-Cache leaked through Nginx for $url"
    }
    $cacheControl = Get-HeaderValue $guest "Cache-Control"
    if ($cacheControl -notmatch "(?i)public" -or $cacheControl -notmatch "(?i)max-age=15") {
        throw "Guest response is missing the public 15-second policy for $url"
    }
    if ($RequireCdn) {
        if (-not (Get-HeaderValue $guest "CF-Ray")) {
            throw "Guest response is missing CF-Ray for $url"
        }
        $guestCdn = (Get-HeaderValue $guest "CF-Cache-Status").ToUpperInvariant()
        if ($CdnPublicStatuses -notcontains $guestCdn) {
            throw "Guest response has unsafe Cloudflare cache status '$guestCdn' for $url"
        }
    }

    $hit = $null
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        $candidate = Invoke-CacheRequest -Url $url
        $edge = (Get-HeaderValue $candidate "X-Radar-Edge-Cache").ToUpperInvariant()
        $cdn = (Get-HeaderValue $candidate "CF-Cache-Status").ToUpperInvariant()
        $originPublic = $OriginPublicStatuses -contains $edge
        $cdnHot = $CdnHotStatuses -contains $cdn
        if ((-not $RequireCdn -and $edge -eq "HIT") -or
            ($RequireCdn -and $originPublic -and $cdnHot)) {
            $hit = $candidate
            break
        }
        Start-Sleep -Seconds 2
    }
    if ($null -eq $hit) {
        if ($RequireCdn) { throw "Cloudflare HIT was not observed for $url" }
        throw "Cache HIT was not observed for $url"
    }

    if ($path.StartsWith("/api/")) {
        $json = $hit.Content | ConvertFrom-Json
        Assert-NoSensitiveJson -Value $json
    }

    Assert-PrivateBypass -Url $url -Kind "cookie"
    Assert-PrivateBypass -Url $url -Kind "authorization"
    $hitEdge = Get-HeaderValue $hit "X-Radar-Edge-Cache"
    $hitCdn = Get-HeaderValue $hit "CF-Cache-Status"
    $results += [pscustomobject]@{
        Path = $path
        Guest = if ($RequireCdn) { "CF:$hitCdn/Radar:$hitEdge" } else { $hitEdge }
        Cookie = "BYPASS"
        Authorization = "BYPASS"
        Version = (Get-HeaderValue $hit "X-Radar-Dataset-Version")
    }
}

if ($ExpectedDatasetVersion) {
    $fresh = $false
    $freshUrl = "$BaseUrl/api/signals?page=1&limit=1"
    for ($attempt = 1; $attempt -le 12; $attempt++) {
        $response = Invoke-CacheRequest -Url $freshUrl
        $actual = Get-HeaderValue $response "X-Radar-Dataset-Version"
        if ($actual -eq $ExpectedDatasetVersion) {
            $fresh = $true
            break
        }
        Start-Sleep -Seconds 5
    }
    if (-not $fresh) {
        throw "Dataset version $ExpectedDatasetVersion was not public within 60 seconds"
    }
}

$null = $CookieHeaderContract
$results | Format-Table -AutoSize
Write-Host "public_cache_verification=passed"
