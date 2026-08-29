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
