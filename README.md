# Yerel Prod Paketi

Bu dizin, Mockup Generator'ın AI inference ve orkestrasyon katmanını yerelde
çalıştırır. Google Drive giriş/çıkış deposu olarak kalır. Paket kendi başına hiçbir
workflow'u içe aktarmaz veya aktive etmez; mevcut prod workflow'una dokunmaz.

Başka bir Windows bilgisayarda güvenli kurulum, test ve cutover için ayrıntılı ve
otoritatif sıra: [`DIGER-CIHAZ-KURULUM.md`](DIGER-CIHAZ-KURULUM.md). Özellikle ComfyUI'yi
`0.0.0.0` üzerinde başlatmadan **önce** firewall adımını tamamlayın.

## Bileşenler

- **ComfyUI:** Windows üzerinde native; FLUX.2 Klein 9B Base inference.
- **n8n 2.34.5:** Docker içinde, yalnız `127.0.0.1:5678` üzerinden erişilir.
- **gateway:** n8n'in mevcut FAL uyumlu isteklerini Comfy API graph'ına çevirir.
- **pdf-raster:** Ham PDF'yi ilk sayfadan PNG'ye dönüştürür; yalnız Compose ağına açıktır.

Gateway ve PDF servisi için host portu yoktur. n8n bunlara sırasıyla
`http://gateway:8787` ve `http://pdf-raster:8080` üzerinden ulaşır. Gateway Windows
ComfyUI'ye `http://host.docker.internal:8188` ile erişir.

## İlk kurulum

1. Docker Desktop'ın WSL2 engine ile çalıştığını doğrulayın. Compose servisleri
   toplamda 3.75 GB ile sınırlandırılmıştır; Docker Desktop'a yaklaşık 4 GB ayırın ve
   32 GB sistem RAM'inin kalanı Comfy offload'a kalsın.
2. ComfyUI'yi güvenlik düzeltmelerini içeren en az `0.28.0` sürümüne güncelleyin.
3. ComfyUI başlatma komutunu hazırlayın fakat henüz çalıştırmayın. Servis daha sonra
   Docker gateway tarafından erişilebilir olmalı; önce 7. adımdaki Windows Firewall
   kuralını tamamlayın. Firewall sonrasında kullanılacak örnek:

   ```powershell
   python main.py --listen 0.0.0.0 --port 8188 --lowvram
   ```

   `0.0.0.0` yalnız Docker erişimi içindir; firewall kuralı olmadan bu komutu
   kullanmayın. Custom node yüklemeyin; Comfy custom node'ları yerel Python kodu
   çalıştırabilir.
4. Gateway Comfy graph'ını programatik kurar; ayrıca API workflow export etmek gerekmez.
   `gateway/config/workflow_config.json` içindeki model, text encoder ve VAE adlarının
   ComfyUI'de kurulu dosyalarla birebir eşleştiğini doğrulayın.
5. Gerçekte kullanılan üç model dosyasını ve gateway workflow yapılandırmasını bir kez
   SHA-256 manifestine sabitleyin. Bu işlem büyük model dosyaları nedeniyle birkaç
   dakika sürebilir:

   ```powershell
   powershell -File scripts/New-AssetManifest.ps1 `
     -DiffusionModel "C:\ComfyUI\models\diffusion_models\flux-2-klein-base-9b-fp8.safetensors" `
     -TextEncoder "C:\ComfyUI\models\text_encoders\qwen_3_8b_fp8mixed.safetensors" `
     -Vae "C:\ComfyUI\models\vae\full_encoder_small_decoder.safetensors"
   ```

   Oluşan `asset-manifest.local.json` makineye özeldir ve git tarafından dışlanır.
6. `.env.example` dosyasını `.env` olarak kopyalayın. Secret üretmek için:

   ```powershell
   powershell -File scripts/New-Secrets.ps1
   ```

   Çıktıyı `.env` içindeki ilgili iki satıra girin ve sekiz Drive folder ID'sini
   doldurun. Workflow config SHA-256'sı ayrı `asset-manifest.local.json` içinde tutulur.
   `.env` paylaşılmamalıdır. `N8N_ENCRYPTION_KEY` kaybolursa n8n
   credential'ları kurtarılamaz.
7. Yönetici PowerShell'de Compose subnet'ine özel Comfy firewall kuralını oluşturun.
   Script container'ları başlatmaz; yalnız Compose nesnelerini oluşturup subnet'i
   belirler. Önceden var olan geniş kapsamlı Python/Comfy/8188 inbound kurallarını
   Windows Defender Firewall ekranından kapatın:

   ```powershell
   powershell -File scripts/Configure-ComfyFirewall.ps1
   ```

   `docker compose down` ile named network silinirse subnet değişebileceğinden bu
   script yeniden çalıştırılmalıdır. Windows profilinde varsayılan inbound davranışı
   **Block** olarak kalmalıdır.
8. Artık 3. adımdaki komutla ComfyUI'yi başlatın. Sonra preflight çalıştırın. Bu kontrol
   model/encoder/VAE/config hash'lerini yeniden hesaplar; beklenen yavaşlık güvenlik ve
   tekrarlanabilirlik içindir:

   ```powershell
   powershell -File scripts/Preflight.ps1
   ```

9. Servisleri başlatın ve `http://127.0.0.1:5678` adresinde owner hesabını oluşturun:

   ```powershell
   powershell -File scripts/Start-LocalProd.ps1
   ```

10. Ayrı bir Google OAuth client/credential tanımlayın. Callback URL, n8n credential
   ekranının verdiği localhost URL'si olmalıdır. Cloud credential secret'ını workflow
   JSON'una kopyalamayın.
11. Yerel metal workflow export'unu inceleyip içe aktarın; ilk yüklemede inactive
   bırakın. Dört input folder ID'sini doğrulamadan Schedule Trigger'ı aktive etmeyin.
   `Map_Categories` folder ID'lerini `$env` üzerinden okuduğu için Code node environment
   erişimi bu private instance'ta açıktır; buraya güvenilmeyen workflow import etmeyin.

Docker Desktop ve ComfyUI'nin kullanıcı oturumunda otomatik başlamasını önce kendi
ayarlarından yapılandırın. Ardından Compose'u oturum açıldıktan bir dakika sonra
başlatmak için, tüm kurulum ve ilk testler tamamlandığında yönetici PowerShell'de şunu
çalıştırın:

```powershell
powershell -File scripts/Install-AutoStartTask.ps1
```

## Operasyon

Durum ve loglar:

```powershell
docker compose ps
docker compose logs --tail 200 gateway n8n pdf-raster
Invoke-RestMethod http://127.0.0.1:8188/system_stats
```

GPU eşzamanlılığı gateway'de, production execution eşzamanlılığı n8n'de `1` olarak
sabitlenmiştir. n8n başarılı execution detaylarını saklamaz; hataları saklar ve yedi
günden eski execution verisini budar. Gateway spool/cache volume'u ayrıca korunur.

Comfy kapalıysa veya gateway circuit-breaker açıksa yeni bir Drive kaynağını Done'a
taşımayın. Hata giderildikten sonra aynı kaynak ve aynı ayarlarla retry idempotent
olmalıdır; seed, step veya çözünürlük otomatik değiştirilmez.

Circuit ancak Comfy/model/Drive kaynaklı temel hata giderilip kuyruk kontrol edildikten
sonra bilinçli olarak sıfırlanır; komut onay ister ve token'ı ekrana yazdırmaz:

```powershell
powershell -File scripts/Reset-GatewayCircuit.ps1
```

Circuit reset başarısız deterministik job kaydını otomatik silmez. Aynı job'ı yeniden
render etmek gerekiyorsa önce Comfy `/queue` ve `/history` içinde aynı gateway job'ının
çalışmadığını doğrulayın; ardından job ID'yi bilinçli olarak sıfırlayıp circuit'i açın:

```powershell
powershell -File scripts/Reset-GatewayJob.ps1 -JobId <64-karakter-job-id>
powershell -File scripts/Reset-GatewayCircuit.ps1
```

Servisleri güvenli biçimde durdurmak için:

```powershell
powershell -File scripts/Stop-LocalProd.ps1
```

`docker compose down --volumes` çalıştırmayın; bu n8n credential ve gateway durumunu
siler.

## Yedek ve geri yükleme

Tutarlı volume yedeği almak için:

```powershell
powershell -File scripts/Backup-LocalProd.ps1
```

Script n8n/gateway'i kısa süre durdurur, iki ayrı `tar.gz` üretir ve servisleri yeniden
başlatır. `.env`, gateway workflow dosyaları ve import edilen workflow export'u volume
yedeğine dahil değildir; bunları şifreli, erişimi sınırlı bir yerde ayrıca saklayın.

Geri yükleme hedef volume'un mevcut içeriğini siler ve bilinçli olarak `-Confirm`
ister:

```powershell
powershell -File scripts/Restore-LocalProd.ps1 -Component n8n -Archive backups\n8n-data-YYYYMMDD-HHMMSS.tar.gz
powershell -File scripts/Restore-LocalProd.ps1 -Component gateway -Archive backups\gateway-data-YYYYMMDD-HHMMSS.tar.gz
```

## Metal cutover ve rollback

Cutover öncesinde:

1. Cloud metal execution'larının tamamen bittiğini doğrulayın.
2. Dört yeni Drive input klasörünü kullanın: Metal Baskısız, Metal Baskılı, Metal
   Revizyon Baskısız, Metal Revizyon Baskılı.
3. Preflight, fixture testleri, reboot testi ve en az üç ürünlük kuyruk testi geçsin.
4. Eski iki cloud metal girişine yeni dosya bırakmayı durdurun.
5. Yerel workflow'u aktive edin; ilk gerçek ürünü insan gözetiminde tamamlayın.

Rollback yalnız manuel yapılır:

1. Önce yerel n8n metal workflow'unu deactivate edin.
2. `docker compose stop n8n gateway` ile yeni iş kabulünü durdurun.
3. Comfy kuyruğunda çalışan iş kalmadığını doğrulayın; staging çıktısını silmeyip
   karantinaya alın.
4. Ayrı/harici n8n ortamında önceden inactive ve credential/env eşlemeleri tamamlanmış,
   dört yeni klasörü anlayan frozen FAL cloud clone'unu ancak bundan sonra aktive edin.
5. Yerel ve cloud metal tüketicilerini aynı anda çalıştırmayın.

Otomatik FAL fallback yoktur. OOM, model/workflow hash farkı, eksik çıktı veya Drive
commit belirsizliği iş akışını durdurur; çözünürlük/step sessizce düşürülmez.

## Testler

Docker Desktop çalışırken:

```powershell
docker build --target test -t mockup-pdf-raster-test pdf-raster
docker run --rm mockup-pdf-raster-test
docker compose config --quiet
```

PDF testleri boş/geçersiz gövdeyi, 25 MiB sınırını, 1600 kare yerleşim sözleşmesini,
`fill` davranışını ve `fit=page` oranını kapsar.
