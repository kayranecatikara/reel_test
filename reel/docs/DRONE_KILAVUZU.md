# AVCI DRONE — TAM KILAVUZ
### 7 inç quadcopter'ın yer kontrolünden uçurulması ve otonom güdüm

> Bu belge, drone'u hiç görmemiş birinin bile kurup uçurabilmesi için
> yazıldı. Her terim ilk geçtiği yerde tanımlanır; hiçbir adım "bilindiği
> varsayılarak" atlanmaz. Kardeş belge: `TALON_KILAVUZU.md` (hedef uçak).
>
> **Son güncelleme:** 29 Ağustos 2026
> **Doğrulanma:** yer testleri yapıldı (ELRS bağı, kumanda ekseni, panel
> joystickleri, kamera, Talon→drone GPS akışı). **Otonom uçuş YAPILMADI.**

---

## 0 · Beş dakikada özet

```bash
# Terminal 1 — Skydagger backend (ELRS köprüsü)
cd ~/projects/drones_of_war_entegrasyon/reel/skydagger
./baslat_backend.sh

# Terminal 2 — drone yer kontrolü
cd ~/projects/drones_of_war_entegrasyon/reel
./baslat_drone.sh
```
→ Tarayıcı: **http://localhost:8810**

| yaparsın | nerede |
|---|---|
| Elle uçurmak | Paneldeki iki joystick, ya da USB kumanda |
| Otonom güdüme geçmek | **OTONOM** düğmesi + pilot izin anahtarı |
| Kamerayı kalibre etmek | `python3 gercek/kamera_ayari.py` → :8020 |
| Acil durdurmak | Kumandadan **çubuk oynat** (anında, mandallı) · panelde **MANUEL** |
| Acil İNDİRMEK | Panelde **⛔ FAILSAFE — DİKEY İNİŞ** — olduğu yerde aşağı iner |

---

## 1 · Sistem nedir — parça parça

### 1.1 Komut zinciri (yerden uçağa)

```
[panel :8810]  ya da  [USB kumanda]
        │
        ▼
   [HAKEM  komut.py]         kimin sözü geçer — dört şart
        │
        ▼
   [CRSF paketleyici]        16 kanal × 11 bit + CRC-8/DVB-S2
        │
        ▼
[Skydagger backend]          UDP 8767  "RC_US c1..c16"
        │
        ▼
     [ESP32]  ──ELRS 2.4 GHz──►  [F405 uçuş kontrolcüsü / Betaflight]
```

### 1.2 Veri zinciri (uçaktan yere)

```
[F405] ──CRSF telemetri──► [ESP32] ──TCP 8766──► [Skydagger backend]
                                                        │
                                                        ▼
                                              [baglanti.py]  konum, hız,
                                                             yatış, batarya
[FPV kamera] ──analog──► [USB yakalama kartı] ──► [kamera_yakala.py]
[Talon bilgisayarı] ──UDP 47800, 5-10 Hz──► [hedef.py]  hedefin GPS'i
```

### 1.3 Terimler

| terim | ne demek |
|---|---|
| **ELRS** (ExpressLRS) | Uzun menzilli açık kaynak RC bağı. 2.4 GHz. |
| **CRSF** (Crossfire) | ELRS'in konuştuğu paket biçimi. 16 kanal, her biri 11 bit. |
| **ESP32** | Yarışma komitesinin verdiği köprü kartı. Bilgisayardan aldığı komutu ELRS'e çevirir. |
| **Skydagger backend** | Komitenin verdiği program. ESP32 ile bilgisayar arasında durur. |
| **Angle mode** | Betaflight uçuş kipi: çubuk **açı** ister, uçak o açıyı tutar. Yarışma şartnamesi **yalnız bunu** kullanmamıza izin veriyor. |
| **Arm** | Motorların dönmesine izin verilmesi. |
| **bbox** (kutu) | Dedektörün hedefin etrafına çizdiği dikdörtgen. Görsel güdümün tek girdisi. |
| **IBVS** | Image-Based Visual Servoing — hedefi *görüntüdeki yerine* göre kovalama. |
| **Kilit** | Hedefin belirli süre kesintisiz ve yeterli güvenle görülmesi. |
| **Faz** | Güdümün o anki modu: **İSTASYON** (GPS ile yaklaş) · **GÖRSEL** (kutuyla kovala) · alt fazlar **KİLİT** / **TERMİNAL**. |

### 1.4 Portlar

| port | kim | ne |
|---|---|---|
| **8810** | `drone_yki.py` | Operatör paneli |
| **8020** | `kamera_ayari.py` | Kamera kalibrasyon aracı |
| 8765 | Skydagger backend | HTTP |
| 8766 | Skydagger backend | TCP — CRSF telemetri |
| 8767 | Skydagger backend | UDP — RC komutları |
| **47800** | `hedef.py` | Talon'dan gelen hedef GPS'i |

---

## 2 · Donanım

### 2.1 Drone
- **7 inç quadcopter**, **F405** uçuş kontrolcüsü, **Betaflight**
- **ELRS alıcı** (Radiomaster Ranger Micro ailesi)
- **FPV kamera** — gövdeye **sabit**, gimbal **yok**, burnun bir miktar
  **yukarısına** bakar (bkz. bölüm 08)
- Analog video vericisi

### 2.2 Yerde
- Laptop
- **ESP32 köprü kartı** — USB ile laptopa, ELRS modülüyle eşli
- **USB video yakalama kartı** — FPV alıcısının çıkışı
- **Kumanda** (JUMPER-RC / RadioMaster Pocket) — USB ile laptopa,
  **yalnız joystick girdisi olarak** kullanılır

> ⛔ Kumanda uçağa **RF ile bağlı değildir** bu kurulumda. Komutlar
> bilgisayardan ESP32 üzerinden gider. Kumanda sadece bir USB oyun
> çubuğudur — ama panelden **önceliklidir** (bölüm 06).

---

## 3 · Kurulum

### 3.1 Paketler ve izinler
```bash
cd ~/projects/drones_of_war_entegrasyon/reel
pip install -r requirements.txt
sudo usermod -aG dialout $USER      # ÇIKIP TEKRAR GİR
```

### 3.2 Skydagger backend (bir kez, ~2 dakika)
```bash
./reel/skydagger/kur.sh
```
Bu, komitenin verdiği Windows `.exe`'sinin içindeki Python kodunu çıkarır ve
yanına taşınabilir bir Python 3.12 + `pyserial` kurar. **Wine gerekmez** —
iki kez denendi ve olmadı (Wine 6.0.3'te `propsys.dll` eksik; GE-Proton
GLIBC 2.38 istiyor, sistemde 2.35 var).

### 3.3 Kumanda eksen haritası
```bash
python3 araclar/kumanda_kalib.py
```
Her eksen için ayrı ayrı sorar. Sonucu `baslat_drone.sh`'a yazılıdır ve
**ölçüldü, varsayılmadı**:

| eksen | numara |
|---|---|
| ROLL | 0 |
| PITCH | 1 |
| THROTTLE | 2 |
| YAW | 3 |
| ARM | 4 |
| KİP (otonom izni) | −1 = atanmadı |

> ⛔ **ARM ile KİP aynı eksene atanamaz.** Araç bunu reddeder: otonom izni
> ARM anahtarına binerse, arm ettiğin anda otonom da açılır.

### 3.4 Kamera optiği — ⛔ HENÜZ YAPILMADI
Bölüm 08. **Bu yapılmadan görsel güdüm yanlış menzil ölçer.**

---

## 4 · Başlatma

**Terminal 1 — Skydagger backend:**
```bash
cd ~/projects/drones_of_war_entegrasyon/reel/skydagger
./baslat_backend.sh
```
Başındaki temizleme adımı 8765 portunu tutan eski süreci kapatır.
`--kapat` ile yalnız kapatılır.

**Terminal 2 — drone yer kontrolü:**
```bash
cd ~/projects/drones_of_war_entegrasyon/reel
./baslat_drone.sh
```
→ **http://localhost:8810**

Faydalı seçenekler:
```bash
./baslat_drone.sh --kapat                    # yalnız kapat
DOW_KAM_KAYNAK=/dev/video2 ./baslat_drone.sh # kamerayı elle seç
DOW_CEV_Y_ISARET=-1.0 ./baslat_drone.sh      # yanal işaret ters çevir
```

**✅ Tamam ölçütü:** panelde `LINK` yeşil, `SAFE` çerçevesi görünüyor,
FPV görüntüsü akıyor.

---

## 5 · ARAÇ MODELİ — neden ayrı bir şey

Güdüm yasası "saniyede kaç metre" der. **Araç modeli** onu "çubuk nerede
durmalı"ya çevirir. Simülasyondan gerçeğe taşırken **yasa değişmez, model
yeniden ölçülür.**

| sabit | değer | nereden |
|---|---|---|
| `DOW_CEV_MODEL` | `aci` | Angle mode'da çubuk açıya eşlenir |
| `DOW_CEV_ACI_MAX` | 60 | Betaflight `angle_limit = 60` |
| `DOW_CEV_Y_ISARET` | **+1.0** | **ölçüldü** — 29 Ağu 2026 yer testi (DoW'da −1 idi) |
| `DOW_GPS_KAYNAK` | `gercek` | Simülasyondaki "truth" ve filtre gerçekte YOK |

> ⚠ `Y_ISARET` yer testinde doğrulandı ama **kesin kanıtı ilk otonom
> uçuştur**: güdüm hatayı kapatıyor mu, büyütüyor mu. İlk denemede araç
> hedeften **kaçıyorsa** ilk bakılacak yer burasıdır:
> `DOW_CEV_Y_ISARET=-1.0 ./baslat_drone.sh`

---

## 6 · HAKEM — komut kimden geliyor

Üç kaynak var: **panel joystickleri**, **USB kumanda**, **otonom güdüm**.
`gercek/komut.py` her karede hangisinin geçerli olduğuna karar verir.

### 6.1 Otonom için DÖRT şart — biri bile düşerse otonom YOK

1. **Panel OTONOM istiyor** — düğmeye basılmış
2. **Pilot izin veriyor** — kumandadaki veto anahtarı
3. **Güdüm taze setpoint üretiyor** — hesap akıyor
4. **Kumandayla bağ teslim süresi içinde** — kumanda kopmamış

> ⛔ Bu dört şartlı kapı, bir bekçinin (R39) yakaladığı gerçek bir emniyet
> hatasından sonra yeniden yazıldı: eski hâlde teslim zaman aşımı yalnız bir
> dalda vardı ve izin/arm mandallı olduğu için o dala hiç girilmiyordu —
> **kumanda kopukken otonom süresiz devam ediyordu.**

Otonom sürerken kumanda kopmuşsa panel bunu `sebep: kumanda_kopuk` diye
**yazar** — operatör görmeden fark edemezdi.

### 6.2 Kumanda devralması

Kumanda takılıyken bile kontrol **panelden**dir. Ama kumandanın
joystickleri **oynamaya başlarsa** kumanda devralır.

| ayar | değer | ne |
|---|---|---|
| `KMD_HAREKET_ESIK` | 0.04 | Bu kadar oynarsa "hareket" sayılır |
| `KMD_HAKIMIYET_S` | 3.0 s | Hareketten sonra kumanda bu kadar hâkim kalır |
| `KMD_ARA_S` | 2.0 s | Kumanda kaybolursa yeniden arama aralığı |
| `PANEL_ASIM_S` | 1.5 s | Panel bu kadar susarsa komutu düşer |

> ⛔ Hareket, çubuk nesnesinin kimliğine değil **değerlerine** bakılarak
> ölçülür. Bir bekçi (R63) bunu yakaladı: tek tampon kullanan bir kaynakta
> nesne hep aynı kalır ve hareket **hiç görünmezdi**.

---

## 7 · PANEL — her özellik

### 7.1 Üst rozetler

| rozet | ne |
|---|---|
| **LINK** | ELRS bağı canlı mı |
| **GPS** | Uydu sayısı ve fix |
| **KİP** | MANUEL / OTONOM |
| **girdi:** | Komut o an kimden geliyor — panel / kumanda / otonom |
| **DISARM / ARM** | Motor kilidi |
| **SUNUCU** | Yarışma sunucusuna bağlantı |

### 7.2 FPV
Yakalama kartından gelen canlı görüntü. Üstüne dedektörün kutusu ve kilit
ölçütü çizilir.

> ⛔ Görüntü **tek kare tek kare** çekilir, kalıcı bağlantıyla değil.
> Sebep ölçüldü: Chrome'un origin başına **6 bağlantı** sınırı. Kalıcı
> MJPEG akışı + istek yığılması paneli donduruyordu. Şimdi durum
> tek bir WebSocket'ten akıyor; 20 saniyelik yükte 200 WS mesajı +
> 288 kare, **0 hata**.

### 7.3 Manuel kumanda
İki sanal joystick. Sol: gaz + yaw. Sağ: pitch + roll.
Kumanda USB'den takılıysa joystickler onunla da oynar.

### 7.4 Düğmeler

| düğme | ne yapar |
|---|---|
| **MANUEL** | Kontrol sende — otonom kapalı |
| **OTONOM** | Otonom talebi. Dört şart sağlanmadan çalışmaz (bölüm 06) |
| **ARM (BASILI TUT)** | Basılı tuttuğun sürece arm. Bırakınca düşer |
| **KÖKEN KUR** | Yerel çerçevenin sıfır noktasını buraya kur. **≥10 uydu şart** |
| **KUMANDAYI YOK SAY** | Kumanda devralmasını kapat (tezgâh kipi) |
| **SAFE** | Aracın bildirdiği emniyet durumu |

> **KÖKEN nedir:** GPS koordinatlarını metreye çeviren yerel çerçevenin
> başlangıç noktası. Kalkışta **yerde** bir kez kurulur.
> ⛔ **Uçuş ortasında değiştirmek**, güdümün altındaki zemini kaydırmaktır:
> bütün konumlar bir anda sıçrar, güdüm dev bir hata görüp tam komut verir.

### 7.5 Telemetri ve 3B konum
Konum, hız, irtifa, yatış, batarya. 3B panel drone ile hedefi birlikte
gösterir; sürükleyerek döndürülür.

---

## 8 · KAMERA OPTİĞİ — ⛔ EN BÜYÜK AÇIK EKSİK

### 8.1 Sorun

`dow/gorus/kamera.py` sabitleri **DoW simülasyonunda** ölçüldü:

```
F_PX = 540.4 px · TILT = 26.50° · MENZIL_C = 997 px·m · 1920×1080
```

Gerçek FPV kamerası **başka mercek, başka montaj açısı, başka çözünürlük**.

**Ne olur:** menzil `R = MENZIL_C / kutu_genisligi` formülüyle çıkıyor.
`F_PX`'te %30 hata → menzilde %30 hata. Güdüm hedefi olduğundan yakın ya da
uzak sanır. **Hata sessizdir, hiçbir yerde patlamaz.**

**Çözünürlük tuzağı ayrıca ölçüldü:** kart 1280×720 verirken 1920×1080
sabitleri kullanılırsa aynı hedef 40 px yerine 27 px görünür ve menzil
**25 m yerine 37 m** denir — **%50 hata**. `drone_yki.py` artık bu
uyuşmazlıkta yüksek sesle uyarıyor.

### 8.2 Nasıl ölçülür — 5 dakika, dedektöre gerek yok

```bash
cd ~/projects/drones_of_war_entegrasyon/reel
python3 gercek/kamera_ayari.py        # tarayıcı: localhost:8020
```

**ODAK (F_PX) kipi.** Delikli iğne (pinhole) modelinden: genişliği `S`
metre olan bir cisim, `R` metre uzakta, görüntüde `w` piksel görünür.
Benzer üçgenler:

```
w / F_PX = S / R        ⟹        F_PX = w · R / S
```

Yani: Talon'u **şerit metreyle ölçülmüş** bir mesafeye koy, görüntüde
**kanat uçlarına tıkla** (= `w` piksel), kanat açıklığını bil
(`S = 1.718 m`). Üç dört farklı mesafede tekrarla.

> ⚠ **Varsayım:** mercek bozulması yok sayılıyor ve `fx = fy` (kare piksel)
> kabul ediliyor. Geniş açı FPV merceklerinde kadrajın **kenarında** bu
> bozulur — hedefi kadrajın **ortasına** koyarak ölç.
>
> ⚠ Mesafeyi **tahmin etme**. O sayı doğrudan `F_PX`'e çarpan giriyor;
> %20 yanlış mesafe %20 yanlış menzil demektir.

**TILT kipi.** Uçağı yerde, **gövdesi yatay** koy. Kamera burnun `TILT`
derece yukarısına baktığı için gerçek ufuk, görüntünün ortasının **altında**
kalır. Ufuk çizgisine tıkla:

```
TILT = atan( (CY − y_ufuk) / F_PX )        CY = görüntü_yüksekliği / 2
```

> ⚠ **Varsayım:** gövdenin yatay olduğu. Uçak burnu yukarı duruyorsa o açı
> `TILT`'e karışır. Şüphedeysen telefon su terazisiyle kontrol et.

**MENZIL_C.** Geometrik hâli doğrudan `F_PX · S`'tir. Ama dedektörün
kutusu gerçek kanat açıklığından biraz **geniştir** (gövdeyi ve payı da
alır). Simülasyonda ölçüldü: geometrik `540.4 · 1.718 = 928.4` iken
dedektör kutularıyla fit edilen `997.0` — **%7.4 pay**. Araç bu payı
uygular ve bir başlangıç değeri verir.

> ⛔ Dedektör gerçek görüntüde çalışmaya başlayınca `MENZIL_C` bu araçla
> **değil**, gerçek kutulardan yeniden fit edilmelidir.

### 8.3 Sonucu uygula

Araç sana yapıştırılacak satırları verir:
```bash
export DOW_OPTIK_W=1280
export DOW_OPTIK_H=720
export DOW_OPTIK_F_PX=402.9
export DOW_OPTIK_TILT=18.29
export DOW_OPTIK_MENZIL_C=743.4
```
`baslat_drone.sh` içinde hazır yorum satırları var; oradaki `#`'leri kaldır.

> ⚠ **Ölçümü hangi çözünürlükte yaptıysan uçuşta da o kullanılmalı.**
> `F_PX` çözünürlükle ölçeklenir.

**Aracın matematiği doğrulandı:** bilinen bir kameradan üretilmiş sentetik
ölçümlerde `F_PX` **%0.06**, `TILT` **0.01°** hatayla geri çıkıyor. Bir
tıklama kanat ucunu ıskalarsa **medyan** %0.2 hatayla kurtarır (aynı veride
ortalama %10 sapıyor) ve panel ölçümler arası sapma %10'u geçince kırmızı
yazar.

---

## 9 · ANGLE MODE DİKEY DÖNGÜ

### 9.1 Sorun
Angle mode'da **gaz çubuğu hız değil itki ister**. Simülasyonda "şu kadar
m/s tırman" diyebiliyorduk; gerçekte "şu kadar gaz ver" diyoruz ve ortaya
çıkan hız pilin, ağırlığın ve yatış açısının fonksiyonu.

### 9.2 Çözüm — dikey hızda PI + yatış ileri beslemesi

```
P      = kırp(KP · hata, ±P_YETKI)
I     += KI · hata · dt              (koşullu; ±I_MAX ile sınırlı)
çubuk  = eğim_sınırla(kırp(P + I + ileri_besleme, THR_MIN, THR_MAX))
```

| sabit | değer | ne |
|---|---|---|
| `KP` | 0.0510 | **Ani** yetki. τ = 1.0 s hedefinden türetildi: KP = 1/(19.6·τ) |
| `KI` | 0.0051 | **Yavaş** yetki |
| `P_YETKI` | ±0.15 | Tek seferde ne kadar sert düzeltme yapılabilir |
| `I_MAX` | ±0.35 | Asılı gazı arama aralığı — geniş olmalı |
| `THR_MIN/MAX` | ∓0.50 | **Mutlak emniyet.** Ne olursa olsun aşılmaz |

Tasarım bağıntısı: `I_MAX + P_YETKI = 0.35 + 0.15 = 0.50 = THR_MAX`.

**Yatış ileri beslemesi:** araç `θ` derece yatınca dikey itki
`cos θ` kadar azalır; telafi `1/cos(θ)^0.5` ile önden verilir — integral
hatayı fark edip yakalamayı beklemez.

**Yumuşak devir (bumpless transfer):** otonoma geçerken integral,
pilotun o anki çubuğundan tohumlanır. Aksi hâlde araç bir anda gaz
değiştirir.

**Telemetri bekçisi:** `TELEM_MIN_HZ = 4.0`. Dikey hız bilgisi bundan
seyrekse döngü **pasife düşer** ve `n_pasif_cagri` sayacı artar — kör
integral en tehlikeli hâldir.

---

## 10 · HEDEF GPS — Talon'dan drone'a

Talon bilgisayarındaki `yayinci.py`, hedefin konumunu **UDP 47800**'e basar.
Drone tarafında `hedef.py` dinler.

**Yayın biçimi = yarışma sunucusunun biçimi.** Böylece drone tarafındaki kod
bugün ile yarışma günü arasında **hiç değişmez**; yalnız verinin geldiği
adres değişir.

```json
{"sunucu_saati": {...},
 "hedef_iha_verileri": [{"takim_no":0, "enlem":41.002892, "boylam":28.656232,
                         "irtifa_ev":80.0, "hiz":22.0, "saat_farki":44}]}
```

### 10.1 Bayatlık — sessiz tuzak

`saat_farki` verinin **kendi yaşı**dır (ms). Paket az önce gelmiş olabilir
ama **içindeki veri** saniyelerce eski olabilir — yayıncı kalp atışı da
basıyor ve telsiz koparsa son bilinen konumu tekrarlar.

> **28 m/s giden bir hedef 500 ms'de 14 m yol alır.** Bayat paketi taze
> saymak, hedefi 14 m yanlış yerde aramaktır.

Bu yüzden yaş = **ulaşma yaşı + `saat_farki`**. `MAX_YAS_S = 1.5` aşılırsa
hedef **YOK** sayılır. Panel ikisini ayrı gösterir: `yas_ulasma` ve
`yas_veri`.

### 10.2 Neden UDP, neden TCP değil
5 Hz'lik bir konum akışında TCP'nin yeniden gönderimi **zararlıdır**:
kaybolan bir paketin geç gelen kopyası taze paketin önüne geçer ve güdüm
eski dünyaya nişan alır. Kaybolan paket **atılmalıdır**; bir sonrakisi
zaten 200 ms sonra geliyor.

### 10.3 Ölçüldü (29 Ağustos 2026)
Uçtan uca: **6 saniyede 60 paket (10 Hz), 0 red, yaş 0.1 s**
(ulaşma 0.06 + veri 0.04).

---

## 11 · GÜDÜM FAZLARI ve YARIŞMA KISITI

| faz | ne yapar |
|---|---|
| **İSTASYON** | Hedef görünmüyor — GPS ile yaklaş, takip istasyonuna otur |
| **GÖRSEL** | Hedef görünüyor — yalnız kutuyla kovala |
| ↳ **KİLİT** | Mesafeyi tut, kilit ölçütünü sağla |
| ↳ **TERMİNAL** | Son yaklaşma |

### ⛔ ÜSTÜN KISIT — yarışma kuralı

> **Görsel temas varken GPS güdümü YASAK.** Yalnız bbox kullanılır.
> Temas kesilince GPS serbest.

Bu yapısal olarak garanti edilmiştir: görsel döngü hedefe dair veriyi
devirde **bir kez sayı olarak** alır; canlı GPS erişimi **yoktur**.
Bir bekçi (`tests/test_bbox_ibvs.py` B5) bunu sınar.

---

## 12 · UÇUŞ PROSEDÜRÜ

> ⛔ **Yer testlerinde pervane ÇIKARILIR.** İstisnasız.

1. **Skydagger backend'i başlat** (Terminal 1) — `LINK` yeşil olacak
2. **Drone yer kontrolünü başlat** (Terminal 2) → `localhost:8810`
3. **Kamerayı doğrula** — FPV görüntüsü akıyor mu, çözünürlük uyarısı var mı
4. **GPS fix'i bekle** — uydu ≥ 10
5. **KÖKEN KUR** — araç yerde, hareketsiz
6. **Kumandayı sına** — çubukları oynat, panel joystickleri takip etmeli
7. **Yönleri doğrula** — Betaflight'ta roll/pitch/yaw doğru yönde mi
8. **Pervaneleri tak**, alanı boşalt
9. **ARM (BASILI TUT)** ve **MANUEL** ile havalan, uçağı tanı
10. **Talon'u uçur** ve hedef GPS'inin aktığını panelden doğrula
11. **OTONOM**'a geç — dört şart sağlanmalı
12. İzle: kutu var mı, faz ne, `girdi:` ne diyor
13. **İniş:** MANUEL'e al, elle indir, **DISARM**

**Otonomdan çıkmanın iki yolu:** panelde **MANUEL**, ya da **kumandada
çubuk oynatmak** — güdüm o tikte durur ve **kendiliğinden geri gelmez**
(mandallı, ölçüldü 2026-08-31). Otonoma dönüş yalnız panelden **OTONOM**.

---

## 13 · ACİL DURUMLAR

| durum | ne yap |
|---|---|
| Araç hedeften **kaçıyor** | MANUEL. Sonra `DOW_CEV_Y_ISARET=-1.0` ile yeniden dene |
| Otonom tuhaf davranıyor | Kumandada çubuk oynat — güdüm anında durur (mandallı) |
| Panel dondu | Kumanda zaten önceliklidir; kumandayla uçur |
| ELRS koptu | ESP32 son çerçeveyi ~200 ms tutar, sonra failsafe |
| Görüntü kesildi | Faz İSTASYON'a düşer, GPS ile devam eder |
| Kontrolsüz | ARM düğmesini bırak → disarm |

> ⛔ **Test bitince araçları havada KONTROLSÜZ BIRAKMA.**

---

## 14 · ARIZA ARAMA — hepsi yaşandı

| belirti | sebep | çözüm |
|---|---|---|
| Backend açılmıyor, "port in use" | Eski süreç 8765'i tutuyor | `./baslat_backend.sh` başındaki temizleme; ya da `--kapat` |
| Backend hiç çıktı vermiyor | readline TTY istiyor, boruda susuyor | Başlatıcı `script -qfec` ile sarmalıyor |
| Panelde **dizüstünün** kamerası çıkıyor | Yakalama kartı bulunamadı | `DOW_KAM_KAYNAK=/dev/video2` |
| `ls /dev/input/js*` boş | Kumanda USB kablosu | **Kabloyu değiştir** — bir kez bozuk çıktı |
| Panel joystickleri kumandayla oynamıyor | Eksen haritası yanlış | `python3 araclar/kumanda_kalib.py` |
| Panel bir süre sonra donuyor | *(çözüldü)* Chrome 6 bağlantı sınırı | Tek WebSocket'e geçildi |
| `uydu = 0`, `KÖKEN KUR` reddediyor | Kapalı ortam, fix yok | Dışarı çık; `kokeni_kur` haklı olarak reddediyor |
| Menzil tuhaf görünüyor | **Kamera optiği kalibre edilmemiş** | Bölüm 08 |
| Açılışta çözünürlük uyarısı | Kart ≠ kalibrasyon çözünürlüğü | `DOW_KAM_W/H` zorla ya da yeniden kalibre et |
| Hedef GPS'i gelmiyor | Talon tarafı kapalı, ya da IP yanlış | Talon'da `./baslat_talon.sh <port> <drone-ip>` |

---

## 15 · KAPALI KALAN İŞLER

| konu | durum |
|---|---|
| **Otonom uçuş** | ⛔ **YAPILMADI** |
| **Kamera optiği** | ⛔ Ölçülmedi — araç hazır, bölüm 08 |
| **Dedektör modeli** | Gerçek görüntüyle eğitiliyor (kullanıcı) |
| `MENZIL_C` dedektör fiti | Dedektör çalışınca gerçek kutulardan yeniden |
| `DOW_CEV_Y_ISARET` | Yer testinde doğrulandı; kesin kanıt ilk otonom uçuş |

---

## 16 · GÜVENLİK

1. **Yer testlerinde pervane çıkarılır.**
2. **Kumanda her zaman elde** — çubuğu oynatmak otonomu keser.
3. **Meskûn mahalde otonom uçuş yapılmaz.**
4. **KÖKEN uçuş ortasında değiştirilmez.**
5. **Kamera kalibre edilmeden otonom görsel güdüm denenmez.**
6. **Test bitince araçlar havada kontrolsüz bırakılmaz.**

---

*Kaynak: `reel/gercek/`, `reel/drone_yki.py` · Bekçiler:
`reel/tests/test_reel.py` (R1–R93) + `tests/test_dow.py` (69) ·
Güdüm yasası `dow/` altında DEĞİŞTİRİLMEDİ; `araclar/denklik.py` 400 tikte
bit bit doğruluyor.*
