# Local FLUX.2 Klein Gateway

Bu servis, mevcut n8n FAL çağrılarının dış sözleşmesini koruyup inference'ı yerel
ComfyUI'de çalıştırır. Yalnız Docker Compose iç ağında kullanılmak üzere tasarlanmıştır;
edit endpoint'inde ayrıca HTTP kimlik doğrulaması yoktur ve host/LAN portu olarak
publish edilmemelidir.

## Davranış

- `POST /fal-ai/flux-2/klein/9b/base/edit`, mevcut FAL gövdesini kabul eder.
- Bir ila dört sıralı PNG/JPEG/WebP `data:`, `http:` veya `https:` referansı desteklenir.
- Boyutların her ekseni 512–2048 arasında ve 16'nın katı olmak zorundadır.
- `seed` zorunludur; gönderilmeyen `guidance_scale` ve `num_inference_steps` değerleri
  açıkça `5` ve `28` olur. Parametre düşürme veya seed değiştirme yapılmaz.
- `sync_mode=true` bir PNG data URI; `false` ise
  `http://gateway:8787/files/<job-id>.png` döndürür.
- İndirilen gerçek referans byte'ları, sıraları, prompt, ölçüler, sampler parametreleri
  ve workflow config hash'i iş kimliğine katılır. Aynı iş tekrar render edilmez.
- SQLite kuyruğu ve PNG spool'u restart boyunca kalır. GPU kuyruğu tek worker/tek iştir.
  Uvicorn worker sayısı `1` kalmalı ve gateway servisi yatay ölçeklenmemelidir.
- Comfy terminal hatası iş kaydını `failed` yapar ve kalıcı circuit-breaker'ı açar.
  Validation veya bozuk/erişilemeyen kaynak URL hataları circuit açmaz.
- Başarılı spool dosyaları varsayılan yedi gün korunur. Süresi dolan deterministik iş
  otomatik yeniden render edilmez; yeni bir seed/ayar yeni bir iş oluşturur.

Yanıtın n8n için gereken çekirdek kısmı:

```json
{
  "images": [
    {
      "url": "http://gateway:8787/files/<job-id>.png",
      "width": 1024,
      "height": 1024,
      "content_type": "image/png"
    }
  ],
  "seed": 40040040,
  "job_id": "<64 lowercase hex>"
}
```

## Canonical Comfy graph sözleşmesi

[`config/workflow_config.json`](config/workflow_config.json), graph'ın tek düzenlenebilir
kontratıdır. Model dosya adlarını kurulu ComfyUI ile birebir eşleştirin. Gateway bu
kontrattan yalnız core node'ları kullanan deterministik API graph'ı kurar:

1. `UNETLoader`, `CLIPLoader (flux2)` ve `VAELoader` modelleri yükler.
2. Positive/negative `CLIPTextEncode` conditioning üretir.
3. Her referans `LoadImage → ImageScaleToTotalPixels (Lanczos, 1 MP) → VAEEncode`
   zincirinden geçer; aynı latent, aynı sırada positive ve negative `ReferenceLatent`
   zincirlerine eklenir.
4. İstek ölçüleri hem `Flux2Scheduler` hem `EmptyFlux2LatentImage` node'una yazılır.
5. `RandomNoise → CFGGuider → Euler/Flux2Scheduler → SamplerCustomAdvanced →
   VAEDecode → SaveImage` resmi Klein Base edit bağlantısını izler.

Kontrat dışından graph veya `class_type` kabul edilmez. Kaynak şablon Comfy'nin
[resmi Klein 9B Base edit workflow'udur](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_flux2_klein_image_edit_9b_base.json).

## Çalıştırma

Normal kullanım üst dizindeki Docker Compose dosyasıyladır. Tek başına geliştirme:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
$env:COMFY_URL = 'http://127.0.0.1:8188'
$env:STATE_DIR = "$PWD\data"
$env:SPOOL_DIR = "$PWD\data\spool"
$env:WORKFLOW_CONFIG_PATH = "$PWD\config\workflow_config.json"
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:8787'
.\.venv\Scripts\python -m uvicorn app.main:create_app --factory --port 8787
```

Temel ortam değişkenleri:

| Değişken | Varsayılan | Amaç |
|---|---|---|
| `COMFY_URL` | `http://host.docker.internal:8188` | Native Windows Comfy API |
| `STATE_DIR` | `/data` | SQLite/veri kökü |
| `SPOOL_DIR` | `/data/spool` | Kalıcı PNG çıktıları |
| `WORKFLOW_CONFIG_PATH` | `/app/config/workflow_config.json` | Sabit graph kontratı |
| `PUBLIC_BASE_URL` | `http://gateway:8787` | n8n'in erişeceği dosya URL kökü |
| `COMFY_TIMEOUT_SECONDS` | `7200` | Bir render için kesin üst süre |
| `INPUT_MAX_BYTES` | `33554432` | Referans başına byte sınırı |
| `SPOOL_RETENTION_DAYS` | `7` | Başarılı PNG saklama süresi |
| `GATEWAY_ADMIN_TOKEN` | boş | Circuit reset için zorunlu secret |

`GET /healthz`; Comfy bağlantısını, minimum `0.28.0` sürümünü, core node'ları,
kurulu model adlarını ve circuit durumunu kontrol eder. Bunlardan biri uygun değilse
HTTP 503 döner. Circuit'in nedeni giderildikten sonra yalnız iç ağdan:

```powershell
Invoke-WebRequest -Method Post `
  -Uri http://gateway:8787/admin/circuit/reset `
  -Headers @{ 'X-Gateway-Admin-Token' = '<secret>' }
```

Circuit reset, başarısız deterministik işi kendiliğinden yeniden kuyruğa almaz. Yeniden
render bilinçli bir operatör işlemi olmalıdır: önce Comfy `/queue` ve `/history` içinde
aynı `gateway_job_id` ile çalışan veya tamamlanmış prompt bulunmadığını doğrulayın.
Aksi halde duplicate GPU render oluşabilir. Doğrulamadan sonra iş kaydını ve circuit'i
ayrı ayrı sıfırlayın:

```powershell
$headers = @{ 'X-Gateway-Admin-Token' = '<secret>' }
Invoke-WebRequest -Method Post `
  -Uri http://gateway:8787/admin/jobs/<job-id>/reset -Headers $headers
Invoke-WebRequest -Method Post `
  -Uri http://gateway:8787/admin/circuit/reset -Headers $headers
```

## Test

Testler gerçek inference yapmaz; sahte Comfy HTTP transport'u kullanır:

```powershell
python -m pytest
```
