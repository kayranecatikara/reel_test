# Talon Yer Kontrol Arayüzü — Yer Bilgisayarı Kurulumu

Bu paket, panelin **yerdeki bir bilgisayarda** çalışmasını sağlar. Uçakla
bağlantı **SiK telsiz** üzerinden kurulur, yani menzil WiFi'ın 100–250 metresi
yerine SiK'in 1–2 kilometresidir.

```
UÇAK                                    YER BİLGİSAYARI
Pixhawk ─TELEM1─ SiK ───433 MHz───► SiK ─USB─ bilgisayar
                                              └─ panel: http://localhost:8000
```

---

## 0. Projeyi indirin

Depo **private** — indirirken GitHub kullanıcı adınız ve bir *personal access
token* sorulacak (parola değil, token).

```
git clone https://github.com/EfeAtakul/talon_arayuz.git
cd talon_arayuz
```

Git kurulu değilse: https://git-scm.com/downloads

> Depoda bir düzeltme yapıldığında bu klasörde `git pull` demeniz yeterli —
> paketi yeniden indirmenize gerek yok.

## 0. Kısayol — Claude Code ile kurdurmak

Bilgisayarda Claude Code varsa aşağıdaki metni olduğu gibi yapıştırın; kurulumu
baştan sona yapar ve bağlantıyı doğrular. Elle kuracaksanız 1. bölümden devam
edin.

```
X-UAV Talon uçağının yer kontrol istasyonunu bu bilgisayara kur.
(Windows ya da Ubuntu — hangisiyse ona göre davran.)

Depo: https://github.com/EfeAtakul/talon_arayuz

Sırayla:
1. Python 3.10+ var mı bak; yoksa kur.
   - Windows: kurulumda "Add Python to PATH" işaretli olsun
   - Ubuntu: sudo apt install -y python3 python3-venv python3-pip
2. Git var mı bak; yoksa kur.
3. Depoyu klonla.
4. Bağımlılıkları kur:
   - Windows: pip install -r requirements.txt
   - Ubuntu: python3 -m venv .venv && source .venv/bin/activate
             && pip install -r requirements.txt
     (Ubuntu 23.04+ sistem Python'una pip ile kurulum yaptırmaz — PEP 668.
      "externally-managed-environment" hatası alırsan venv kullan,
      --break-system-packages ile ZORLAMA.)
5. Seri portları listele, SiK telemetri telsizinin hangisinde olduğunu bul.
   - Windows: Aygıt Yöneticisi, genelde "USB Serial Port (COMx)" veya
     "Silicon Labs CP210x". Bluetooth portlarını eleme.
   - Ubuntu: ls -l /dev/serial/by-id/  ve  dmesg | tail
6. Ubuntu ise ayrıca:
   - sudo usermod -aG dialout $USER   (sonra oturum kapat-aç gerekir, söyle)
   - ModemManager çalışıyorsa kapat: sudo systemctl disable --now ModemManager
7. Paneli başlat:
   - Windows: baslat.bat <COM>
   - Ubuntu:  chmod +x baslat.sh && ./baslat.sh <port>
8. http://localhost:8000 açıldığını doğrula ve /api/telemetri çıktısında
   "bagli": true geldiğini göster. Gelmiyorsa sebebini söyle
   (uçakta enerji yok / SiK ışığı sabit yeşil değil / yanlış COM / menzil dışı).

KURALLAR — istisnasız:
- Bu gerçek bir uçak ve pervanesi takılı olabilir. ARM etme, uçuş modu
  değiştirme, motora gaz gönderme, servo oynatma, görev başlatma — hiçbirini
  yapma. Yalnızca kurulum ve okuma komutları.
- Parametre YAZMA. Sadece oku.
- Bir şey belirsizse dur ve sor.

Kurulum bitince README.md ve UCUS_PROSEDURU.md dosyalarını özetle: uçak nasıl
kalkıyor, nasıl iniyor, acil durumda ne yapılıyor.
```

> Panel açıldıktan sonra uçuş öncesi kontrol ve saha prosedürü için
> `UCUS_PROSEDURU.md`'yi okuyun — özellikle baştaki **acil durum kartını**.

---

## 1. Python kurulumu

**Windows:** https://www.python.org/downloads/ adresinden Python 3.10+ indirin.

> ⚠️ Kurulumda **"Add Python to PATH"** kutusunu işaretleyin. Unutulursa
> `python` komutu bulunamaz.

**Ubuntu / Debian:** Python kurulu gelir ama `venv` ve `pip` ayrı paketlerdedir.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
python3 --version      # 3.10 veya üstü olmalı
```

## 2. Bağımlılıklar

Üç paket kurulur: `pymavlink` (MAVLink protokolü), `flask` (web sunucusu) ve
`pyserial` (seri port). Üçüncüsü `requirements.txt`'te açıkça yazılıdır —
pymavlink onu kendiliğinden kurmuyor ve eksikken panel açılır ama araca
**hiç bağlanamaz.**

**Windows** — bu klasörde bir komut satırı açın:
```
pip install -r requirements.txt
```

**Ubuntu / Debian** — sanal ortam (venv) kullanın:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> ⚠️ **Ubuntu 23.04 ve sonrasında `pip install` doğrudan çalışmaz.**
> Şu hatayı alırsınız:
> ```
> error: externally-managed-environment
> ```
> Bu bir arıza değil, dağıtımın koruması (PEP 668): sistem Python'una pip ile
> paket kurulmasını engelliyor. Doğru çözüm yukarıdaki **venv**'dir.
> `--break-system-packages` ile zorlamayın — sistem paketlerini bozar.

`.venv` klasörü depoya girmez (`.gitignore`'da). `baslat.sh` varsa
kendiliğinden etkinleştirir, elle `source` etmenize gerek kalmaz.

## 3. SiK yer modülünü takın

USB'ye takın ve hangi porta düştüğünü bulun.

**Windows:** Aygıt Yöneticisi → **Bağlantı noktaları (COM ve LPT)**
SiK genelde `USB Serial Port (COM3)` ya da `Silicon Labs CP210x (COM4)` diye görünür.

**Ubuntu / Linux:**
```bash
ls -l /dev/serial/by-id/          # kalici isim — tercih edin
ls /dev/ttyUSB*                   # ya da klasik isim
dmesg | tail                      # SiK'i taktiktan hemen sonra
```

Genelde `/dev/ttyUSB0`. Ama **USB yuvası değişince numara da değişir**;
`/dev/serial/by-id/...` altındaki isim cihaza bağlıdır, değişmez:

```bash
./baslat.sh /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0
```

### Ubuntu'da iki tuzak

**1 · İzin — `dialout` grubu.** Kullanıcı bu grupta değilse port açılmaz:

```
serial.serialutil.SerialException: [Errno 13] Permission denied: '/dev/ttyUSB0'
```

```bash
sudo usermod -aG dialout $USER
```

> ⚠️ Grup üyeliği **oturumu kapatıp açmadan** geçerli olmaz. `newgrp dialout`
> yalnızca o terminal için çalışır.

**2 · ModemManager.** Ubuntu'da bu servis `/dev/ttyUSB*` portlarını modem
sanıp AT komutu gönderir ve MAVLink akışını bozar. Belirtisi sinsi: panel
bağlanır, sonra düşer, ya da telemetri saçmalar.

```bash
systemctl is-active ModemManager      # active ise kapatın
sudo systemctl disable --now ModemManager
```

`baslat.sh` her ikisini de başlamadan önce kontrol eder ve uyarır.

## 4. Çalıştırın

**Windows:**
```
baslat.bat COM3
```

**Ubuntu / Linux:**
```bash
chmod +x baslat.sh        # bir kez, depodan yeni çektiyseniz
./baslat.sh /dev/ttyUSB0
```

`baslat.sh` başlamadan önce şunları denetler ve eksikse ne yapılacağını yazar:
venv etkin mi, paketler kurulu mu, port var mı, yazma izni var mı,
ModemManager çalışıyor mu.

Baud varsayılan **57600** — SiK'in `SERIAL1_BAUD = 57` ayarıyla eşleşir.
Farklıysa ikinci argüman olarak verin:
`baslat.bat COM3 115200` · `./baslat.sh /dev/ttyUSB0 115200`

Tarayıcıdan: **http://localhost:8000**

---

## Telefondan bağlanmak

Panel `0.0.0.0:8000` dinliyor, yani aynı ağdaki her cihaz erişebilir.

1. Bilgisayarın IP adresini öğrenin — panel açılışta yazdırır:
   ```
   Arayüz hazır:
      http://localhost:8000
      http://192.168.1.42:8000     (ağdaki başka cihazdan)
   ```
2. Telefonu **aynı WiFi ağına** bağlayın (ya da bilgisayarın hotspot'una)
3. Telefondan o adresi açın

Sahada bilgisayarın kendi hotspot'unu açmanız gerekebilir (Windows: Ayarlar →
Mobil etkin nokta).

---

## Bilinen sınır: preflight butonu

**UÇUŞ ÖNCESİ KONTROL** butonu bu kurulumda **çalışmaz.**

Sebep: seri portu **tek süreç** açabilir. Panel SiK portunu tutuyor; preflight
ayrı bir süreç olarak aynı porta bağlanmaya çalışır ve başarısız olur.

Bu bir kayıp değil — preflight'ın gösterdiği her şey zaten panelde var:
GPS fix, batarya, mod, arm durumu ve otopilotun kendi arm gerekçeleri
(mesajlar bölümünde). Arm'a bastığınızda ArduPilot zaten eksikleri tek tek yazar.

Gerçekten preflight çalıştırmak isterseniz **paneli kapatın**, sonra
`python -m control.preflight` deyin. Port boşalınca çalışır.

---

## Mission Planner ile aynı anda kullanmak

**Aynı SiK portunu ikisi birden açamaz.** Üç seçenek:

**A — Sırayla kullanın.** MP'yi kapatıp paneli açın, ya da tersi. En basiti.

**B — Mission Planner'ı köprü yapın.** MP SiK'e bağlanır ve MAVLink'i UDP'ye
yayınlar; panel oradan okur.

MP'de: bağlandıktan sonra `Ctrl+F` → **Mavlink** → UDP çıkışı ekleyin
(127.0.0.1:14550). Sonra paneli seri port yerine UDP ile başlatın:

```
Windows:  set MAV_ENDPOINT=udp:127.0.0.1:14550 && python -m gcs.sunucu
Linux:    MAV_ENDPOINT=udp:127.0.0.1:14550 python3 -m gcs.sunucu
```

Bu şekilde MP haritası ve panel aynı anda çalışır.

**C — MAVProxy köprüsü kurun.** `pip install MAVProxy`, sonra:
```
mavproxy.py --master=COM3 --baudrate=57600 --out=udp:127.0.0.1:14550
```
Panel yine UDP'den okur. MP de ikinci bir `--out` ile beslenebilir.

---

## SiK bant genişliği

Panel, uçaktan saniyede ~520 bayt telemetri istiyor (ATTITUDE 5 Hz,
konum 5 Hz, VFR_HUD 2 Hz, GPS/batarya/görev 1 Hz). SiK 57600 baud'un gerçek
kapasitesi ~2500–3500 B/s, yani panel bunun **yaklaşık altıda birini**
kullanıyor. Rahat çalışır.

> Mission Planner'ı da aynı linke bağlarsanız onun telemetri hızlarını
> **1–2 Hz**'de tutun. MP varsayılanı (10 Hz, tüm akışlar) tek başına
> ~8.7 KB/s ister ve linki doyurur — telemetri gecikir, komutlar geçmez.

---

## Görev yükleme SiK üzerinden

Çalışır ama USB'ye göre yavaştır. Ölçüm (USB, gerçek Pixhawk): 20 öğelik elips
görevi **0.42 saniye**. SiK'te her öğe için gidiş-dönüş gecikmesi eklendiğinden
**3–5 saniye** bekleyin.

Panel yüklemeden sonra görevi araçtan **geri okuyup öğe sayısını doğruluyor**,
yani yarım yükleme sessizce geçmez.

---

## Sorun giderme

| Belirti | Sebep / çözüm |
|---|---|
| `python bulunamadı` | PATH'e eklenmemiş — Python'u "Add to PATH" ile yeniden kurun |
| `Araç bağlı değil` (panel açık ama nokta kırmızı) | Yanlış COM port ya da baud. SiK LED'i sabit yeşil mi (link kurulu)? |
| `Permission denied /dev/ttyUSB0` | `sudo usermod -aG dialout $USER`, çıkış-giriş |
| Port başka süreç tarafından tutuluyor | Mission Planner açıksa kapatın |
| Telemetri kesik kesik | MP de bağlıysa hızlarını düşürün, ya da kapatın |
| Panel açılıyor ama veri yok | SiK yer modülü ile air modülü aynı NETID/AIR_SPEED'de mi? |

---

## Uçakta yardımcı bilgisayar yok

Bu kurulumda uçakta **yalnızca Pixhawk ve SiK telsiz** vardır. Görev planlama,
telemetri ve kontrol tamamen yerdeki Windows dizüstünde çalışır.

İki panel örneğini aynı anda çalıştırmayın (örneğin biri USB'den, biri SiK'ten).
İkisi birden görev yüklerse çakışır: panelin görev yükleme kilidi
(`GOREV_KILIDI`) yalnızca kendi süreci içinde geçerlidir.
