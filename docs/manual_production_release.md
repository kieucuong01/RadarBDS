# Commit, Push, Deploy Production Thu Cong

Chay cac lenh ben duoi trong PowerShell tai thu muc goc cua Radar BDS.

## 1. Mo dung thu muc va kiem tra nhanh

```powershell
Set-Location "C:\Users\ASUS\Documents\Claude\Projects\Radar BDS"
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"

git branch --show-current
git status --short
git diff --check
```

Nhanh phat hanh production phai la `main`. Doc danh sach file va dam bao khong
co `.env`, database dump, image, log, report hoac file runtime bi dua vao Git.

## 2. Chay kiem tra truoc khi commit

```powershell
& $py -X utf8 -m py_compile app.py services\market_data.py services\image_assets.py
node --check static\js\main.js
node --check static\js\auth.js
node --check static\js\main\auth_cta.js
& $py -X utf8 -m pytest tests
```

Chi tiep tuc khi tat ca lenh tra ve exit code `0`.

## 3. Commit toan bo thay doi hien tai

```powershell
git status --short
git add -A
git diff --cached --stat
git diff --cached --check
git commit -m "Mo ta ngan gon thay doi"
```

`git add -A` se dua tat ca file chua ignore vao commit. Neu thay file ngoai pham
vi mong muon trong `git diff --cached --stat`, bo stage file do:

```powershell
git restore --staged "duong-dan-file"
```

## 4. Push len GitHub

```powershell
git push origin main
git status --short --branch
```

Ket qua mong doi: nhanh local khong con thay doi va khong lech `origin/main`.

## 5. Deploy production

```powershell
.\scripts\deploy_production.ps1
```

Script se dung SSH key tai
`$env:USERPROFILE\.ssh\radar_bds_deploy_rsa`, fast-forward code tren VPS,
restart `radar-bds.service`, kiem tra API va prewarm cache.

Khong chay `reprocess --full` cho thay doi UI, CSS, JavaScript hoac template.
Chi reprocess khi da thay doi parser, dedup, valuation, schema hoac quality gate.

## 6. Kiem tra website production

```powershell
$urls = @(
    "https://radarbds.vn/",
    "https://radarbds.vn/robots.txt",
    "https://radarbds.vn/sitemap.xml",
    "https://radarbds.vn/api/dashboard",
    "https://radarbds.vn/api/signals?page=1&limit=3"
)

foreach ($url in $urls) {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 30
    "{0} {1}" -f $response.StatusCode, $url
}
```

Tat ca URL phai tra ve HTTP `200`. Voi thay doi UI, mo trang bang cua so an danh
hoac hard refresh bang `Ctrl+F5` de tranh cache cu.

## Quy trinh rut gon hang ngay

Sau khi da tu xem lai danh sach file:

```powershell
Set-Location "C:\Users\ASUS\Documents\Claude\Projects\Radar BDS"
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"

git status --short
git diff --check
& $py -X utf8 -m pytest tests
git add -A
git diff --cached --stat
git commit -m "Mo ta ngan gon thay doi"
git push origin main
.\scripts\deploy_production.ps1
```

Neu test, commit, push hoac deploy bao loi thi dung tai buoc do; khong bo qua loi
de tiep tuc sang production.
