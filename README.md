# reel_test — Avcı Drone ile Talon'u Otonom Vurma

**Ana hedef:** bir **avcı drone**, sabit kanatlı bir **hedef uçağı (Talon)**
otonom güdüm koduyla bulup vuracak. GPS ile yaklaşır, hedefi kamerada
görünce GPS'i bırakıp yalnız görüntüyle kovalar ve temas eder.

Güdüm yasaları bir simülatörde (Drones of War) geliştirilip ölçüldü;
bu depo onları **gerçek donanıma** taşır. Yasa değişmedi — değişen, aracın
ve kameranın modeli.

```
https://github.com/kayranecatikara/reel_test
```

> **Bu belgeyi hiç bilmeyen biri baştan sona okuyup sistemi çalıştırabilir.**
> Her terim ilk geçtiği yerde tanımlanır; her komut olduğu gibi yazılıdır.
> Kurulumu bir yapay zekâya yaptırmak istersen: en alttaki **Kurulum promptu**.

---

## Belgeler — nereden başlanır

| belge | ne anlatır |
|---|---|
| **`reel/docs/DRONE_YKI.html`** | 🚁 Avcı drone yer kontrolü — 0'dan aç, kullan, görevi icra et |
| **`reel/docs/TALON_YKI.html`** | 🛩️ Talon yer kontrolü — 0'dan aç, kullan, görevi icra et |
| `reel/README.md` | Ayrıntılı işletim kılavuzu (iki bilgisayar birlikte) |
| `reel/docs/DRONE_KILAVUZU.md` · `TALON_KILAVUZU.md` | Aynı içerik, Markdown |
| `docs/SIMULASYON_KURULUM.md` | Simülatör tarafı (güdüm burada ölçüldü) |
| `CLAUDE.md` | Bu depoda geliştirme kuralları — yapay zekâ da buna uyar |

**İki HTML dosyasını tarayıcıda aç** — çevrimdışı çalışırlar:
```bash
xdg-open reel/docs/DRONE_YKI.html
xdg-open reel/docs/TALON_YKI.html
```

---

## Sistem tek bakışta

```
 ┌─ BİLGİSAYAR 1 — TALON ────────────┐   ┌─ BİLGİSAYAR 2 — DRONE ───────────┐
 │                                    │   │                                   │
 │  Pixhawk ─SiK telsiz─> yayinci.py  │   │  ESP32 ─ELRS─> drone_yki.py       │
 │                          │         │   │  kumanda ─USB─>    │              │
 │              ┌───────────┴──────┐  │   │  kamera ─USB─>     │              │
 │              │                  │  │   │                    ▼              │
 │       udp:14550/14552/14554  udp:47800 ──────────>  hedef GPS (5-10 Hz)    │
 │              │                     │   │                    │              │
 │      arayüz :8000                  │   │             panel :8810           │
 │      harita :8010                  │   │       kamera ayarı :8020          │
 └────────────────────────────────────┘   └───────────────────────────────────┘
                        ikisi AYNI AĞDA (ethernet / WiFi)
```

| bilgisayar | ne uçurur | ne çalıştırır | arayüz |
|---|---|---|---|
| **TALON** | Hedef uçak (sabit kanat, ArduPlane) | `reel/baslat_talon.sh` | `:8000` · harita `:8010` |
| **DRONE** | Avcı drone (7" quad, Betaflight) | `reel/baslat_drone.sh` | `:8810` · kalibrasyon `:8020` |

⛔ **İki bilgisayar aynı ağda olmalı.** Talon tarafı hedef konumunu drone
bilgisayarının IP'sine UDP ile basar.

---

## Hızlı başlangıç

### Her iki bilgisayarda, bir kez
```bash
git clone https://github.com/kayranecatikara/reel_test.git
cd reel_test
pip install -r reel/requirements.txt

sudo usermod -aG dialout $USER          # ÇIKIP TEKRAR GİR
sudo systemctl disable --now ModemManager
```
`ModemManager` her yeni seri porta AT komutu gönderip "modem mi?" diye yoklar
ve MAVLink akışını bozar.

### TALON bilgisayarı
```bash
cd reel
pip install -r talon/arayuz/requirements.txt

# Uçuş alanının haritasını BİR KEZ indir (internet varken)
python3 talon/gorev_plani.py --indir <ENLEM>,<BOYLAM> --yaricap 2000 --z 14-17

# Uçuş günü — tek komut, üç süreç
./baslat_talon.sh <seri-port> <DRONE-BILGISAYARI-IP>
```
→ **http://localhost:8000**

### DRONE bilgisayarı
```bash
cd reel
./skydagger/kur.sh                      # bir kez, ~2 dk

# Terminal 1
./skydagger/baslat_backend.sh
# Terminal 2
./baslat_drone.sh
```
→ **http://localhost:8810**

### Donanım yokken denemek
```bash
cd reel
python3 drone_yki.py --sahte            # sahte ELRS, panel açılır
./baslat_talon.sh --sahte 127.0.0.1     # daire çizen sahte Talon
```

---

## Durum — dürüstçe

| konu | durum |
|---|---|
| Güdüm yasası sim'den taşındı | ✅ **bit bit aynı** (`araclar/denklik.py`, 400 tik) |
| Talon: bağlantı, GPS, görev yükleme, AUTO, motor tetikleme | ✅ yer testi yapıldı |
| Talon → drone hedef GPS akışı | ✅ ölçüldü: 10 Hz, 0 red, yaş 0.1 s |
| Drone: ELRS bağı, kumanda, panel, kamera | ✅ yer testi yapıldı |
| Elden atış ölü zamanı | ✅ 1.20 s → **0.20 s** (uçak iki kez bu yüzden düşmüştü) |
| **Kamera optiği kalibrasyonu** | ⛔ **YAPILMADI** — araç hazır (`gercek/kamera_ayari.py`) |
| **Dedektör modeli** | ⛔ gerçek görüntüyle eğitiliyor |
| **Talon havada uçuş** | ⛔ yapılmadı |
| **Drone otonom uçuş** | ⛔ yapılmadı |

---

## Emniyet — pazarlığa açık değil

1. **Yer testlerinde pervane ÇIKARILIR.**
2. **Kumanda her zaman açık ve elde** — çubuğu oynatmak otonomu keser.
3. **Meskûn mahalde otonom uçuş yapılmaz.**
4. **Havadayken acil DISARM'a basılmaz** — motor durur, araç düşer.
5. **Kalkış ölü zamanı > 1 s ise uçak elden ATILMAZ.**
6. **Kamera kalibre edilmeden otonom görsel güdüm denenmez.**
7. **Test bitince araçlar havada kontrolsüz bırakılmaz.**

---

## Depo yapısı

```
reel/                       ⭐ GERÇEK DONANIM
├── baslat_drone.sh         DRONE bilgisayarı — tek komut
├── baslat_talon.sh         TALON bilgisayarı — tek komut (3 süreç)
├── drone_yki.py            drone yer kontrolü — tek giriş noktası
├── gercek/                 drone tarafı
│   ├── arayuz.py             ARAÇ SÖZLEŞMESİ (eksen/işaret/birim kuralları)
│   ├── komut.py              ⭐ HAKEM — pilot/güdüm/panel arasında
│   ├── dikey.py              ⭐ Angle modunda dikey kapalı döngü
│   ├── kamera_ayari.py       ⭐ kamera optiğini SAHADA ölç
│   ├── crsf.py · elrs.py · skydagger.py    ELRS zinciri
│   ├── baglanti.py · konum.py · hedef.py   telemetri, çerçeve, hedef
│   ├── kamera_yakala.py · panel.py         video ve operatör arayüzü
│   └── sunucu.py             yarışma sunucusu istemcisi
├── talon/                  Talon tarafı
│   ├── yayinci.py            MAVLink hub (3 ayna) + 5 Hz hedef yayını
│   ├── gorev_plani.py        ⭐ harita üstünde waypoint + AUTO başlat
│   ├── karo.py               çevrimdışı OSM karo önbelleği
│   ├── kalkis_ayari.py       elden atış kalkış parametreleri
│   ├── atis_testi.py         atış algılama ölçümü (pervanesiz)
│   ├── baglanti_testi.py     beş katmanlı bağlantı teşhisi
│   └── arayuz/               talon_arayuz (olduğu gibi alındı, KAYNAK.md)
├── skydagger/              komitenin ESP32 backend'i (çıkarıcı + başlatıcı)
├── docs/                   ⭐ DRONE_YKI.html · TALON_YKI.html + Markdown
└── tests/test_reel.py      R1..R98 bekçileri

dow/                        güdüm yasaları — SİMÜLASYONDAN, DEĞİŞTİRİLMEZ
araclar/                    ölçüm/analiz araçları (denklik.py dahil)
tests/                      sim bekçileri (69)
docs/                       simülasyon belgeleri ve sicil
CLAUDE.md                   geliştirme kuralları
```

### ⛔ `dow/` altındaki güdüm yasaları DEĞİŞTİRİLMEDİ

Gerçek donanıma taşıma, **dikişlerle** yapıldı: hepsi varsayılan olarak
kapalı, hepsi `DOW_*` env değişkeniyle açılır.

| dikiş | ne için |
|---|---|
| `Beyin(baglanti=…, cevirici=…)` | gerçek araç bağlantısı ve çeviriciyi takmak |
| `DOW_CEV_*` | araç modeli sabitleri (Angle mode, açı sınırı, yanal işaret) |
| `DOW_OPTIK_*` | kamera optiği (F_PX, TILT, MENZIL_C, çözünürlük) |
| `Ayar.GPS_KAYNAK="gercek"` | sim'in "truth" ve filtresi gerçekte yok |

Hiçbiri verilmezse güdüm çıktısı simülasyondakiyle **birebir aynıdır**:
```bash
python3 araclar/denklik.py yaz  logs/a.json
python3 araclar/denklik.py kiyas logs/a.json logs/b.json   # ✅ BİT BİT AYNI
```

---

## Testler

```bash
python3 -m pytest reel/tests/test_reel.py tests/ -q      # 168 bekçi
```

Bekçiler süs değil — **her biri yaşanmış bir hataya** karşılık gelir.
Örnekler:

| bekçi | neyi koruyor |
|---|---|
| R39 | Kumanda kopukken otonomun süresiz devam etmesi |
| R63 | Hareket algılamanın nesne kimliğine bakıp değeri kaçırması |
| R74 | Taze gelen paketin içindeki bayat veriyi taze sanmak |
| R88 | İki programın aynı UDP portunda birbirinin paketini çalması |
| R90 | Kamera optiği varsayılanının sessizce kayması |
| R98 | `--sahte` yolunun backend arayıp çıkış 2 vermesi |
| B5 | **Görsel temas varken GPS güdümü kullanılması (yarışma kuralı)** |

---
---

# 🤖 KURULUM PROMPTU

> Aşağıdaki metni **olduğu gibi** bir yapay zekâ ajanına (Claude Code vb.)
> ver. Temiz bir Ubuntu makinede depoyu kurar, doğrular ve neyin eksik
> olduğunu söyler. **Uçuş yaptırmaz** — kurulum ve doğrulama yapar.

```text
Bu depoyu temiz bir Ubuntu makinesine kur ve çalıştığını DOĞRULA:

    https://github.com/kayranecatikara/reel_test

Bu, TEKNOFEST için bir avcı drone sistemidir. Ana hedef: bir quadcopter'ın,
sabit kanatlı bir hedef uçağı (Talon) otonom güdüm koduyla bulup vurması.
İki ayrı bilgisayarda çalışır: biri Talon'u uçurur ve konumunu yayınlar,
diğeri drone'u sürer.

⛔ ÖNCE ŞUNLARI OKU VE UY:
  1. Depodaki CLAUDE.md geliştirme kurallarıdır — sen de onlara uyacaksın.
  2. reel/docs/DRONE_YKI.html ve reel/docs/TALON_YKI.html işletim
     kılavuzlarıdır; kurulumdan sonra kullanıcıya bunları göster.
  3. dow/ altındaki güdüm yasalarını DEĞİŞTİRME. Simülasyonda ölçülmüş
     davranış oradadır ve gerçek donanıma "dikiş"lerle bağlanır
     (DOW_CEV_*, DOW_OPTIK_*). Bir şeyi değiştirmen gerekirse önce sor.

YAP:

A) KURULUM
   1. Depoyu klonla.
   2. Python paketlerini kur:
        pip install -r reel/requirements.txt
        pip install -r reel/talon/arayuz/requirements.txt
   3. Seri port izni ve ModemManager:
        sudo usermod -aG dialout $USER        # oturum yenilenmeli
        sudo systemctl disable --now ModemManager
      (ModemManager her yeni seri porta AT komutu gönderip MAVLink akışını
       bozar — bu adım atlanırsa telemetri hiç gelmez.)
   4. v4l-utils kur (kamera teşhisi için):  sudo apt install -y v4l-utils

B) DOĞRULAMA — hepsi donanımsız çalışır
   1. Bekçiler geçmeli:
        python3 -m pytest reel/tests/test_reel.py tests/ -q
      168 test geçmeli. Geçmeyen varsa DUR ve raporla.
   2. Güdüm bit bit aynı olmalı:
        python3 araclar/denklik.py yaz logs/a.json
        python3 araclar/denklik.py yaz logs/b.json
        python3 araclar/denklik.py kiyas logs/a.json logs/b.json
      "BİT BİT AYNI" demeli.
   3. Donanımsız açılış:
        cd reel && python3 drone_yki.py --sahte --port 8811
      Panel http://localhost:8811 açılmalı. Sonra kapat.
   4. Talon planlayıcısı:
        cd reel/talon && python3 gorev_plani.py --port 8011
      http://localhost:8011 açılmalı (harita boş olabilir). Sonra kapat.
   5. Kamera cihazlarını listele:
        cd reel && python3 gercek/kamera_ayari.py --tara

C) RAPOR — kullanıcıya şunları SAYIYLA söyle
   - Kaç test geçti, denklik sonucu ne çıktı.
   - Hangi video cihazları bulundu, yakalama kartı var mı.
   - Seri portlar (ls -l /dev/serial/by-id/) ve kumanda (ls /dev/input/js*).
   - Eksik olanlar: kamera optiği kalibre edilmiş mi
     (baslat_drone.sh içinde DOW_OPTIK_* satırları yorumda mı),
     uçuş alanı haritası indirilmiş mi (~/.skydagger/karolar).

D) YAPMA
   - Uçuş yaptırma, araca komut gönderme, ARM etme.
   - dow/ altındaki güdüm kodunu değiştirme.
   - Kendi kafana göre commit/push yapma — önce sor.

Bittiğinde kullanıcıya sırayla ne yapması gerektiğini yaz:
kamera kalibrasyonu, harita indirme, ve iki bilgisayarın başlatma komutları.
```
