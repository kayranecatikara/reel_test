# GERÇEK ORTAM YER KONTROL SİSTEMİ — Avcı Drone + Hedef Talon

Simülasyonda geliştirilmiş **GPS güdümü** ve **görsel (IBVS) güdümü**, gerçek
donanımda çalıştırmak için. İki bilgisayar, iki araç, tek görev.

> **Bu belgeyi hiç bilmeyen biri baştan sona okuyup sistemi çalıştırabilir.**
> Terimler ilk geçtikleri yerde tanımlanır; her komut olduğu gibi yazılıdır.

---

## 0 · Sistem tek bakışta

```
 ┌─ BİLGİSAYAR 1 — TALON ────────────┐   ┌─ BİLGİSAYAR 2 — DRONE ───────────┐
 │                                    │   │                                   │
 │  Pixhawk ─SiK telsiz─> yayinci.py  │   │  ELRS ─CRSF─> drone_yki.py        │
 │                          │         │   │  kumanda ─USB─>    │              │
 │              ┌───────────┴──────┐  │   │  kamera ─USB─>     │              │
 │              │                  │  │   │                    ▼              │
 │       udp:14550           udp:47800 ───────────────>  hedef GPS (5 Hz)     │
 │              │                     │   │                    │              │
 │       talon_arayuz                 │   │             panel :8810           │
 │       (rota çiz, uçur)             │   │             (video + joystick)    │
 └────────────────────────────────────┘   └───────────────────────────────────┘
                        ikisi AYNI AĞDA (ethernet / WiFi)
```

| bilgisayar | ne yapar | ne çalıştırır |
|---|---|---|
| **TALON** | hedef uçağı uçurur, konumunu **5 Hz** yayınlar | `baslat_talon.sh` + `talon_arayuz` |
| **DRONE** | avcı drone'u sürer, görür, güder | `baslat_drone.sh` |

---

## 1 · Temel kavramlar (bunlar bilinmeden ilerlenmesin)

| terim | ne demek |
|---|---|
| **CRSF (Crossfire)** | Kumanda ile alıcı arasındaki dijital protokol. Bizim yer bilgisayarı da bu dili konuşur. |
| **ELRS (ExpressLRS)** | 2.4 GHz telsiz sistemi. CRSF'i havadan taşır. |
| **Angle mode** | Uçuş kartı kipi: çubuk konumu bir **yatış açısı** demektir. ⛔ Şartname yalnız buna izin veriyor. |
| **failsafe** | Telsiz koptuğunda uçuş kartının yaptığı şey. Bizde **AUTO-LAND** (kontrollü iniş). |
| **arm / disarm** | Motorların yetkilendirilmesi / kesilmesi. ⛔ Havada disarm = serbest düşüş. |
| **hakem (KomutSureci)** | Pilot ile güdüm arasında kimin komut vereceğine karar veren katman. |
| **kilit** | Şartnamenin puanladığı şey: hedefi belirli bir kadraj bölgesinde, yeterince büyük ve **10 s içinde toplam 5 s** görmek. |
| **yerel köken** | Kalkış noktası. Bütün GPS koordinatları buna göre metreye çevrilir. |

---

## 2 · Donanım ve kablolama

### 2.1 Drone tarafı

| parça | not |
|---|---|
| Uçuş kartı | SpeedyBee/SPEDIX **F405**, Betaflight 2025.12.5 |
| Sensörler | ICM42688P (jiro/ivme), **DPS310 barometre**, **QMC5883 pusula**, **u-blox M10 GPS** |
| Alıcı | ELRS, **UART2**, `serialrx_provider = CRSF` |
| Kamera | analog → VTX → yer alıcısı → **USB yakalama kartı** |
| **Komut yolu** | **Skydagger**: yer bilgisayarı → backend → USB → **ESP32** → tek tel → ELRS TX → drone |

**Betaflight'ta doğrulanmış ayarlar** (`reel/docs/DONANIM_KONTROL.md` ile kontrol edin):

```
ARM        AUX1 (kanal 5)  1800-2100
ANGLE      AUX5 (kanal 9)  900-2100      -> DAİMA AÇIK
ALTHOLD    AUX2 (kanal 6)  1700-2100     -> ⛔ KULLANILMIYOR (şartname)
POS HOLD   AUX4 (kanal 8)  1700-2100     -> ⛔ KULLANILMIYOR (şartname)
angle_limit = 60            failsafe_procedure = AUTO-LAND
```

⛔ Kullanılmayan kanallarımız **1500 µs** gider; bu 1700'ün altındadır, yani
ALTHOLD ve POS HOLD **yapısal olarak kapalı kalır.** Şartname ihlali imkânsızdır.

### 2.2 Talon tarafı

| parça | not |
|---|---|
| Otopilot | Pixhawk 2.4.8, ArduPlane 4.7 |
| Telemetri | SiK 433 MHz → USB, **57600 baud** |
| Kontrol | `talon_arayuz` deposu (rota çizme, görev yükleme, manuel) |

---

## 3 · Kurulum (her iki bilgisayarda bir kez)

```bash
# 1) Depoyu al
git clone <reel_test-adresi> && cd reel_test

# 2) Sanal ortam ve paketler
python3 -m venv .venv && . .venv/bin/activate
pip install -r reel/requirements.txt

# 3) Seri port izni  (ÇIKIP TEKRAR GİRMEK ŞART)
sudo usermod -aG dialout $USER

# 4) ModemManager'ı kapat — seri porta AT komutu gönderip akışı bozar
sudo systemctl disable --now ModemManager
```

**Talon bilgisayarında ayrıca** `talon_arayuz`:
```bash
git clone https://github.com/EfeAtakul/talon_arayuz.git
cd talon_arayuz && python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

### Ağ
İki bilgisayar aynı ağda olmalı. Drone bilgisayarının IP'sini öğrenin:
```bash
hostname -I
```
Yayın (broadcast) engelleniyorsa Talon tarafında `--hedef <drone-ip>` verin.

---

## 4 · ⭐ GÖREVİN İCRASI — adım adım

> Sıra önemlidir. Her adımın **"tamam" ölçütü** yazılıdır; sağlanmadan
> bir sonrakine geçilmez.

### ADIM 1 — Talon bilgisayarı: yayıncıyı başlat

```bash
cd reel_test/reel
./baslat_talon.sh /dev/ttyUSB0 192.168.1.50
```
`/dev/ttyUSB0` = SiK telsizi, `192.168.1.50` = drone bilgisayarının IP'si.

**✅ Tamam ölçütü:** ekranda 2 saniyede bir konum satırı akmalı:
```
41.1050, 29.0230  irtifa  40.0 m  hız 22.0 m/s   yayın 137  mavlink 4820
```
`⚠ GPS bekleniyor` yazıyorsa Talon dışarıda ve fix almış olmalı.

> **⛔ Neden önce bu:** seri portu **tek süreç** açabilir. Bu betik portu
> açar ve trafiği `udp:14550`'ye aynalar; arayüz oraya bağlanır. Sıra
> ters olursa yayıncı porta erişemez.

### ADIM 2 — Talon bilgisayarı: kontrol arayüzünü aç

**İkinci bir terminalde:**
```bash
cd talon_arayuz
MAV_ENDPOINT=udp:127.0.0.1:14550 ./baslat.sh udp:127.0.0.1:14550
```
Tarayıcı: **http://localhost:8000**

**✅ Tamam ölçütü:** bağlantı noktası yeşil, telemetri akıyor.

Buradan: **KARE / DAİRE / ELİPS** seçip **YÜKLE → BAŞLAT** ile Talon'a rota
çizdirilir. Talon o rotayı uçarken konumu otomatik olarak drone
bilgisayarına akmaya devam eder.

### ADIM 3 — Drone bilgisayarı: SKYDAGGER BACKEND'İ HAZIRLA

**Bir kez kurulum** (ilk seferde, ~2 dakika):
```bash
./reel/skydagger/kur.sh
```
⛔ **Wine GEREKMEZ.** Komitenin `skydagger-backend.exe` dosyası aslında
PyInstaller ile paketlenmiş bir **Python 3.12** uygulamasıdır ve kodunun
içinde açıkça `/dev/ttyUSB0` desteği vardır — Linux'ta **doğal** çalışır.
`kur.sh` taşınabilir bir Python 3.12 indirir (sudo gerekmez), pyserial kurar
ve backend'i `.exe`'nin içinden çıkarır.

> ⚠ Wine denendi ve **olmadı**: Ubuntu'nun wine 6.0.3'ünde
> `propsys.dll.VariantToString` yok; GE-Proton11-5'in wine'ı ise GLIBC 2.38
> istiyor (sistemde 2.35). Doğal yol ikisinden de sağlam.

**Her açılışta:**
```bash
./reel/skydagger/baslat_backend.sh          # önceki örneği KENDİSİ kapatır
./reel/skydagger/baslat_backend.sh --kapat  # yalnız kapat
```

> ⛔ **`pkill -f backend.py` İŞE YARAMAZ** — süreç `yukleyici.py` adıyla
> koşuyor. Bu ayrıntıyı bilmen gerekmesin diye başlatıcı temizliği kendisi
> yapıyor: önceki örneği kapatır, portun (8765) boşalmasını bekler, sonra
> açar. Aynısı `baslat_drone.sh` için de geçerli (`--kapat` desteğiyle).

⛔ **Bu adım atlanamaz.** Bizim yazılımımız backend'e *bağlanır*; onu
başlatmaz ve ona kurulum komutu **göndermez** (Skydagger rehberi §8:
*"Harici script yalnızca kanal verisi üretir"*). Kurulumu **operatör**
backend konsolundan yapar:

| sıra | konsola yazılacak | ne olmalı |
|---|---|---|
| 1 | *(backend'i çalıştır)* | konsol açılır |
| 2 | `/connect` | ESP32'nin seri portu bulunur |
| 3 | `RC_ENABLE` | ELRS modülü **MAVİ** yanar (linkli) |
| 4 | `STOP` | **sarı** (link yok) — RC modundan çıkıldı |
| 5 | `EXTERNAL` | harici script artık kabul edilir |

> `/connect` "USB cihaz yok" diyorsa: kablo **veri kablosu** mu, CP210x
> sürücüsü kurulu mu (README.txt'e bakın), `/ports` ne diyor.
>
> ⛔ **Moddan çıkmak için Ctrl-C DEĞİL**, `RC STOP` / `EXTERNAL STOP` yazın —
> derlenmiş sürümde Ctrl-C tüm konsolu kapatabilir.

### ADIM 3b — Drone bilgisayarı: yer kontrolünü başlat

```bash
cd reel_test/reel
./baslat_drone.sh
```

Açılışta şunları basar — **hepsini okuyun:**
```
BAĞ       : SKYDAGGER  127.0.0.1:8767  (RC=UDP, telemetri=TCP)
KUMANDA   : RadioMaster Pocket (8 eksen)
HEDEF     : UDP :47800 dinleniyor (Talon bilgisayarı)
ÇEVİRİCİ  : MODEL=aci  ACI_MAX=60  Y_ISARET=-1.0
KAMERA    : 0  720x576
PANEL     : http://127.0.0.1:8810
```

**✅ Tamam ölçütü:** `BAĞ`, `KAMERA` ve `HEDEF` satırlarında ⛔ yok.

> ⛔ **İLK 5 SANİYE YALNIZ SAFE BASILIR** (rehber §8: *"Kontrol verisini
> hemen basmayın"*). Bu pencerede ne komut verirsen ver, dron SAFE görür.
> Modülün **MAVİ** ışığını tam o sırada doğrula. Pencere kodda uygulanır,
> operatörün hatırlamasına bırakılmaz (bekçi R58).

> **⛔ `Y_ISARET` ÖLÇÜLMEDEN OTONOM AÇMAYIN.** Bu sayı, roll çubuğunun
> aracı hangi yöne götürdüğünü söyler. Yanlışsa güdüm hatayı kapatmak
> yerine **büyütür**: araç hedeften kaçar ve daire çizer. Ölçüm:
> `python3 reel/araclar/isaret_olc.py` (ayrı belge).

### ADIM 4 — Paneli aç ve sağlığı doğrula

Tarayıcı: **http://127.0.0.1:8810**

Üst şeritte beş rozet var. **Hepsi yeşil olmadan uçulmaz:**

| rozet | yeşil olması için |
|---|---|
| `LINK` | drone açık, ELRS bağlı, telemetri akıyor |
| `GPS` | uydu ≥ 10 **ve** yerel köken kurulmuş |
| `girdi:` | `kumanda` (fiziksel) ya da `panel` |
| `ARM` | pilot arm ettiğinde yeşil olur (yerdeyken kırmızı normal) |
| `SUNUCU` | yarışma sunucusuna bağlıysa (denemede kapalı olabilir) |

### ADIM 5 — Manuel uçuş (⛔ önce daima bu)

Panelde **iki joystick** vardır:

| joystick | yatay eksen | dikey eksen |
|---|---|---|
| **SOL** | dönüş (yaw) — bırakınca ortalanır | **gaz** — bırakınca **ORTALANMAZ** |
| **SAĞ** | yanal (roll) — ortalanır | ileri/geri (pitch) — ortalanır |

**Fiziksel kumanda takılıysa joystickler kilitlenir ve onun konumunu
gösterir.** Kumanda daima önceliklidir — ele yakın olan kazanır.

**Arm etmek:** `ARM (BASILI TUT)` düğmesine **basılı tutun**. Bıraktığınızda
disarm olur. ⛔ Tek tıkla arm edilemez; yanlışlıkla motor çalıştırmayı
imkânsız kılar.

**✅ Tamam ölçütü:** araç joystick komutlarına beklendiği gibi tepki
veriyor, eksenler doğru yönde.

### ADIM 6 — Otonom güdüme geçiş

Otonom için **DÖRT ŞART BİRDEN** gerekir. Biri düşerse **anında manuele
düşer**:

1. Panelde **OTONOM** düğmesi seçili
2. Pilotun izin anahtarı açık (fiziksel kumandada AUX2)
3. Güdüm taze komut üretiyor (< 200 ms)
4. Kumandayla bağ taze (< 3 s)

Panelde `kaynak` alanı **OTONOM** yazdığında güdüm devrededir.
Yazmıyorsa yanındaki `sebep` niçin olmadığını söyler:

| sebep | anlamı | ne yapılır |
|---|---|---|
| `pilot_vetosu` | izin anahtarı kapalı | kumandadaki anahtarı aç |
| `gudum_bayat` | güdüm süreci takıldı | terminale bak, hedef geliyor mu |
| `kumanda_kopuk` | kumanda USB'si gitti (otonom sürüyor) | USB'yi kontrol et |
| `teslim_suresi` | kumanda 3 s'dir kopuk → **paket kesildi** | araç AUTO-LAND yapıyor |

### ADIM 7 — Görsel güdüm ve kilit

```bash
./baslat_drone.sh /dev/ttyUSB0 --gorsel
```
Panelde video üzerinde:
- **Mavi dörtgen** = AV (Hedef Vuruş Alanı): kenarlardan %25 / %10 kırpılmış bölge
- **Turuncu kutu** = hedef görüldü ama kilit ölçütünü geçmiyor
- **Yeşil kutu** = bu kare kilit sayılıyor
- Alt yazı: `KILIT 3.4/5.0 s` — 10 saniyelik pencerede biriken kilit süresi

⛔ **Dedektör modeli oyun görüntüleriyle eğitildi.** Gerçek Talon'u
görebilmesi için gerçek uçuş görüntüsüyle yeniden eğitilmesi gerekir.
Bu tamamlanmadan görsel güdüm sonucu değerlendirilmez.

### ADIM 8 — Kapanış

Terminalde **Ctrl+C**. ⛔ Araç havadayken kapatmayın — **önce pilot indirsin.**

---

## 5 · ⛔ EMNİYET — pazarlığa açık değil

1. **Arm yalnız insandan gelir.** Güdümün arm kanalına erişimi *yoktur*;
   `OtonomIstek` yapısında arm alanı yoktur. Bir yazılım hatası yerdeki
   aracı çalıştıramaz.
2. **Disarm asla "emniyet tedbiri" olarak gönderilmez.** Havada disarm =
   serbest düşüş. Toptan kayıpta paket **kesilir** ve uçuş kartının
   AUTO-LAND'i devreye girer.
3. **Pilot her zaman son sözü söyler.** İzin anahtarı kapanınca otonom
   *o tikte* düşer.
4. **Kumanda 3 saniye kopuk kalırsa paket kesilir.** Müdahale edecek
   kimse yokken otonom devam etmez.
5. **Yalnız Angle modu.** ALTHOLD ve POS HOLD kanallarımız 1500 µs gider,
   yani eşiğin altında — açılmaları imkânsız.
6. **Pervaneler, yerdeki her denemede çıkarılır.**

---

## 6 · Arıza arama

| belirti | sebep | çare |
|---|---|---|
| `backend'e ulaşılamıyor` | backend kapalı / EXTERNAL yapılmadı | ADIM 3'teki 5 satırı sırayla uygula |
| `/connect` "USB cihaz yok" | veri kablosu değil, ya da sürücü yok | başka kablo; **CP210x VCP** sürücüsü kur; `/ports` ile bak |
| modül **sarı** kalıyor | link yok | `RC_ENABLE` yapıldı mı, modül 2S pilden besleniyor mu, bind var mı (rehber §9.1) |
| RC gidiyor ama arm olmuyor | AUX1 sıçramıyor | BF **Receiver** sekmesinde CH5'in ~2000'e çıktığını doğrula (rehber §10.3) |
| `LINK` kırmızı | telemetri akmıyor | drone açık mı, alıcı bağlı mı, `crc_hata` artıyor mu |
| `GPS` kırmızı | uydu < 10 | dışarı çık, gökyüzü açık olsun |
| video yok | yanlış cihaz | `ls /dev/video*`, `DOW_KAM_KAYNAK=2 ./baslat_drone.sh ...` |
| hedef `YOK` | UDP gelmiyor | Talon yayıncısı çalışıyor mu, `--hedef <drone-ip>` verildi mi, güvenlik duvarı |
| Talon arayüzü bağlanmıyor | sıra ters | **önce** `baslat_talon.sh`, **sonra** panel |
| araç ters yöne gidiyor | `Y_ISARET` yanlış | `araclar/isaret_olc.py` ile ölç |

---

## 7 · Donanımsız deneme (masa başı)

Her şey donanım olmadan sınanabilir:

```bash
# Terminal 1 — sahte Talon (200 m yarıçaplı daire, 22 m/s)
./baslat_talon.sh --sahte 127.0.0.1

# Terminal 2 — sahte Skydagger backend + drone yer kontrolü
./baslat_drone.sh --sahte-backend

# Tarayıcı: http://127.0.0.1:8810
```
Panelde hedef görünür, joystickler çalışır, hakem kip geçişlerini yapar.
⚠ ELRS yok, kamera yok — yalnız mantık sınanır.

**Bekçileri koştur** (her değişiklikten sonra):
```bash
python3 -m pytest reel/tests/test_reel.py tests/test_dow.py -q
```

---

## 8 · Dosya haritası

```
reel/
├── baslat_drone.sh          ► DRONE bilgisayarı başlatıcısı
├── baslat_talon.sh          ► TALON bilgisayarı başlatıcısı
├── drone_yki.py             drone yer kontrolü — tek giriş noktası
├── gercek/
│   ├── arayuz.py            ARAÇ SÖZLEŞMESİ (eksen/işaret/birim kuralları)
│   ├── baglanti.py          CRSF telemetri -> güdümün beklediği biçim
│   ├── crsf.py              Crossfire protokolü (komut ↑ / telemetri ↓)
│   ├── elrs.py              seri bağ
│   ├── komut.py             ⭐ HAKEM — pilot/güdüm/panel arasında
│   ├── kumanda.py           kumandayı USB joystick olarak okur
│   ├── dikey.py             ⭐ Angle modunda dikey kapalı döngü
│   ├── konum.py             GPS ↔ yerel metre
│   ├── hedef.py             hedef GPS kaynağı (sunucu ya da Talon)
│   ├── sunucu.py            yarışma sunucusu istemcisi
│   ├── kamera_yakala.py     yakalama kartı
│   └── panel.py             operatör arayüzü (video + joystick)
├── talon/yayinci.py         MAVLink hub + 5 Hz hedef yayını
├── araclar/dikey_sim.py     dikey döngü tezgâhı (donanımsız)
├── tests/test_reel.py       R1..R55 bekçileri
└── docs/DONANIM_KONTROL.md  uçuştan önce doldurulacak kontrol listesi
```

⛔ **`dow/` altındaki güdüm yasaları DEĞİŞTİRİLMEDİ.** Simülasyonda ölçülmüş
davranış birebir korunuyor; `araclar/denklik.py` 400 tikte bit bit
karşılaştırma yapıyor ve `tests/test_dow.py` 69 bekçiyle bunu sınıyor.
