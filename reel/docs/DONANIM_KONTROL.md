# DONANIM KONTROL LİSTESİ — uçuştan çok önce, masada

> Bu belgedeki her satır **bir bilinmeyeni kapatır.** Hepsi cevaplanmadan
> gerçek uçuş planlanamaz; çünkü cevaplardan bazıları güdümün dikey
> kanalının **çalışıp çalışamayacağını** belirliyor.
>
> Nasıl yapılır: drone'u USB ile bilgisayara tak, **Betaflight Configurator**
> aç, **CLI** sekmesine geç, aşağıdaki komutları tek tek yapıştır ve çıktıyı
> kaydet. Pervaneler ÇIKARILMIŞ olsun (CLI'de arm denemesi yok ama alışkanlık
> hayat kurtarır).

---

## 0 · Çıktıyı topla (tek komut)

CLI'ye şunu yapıştır ve **tüm çıktıyı** bir metin dosyasına kopyala:

```
version
status
get rcmap
get serialrx_provider
get failsafe_procedure
get small_angle
get angle_limit
get gps_provider
get mag_hardware
get baro_hardware
```

Sonra ayrı olarak (uzun çıktılar):

```
aux
serial
```

---

## 1 · ⛔ EN KRİTİK SORU — dikey kanal çalışabilir mi?

Güdümün çeviricisi (`dow/gudum/cevirici.py`) throttle çubuğunu bir
**TIRMANMA HIZI KOMUTU** sanıyor. DoW'da öyleydi ve ölçüldü:

```
thr  +1.00  +0.50  +0.25  0.00 | -0.60  -1.00
vz   33.51  16.80   8.79  0.88 | -0.24  -6.95     (m/s)
```

**Betaflight'ta bu YALNIZ `ALT_HOLD` kipinde doğrudur.** Normal `ANGLE`
kipinde throttle doğrudan **itki**dir; yani "yarım çubuk" bir hız değil bir
kuvvet demektir ve araç o çubukta sonsuza kadar hızlanır ya da düşer.

| ne bakılır | nerede | ne olmalı | olmazsa ne olur |
|---|---|---|---|
| Betaflight sürümü | `version` | **≥ 4.5** | ALT_HOLD kipi yok → B planı |
| Barometre | `status` içinde `BARO` | var | ALT_HOLD çalışmaz → B planı |
| ALT_HOLD kipi atanmış mı | `aux` | bir AUX'a atanmış | atanır |

**A PLANI (ALT_HOLD var):** throttle = tırmanma hızı. Çeviricinin modeli
yapısal olarak GEÇERLİ; yalnız katsayıları (eğim, orta nokta) gerçek araçta
ölçülür. `araclar/dikey_olc.py` bunu güvenli biçimde yapar.

**B PLANI (ALT_HOLD yok):** throttle'ı biz kapatırız — CRSF `VARIO`
çerçevesinden gelen düşey hızı okuyup küçük bir düzeltici döngüyle throttle
üretiriz. ⚠ Bu **güdüm yasasını değiştirmez**; çeviricinin *araç modelini*
değiştirir — ki o model zaten DoW için ÖLÇÜLMÜŞ bir araç özelliğiydi, evrensel
bir kural değil. Bedeli: bir ayar turu daha ve daha yüksek gecikme.

---

## 2 · Konum nereden gelecek — GPS var mı?

GPS fazı (istasyon tutma) hedefin ve **bizim** konumumuzu ister.

| ne bakılır | nerede | ne olmalı |
|---|---|---|
| GPS donanımı | `status` içinde `GPS`, `get gps_provider` | takılı ve fix alıyor |
| Uydu sayısı | Configurator → GPS sekmesi | **dışarıda ≥ 10** |
| Pusula (mag) | `get mag_hardware`, `status` | tercihen var |

**Pusula neden önemli:** CRSF `ATTITUDE` çerçevesindeki `yaw`, kartın burun
kestirimidir. Pusulasız Betaflight bunu yalnız GPS rotasından ve jiroskop
tümlevinden çıkarır; **araç yavaşken ya da asılı dururken kayar.** Bizim
çeviricimiz dünya hızını gövdeye çevirmek için `yaw`ı kullanıyor
(`dunya_govde`); yaw kayarsa yanal komut yanlış eksene biner.

⚠ GPS yoksa: **görsel güdüm yine çalışır** (kamera GPS bilmez), ama GPS
yaklaşma fazı çalışmaz — yani hedefe kadar elle götürmek gerekir.

---

## 3 · Kanal sırası — "pitch verdim, araç yattı" hatasına karşı

```
get rcmap
```

Betaflight varsayılanı `AETR` → kanal 1 roll, 2 pitch, 3 throttle, 4 yaw.
Kodumuzun varsayılanı da bu (`crsf.KanalHaritasi`). **Farklıysa** haritayı
ona göre kurarız; sınamak için `araclar/kanal_testi.py` her ekseni tek tek
oynatır ve Configurator'ın **Receiver** sekmesinde hangi çubuğun kıpırdadığı
gözle görülür.

---

## 4 · Alıcı ve telemetri

| ne bakılır | ne olmalı | niye |
|---|---|---|
| `get serialrx_provider` | **CRSF** | ELRS CRSF konuşur |
| `serial` | RX'in bağlı olduğu UART'ta `SERIAL_RX` açık | |
| Telemetri | CRSF'te **otomatiktir**, ayrı ayar istemez | konum/duruş bize buradan gelir |

---

## 5 · ⛔ EMNİYET — link koparsa ne oluyor?

```
get failsafe_procedure
```

| değer | anlamı | bizim için |
|---|---|---|
| `DROP` | motorlar durur, araç düşer | **kabul edilemez** — kalabalık yok ama araç gider |
| `LAND` | kontrollü alçalır | makul varsayılan |
| `GPS_RESCUE` | eve döner | **GPS + pusula varsa en iyisi** |

Ayrıca:
- `get small_angle` — Betaflight bu açıdan fazla yatıkken **arm etmez**.
  Varsayılan 25°. Yerde eğimli bir zeminde "arm olmuyor" derdinin sebebi
  genelde budur.
- `get angle_limit` (eski adı `max_angle_inclination` / `level_limit`) —
  ANGLE kipinde ulaşılabilen en büyük yatış. **Bu sayı bizim
  `CevCfg.A_MAX`'ımızın gerçek karşılığıdır**: yatay ivme `a = g·tan(açı)`.
  30° → 5.7 m/s², 45° → 9.8 m/s², 60° → 17 m/s².
  ⚠ DoW'da A_MAX = 34 m/s² ölçülmüştü — bu, **60°'de beklenenin 2 katı**,
  yani oyun fiziği gerçekçi değildi. Gerçek araçta bu sayı çok daha
  küçük olacak ve **yanal çeviklik belirgin düşecek.** Bu, sim sonuçlarının
  birebir taşınmayacağı en somut noktadır.

---

## 6 · ELRS TX modülü — PC ona nasıl konuşacak?

Ranger Micro bir **JR yuvası** modülüdür; USB'si genelde yalnız firmware
içindir. PC'den CRSF vermenin iki yolu var:

**YOL 1 — DOĞRUDAN (basit, emniyet pilotu YOK):**
USB-TTL çevirici (CP2102/FT232) JR yuva pinlerine lehimlenir/bağlanır.
Modül **pilden** beslenir (USB 2 A veremez).

**YOL 2 — KUMANDA ÜZERİNDEN (⭐ ÖNERİLEN, emniyet pilotu VAR):**
Modül kumandaya takılır; PC kumandanın **eğitmen (trainer) girişine** bağlanır
ve kumandada bir anahtar "pilot / bilgisayar" seçer. Bu, otonom uçuşun
klasik emniyet düzeneğidir: **pilot bir anahtarla anında devralır.**

⚠ Kod her iki yolda da AYNI — değişen tek şey seri portun fiziksel ucu.
Ama **emniyet açısından ikisi aynı değil.** Yol 1'de, yazılım ya da
bilgisayar takılırsa devralacak kimse yoktur.

**Cevaplanacak:** elde hangi kumanda var, eğitmen girişi (trainer jack) var mı?

---

## 7 · Kamera ve video indirme

| ne | ne yazılacak |
|---|---|
| kamera modeli / görüş açısı | |
| VTX ve yer alıcısı | |
| yakalama kartı modeli | |
| kartın verdiği çözünürlük | `v4l2-ctl --list-formats-ext -d /dev/video0` |

⚠ **Kamera montaj açısı** ölçülecek: DoW'da kamera burnun **26.5° YUKARISINA**
bakıyordu ve güdüm bunu telafi ediyor. Gerçek montaj farklıysa
`dow/gorus/kamera.py` sabitleri yeniden ölçülmelidir
(`araclar/kamera_kalib_gercek.py` — Faz 5).

---

## 8 · Çıktı şablonu — doldurulup depoya konur

```
Betaflight sürümü .......:
Barometre ...............: var / yok
ALT_HOLD kipi ...........: var / yok   (atandığı AUX: )
GPS .....................: var / yok   (dışarıda uydu: )
Pusula (mag) ............: var / yok
rcmap ...................:
serialrx_provider .......:
failsafe_procedure ......:
small_angle .............:
angle_limit .............:
Kumanda modeli ..........:            (trainer girişi: var/yok)
Kamera ..................:
VTX / alıcı .............:
Yakalama kartı ..........:            (çözünürlük: )
```
