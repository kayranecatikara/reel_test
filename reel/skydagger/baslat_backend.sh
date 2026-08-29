#!/usr/bin/env bash
# ==============================================================================
# SKYDAGGER BACKEND'İ BAŞLATIR  (Linux, Wine YOK)
# ==============================================================================
# ⛔ TTY SARMALAYICISI ŞART: backend `readline` kullanıyor. Boruya bağlanınca
#    konsol hiç açılmıyor ve HİÇ ÇIKTI VERMİYOR — hata da vermiyor.
#    `script -qfec` bu yüzden var (CLAUDE.md §9'daki MAVProxy tuzağı).
set -u
cd "$(dirname "$0")"
KOK="$HOME/.skydagger"
kirmizi(){ printf '\033[31m%s\033[0m\n' "$*"; }

[ -x "$KOK/py312/bin/python3" ] || { kirmizi "  HATA: kurulum yapılmamış -> ./kur.sh"; exit 1; }
[ -f "$KOK/backend.pyc" ]       || { kirmizi "  HATA: backend.pyc yok -> ./kur.sh"; exit 1; }

if [ -e /dev/ttyUSB0 ] && [ ! -w /dev/ttyUSB0 ]; then
    kirmizi "  UYARI: /dev/ttyUSB0 yazılabilir değil"
    echo   "         sudo usermod -aG dialout \$USER   (sonra OTURUMU KAPAT-AÇ)"
fi
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet ModemManager 2>/dev/null; then
    kirmizi "  UYARI: ModemManager çalışıyor — ESP32'nin portuna AT komutu"
    kirmizi "         gönderip akışı bozabilir:"
    echo   "         sudo systemctl disable --now ModemManager"
fi

cat <<'BILGI'

  ┌─ SKYDAGGER BACKEND ─────────────────────────────────────────────┐
  │  Web/HTTP  http://127.0.0.1:8765                                │
  │  Komut TCP 127.0.0.1:8766   (satır protokolü + telemetri)       │
  │  RC   UDP  127.0.0.1:8767   (bizim yazılım buraya basar)        │
  ├─ SIRA (rehber §5) ──────────────────────────────────────────────┤
  │  /connect     → ESP32 portu bulunur                             │
  │  RC_ENABLE    → SONRA modüle 2S pili tak → ışık MAVİ olmalı     │
  │  STOP         → sarı (durdurmanın çalıştığı doğrulanır)         │
  │  EXTERNAL     → bizim yazılım devralır                          │
  ├─ KAPANIŞ (⛔ sırayla) ──────────────────────────────────────────┤
  │  EXTERNAL STOP  →  /disconnect  →  pil çek  →  USB çek          │
  │  ⛔ /disconnect ATLANIRSA ESP kötü boot moduna düşebilir         │
  └─────────────────────────────────────────────────────────────────┘

BILGI
export SKY_PYC="$KOK/backend.pyc"
exec script -qfec "$KOK/py312/bin/python3 -u $(pwd)/yukleyici.py $*" /dev/null
