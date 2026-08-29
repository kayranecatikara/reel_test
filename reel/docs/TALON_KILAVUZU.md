# TALON — TAM KILAVUZ
### Sabit kanatlı hedef İHA'nın yer istasyonundan kontrolü

> Bu belge, Talon'u hiç görmemiş birinin bile kutuyu açıp uçurabilmesi için
> yazıldı. Her terim ilk geçtiği yerde tanımlanır. Hiçbir adım "bilindiği
> varsayılarak" atlanmaz.
>
> **Son güncelleme:** 29 Ağustos 2026 · **Doğrulanma durumu:** yer testleri
> yapıldı (bağlantı, GPS fix, görev yükleme, ARM, AUTO, motor tetikleme).
> **Havada uçuş henüz yapılmadı.**

---

## 0 · Beş dakikada özet

```bash
cd ~/projects/drones_of_war_entegrasyon/reel
./baslat_talon.sh
```
→ Tarayıcıda **http://localhost:8000**. Başka hiçbir yere gitmen gerekmiyor.

| yaparsın | nerede |
|---|---|
| Hazır şekil uçurmak (kare, daire, elips) | arayüzün **Şekil çiz** bölümü |
| Harita üstünde kendi rotanı çizmek | **GÖREV PLANLAMA — HARİTA** düğmesi |
| Elle uçurmak | **MANUEL KONTROL** düğmesi |
| Acil durdurmak | **RTL** ya da **ACİL — MOTORU DURDUR** |

---

## 1 · Sistem nedir — parça parça

### 1.1 Fiziksel zincir

```
[Pixhawk uçuş kontrolcüsü]        uçağın içinde, otopilot
        │
        │ SiK telemetri telsizi (433/915 MHz, 57600 baud)
        ▼
[USB telemetri modülü]            senin laptopunda
        │
        ▼
[yayinci.py]                      seri portu AÇAN tek program
        │
        ├──► udp:14552   arayüzün kendisi
        ├──► udp:14550   arayüzün alt süreçleri (uçuş öncesi kontrol vb.)
        ├──► udp:14554   görev planlayıcı (harita)
        └──► udp:47800   drone bilgisayarı — 5 Hz hedef konumu
```

**Neden aracı bir dağıtıcı var:** bir seri portu aynı anda **tek** program
açabilir. Arayüz doğrudan açsaydı, planlayıcı ve drone bilgisayarı aynı
telemetriyi göremezdi. `yayinci.py` portu tek başına açar ve gelen her
MAVLink paketini dört yere kopyalar.

**⛔ Her tüketiciye AYRI port.** Aynı UDP portuna iki program bağlanırsa
işletim sistemi çekirdeği her paketi yalnız **birine** verir. İkisi de
paketlerin yarısını görür, ikisi de hata vermez. Telemetri "biraz seyrek"
görünür ve sebebi asla anlaşılmaz. *(18 Ağustos 2026'da yaşandı.)*

### 1.2 Terimler

| terim | ne demek |
|---|---|
| **MAVLink** | Otopilotla yer istasyonu arasındaki mesaj dili. Her mesajın bir tipi var (HEARTBEAT, GLOBAL_POSITION_INT…). |
| **HEARTBEAT** | Otopilotun saniyede birkaç kez "buradayım, şu moddayım, arm'lıyım/değilim" demesi. Bağlantının canlı olduğunu bundan anlarız. |
| **ARM** | Motorun dönmesine izin verilmesi. DISARM = motor kilitli, ne olursa olsun dönmez. |
| **Uçuş modu** | Otopilotun o an hangi kurala göre uçtuğu (elle, yarı otomatik, tam otomatik…). Bölüm 5. |
| **Waypoint** | Görev noktası — uçağın sırayla gideceği bir GPS koordinatı + irtifa. |
| **Görev (mission)** | Waypoint'lerin sıralı listesi. Otopilotun hafızasına yazılır. |
| **EV noktası (home)** | Kalkış yeri. Bütün görev buna GÖRE kurulur; RTL buraya döner. |
| **GPS fix** | GPS'in konumu gerçekten çözmüş olması. `3D-11` = üç boyutlu çözüm, 11 uydu. Fix yokken koordinatlar 0,0 gelir. |
| **RTL** | Return To Launch — eve dön. |
| **Failsafe** | Bağlantı kesilince otopilotun kendiliğinden yaptığı şey. |
| **Telemetri** | Uçaktan yere akan durum verisi (konum, hız, irtifa, batarya…). |

### 1.3 Programlar

| program | port | işi |
|---|---|---|
| `talon/yayinci.py` | — | Seri portu açar, MAVLink'i dört yere aynalar, drone'a 5 Hz hedef konumu yayınlar |
| `talon/arayuz` (`gcs.sunucu`) | **8000** | Ana yer kontrol arayüzü |
| `talon/gorev_plani.py` | **8010** | Harita üstünde waypoint planlayıcı |
| `talon/baglanti_testi.py` | — | Bağlantı arızasını beş katmanda teşhis eder |
| `talon/kalkis_ayari.py` | — | Kalkış parametrelerini okur/yazar, ölü zamanı hesaplar |
| `talon/atis_testi.py` | — | Elden atış algılamasını ölçer (arm etmeden, pervanesiz) |
| `talon/karo.py` | — | Çevrimdışı harita karolarını indirir/saklar |

---

## 2 · Donanım ve kablolama

### 2.1 Uçakta
- **Pixhawk** uçuş kontrolcüsü, ArduPlane 4.7 yüklü
- **SiK telemetri telsizi** (uçak tarafı) — Pixhawk'ın TELEM1 portunda
- **GPS + pusula** modülü
- **LiPo pil** — 6S (panelin 20.4 V iniş eşiği bunu gösteriyor: 3.4 V/hücre)
- **Pitot (hava hızı) sensörü YOK** — bunun sonuçları için §6.4
- Pervane: **yer testlerinde ÇIKARILIR**

### 2.2 Yerde
- Laptop
- **SiK telemetri telsizi** (yer tarafı) — USB ile laptopa
- Kumanda (Radiomaster) — iptal yolu olarak **her zaman elde ve açık**

### 2.3 Bağlantı sırası
1. Telemetri modülünü laptopa tak
2. Uçağa pil bağla
3. İki telsizin de yeşil/mavi LED'i **sabit** yanmalı — yanıp sönüyorsa
   eşleşmemişler demektir

Portu gör:
```bash
ls -l /dev/serial/by-id/
```
Bir satır çıkmalı. Çıkmıyorsa kabloyu değiştir (kablo arızası bu projede
bir kez yaşandı ve saatler yedi).

---

## 3 · Kurulum (her bilgisayarda BİR KEZ)

```bash
# 1) Depoyu al
cd ~/projects
git clone <depo-adresi> drones_of_war_entegrasyon
cd drones_of_war_entegrasyon/reel

# 2) Paketler
pip install -r requirements.txt
pip install -r talon/arayuz/requirements.txt

# 3) Seri port izni — ÇIKIP TEKRAR GİRMEK ŞART
sudo usermod -aG dialout $USER

# 4) ModemManager'ı kapat
#    Bu servis her yeni seri porta AT komutu gönderip "modem mi?" diye
#    yoklar. Pixhawk'ın MAVLink akışını bozar.
sudo systemctl disable --now ModemManager
```

### 3.1 Haritayı önceden indir (ÖNEMLİ)

Sahada internet olmayabilir. Uçuş alanının karolarını **evde** indir:

```bash
cd ~/projects/drones_of_war_entegrasyon/reel/talon
python3 gorev_plani.py --indir 41.002892,28.656232 --yaricap 2000 --z 14-17
```

Koordinatı Google Maps'te alana **sağ tıklayarak** alırsın (en üstteki sayı
çifti, tıklayınca kopyalanır).

| yarıçap | zoom | karo | boyut | süre |
|---|---|---|---|---|
| 1 km | 14-17 | ~324 | ~6 MB | ~1 dk |
| 2 km | 14-17 | ~740 | ~15 MB | ~1 dk |
| 2 km | 14-18 | ~2261 | ~45 MB | ~5 dk |

**Zoom ne demek:** haritanın kaç kat yakınlaştığı. 41° enlemde:

| zoom | 1 piksel | 1 karo |
|---|---|---|
| 14 | 7.2 m | 1843 m |
| 15 | 3.6 m | 922 m |
| 16 | 1.8 m | 461 m |
| 17 | 0.9 m | 230 m |
| 18 | 0.4 m | 115 m |

Aralık indirdiğin için hepsi çalışır; uzaktan bakarken düşük zoom, waypoint
koyarken yüksek zoom kullanılır.

Karolar `~/.skydagger/karolar` altında durur. Sahada telefonu hotspot
yaparsan aynı komut orada da çalışır.

---

## 4 · Başlatma — tek komut

```bash
cd ~/projects/drones_of_war_entegrasyon/reel
./baslat_talon.sh
```

Çıktı şöyle olmalı:
```
YAYINCI: /dev/serial/by-id/...  ->  udp:14552 + udp:14550 + udp:14554 + udp://...:47800
HARİTA : http://localhost:8010   (görev planlayıcı)
ARAYÜZ : http://localhost:8000
```

**Üç süreç birden açılır.** `Ctrl+C` üçünü birden kapatır.

Seçenekler:
```bash
./baslat_talon.sh /dev/ttyUSB0 192.168.1.50   # port ve drone IP'sini elle ver
./baslat_talon.sh --sahte 192.168.1.50        # Pixhawk yokken (sahte hedef)
./baslat_talon.sh --kapat                     # yalnız kapat
```

**Tamam ölçütü:** arayüzde `BAĞLANTI: BAĞLI`, telemetri sayıları akıyor.

Akmıyorsa:
```bash
cd ~/projects/drones_of_war_entegrasyon/reel/talon
python3 baglanti_testi.py
```
Beş katmanı sırayla söyler: port var mı → açılıyor mu → bayt geliyor mu →
MAVLink çözülüyor mu → hangi mesajlar geliyor. Zincirin nerede koptuğunu
tam olarak gösterir.

---

## 5 · UÇUŞ MODLARI — tek tek

Uçuş modu, otopilotun o an **hangi kurala göre** uçtuğudur. Panelin
**UÇUŞ MODU** satırından değiştirilir.

### MANUAL
Kumanda çubukları doğrudan kumanda yüzeylerine gider. Otopilot **hiçbir
şey yapmaz** — ne dengeler, ne sınırlar. Uçak neye ayarlıysa öyle uçar.
- **Ne zaman:** otopiloda güvenmediğin an; acil iptal yolu.
- **Risk:** her şey senin elinde. Uçağı elle uçurmayı bilmiyorsan burada
  düşürürsün.

### STAB (STABILIZE)
Çubukları bıraktığında uçak **kanatlarını düzler ve burnunu yatay tutar**.
Çubuk verdiğinde istediğin gibi döner. Yani "bıraktığında kendini toparlar".
- **Ne zaman:** elle uçarken güvenli seçenek.
- **Sınırı yok:** çubuğu sonuna kadar itersen uçak devrilebilir.

### FBWA (Fly-By-Wire A) ⭐ elle uçuşun varsayılanı
"Kablo ile uçuş". Çubuk artık *kumanda yüzeyini* değil, **istenen açıyı**
söyler. Aileron çubuğunu yarıya itmek "yarım yatış açısı istiyorum" demektir.
Otopilot o açıyı tutar ve **sınırların dışına çıkmana izin vermez**.
- Yatış sınırı: `ROLL_LIMIT_DEG`
- Burun yukarı/aşağı sınırı: `PTCH_LIM_MAX_DEG` / `PTCH_LIM_MIN_DEG`
- **Ne zaman:** elle uçmanın en güvenli hali. Yeni pilot burada uçar.
- **Gaz sende** — otopilot gazı yönetmez.

### LOITER
Uçak **bulunduğu noktanın etrafında daire çizerek bekler**. Sen hiçbir şey
yapmazsın.
- **Ne zaman:** "düşünmem lazım" anı. Görev durdurmanın doğru yolu.
- Daire yarıçapı `WP_LOITER_RAD` parametresiyle belirlenir.

### AUTO
Otopilot **yüklü görevi** baştan sona kendi uçar: kalkış, waypoint'ler,
görev sonu davranışı.
- **Ne zaman:** asıl uçuş.
- ⚠ Panelin mod satırında AUTO **düğmesi yoktur** — AUTO'ya `BAŞLAT`
  düğmeleriyle geçilir (§6.5). Bu bilinçli: AUTO'ya girmek "görevi başlat"
  demektir ve yanlışlıkla basılmamalıdır.

### RTL (Return To Launch)
Eve döner ve **çember çizerek bekler**. Kendiliğinden inmez —
ancak görevde `DO_LAND_START` varsa ve `RTL_AUTOLAND` açıksa iner.
- **Ne zaman:** acil. Panelde sarı **RTL — EVE DÖN** düğmesi.

### AUTOLAND (ArduPlane 4.6+)
Uçak nerede olursa olsun **kalktığı yere iner**: base leg + final + flare
paternini kendisi kurar. Panelde **🛬 ŞİMDİ İN — KALKIŞ YERİNE**.

**⛔ İKİ ŞARTI VAR, ikisi de sağlanmazsa mod sessizce reddedilir:**
1. **Uçak UÇUYOR olmalı.** Yerdeyken "Must already be flying!" der.
2. **Kalkış yönü YAKALANMIŞ olmalı.** Yön, uçuş sırasında GPS yer
   rotasından alınır ve yalnız bazı modlar yakalar: **AUTO, FBWA, MANUAL,
   TAKEOFF, ACRO, STABILIZE, TRAINING, AUTOTUNE**. LOITER / CRUISE / FBWB /
   RTL **yakalamaz**. Ve **DISARM yön kaydını SİLER** — her uçuşta yeniden
   yakalanması gerekir.

Panelin **Otomatik iniş — hazır mı** bölümü tam bunu gösterir. "Kalkış
yönü: henüz yakalanmadı" yazıyorsa AUTOLAND çalışmaz.

### AUTOTUNE
Uçuş modu **değil**, bir öğrenme anahtarıdır — mod değişmez. Açıkken
otopilot senin çubuk hareketlerine bakarak kendi PID kazançlarını ayarlar.
- Yalnız **AUTO, FBWA, FBWB, LOITER** modlarında kabul edilir. MANUAL/CRUISE'da
  otopilot "Autotuning not allowed in this mode!" yazar.
- **Açıkken çubukları SERT oynat** — yumuşak hareketten öğrenemez.
- **İnişten önce KAPAT.**

---

## 6 · ARAYÜZ — her özellik tek tek

### 6.1 Üst telemetri şeridi

| alan | ne gösterir | neye dikkat |
|---|---|---|
| **BAĞLANTI** | MAVLink akıyor mu | `BAĞLI` değilse hiçbir şey yapma |
| **ARM** | motor kilidi | `disarm` = motor dönmez |
| **MOD** | o anki uçuş modu | §5 |
| **BATARYA** | volt ve yüzde | 20.4 V'ta otomatik iniş devreye giriyor (panelde yazılı) |
| **GPS** | fix tipi ve uydu sayısı | `3D-11` iyi. `3D` ve **≥10 uydu** olmadan görev yükleme |
| **İRTİFA** | EV noktasına göre yükseklik | yerde 0 m |
| **HIZ** | yer hızı | pitot yok, bu GPS hızıdır |
| **GAZ** | motor yüzdesi | yerde %0 |
| **GÖREV** | yüklü şeklin adı ve aktif öğe | `KARE #1` = kare görevi, 1. öğede |

### 6.2 3B panel (sağ üst)
Uçağın konumunu, rotayı ve ufku üç boyutlu gösterir.
- **sürükle** → döndür · **tekerlek** → yakınlaş · **sığdır** → hepsini çerçevele
- `eve <x> · irtifa <y>` — eve uzaklık ve yükseklik

### 6.3 MANUEL KONTROL
Ekranda iki sanal joystick açar; kumanda yokken uçağı arayüzden uçurmanı
sağlar.

**⛔ AUTO modundayken REDDEDİLİR.** Sebep: `STICK_MIXING=1` parametresi
yüzünden RC girdisi AUTO'nun navigasyon çıkışına **karışır**. Sessizce
AUTO'dan çıkmak yerine arayüz açıkça reddediyor: *"GPS görevi uçuyor —
önce GÖREVİ DURDUR'a basın."*

İçindeki düğmeler: ARM / DISARM · gazı sıfırla · RTL · ŞİMDİ İN · ACİL.

### 6.4 GÖREV PLANLAMA — HARİTA
Harita planlayıcıyı yeni sekmede açar (§7).

⚠ **Şekil görevi ile harita görevi AYNI ARACA yazar. Son yüklenen
geçerlidir.** Arayüz araçtaki görevi geri okumadığı için ikisini karıştırmak
kolaydır — hangisinin yüklü olduğunu planlayıcıdan teyit et.

### 6.5 Şekil çiz — GPS görevi

**KARE / DAİRE / ELİPS** — hazır rota şekilleri.

| alan | ne |
|---|---|
| Kenar (m) / Yarıçap (m) | şeklin boyutu |
| Kısa eksen (m) | yalnız elipste |
| İrtifa (m) | waypoint yüksekliği |
| Tur (0=∞) | şeklin kaç kez uçulacağı |
| Yön (°) | şeklin kuzeye göre döndürülmesi |
| Merkez | **Kalkış noktası** ya da **Uçağın şu anki konumu** |

**Görev bitince:** `EVE DÖN (RTL)` · `BEKLE (LOITER)` · `OTOMATİK İN`

Altındaki özet satırı gerçek sayıları verir:
*"çevre 1000 m · aralık 250 m · kabul 60 m · en dar kıvrım 125 m · eve en
fazla 177 m · ~3 dk"* — **en dar kıvrım**, uçağın dönüş yarıçapından küçükse
o şekil uçulamaz.

**Düğmeler:** `GÖREVİ YÜKLE` → `BAŞLAT` → `GÖREVİ DURDUR` → `GÖREVİ SİL`

**⚠ BİLİNEN DAVRANIŞ — GPS uyarısı DONABİLİR.** "GPS fix yok (fix=0, 0 uydu)"
uyarısı ve `GÖREVİ YÜKLE` kilidi yalnız **sen bir alana dokununca**
tazelenir, telemetri döngüsünde değil. Sayfayı fix gelmeden açtıysan uyarı
donmuş kalır. **Çözüm: KARE düğmesine bir kez bas** (ya da F5).

**⚠ BİLİNEN DAVRANIŞ — arayüz aracı GERİ OKUMAZ.** `BAŞLAT` yalnız
*arayüzün kendi yüklediği* göreve bakar. Harita planlayıcıdan yüklenen görev
araçta olsa bile arayüz "Araçta yüklü görev yok" der ve `BAŞLAT` kapalı
kalır. **Harita görevini planlayıcının kendi BAŞLAT'ıyla başlat.**

### 6.6 Otomatik iniş — hazır mı
AUTOLAND'in dört şartını canlı gösterir:

| satır | ne demek |
|---|---|
| Patern / çit | iniş paterninin boyu / güvenlik çiti |
| Süzülme | süzülme açısı (ör. 7.1°, nominal 4.8°) |
| **Kalkış yönü** | **yakalandı mı** — "henüz yakalanmadı" ise AUTOLAND ÇALIŞMAZ |
| Batarya 2. kademe | düşük voltajda ne olacak (ör. OTOMATİK İNİŞ @ 20.4 V) |

### 6.7 ARM / DISARM ve uçuş öncesi
- **ARM** — motora izin ver. Otopilot kendi ön kontrollerini yapar;
  reddederse sebebini **Otopilot mesajları** bölümünde yazar.
- **DISARM** — motoru kilitle. *Kalkış yönü kaydını da SİLER (§5 AUTOLAND).*
- **UÇUŞ ÖNCESİ KONTROL** — ayrı bir program çalıştırıp tam rapor basar
  (sensörler, GPS, pusula, batarya, parametreler).
- **RTL — EVE DÖN** (sarı) — acil dönüş.
- **🛬 ŞİMDİ İN — KALKIŞ YERİNE** — AUTOLAND.

### 6.8 Otopilot mesajları
Uçaktan gelen ham metin mesajları (STATUSTEXT). ARM reddedildiğinde,
mod değişmediğinde, bir şey ters gittiğinde **sebep buradadır**.
Örnek: `PreArm: In landing sequence` — görev son öğede (RTL) takılı kalmış;
başlangıç öğesini sabitlemek gerekir (§7.4).

### 6.9 ACİL
**⚠ ACİL — MOTORU DURDUR (DISARM) ⚠** — motoru anında kilitler.

**⛔ HAVADAYKEN BU DÜĞMEYE BASMA.** Motor durur ve uçak süzülerek düşer.
Havadaki acil yolun **RTL** ya da **MANUAL**'dir. Bu düğme yerdeki
acil içindir (pervane dönerken biri yaklaştı gibi).

---

## 7 · HARİTA PLANLAYICI (localhost:8010)

### 7.1 Neden ayrı
Hazır şekiller (kare/daire) alanı tanımıyor. Gerçek arazide "şu ağacın
solundan geç, şu binadan uzak dur" demek için haritaya bakarak nokta
koymak gerekir.

### 7.2 Üst rozetler
`MAVLINK <paket sayısı>` · `EV ✔` · `KARO <sayı>` · `<MOD> · ARMLI/DISARM` ·
`<n> nokta`

### 7.3 Harita
- **tıkla** → waypoint ekle · **sürükle** → kaydır · **sağ tık** → son
  noktayı sil · **tekerlek / + −** → yakınlaş · **⌖** → EV noktasına dön
- **yeşil daire** = EV noktası · **sarı ok** = uçağın konumu ve pusula yönü ·
  **mavi numaralı daireler** = waypoint'ler, aralarındaki çizgi rota
- Sağ altta **ölçek çubuğu**, sol altta OpenStreetMap künyesi
- Harita **tamamen çevrimdışıdır**; karoları indirilmemiş bölge koyu görünür
  ve ekranda "⚠ bu bölgenin karoları indirilmemiş" yazar

⚠ **Noktaların uzaklığına bak.** Sağdaki tabloda her noktanın `kuzey`,
`doğu`, `irtifa` ve `uzaklık` değeri var. Yanlışlıkla konmuş bir nokta
kilometrelerce uzakta olabilir — yüklemeden önce tabloyu oku.

### 7.4 Görev bölümü

| alan | ne |
|---|---|
| Kalkış irtifası (m) | TAKEOFF öğesinin hedef yüksekliği |
| Varsayılan waypoint irtifası (m) | yeni konan noktaların irtifası |
| Görev bitince | `EVE DÖN (RTL)` ya da `HAVADA BEKLE (LOITER)` |

**GÖREVİ YÜKLE** — görevi kurar ve araca yazar. Kurulan liste:
```
0  EV noktası
1  TAKEOFF          (kalkış irtifasına tırman)
2..n  WAYPOINT      (senin noktaların)
n+1  RTL / LOITER   (görev bitince)
```
3 waypoint → 6 öğe. 7 waypoint → 10 öğe.

**GÖREVİ BAŞLAT (AUTO)** — onay sorar, sonra üç işi sırayla yapar:

1. **`mission_set_current(1)`** — başlangıç öğesini sabitler.
   *Neden:* `MIS_RESTART=0` olduğu için AUTO'ya girmek görevi **kaldığı
   yerden** sürdürür; sen baştan başlayacağını sanırsın. Ayrıca son öğede
   (RTL) takılı kalmak, aracın **"PreArm: In landing sequence"** deyip
   ARM'ı reddetmesine yol açar.
2. **Yerdeyken zaten AUTO'daysan araya FBWA sokar.**
   *Neden:* araç zaten AUTO'daysa "AUTO'ya geç" komutu hiçbir şey yapmaz;
   ArduPlane'in elden-atış tetikleyicisi (`auto_takeoff_check`) **hiç
   çalışmaz**. Uçak arm'lı halde yerde bekler ve `DISARM_DELAY` dolunca
   kendiliğinden disarm olur. *(SITL'de ölçüldü: 600 saniye boyunca
   irtifa 0.)*
   **Havadayken YAPILMAZ** — uçuş ortasında moddan çıkmak rotayı bozar.
3. **AUTO'ya geçer ve HEARTBEAT ile DOĞRULAR.**
   *Neden:* `set_mode` komutunun onayı (ACK) yoktur. Tek gönderimde paket
   düşerse komut sessizce kaybolur. SiK telsizinde paket kaybı normaldir,
   bu yüzden birkaç kez denenip aracın bildirdiği mod okunur.

Uçak **havadaysa** kalkış adımı atlanır, görev ilk waypoint'ten başlar.

`GÖREVİ BAŞLAT` gri ise **üstüne gel** — neden kapalı olduğunu yazar
(bağlantı yok / görev yüklenmedi / araç ARM değil).

**DURDUR (LOITER)** — uçak bulunduğu yerde tur atarak bekler.
**ARAÇTAKİ GÖREVİ SİL** — otopilotun hafızasındaki görevi siler.

### 7.5 Harita önbelleği
Kaç karo, kaç MB, hangi dizin. **ALANI İNDİR** düğmesi seçtiğin yarıçap ve
zoom aralığını indirir (ilerleme çubuğuyla). İki indirme aynı anda
çalışamaz — OpenStreetMap gönüllü sunucularıdır, saniyede ~8 istekten
fazlası IP engeline yol açar.

---

## 8 · ELDEN ATIŞLA KALKIŞ

> **⛔ EN KRİTİK BÖLÜM.** Bu uçak daha önce **iki kez tam atış anında
> düştü.** Sebebi ölçüldü ve giderildi; aşağıdakiler o ölçümlerin sonucu.

### 8.1 Neden düşüyordu — aritmetik

Elden attığında motor hemen çalışmaz. Arada geçen süreye **ölü zaman**
diyoruz:

```
ölü zaman = TKOFF_THR_DELAY × 0.1 s  +  TKOFF_THR_MAX / THR_SLEWRATE
            ───────────────────────     ─────────────────────────────
            atış algılandıktan          gazın 0'dan tam açılmaya
            sonraki bekleme             çıkması için geçen süre
```

**Eskiden:** `THR_SLEWRATE = 83 %/s` idi → `100/83 = 1.20 s`.
Motorsuz 1.20 saniyede uçak **7.1 m** düşebilir. Elden atış yüksekliğin
**1.7 m**. Yani uçak yere çarpmadan motorun çalışması **mümkün değildi.**

**Şimdi:** `THR_SLEWRATE = 0` (= sınır yok, gaz **anında** tam açılır) →
ölü zaman **0.20 s** (yalnız yazılım). Motor ve pervane ataleti dahil
gerçekte ~0.5 s.

### 8.2 Atış hızı — ikinci şart

Motor çalışsa bile uçağın **uçabilecek hıza** ulaşması gerekir. Enerji açığı:

```
h = (v_min² − v_atış²) / (2g)
```
`v_min` = uçağın uçabildiği en düşük hız (`AIRSPEED_MIN`), `v_atış` = senin
attığın hız, `g` = 9.81 m/s².

`AIRSPEED_MIN = 15 m/s` iken **gereken atış hızı ≥ 13.8 m/s**.
Bu, **sert bir atıştır** — hafifçe salıvermek yetmez.

### 8.3 Atış algılama eşiği

Otopilot, ivmeölçerden gelen ileri ivme `TKOFF_THR_MINACC` değerini
aşınca "atıldım" der.

**Senin ölçümün** (`atis_testi.py`, 29 Ağustos 2026):
- eşik: **11.0 m/s²**
- tepe ivme: **15.7 m/s²** — 5 atışın 4'ü algılandı
- bir atış **11.7** ile sınırda kaldı → **zayıf atma**

### 8.4 Kalkış parametreleri — her biri ne yapıyor

| parametre | değer | ne yapar |
|---|---|---|
| `TKOFF_THR_MINACC` | 11 m/s² | atış algılama eşiği |
| `TKOFF_THR_DELAY` | 0-2 (×0.1 s) | atış algılandıktan sonra gazı açmadan önceki bekleme |
| `TKOFF_THR_MAX` | 100 % | kalkışta gidilecek gaz |
| **`THR_SLEWRATE`** | **0** | gazın saniyede en fazla kaç % değişebileceği. **0 = sınır yok = anında** |
| `TKOFF_LVL_PITCH` | 12° | ilk tırmanışta tutulacak burun açısı |
| `TKOFF_LVL_ALT` | — | bu irtifaya kadar kanatlar düz tutulur |
| `TKOFF_ALT` | — | kalkışın biteceği irtifa |
| `AIRSPEED_MIN` | 15 m/s | uçabildiği en düşük hız (stall payı buradan gelir) |
| `AIRSPEED_CRUISE` | — | seyir hızı |
| `PTCH_LIM_MAX/MIN_DEG` | — | burun yukarı/aşağı sınırları |
| `ROLL_LIMIT_DEG` | — | yatış sınırı |
| `TKOFF_TIMEOUT` | — | kalkış bu sürede olmazsa iptal |
| `ARSPD_TYPE` | — | hava hızı sensörü tipi. **Pitot yok → 0 olmalı** |
| `ARSPD_USE` | — | hava hızı güdümde kullanılıyor mu |

Hepsini oku ve ölü zamanı hesapla:
```bash
cd ~/projects/drones_of_war_entegrasyon/reel/talon
python3 kalkis_ayari.py
```
Değiştirmek için:
```bash
python3 kalkis_ayari.py --yaz THR_SLEWRATE=0
```
(onay sorar)

**⛔ Ölü zaman 1 saniyenin üstündeyse ATMA.**

### 8.5 Nasıl atmalısın

1. **Rüzgâra karşı** dur
2. Uçağı **iki elinle gövdeden** tut
3. **Koş** ve **sert** at
4. **Düz ileri, burun ~10° yukarı**
   - ⛔ **Dik yukarı ATMA** — burun ne kadar dikse hız o kadar çabuk
     kaybolur, uçak stall eder ve düşer
   - ⛔ **Aşağı doğru atma** — irtifa zaten yok
5. Attıktan sonra **elini çek**, uçağa dokunma
6. Gaz ~0.5 s içinde tam açılır

---

## 9 · UÇUŞ PROSEDÜRÜ — adım adım

### ADIM 1 — Kurulum
Telemetriyi tak, uçağa pil bağla, `./baslat_talon.sh`, **localhost:8000** aç.
✅ `BAĞLANTI: BAĞLI`

### ADIM 2 — GPS fix
Uçağı açık gökyüzü altına koy, 1-3 dakika bekle.
✅ `GPS: 3D` ve **uydu ≥ 10**

Uyarı donmuşsa **KARE**'ye bir kez bas.

### ADIM 3 — Kalkış parametreleri
```bash
python3 talon/kalkis_ayari.py
```
✅ Ölü zaman **≈ 0.20 s**, `THR_SLEWRATE = 0`, `TKOFF_THR_MAX = 100`

### ADIM 4 — Uçuş öncesi kontrol
Arayüzde **UÇUŞ ÖNCESİ KONTROL**. Raporu oku, kırmızı satır kalmasın.

### ADIM 5 — Görev
Ya arayüzden hazır şekil, ya **GÖREV PLANLAMA — HARİTA**'dan kendi rotan.
- Waypoint tablosundaki **uzaklıkları oku** — yanlış nokta var mı?
- Rota **boş alanın üstünde** mi?
- **GÖREVİ YÜKLE**
✅ "✔ n öğe yüklendi"

### ADIM 6 — Son fiziksel kontrol
- Pervane **takılı ve sıkı**, dönme yönü doğru
- Kumanda yüzeyleri kumandayla oynuyor, yönler doğru
- **Kumanda açık ve elinde** — iptal yolun bu
- Rüzgâr yönü belli, **rüzgâra karşı** atacaksın
- Önünde ≥ 50 m boş alan, **insan yok**

### ADIM 7 — ARM
Arayüzden **ARM**. Motor **dönmez** — bu normal, atış bekleniyor.
Reddedilirse **Otopilot mesajları**'nı oku.

### ADIM 8 — BAŞLAT
- Şekil görevi → arayüzdeki **BAŞLAT**
- Harita görevi → planlayıcıdaki **GÖREVİ BAŞLAT (AUTO)**

✅ `MOD: AUTO` ve *"AUTO'ya geçildi — motor, uçağı ATTIĞINIZDA dönmeye
başlar (fırlatma ivmesi bekleniyor)."*

### ADIM 9 — AT
§8.5'e göre. Attıktan sonra elini çek.

### ADIM 10 — Uçuş
- 3B panelden ve telemetriden takip et
- Ters giderse: **RTL** → eve döner, ya da kumandadan **MANUAL** → sen uçur

### ADIM 11 — İniş
- **🛬 ŞİMDİ İN** (AUTOLAND) — kalkış yönü yakalanmışsa
- ya da elle FBWA/MANUAL

### ADIM 12 — Kapanış
**Önce DISARM**, sonra pil. Terminalde `Ctrl+C`.

---

## 10 · ACİL DURUMLAR

| durum | ne yap |
|---|---|
| Uçak yanlış yöne gidiyor | **RTL — EVE DÖN** |
| RTL de çalışmıyor | Kumandadan **MANUAL**, elle uçur |
| Otonom uçuşu durdurmak | **GÖREVİ DURDUR** / **DURDUR (LOITER)** → çember çizip bekler |
| Yerde pervane dönüyor, biri yaklaştı | **⚠ ACİL — MOTORU DURDUR** |
| Batarya düşük | 20.4 V'ta otomatik iniş devreye girer; beklemeden **RTL** |
| Telemetri koptu | Failsafe devreye girer. Arayüzün belgesine göre bu kurulumda `FS_LONG_ACTN=1` (RTL) — **uçuştan önce `kalkis_ayari.py` ile teyit et** |

**⛔ HAVADAYKEN ACİL DISARM'A BASMA.** Motor durur, uçak düşer.

---

## 11 · ARIZA ARAMA — hepsi yaşandı

| belirti | sebep | çözüm |
|---|---|---|
| `/dev/serial/by-id/` boş | kablo arızası ya da modül takılı değil | **kabloyu değiştir** — bu bir kez saatler yedi |
| Telemetri hiç gelmiyor | ModemManager seri porta AT komutu basıyor | `sudo systemctl disable --now ModemManager` |
| Telemetri seyrek/kesik | iki program aynı UDP portunda | her tüketiciye ayrı port (§1.1) |
| "GPS fix yok (fix=0, 0 uydu)" ama üstte `3D-11` | uyarı donmuş, telemetride tazelenmiyor | **KARE**'ye bas ya da F5 |
| `BAŞLAT` gri, "Araçta yüklü görev yok" | arayüz araçtaki görevi geri okumaz | harita görevini **planlayıcının** BAŞLAT'ıyla başlat |
| `PreArm: In landing sequence` | görev son öğede (RTL) takılı | planlayıcının BAŞLAT'ı `mission_set_current(1)` gönderip temizler |
| ARM'lı, AUTO'da, yerde bekliyor, motor dönmüyor | zaten AUTO'daydı, kalkış tetiği hiç çalışmadı | planlayıcının BAŞLAT'ı araya FBWA sokarak çözer |
| Joystick açılmıyor | AUTO modunda, `STICK_MIXING=1` | önce **GÖREVİ DURDUR** |
| AUTOLAND reddediliyor | uçmuyor ya da kalkış yönü yakalanmamış | §5 AUTOLAND; DISARM yön kaydını siler |
| Autotune reddediliyor | MANUAL/CRUISE'da | AUTO/FBWA/FBWB/LOITER'a geç |
| Harita siyah | o bölgenin karoları indirilmemiş | **ALANI İNDİR** ya da `--indir` |
| Panel 8010 açılmıyor | planlayıcı düşmüş | `logs/gorev_plani.log` |

**Bağlantı arızasında ilk komut:**
```bash
python3 talon/baglanti_testi.py
```

---

## 12 · KAPALI KALAN İŞLER

| konu | durum |
|---|---|
| **Havada uçuş testi** | ⛔ **YAPILMADI.** Bu belgedeki her şey yer testiyle doğrulandı |
| `AIRSPEED_MIN = 15` | tahmin. Talon'un gerçek stall hızı ilk uçuştan ölçülecek |
| `ARSPD_TYPE` | pitot yokken 0 olmalı — teyit edilecek |
| `TKOFF_THR_MINACC` 11 → 9 | zayıf atışta pay bırakır; kararı ilk uçuş sonrası |
| Arayüzün görev geri okuması | yukarı akış davranışı; düzeltmek vendored kodu ayrıştırır |

---

## 13 · GÜVENLİK — pazarlığa açık değil

1. **Yer testlerinde pervane ÇIKARILIR.**
2. **Kumanda her zaman açık ve elde.** Tek gerçek iptal yolu.
3. **Meskûn mahalde otonom uçuş yapılmaz.** SHGM kuralları ve düşme riski.
   Uçuş alanı: insan, araç, bina ve yoldan uzak, açık arazi.
4. **Havadayken ACİL DISARM'a basılmaz.**
5. **Ölü zaman > 1 s ise atılmaz.**
6. **Kimse uçağın önünde durmaz.**

---

*Kaynak: `reel/talon/`. Bekçiler: `reel/tests/test_reel.py` (R1–R89).
Arayüz `talon_arayuz` deposundan alındı (commit 1e03e60); yerel
değişiklikler `reel/talon/arayuz/KAYNAK.md`'de yazılıdır.*
