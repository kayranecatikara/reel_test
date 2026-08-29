# Bu klasör `talon_arayuz` deposundan ALINDI

Kaynak: https://github.com/EfeAtakul/talon_arayuz  (commit `1e03e60`)
Alınma tarihi: 2026-08-29

⛔ **KOD DEĞİŞTİRİLMEDİ.** Bu klasördeki `control/`, `gcs/` ve parametre
dosyaları depodan **olduğu gibi** alınmıştır. Talon bu yığınla daha önce
düzgün uçuruldu; çalışan bir şeyi elden geçirmenin sebebi yok.

**Bizim eklediklerimiz bu klasörün DIŞINDA:**

| dosya | ne yapar |
|---|---|
| `reel/talon/yayinci.py` | MAVLink dağıtıcısı + 5 Hz hedef yayını |
| `reel/talon/gorev_plani.py` | serbest waypoint görevi üretir |
| `reel/baslat_talon.sh` | ikisini doğru sırayla başlatır |

**Niye ayrı:** yukarıdaki depo güncellenirse bu klasörü değiştirmeden
tazeleyebilelim. Ekleme yapmak için oradaki dosyalara dokunmak
gerekmiyor — `gcs/sunucu.py` zaten `/api/gorev` ucunu sunuyor ve görev
öğelerini MAVLink protokolüyle yüklüyor (`gorev_yukle_protokol`).

## Orijinal belgeler
* `README_orijinal.md` — deponun kendi kılavuzu
* `KURULUM.md`, `UCUS_PROSEDURU.md` — kurulum ve uçuş prosedürü
* `yedek_parametre_2026-08-17.param` — çalışan parametre yedeği

## ⚠ YEREL DEĞİŞİKLİKLER — `talon_arayuz` 1e03e60'ta YOKTUR

Depo aynen alındı; aşağıdakiler bizim eklediğimizdir. Yukarı akıştan
yeniden çekilirse bunlar TEKRAR uygulanmalıdır.

| dosya | ne | neden |
|---|---|---|
| `gcs/static/index.html` | `#haritaAc` düğmesi + açıklaması (`<section>`, MANUEL KONTROL'ün altında) ve `click` işleyicisi (`gorevDurumCiz` üstünde) | Harita planlayıcısı ayrı bir programdır (port 8010). Kullanıcı iki arayüz arasında URL kovalamasın diye tek giriş noktası: `localhost:8000`. |

**Kod tarafında hiçbir şey değiştirilmedi** — güdüm, görev protokolü,
mod komutları, parametre yolu olduğu gibi duruyor. Değişiklik yalnız
statik HTML'e eklenen bir düğme ve `window.open` çağrısıdır.

### Bilinçli olarak DEĞİŞTİRİLMEYENLER

* **`planla()` yalnız kullanıcı girdisinde çalışıyor**, telemetri
  döngüsünde değil (`index.html`). Sayfa GPS fix'ten önce açılırsa
  "GPS fix yok" uyarısı ve `GÖREVİ YÜKLE` kilidi DONMUŞ kalır; bir
  şekil düğmesine basmak ya da sayfayı yenilemek çözer.
  *(29 Ağu 2026'da sahada yaşandı.)*
* **Arayüz araçtaki görevi GERİ OKUMAZ**; yalnız kendi yüklediğini
  hatırlar (`sunucu.py` `durum.gorev`). Planlayıcıdan yüklenen görev
  onun için görünmez ve `BAŞLAT` kapalı kalır. Bu yüzden planlayıcının
  kendi `GÖREVİ BAŞLAT` düğmesi var (bkz. R85-R87).

İkisi de yukarı akış davranışıdır; düzeltmek vendored kodu ayrıştırırdı.
