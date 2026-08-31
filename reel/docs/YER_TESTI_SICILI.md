# YER TESTİ SİCİLİ — pervanesiz, ölçülmüş sonuçlar

Bu dosya **ölçülmüş** sonuçları tutar. Tahmin, beklenti ve "çalışıyor gibi"
buraya yazılmaz. Her satırın yanında nasıl ölçüldüğü durur.

---

## 2026-08-31 · YÖN İŞARETİ DOĞRULANDI — `DOW_CEV_Y_ISARET = +1.0`

**Soru:** güdüm hatayı KAPATIYOR mu, BÜYÜTÜYOR mu? Çevirici dünya çerçevesindeki
hız isteğini gövdeye çevirirken `Y_ISARET` yanlışsa yanal kanal AYNALANIR ve
araç hedeften KAÇAR. `baslat_drone.sh` bunu *"kesin kanıtı ilk otonom uçuştur"*
diye açık bırakmıştı.

**Yöntem:** `gercek/yon_testi.py --mod cevir`. Araç yerde, DISARM, pervanesiz,
panelde OTONOM. Araç elle dört farklı burun yönüne çevrildi. Güdümün ürettiği
GÖVDE çubukları `yaw` ile DÜNYA çerçevesine geri döndürüldü. Hedef sabit
olduğuna göre dünya yönü, burun yönünden BAĞIMSIZ olmalıdır.

İki hipotez birlikte ölçüldü: H0 = işaret doğru, H1 = işaret ters.

**Ölçüm (37 örnek, 2'si doyumda elendi, 5 burun aralığı):**

| burun aralığı | n | H0 dünya yönü | H1 dünya yönü |
|---|---|---|---|
| 0–45° | 1 | 171.0° | 194.6° |
| 45–90° | 1 | 154.7° | 305.3° |
| 225–270° | 9 | 159.4° | 340.2° |
| 270–315° | 7 | 173.4° | 28.2° |
| 315–360° | 17 | 162.4° | 132.6° |

```
TOPLANMA        H0 = 0.992      H1 = 0.156      fark +0.836   (eşik 0.15)
HEDEFE SAPMA    H0 = +0.4°      H1 = -92.9°
H0 mutlak sapma medyan 1.0°  ·  en kötü 3.5°
```

**Hüküm: `Y_ISARET = +1.0` DOĞRU.** Sapma medyanı GPS gürültüsü seviyesinde.

⚠ Talon ile drone testte ~1 m aradaydı. Bu sonucu bozmaz: sınanan şey
"komut hedefe mi bakıyor" değil, **"aracı çevirince dünya yönü değişiyor mu"**
— ve o değişmezlik mesafeden bağımsızdır. Ayrıca komut, geometri GPS
gezinmesiyle kayarken hedef kerterizini BİRLİKTE takip etti (17 s: 170.4 vs
171.5 · 23 s: 161.9 vs 161.6 · 32 s: 152.6 vs 151.9).

---

## 2026-08-31 · MANYETOMETRE SORUNU ÇÖZÜLDÜ

**Belirti:** `yaw` araç sabitken 40 saniye boyunca TAM OLARAK −47.3°'de donuk
(yayılım 0.0°). Araç çevrilince gyro takip ediyor, bırakınca ANİDEN eski
değere dönüyor.

**Eleme sırası:**
1. `status` → `MAG: QMC5883` **tespit edildi** — donanım var
2. `get mag` → `mag_calibration = 569,-1478,275` — kalibre EDİLMİŞ
3. **Yalnız USB gücüyle** (pil yok) kart elde çevrildi → pusula **DÜZGÜN
   takip etti** ⇒ sensör ve I2C kablosu SAĞLAM, sorun pille gelen parazit
4. Kullanıcı manyetometreyi YENİDEN kalibre etti

**Sonuç:** yön testinde `burun` sütunu −79 → +2.8 → −41.9 → +50 → −24.4 →
+58.2 → −110 arasında gezdi ve **yeni değerlerde KALDI**. Donma gitti.

⚠ `mag_declination` bölge için 5.9° ölçüldü → `set mag_declination = 59`.
Girilmezse yön açısı 5-6° kayık kalır.

---

## 2026-08-31 · PERVANESİZ YER TESTİ A/B/C/D — HEPSİ GEÇTİ

| adım | ne sınandı | sonuç |
|---|---|---|
| **A** | kumandayla manuel; çubuk→pad eşlemesi | ✔ eşleme DOĞRU |
| **B** | panelle manuel; RC sayacı artıyor | ✔ |
| **C** | ARM — panel (basılı tut) ve kumanda anahtarı | ✔ ARM oldu |
| **D** | pilot çubukla devralma mandalı | ✔ `sebep = pilot_devraldi` |

⛔ C adımının ön koşulu: panelin sol pad'i (gaz) **en aşağıda** olmalı.
Açılışta ORTADA durur = 1500 µs = yarım gaz ve Betaflight öyle arm ETMEZ.

---

## AÇIK KALANLAR — ilk otonom uçuştan önce

| iş | durum |
|---|---|
| Pil | 21.4 V (6S'te 3.57 V/hücre) — **şarj edilmeli** |
| `vbat_min_cell_voltage = 250` | 2.5 V çok düşük, yükseltilmeli |
| Dikey iniş (ALT HOLD + POS HOLD) | tezgâhta doğrulandı, **hiç UÇMADI** |
| `DOW_INIS_CUBUK = -0.35` | alçalma hızı **ölçülmedi** |
| `ap_hover_throttle = 1310` | gerçek asılı gazla karşılaştırılmadı |
| `MENZIL_C` | türetme, **ölçüm değil** (görsel faz menzilini etkiler) |
| Talon `AIRSPEED_MIN = 15` | tahmin (pitot yok) |
