# Diğer Windows Cihaz Kurulum ve Devreye Alma Rehberi

Son güncelleme: 12 Ağustos 2026

Bu belge, `local-prod` paketini FLUX.2 Klein 9B Base ve ComfyUI kurulu olan diğer
Windows bilgisayara taşımak, izole test klasörlerinde doğrulamak ve yalnız açık bir
operatör kararıyla metal üretimine almak içindir.

## Kayıtlı durum

- [x] Kullanıcı hedef bilgisayarda ComfyUI ve FLUX.2 Klein 9B Base kurulumunu
  yaptığını bildirdi.
- [x] Yerel Comfy gateway, PDF raster servisi ve metal-only n8n workflow hazırlandı.
- [x] Yerel ve frozen rollback workflow exportları `active:false` olarak doğrulandı.
- [x] Gateway testleri 12/12, PDF testleri 7/7 ve workflow statik doğrulaması geçti.
- [x] r39 prod prompt, seed, ölçü ve master yönlendirme kodları korundu.
- [x] Mevcut prod workflow dosyasına dokunulmadı.
- [ ] Hedefteki Comfy sürümü, tam model adları/hashleri ve API erişimi bu çalışma
  alanından henüz doğrulanmadı.
- [ ] Paket hedef bilgisayarda henüz bu çalışma alanından doğrulanmadı.
- [ ] Hedef bilgisayarda Docker, firewall, gateway health ve gerçek inference testi yapılmadı.
- [ ] Google OAuth ve gerçek Drive klasörleri bağlanmadı.
- [ ] Dört fixture, reboot, hata ve üç ürün kuyruk testleri yapılmadı.
- [ ] Prod metal cutover yapılmadı; workflow aktive edilmedi.

`Start-LocalProd.ps1`, import işlemi ve asset manifesti temiz bir kurulumda workflow
aktive etmez. Prod tüketimini başlatan normal işlem, tüm kabul kapılarından sonra n8n
arayüzünde yerel workflow için bilinçli olarak `Activate` seçilmesidir. Buna karşılık
`Manual Trigger`, workflow inactive olsa bile gerçek Drive dosyasını işleyebilir.
Aktif workflow içeren eski veya restore edilmiş bir n8n volume'u başlatmak da schedule'ı
yeniden devreye sokabilir.

## Hedef topoloji

```text
Google Drive
    |
    v
n8n (Docker, yalnız 127.0.0.1:5678)
    |                       |
    v                       v
gateway (Docker)       pdf-raster (Docker)
    |
    v
ComfyUI + Klein 9B (native Windows, TCP 8188)
```

Gateway ve PDF servisi host/LAN portu yayınlamaz. Gateway, native ComfyUI'ye
`http://host.docker.internal:8188` üzerinden erişir. GPU ve n8n production
concurrency değeri `1` olarak kalır. Google Drive giriş/çıkış deposu olarak kullanılmaya
devam eder.

## 1. Ön koşullar

- Windows, güncel NVIDIA sürücüsü ve çalışır FLUX.2 Klein 9B Base kurulumu.
- ComfyUI en az `0.28.0`; bu graph için custom node gerekmez.
- Docker Desktop ve WSL2 engine. İlk image build için internet erişimi gerekir.
- Model, Docker volume, staging ve çıktıların büyümesine yetecek boş SSD alanı.
- Docker servisleri için yaklaşık 4 GB başlangıç bütçesi; gerçek kullanım ölçülüp
  engine overhead'i için gerekirse artırılırken Comfy offload RAM'i korunmalıdır.
- Firewall değişikliği ve daha sonra autostart kurulumu için yönetici PowerShell.
- Self-hosted n8n için ayrı bir Google OAuth client.
- İzole test için dört input, iki output ve iki Done olmak üzere sekiz Drive klasörü.

Uzun üretim sırasında Windows uyku/hibernation ve otomatik yeniden başlatma davranışını
kontrol edin. Hedef cihazın yeterliliği yalnız gerçek 1024 ve 2048 inference testleriyle
kabul edilir; kurulu modelin ComfyUI arayüzünde açılması tek başına yeterli değildir.

Resmî kaynaklar:

- [Docker Desktop Windows kurulumu](https://docs.docker.com/desktop/setup/install/windows-install/)
- [n8n Google OAuth2 kurulumu](https://docs.n8n.io/integrations/builtin/credentials/google/oauth-single-service/)
- [ComfyUI belgeleri](https://docs.comfy.org/)

## 2. Paketi hedef bilgisayara kopyalama

Tercihen tüm `Mockup Generator` klasörünü hedef bilgisayara kopyalayın. Örnek:

```text
C:\MockupGenerator
```

Yalnız runtime için `local-prod` yeterlidir. Ancak kaynak r39 workflow doğrulayıcısı ve
karşılaştırma araçları tüm repo yapısını beklediği için tam klasörü taşımak daha güvenlidir.

PowerShell'de paket köküne geçin:

```powershell
Set-Location 'C:\MockupGenerator\local-prod'
```

## 3. İzole Drive klasörlerini oluşturma

İlk kurulumda prod klasörlerini kullanmayın. Önerilen test klasörleri:

```text
TEST - Metal Baskısız Input
TEST - Metal Baskılı Input
TEST - Metal Revizyon Baskısız Input
TEST - Metal Revizyon Baskılı Input
TEST - Metal Output
TEST - Metal Done
TEST - Metal Revizyon Output
TEST - Metal Revizyon Done
```

Bir Drive klasör URL'sinde `folders/` sonrasındaki bölüm klasör ID'sidir:

```text
https://drive.google.com/drive/folders/KLASOR_ID
```

Dört input ID'si birbirinden farklı olmalı ve hiçbir input, output veya Done klasörüyle
aynı olmamalıdır. Workflow bu koşulu runtime sırasında ayrıca denetler.

## 4. `.env` ve secret'ları hazırlama

```powershell
Set-Location 'C:\MockupGenerator\local-prod'
Copy-Item .env.example .env
powershell -File .\scripts\New-Secrets.ps1
notepad .env
```

Üretilen iki değeri `.env` içindeki karşılıklarına elle yazın. Çıktıyı mesaja, workflow
JSON'una veya kaynak kontrolüne koymayın:

```text
N8N_ENCRYPTION_KEY=...
GATEWAY_ADMIN_TOKEN=...
```

Ardından sekiz test Drive ID'sini doldurun:

```text
DRIVE_METAL_UNPRINTED_INPUT_ID
DRIVE_METAL_PRINTED_INPUT_ID
DRIVE_METAL_REVISION_UNPRINTED_INPUT_ID
DRIVE_METAL_REVISION_PRINTED_INPUT_ID
DRIVE_METAL_OUTPUT_ID
DRIVE_METAL_DONE_ID
DRIVE_METAL_REVISION_OUTPUT_ID
DRIVE_METAL_REVISION_DONE_ID
```

`N8N_ENCRYPTION_KEY` kaybolursa n8n içinde saklanan OAuth credential'ları kurtarılamaz.
`.env` dosyasını erişimi sınırlı ve şifreli bir yerde ayrıca yedekleyin.

## 5. Comfy model dosyalarını doğrulama

Portable ComfyUI için beklenen dosyalar:

```text
C:\ComfyUI_windows_portable\ComfyUI\models\diffusion_models\flux-2-klein-base-9b-fp8.safetensors
C:\ComfyUI_windows_portable\ComfyUI\models\text_encoders\qwen_3_8b_fp8mixed.safetensors
C:\ComfyUI_windows_portable\ComfyUI\models\vae\full_encoder_small_decoder.safetensors
```

Dosya varlığını ve gerçek ağırlık dosyaları olduklarını kontrol edin:

```powershell
$ComfyRoot = 'C:\ComfyUI_windows_portable\ComfyUI'
Get-Item `
  "$ComfyRoot\models\diffusion_models\flux-2-klein-base-9b-fp8.safetensors", `
  "$ComfyRoot\models\text_encoders\qwen_3_8b_fp8mixed.safetensors", `
  "$ComfyRoot\models\vae\full_encoder_small_decoder.safetensors" |
  Select-Object FullName, Length
```

Birkaç yüz byte büyüklüğündeki dosya gerçek model değil, eksik bir Git-LFS pointer'ı
olabilir. Model adları `gateway\config\workflow_config.json` ile harfiyen eşleşmelidir.
`extra_model_paths` kullanılıyorsa Comfy'nin verdiği ad bir alt klasör öneki içerebilir;
bu durumda dosyayı körlemesine yeniden adlandırmayın. Comfy `/object_info` değerine göre
config'i düzeltin, asset manifestini yeniden üretin ve gateway'i yeniden build edin.

Bu paket, sabitlenmiş resmi 9B Base edit şablonundaki
`full_encoder_small_decoder.safetensors` VAE'sini kullanır. Farklı isimli bir VAE'nin
aynı dosya olduğu varsayılmamalıdır.

## 6. Asset manifestini oluşturma

Gerçek yolları kullanın:

```powershell
Set-Location 'C:\MockupGenerator\local-prod'
powershell -File .\scripts\New-AssetManifest.ps1 `
  -DiffusionModel "$ComfyRoot\models\diffusion_models\flux-2-klein-base-9b-fp8.safetensors" `
  -TextEncoder "$ComfyRoot\models\text_encoders\qwen_3_8b_fp8mixed.safetensors" `
  -Vae "$ComfyRoot\models\vae\full_encoder_small_decoder.safetensors"
```

Oluşan `asset-manifest.local.json`, üç model dosyasıyla gateway graph config'inin
SHA-256 değerlerini sabitler. Config veya model bilinçli değişirse manifest yeniden
üretilmelidir.

## 7. Comfy firewall kuralını önce oluşturma

Docker Desktop engine çalışırken, ComfyUI'yi henüz `0.0.0.0` üzerinde başlatmadan önce
yönetici PowerShell açın:

```powershell
Set-Location 'C:\MockupGenerator\local-prod'
powershell -File .\scripts\Configure-ComfyFirewall.ps1
```

Script Compose ağını/container nesnelerini oluşturabilir fakat servis veya workflow
başlatmaz. Ardından:

```powershell
Get-NetFirewallProfile | Select-Object Name, Enabled, DefaultInboundAction
Get-NetFirewallRule -DisplayName 'Mockup Generator - ComfyUI from Docker only' |
  Get-NetFirewallAddressFilter
```

Kabul koşulları:

- Windows profilinde varsayılan inbound davranışı `Block` olarak kalır.
- Yeni kuralın `RemoteAddress` değeri Compose subnet'idir.
- Eski ve geniş kapsamlı Python, ComfyUI veya TCP 8188 inbound allow kuralları kapalıdır.
- TCP 8188 `Any`, LAN veya internete açılmaz.

`docker compose down` named network'ü siler/değiştirirse firewall scriptini yeniden
çalıştırın. Docker/WSL NAT davranışı cihaza göre değişebildiği için ilerideki
container-to-host testi zorunludur; sorun olursa kuralı `Any` yapmayın.

## 8. Native ComfyUI'yi başlatma

Portable kurulum:

```powershell
Set-Location 'C:\ComfyUI_windows_portable'
.\python_embeded\python.exe -s .\ComfyUI\main.py `
  --windows-standalone-build `
  --listen 0.0.0.0 `
  --port 8188 `
  --lowvram `
  --preview-method none
```

Manuel/venv kurulumunun karşılığı:

```powershell
.\venv\Scripts\python.exe .\main.py `
  --listen 0.0.0.0 `
  --port 8188 `
  --lowvram `
  --preview-method none
```

Gateway şu an Comfy auth header göndermediği için `--api-key` eklemeyin. Comfy'yi LAN
veya internete açmayın; custom node kurmayın.

Host kontrolleri:

```powershell
$Stats = Invoke-RestMethod http://127.0.0.1:8188/system_stats -TimeoutSec 10
$Stats.system.comfyui_version
$Stats.devices | Format-List name, type, vram_total

$ObjectInfo = Invoke-RestMethod http://127.0.0.1:8188/object_info -TimeoutSec 30
$ObjectInfo.UNETLoader.input.required.unet_name[0]
$ObjectInfo.CLIPLoader.input.required.clip_name[0]
$ObjectInfo.VAELoader.input.required.vae_name[0]
```

Comfy sürümü en az `0.28.0` olmalı ve config'teki üç model adı listelerde bulunmalıdır.

## 9. Preflight ve yerel servisleri başlatma

```powershell
Set-Location 'C:\MockupGenerator\local-prod'
powershell -File .\scripts\Preflight.ps1
powershell -File .\scripts\Start-LocalProd.ps1
```

Preflight şunları kontrol eder: Docker engine, `.env`, secret uzunlukları, sekiz ID'nin
dolu olması, asset hashleri, host Comfy API/sürümü ve Compose config. Drive klasör
izinlerini, Google OAuth'u, tüm Comfy node/model listesini veya gerçek inference'ı
kontrol etmez.

Servis durumu ve loglar:

```powershell
docker compose ps
docker compose logs --tail 200 gateway n8n pdf-raster
```

Docker container'ından Windows Comfy'ye erişim:

```powershell
docker compose exec -T gateway python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:8188/system_stats',timeout=10).status)"
```

Beklenen değer `200` olmalıdır.

Gateway health kontrolü host portundan değil, container içinden yapılır:

```powershell
docker compose exec -T gateway python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8787/healthz',timeout=15).read().decode())"
```

Devam etmek için HTTP 200 ve şu durumlar gereklidir:

```text
healthy: true
comfy_reachable: true
missing_node_types: []
missing_models: []
circuit.open: false
```

Gateway sağlıksızken n8n'in başlamaması bilinçli bir güvenlik kapısıdır.

## 10. Workflow olmadan gerçek 1024 inference smoke testi

Bu test n8n veya Drive'a dokunmaz. Gerçek bir metal master PNG seçin:

```powershell
Set-Location 'C:\MockupGenerator\local-prod'
$Reference = 'C:\TestAssets\real-metal-master.png'
docker compose cp $Reference gateway:/tmp/smoke-input.png

@'
import base64, json, re, struct, urllib.request

api = 'http://127.0.0.1:8787/fal-ai/flux-2/klein/9b/base/edit'
with open('/tmp/smoke-input.png', 'rb') as handle:
    image = 'data:image/png;base64,' + base64.b64encode(handle.read()).decode('ascii')

body = {
    'prompt': 'Create a photorealistic neutral-daylight product photograph. Preserve the exact product geometry and every opening.',
    'negative_prompt': 'changed geometry, filled openings, visible mounting hardware, warm orange wall, generic AI decor',
    'image_urls': [image],
    'image_size': {'width': 1024, 'height': 1024},
    'seed': 40040040,
    'guidance_scale': 5,
    'num_inference_steps': 28,
    'output_format': 'png',
    'sync_mode': False,
    'num_images': 1,
    'enable_prompt_expansion': False,
}
encoded = json.dumps(body).encode()

def post():
    request = urllib.request.Request(
        api,
        data=encoded,
        method='POST',
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(request, timeout=7500) as response:
        return json.load(response)

first = post()
second = post()
assert re.fullmatch(r'[0-9a-f]{64}', first['job_id'])
assert second['job_id'] == first['job_id']

with urllib.request.urlopen(first['images'][0]['url'], timeout=60) as response:
    png = response.read()
assert png[:8] == b'\x89PNG\r\n\x1a\n'
assert struct.unpack('>II', png[16:24]) == (1024, 1024)

with open('/tmp/smoke-output.png', 'wb') as handle:
    handle.write(png)
print(json.dumps({'job_id': first['job_id'], 'bytes': len(png), 'dimensions': [1024, 1024]}))
'@ | docker compose exec -T gateway python -

docker compose cp gateway:/tmp/smoke-output.png .\smoke-output.png
```

Kabul koşulları:

- OOM veya terminal Comfy hatası olmadan gerçek 1024×1024 PNG oluşur.
- Aynı istek ikinci kez aynı 64 karakterli `job_id` değerini döndürür.
- Comfy ikinci GPU render'ı kuyruğa almaz; sonuç gateway cache/spool'dan gelir.
- Görselde ürün silüeti, tüm açıklıklar ve oran korunur.
- Toz boya dokusu görünür; siyah yüzey gri/gümüşe dönmez.
- Uygun sahnede güçlü doğal gün ışığı vardır.
- Duvar/background aşırı sıcak değildir.
- Beyaz vazo benzeri jenerik AI dekorları ve görünür montaj donanımı yoktur.
- Görünüm fotogerçekçidir.

Metal cutover öncesinde gerçek 1248×832 sahne ve fixture üzerinden M13 2048×2048 de
geçmelidir. Başarısızlıkta seed, step veya çözünürlük sessizce düşürülmez; kurulum/hardware
blocker'ı olarak kaydedilir.

## 11. n8n owner hesabı ve Google OAuth

Tarayıcıdan yalnız yerel adresi açın:

```text
http://127.0.0.1:5678
```

Owner hesabını oluşturun. Self-hosted n8n Managed OAuth kullanmaz; Google Cloud'da
custom OAuth client gerekir:

1. Ayrı bir Google Cloud projesi oluşturun.
2. Google Drive API'yi etkinleştirin.
3. OAuth consent screen'i yapılandırın.
4. `Web application` tipinde OAuth client oluşturun.
5. n8n credential ekranının gösterdiği redirect URI'yi Google'a harfiyen ekleyin.
   Yerel kurulumda normal değer:

   ```text
   http://localhost:5678/rest/oauth2-credential/callback
   ```

6. Client ID ve Client Secret'ı n8n'e girin.
7. `Sign in with Google` ile üretimde kullanılacak Drive hesabını yetkilendirin.
8. Credential'ı örneğin `LOCAL PROD Google Drive` adıyla kaydedin.

External consent screen `Testing` durumundaysa Google refresh token'ı Drive kapsamları
için genellikle yedi gün sonra sona erer. Uzun süreli kullanım öncesinde Workspace için
uygunsa `Internal` seçin veya gerekli production/verification sürecini tamamlayın.

## 12. Yerel workflow'u inactive olarak import etme

n8n'de şu dosyayı import edin:

```text
workflow\metal-local-prod.json
```

Import sonrasında:

1. Workflow'un `Inactive` olduğunu UI'dan yeniden doğrulayın.
2. `LOCAL PROD Google Drive` placeholder'ı kullanan 14 Drive node'unun tamamını az önce
   oluşturulan tek Google Drive credential'a eşleyin.
3. Workflow'u kaydedin fakat `Activate` seçmeyin.
4. `Map_Categories` node'undaki dört kategori ve `$env` ifadelerini inceleyin.
5. Test `.env` değerlerinin sekiz izole test klasörüne ait olduğunu yeniden doğrulayın.

Import ve credential eşleme prod schedule'ını başlatmaz.

## 13. Dört zorunlu fixture testi

Her fixture'ı tek başına ilgili test input klasörüne bırakın ve inactive workflow'da
`Manual Trigger` çalıştırın. Manual Trigger gerçek Drive dosyası üzerinde işlem yapar.

| Fixture | Beklenen final | Beklenen inference | Özel kontrol |
|---|---:|---:|---|
| Normal baskısız PDF | M01–M18, 18 PNG | 20 | Standard master fill `.60`, high-fill `.86`, M13 2048×2048 |
| Normal baskılı PDF | M01–M15, 15 PNG | 15 | Master yok, PDF fill `.86` |
| Revizyon baskısız raster | M01/M02/M15, 3 PNG | 5 | İki master + üç sahne |
| Revizyon baskılı raster | M01/M02/M15, 3 PNG | 3 | Master yok |

Her fixture için doğrulayın:

- n8n execution `success` olur ve gateway/Comfy logunda parametre düşümü yoktur.
- Beklenen dosya adları tam ve tekildir; eksik veya duplicate PNG yoktur.
- PNG'ler açılır ve beklenen ölçülerdedir.
- `_LOCAL_STAGING__<source-id>` klasörü yalnız işlem sırasında kullanılır ve başarıda
  kaynak basename'ini taşıyan final klasöre dönüşür.
- Kaynak, final manifest tamamlanıp commit edildikten sonra doğru Done klasörüne taşınır.
- Ürün geometrisi/openwork, derin siyah yüzey, toz boya, nötr gün ışığı ve fotogerçekçilik
  insan gözüyle kontrol edilir.
- M01, M02, M13 ve makro sahneler özellikle incelenir.

## 14. Hata, yeniden başlatma ve kapasite kabul kapıları

İzole test klasörlerinde ayrıca şunlar geçmelidir:

- Aynı kaynağın yeniden denenmesinde tamamlanmış sahneler yeniden render edilmez.
- Comfy kapalıyken/terminal hata verdiğinde kaynak Done'a taşınmaz ve eksik final commit
  edilmez.
- Temel hata giderildikten sonra Comfy `/queue` ve `/history` kontrol edilmeden failed job
  veya circuit resetlenmez. Gerekirse sırayla:

  ```powershell
  powershell -File .\scripts\Reset-GatewayJob.ps1 -JobId <64-karakter-job-id>
  powershell -File .\scripts\Reset-GatewayCircuit.ps1
  ```

- Docker/n8n restart sonrasında staging'den güvenli devam edilir.
- Tam Windows reboot sonrasında Comfy, gateway, n8n ve Google OAuth yeniden sağlıklı olur.
- Arka arkaya en az üç farklı ürün GPU concurrency `1` ile sıra bozulmadan tamamlanır.
- Gerçek M13 2048×2048 OOM olmadan tamamlanır.
- Beş normal baskısız ürünlük süre ölçümü toplam en fazla 20 saat hedefini karşılar.
- Temsilî çıktılar r39/FAL referanslarıyla yan yana görsel QA'dan geçer.

Autostart'ın başarılı görünmesi reboot testinin yerine geçmez. Docker, native Comfy hazır
olmadan container'ları başlatırsa gateway circuit açabilir; schedule aktif edilmeden önce
gerçek açılış sırası gözlenmelidir.

## 15. Test ID'lerinden prod ID'lerine geçiş

Dört fixture ve kabul testleri geçtikten sonra workflow hâlâ inactive iken `.env` içindeki
test ID'lerini şu gerçek hedeflerle değiştirin:

- Dört yeni ve birbirinden ayrık prod metal input klasörü.
- Mevcut normal/revizyon output ve Done klasörleri.

n8n container environment'ının değişmesi için restart yerine recreate edin:

```powershell
Set-Location 'C:\MockupGenerator\local-prod'
powershell -File .\scripts\Preflight.ps1
docker compose up -d --force-recreate n8n
docker compose ps
```

Workflow inactive kalmalıdır. Dört yeni prod input boşken Manual Trigger ile salt boş
klasör smoke'u yapın; hiçbir dosya üretmemeli veya taşımamalıdır.

## 16. Cutover öncesi yedek ve ayrı rollback ortamı

Credential oluşturulduktan ve testler geçtikten sonra volume yedeği alın:

```powershell
powershell -File .\scripts\Backup-LocalProd.ps1
```

Ayrıca `.env`, `asset-manifest.local.json`, gateway config'i ve iki workflow export'unu
şifreli ve erişimi sınırlı bir yerde saklayın.

Frozen rollback workflow'u şu dosyadır:

```text
workflow\metal-cloud-rollback-frozen.json
```

Rollback kopyası, yerel Docker/n8n kapalıyken de çalışabilmesi için **ayrı/harici ve
environment erişimi yönetilebilen bir n8n ortamına** cutover'dan önce import edilip
`active:false` tutulmalıdır. Bu harici ortamda:

- Aynı sekiz `DRIVE_*` environment değeri bulunur.
- Code node environment erişimi açıktır.
- 14 Drive node'u çalışan Google Drive credential'a eşlenir.
- Üç FAL node'u `FROZEN ROLLBACK FAL` credential'ına eşlenir.
- İki PDF node'u `FROZEN ROLLBACK PDF Raster` credential'ına eşlenir.
- Health ve credential kontrolleri geçer; workflow inactive kalır.

Bu ayrı rollback ortamı hazır değilse prod cutover yapılmaz. Aynı Drive input setini
tüketen yerel ve cloud workflow hiçbir zaman aynı anda aktif olamaz.

## 17. Prod cutover — ayrı ve son manuel kapı

Bu bölüme ancak önceki bütün checkbox ve kabul kapıları tamamlandıktan sonra geçilir:

1. Eski cloud metal girişlerine yeni dosya bırakmayı durdurun.
2. Eski metal execution'larının tamamen bittiğini ve eski inputların drain olduğunu
   doğrulayın. Cloud ana workflow diğer kategoriler için çalışmaya devam edebilir.
3. Yerel preflight ve gateway health'i yeniden kontrol edin.
4. Dört fixture, 2048, reboot, hata, üç ürün kuyruk, süre ve insan görsel QA sonuçlarını
   kaydedin.
5. Harici frozen rollback workflow'unun hazır ve inactive olduğunu doğrulayın.
6. n8n UI'da yalnız `metal-local-prod` workflow'unu `Activate` edin.
7. Dört yeni inputtan yalnız birine tek gerçek ürün koyun.
8. İlk ürünün staging → final → Done zincirini ve görüntülerini insan gözetiminde
   tamamlayın.

Bu adım kullanıcı/operatör açıkça karar vermeden uygulanmaz.

## 18. Manuel rollback

1. Yerel metal workflow'u önce `Deactivate` edin ve yeni input kabulünü durdurun.
2. Çalışan n8n execution, gateway job ve Comfy kuyruğunu bitirin veya güvenli şekilde
   durdurun.
   Kuyruk tamamen boşaldıktan sonra yerel stack'in yeni iş kabulünü kapatmak için:

   ```powershell
   docker compose stop n8n gateway
   ```

3. Kısmi `_LOCAL_STAGING__...` klasörünü silmeyin; output root dışında karantinaya alın.
   Kaynak inputta kalmalıdır.
4. Harici rollback n8n'in health, sekiz env ve credential durumunu doğrulayın.
5. Frozen cloud rollback workflow'unu ancak yerel tüketici tamamen kapandıktan sonra
   aktive edin.
6. İlk cloud ürününü de insan gözetiminde tamamlayın.

Otomatik FAL fallback yoktur. Yerel ve cloud metal tüketicisini eşzamanlı açmayın.

## 19. Autostart ve normal operasyon

Tüm kurulum/testler tamamlandıktan sonra ComfyUI'nin aynı güvenli argümanlarla kullanıcı
oturumunda otomatik başladığını doğrulayın. Ardından yönetici PowerShell'de Compose için:

```powershell
powershell -File .\scripts\Install-AutoStartTask.ps1
```

Bu görev oturum açıldıktan yaklaşık bir dakika sonra Compose stack'ini başlatır; Comfy
hazırlığını kesin bir boot bariyeriyle garanti etmez. Bu nedenle autostart sonrası gerçek
reboot testi zorunludur.

Günlük kontroller:

```powershell
docker compose ps
docker compose logs --tail 200 gateway n8n pdf-raster
Invoke-RestMethod http://127.0.0.1:8188/system_stats
```

Güvenli durdurma:

```powershell
powershell -File .\scripts\Stop-LocalProd.ps1
```

Credential ve gateway durumunu sileceği için şunu kullanmayın:

```text
docker compose down --volumes
```

## Kurulum kabul kaydı

Hedef cihazda çalışırken aşağıdaki alanları doldurun:

```text
Kurulum tarihi:
Operatör:
Bilgisayar/GPU:
NVIDIA driver:
ComfyUI sürümü/commit:
Diffusion model SHA-256:
Text encoder SHA-256:
VAE SHA-256:
Gateway config SHA-256:
Docker Desktop sürümü:
n8n sürümü: 2.34.5
1024 smoke job_id/sonuç:
1248×832 smoke job_id/sonuç:
M13 2048×2048 sonuç/süre/peak VRAM:
Dört fixture sonucu:
Reboot testi:
Üç ürün kuyruk testi:
Beş ürün toplam süresi:
Görsel QA kararı:
Backup arşivleri:
Harici rollback hazır mı:
Prod workflow active mı: HAYIR (cutover'a kadar)
Notlar:
```
