#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
TALON GÖREV PLANLAYICI — Mission Planner yerine, tarayıcıdan waypoint
================================================================================
Adres: http://localhost:8010   (Talon bilgisayarında)

⛔ VENDORLANAN ARAYÜZE HİÇ DOKUNMAZ. `talon/arayuz/` altındaki kod olduğu
   gibi durur; bu araç YAYINCININ ALT SÜREÇ AYNASINA (udp:127.0.0.1:14550)
   kendi bağlanır ve görevi MAVLink protokolüyle kendisi yükler.
   Böylece depo güncellenirse bu araç etkilenmez.

⛔ HARİTA KAROSU KULLANILMAZ. Sahada internet olmayabilir; OpenStreetMap
   karosu çeken bir plan ekranı orada BOŞ açılırdı. Onun yerine KALKIŞ
   NOKTASINA GÖRE METRE ızgarası kullanılır — drone panelindeki 3B
   görünümle aynı çerçeve (x=kuzey, y=doğu).

GÖREV YAPISI (ArduPlane'in beklediği sıra):
    0  ev noktası (WAYPOINT, araç bunu kendi ezer)
    1  TAKEOFF          — kalkış açısı + hedef irtifa
    2..N WAYPOINT       — senin koyduğun noktalar
    N+1 bitiş           — RTL (eve dön) ya da LOITER (havada bekle)

⚠ MISSION_ITEM_INT kullanılır, MISSION_ITEM değil: lat/lon tam sayıdır
  (1e-7 derece), float'ta ~1 m kuantalama olurdu.
================================================================================
"""
import argparse
import json
import math
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BURASI = os.path.dirname(os.path.abspath(__file__))
for _p in (KOK, BURASI):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from gercek.konum import YerelCerceve            # noqa: E402
import karo as KARO                              # noqa: E402

# pymavlink modül düzeyinde lazım: hem MAVLink döngüsü hem `komut_mod`
# kullanıyor. Yoksa araç uçları çalışmaz ama panel/harita yine açılır.
try:
    from pymavlink import mavutil
except ImportError:                                  # pragma: no cover
    mavutil = None

_D = {"mav": None, "ev": None, "konum": None, "kip": None, "bagli": False,
      "son_mesaj": "", "n_paket": 0, "indirme": None, "yon": None,
      "mod": None, "armli": False, "gorev": None,
      "hiz": None, "hava_hizi": None, "gaz": None, "irtifa": None,
      "tirmanis": None, "uydu": None, "fix": None,
      "pil_v": None, "pil_yuzde": None, "aktif_oge": None}
_kilit = threading.Lock()


# ======================================================================
#  MAVLINK
# ======================================================================
def _mav_dongu(adres):
    if mavutil is None:
        print("  ⛔ pymavlink yok: pip install pymavlink")
        return
    while True:
        try:
            m = mavutil.mavlink_connection(adres)
            with _kilit:
                _D["mav"] = m
            while True:
                msg = m.recv_match(blocking=True, timeout=2.0)
                if msg is None:
                    with _kilit:
                        _D["bagli"] = False
                    continue
                t = msg.get_type()
                with _kilit:
                    _D["bagli"] = True
                    _D["n_paket"] += 1
                    if t == "GLOBAL_POSITION_INT":
                        _D["konum"] = (msg.lat / 1e7, msg.lon / 1e7,
                                       msg.relative_alt / 1000.0)
                        # hdg: santi-derece, 65535 = bilinmiyor
                        h = getattr(msg, "hdg", 65535)
                        _D["yon"] = None if h == 65535 else h / 100.0
                    elif t == "HOME_POSITION":
                        _D["ev"] = (msg.latitude / 1e7, msg.longitude / 1e7,
                                    msg.altitude / 1000.0)
                    elif t == "VFR_HUD":
                        # ⭐ Talon'un CANLI uçuş verisi (2026-08-29).
                        #   Planlayıcı zaten MAVLink dinliyordu ama yalnız
                        #   konum/mod alıyordu; hız, irtifa ve gaz ekranda
                        #   yoktu ve operatör harita sekmesindeyken uçağın
                        #   ne yaptığını göremiyordu.
                        _D["hiz"] = msg.groundspeed
                        _D["hava_hizi"] = msg.airspeed
                        _D["gaz"] = msg.throttle
                        _D["irtifa"] = msg.alt
                        _D["tirmanis"] = msg.climb
                    elif t == "GPS_RAW_INT":
                        _D["uydu"] = msg.satellites_visible
                        _D["fix"] = msg.fix_type
                    elif t == "SYS_STATUS":
                        _D["pil_v"] = msg.voltage_battery / 1000.0
                        _D["pil_yuzde"] = (msg.battery_remaining
                                           if msg.battery_remaining != -1
                                           else None)
                    elif t == "MISSION_CURRENT":
                        _D["aktif_oge"] = msg.seq
                    elif t == "HEARTBEAT":
                        _D["kip"] = msg.custom_mode
                        _D["mod"] = PLANE_MODLARI.get(msg.custom_mode, "?")
                        _D["armli"] = bool(
                            msg.base_mode
                            & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                    elif t == "STATUSTEXT":
                        _D["son_mesaj"] = msg.text.strip()
        except Exception as e:
            with _kilit:
                _D["bagli"] = False
                _D["son_mesaj"] = "bağlantı: %s" % e
            time.sleep(2.0)


# ArduPlane uçuş modu numaraları — ARAYÜZÜN KENDİ TABLOSUNDAN okunur.
# ⛔ Buraya elle sayı yazmak, iki programın farklı moda "AUTO" demesi
#   demektir; biri uçağı AUTO'ya alırken diğeri GUIDED'a alır ve kimse
#   fark etmez. Tek kaynak: arayuz/control/mav_common.py
def _mod_tablosu():
    import importlib.util
    p = os.path.join(BURASI, "arayuz", "control", "mav_common.py")
    try:
        spec = importlib.util.spec_from_file_location("_avci_mavcommon", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return dict(mod.PLANE_MODE_NAMES)
    except Exception as e:                           # pragma: no cover
        print("  ⚠ mod tablosu okunamadı (%s): mod değiştirme KAPALI" % e)
        return {}


PLANE_MODLARI = _mod_tablosu()
MOD_NO = {a.lower(): n for n, a in PLANE_MODLARI.items()}

# Yerdeyken bu modlardan birindeysek AUTO'ya geçmeden ÖNCE çıkılır (aşağıda).
_OTOMATIK_MODLAR = ("auto", "rtl", "loiter", "guided", "takeoff")
HAVADA_IRTIFA = 5.0        # m — bunun üstü "havada" sayılır


def komut_mod(mod_adi, deneme=3, sure=1.6):
    """Uçuş modunu değiştir ve HEARTBEAT ile DOĞRULA.

    ⚠ set_mode'un ACK'i YOKTUR. Tek gönderimde paket düşerse komut sessizce
      kaybolur. SiK telsizinde paket kaybı normaldir; bu yüzden birkaç kez
      denenip her seferinde aracın bildirdiği mod okunur.
      (Arayüzün `komut_mod`'u ile aynı mantık — orada SITL'de ölçülmüş.)
    """
    no = MOD_NO.get(mod_adi.lower())
    with _kilit:
        m = _D["mav"]
    if no is None or m is None:
        return False
    for _ in range(deneme):
        m.mav.set_mode_send(
            m.target_system,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, no)
        t0 = time.time()
        while time.time() - t0 < sure:
            with _kilit:
                if _D["kip"] == no:
                    return True
            time.sleep(0.1)
    return False


def _havada():
    with _kilit:
        return bool(_D["armli"]) and (_D["konum"] or (0, 0, 0))[2] > HAVADA_IRTIFA


def _ev_al():
    """Görevin dayanacağı EV noktası. Yoksa (None, sebep)."""
    with _kilit:
        ev, konum = _D["ev"], _D["konum"]
    if ev and abs(ev[0]) > 1e-7:
        return ev, "araçtan alınan EV noktası"
    if konum and abs(konum[0]) > 1e-7:
        return konum, "aracın ŞU ANKİ konumu (EV noktası gelmedi)"
    return None, ("konum yok — GPS fix bekleniyor. ⛔ Görev, EV noktasına "
                  "GÖRE kurulur; fix olmadan waypoint'in nereye düşeceği "
                  "belirsizdir.")


def _oge(seq, komut, param1=0.0, lat=0.0, lon=0.0, irtifa=0.0, current=0):
    return dict(seq=seq, frame=3, command=komut, current=current,
                autocontinue=1, param1=float(param1), param2=0.0, param3=0.0,
                param4=0.0, x=int(round(lat * 1e7)), y=int(round(lon * 1e7)),
                z=float(irtifa))


def gorev_kur(noktalar, ev, kalkis_irtifa=50.0, kalkis_pitch=15.0,
              bitince="rtl"):
    """Waypoint listesinden MISSION_ITEM_INT dizisi üretir.

    `noktalar`: [{"kuzey": m, "dogu": m, "irtifa": m}, ...]  EV'e göre metre.
    """
    from pymavlink import mavutil
    M = mavutil.mavlink
    cer = YerelCerceve().kokeni_kur(ev[0], ev[1], ev[2])
    ogeler = [
        # 0: ev noktası — araç bunu kendi ezer ama sıra bozulmamalı
        _oge(0, M.MAV_CMD_NAV_WAYPOINT, lat=ev[0], lon=ev[1], irtifa=0.0,
             current=1),
        # 1: kalkış
        _oge(1, M.MAV_CMD_NAV_TAKEOFF, param1=kalkis_pitch,
             lat=ev[0], lon=ev[1], irtifa=float(kalkis_irtifa)),
    ]
    for i, n in enumerate(noktalar):
        enlem, boylam, _ = cer.dereceye(float(n["kuzey"]), float(n["dogu"]), 0.0)
        ogeler.append(_oge(2 + i, M.MAV_CMD_NAV_WAYPOINT,
                           lat=enlem, lon=boylam,
                           irtifa=float(n.get("irtifa", kalkis_irtifa))))
    son = len(ogeler)
    if bitince == "loiter":
        ogeler.append(_oge(son, M.MAV_CMD_NAV_LOITER_UNLIM,
                           lat=ev[0], lon=ev[1], irtifa=float(kalkis_irtifa)))
    else:
        ogeler.append(_oge(son, M.MAV_CMD_NAV_RETURN_TO_LAUNCH))
    return ogeler


def gorev_yukle(ogeler, zaman_asimi=25.0):
    """MISSION_COUNT → MISSION_REQUEST → MISSION_ITEM_INT → MISSION_ACK.

    ⛔ "Kabul edildi" DEMEK OTURDU DEMEK DEĞİLDİR: yükleme sonunda öğe
       sayısı GERİ OKUNUR. Yarım kalmış bir görev, uçakta ESKİ görevin
       kalmasıyla sonuçlanır ve o çok tehlikelidir.
    """
    from pymavlink import mavutil
    with _kilit:
        m = _D["mav"]
    if m is None:
        return False, {"hata": "MAVLink bağlantısı yok"}
    hedef_s = m.target_system or 1
    hedef_b = m.target_component or 1
    m.mav.mission_count_send(hedef_s, hedef_b, len(ogeler))
    gonderilen = set()
    t0 = time.time()
    while time.time() - t0 < zaman_asimi:
        msg = m.recv_match(
            type=["MISSION_REQUEST", "MISSION_REQUEST_INT", "MISSION_ACK"],
            blocking=True, timeout=2.0)
        if msg is None:
            continue
        t = msg.get_type()
        if t == "MISSION_ACK":
            ok = (msg.type == 0)
            return ok, {"ack": int(msg.type),
                        "gonderilen": len(gonderilen),
                        "hata": None if ok else "araç görevi REDDETTİ (ack=%d)"
                                                % msg.type}
        i = msg.seq
        if i >= len(ogeler):
            continue
        o = ogeler[i]
        m.mav.mission_item_int_send(
            hedef_s, hedef_b, o["seq"], o["frame"], o["command"],
            o["current"], o["autocontinue"], o["param1"], o["param2"],
            o["param3"], o["param4"], o["x"], o["y"], o["z"])
        gonderilen.add(i)
    return False, {"hata": "zaman aşımı — araç görev isteği göndermeyi bıraktı",
                   "gonderilen": len(gonderilen)}


def gorev_sil():
    with _kilit:
        m = _D["mav"]
    if m is None:
        return False, "bağlantı yok"
    m.mav.mission_clear_all_send(m.target_system or 1, m.target_component or 1)
    msg = m.recv_match(type="MISSION_ACK", blocking=True, timeout=5.0)
    return (msg is not None and msg.type == 0), ("silindi" if msg else "cevap yok")


# ======================================================================
#  WEB
# ======================================================================
SAYFA = r"""<!doctype html><html lang=tr><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>TALON — GÖREV PLANI</title><style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:#0b0e13;color:#dfe6f0;
  font:13px/1.45 ui-monospace,Menlo,Consolas,monospace;min-height:100vh}
.ust{display:flex;gap:10px;align-items:center;padding:8px 12px;
     background:#131924;border-bottom:1px solid #223;flex-wrap:wrap}
.ust b{font-size:15px;letter-spacing:1px}
.rozet{padding:3px 9px;border-radius:4px;font-weight:700;font-size:12px}
.ok{background:#123d1e;color:#5fe08a}.kotu{background:#3d1212;color:#ff7b7b}
.uyari{background:#3d3312;color:#ffd166}
main{display:grid;grid-template-columns:1fr 320px;gap:10px;padding:10px}
@media(max-width:900px){main{grid-template-columns:1fr}}
.kutu{background:#131924;border:1px solid #223;border-radius:8px;padding:10px}
.kutu h3{font-size:11px;letter-spacing:1.5px;color:#7d8aa0;margin-bottom:7px;
         text-transform:uppercase}
.harita{position:relative}
#plan{width:100%;height:70vh;min-height:380px;display:block;background:#0d1117;
      border-radius:6px;cursor:crosshair;touch-action:none}
#plan.suru{cursor:grabbing}
.zum{position:absolute;left:10px;top:34px;display:flex;flex-direction:column;
     gap:4px;z-index:5}
.zum button{width:30px;height:30px;flex:none;padding:0;font-size:16px;
     background:#131924e0}
.olcubar{position:absolute;right:12px;bottom:10px;z-index:5;color:#dfe6f0;
     font-size:11px;text-align:center;text-shadow:0 0 4px #000;pointer-events:none}
.olcubar div{border:2px solid #dfe6f0;border-top:0;height:6px}
.katki{position:absolute;left:10px;bottom:8px;z-index:5;font-size:9px;
     color:#7d8aa0;text-shadow:0 0 4px #000;pointer-events:none}
table{width:100%;border-collapse:collapse;font-size:12px}
td,th{padding:3px 4px;text-align:left;border-bottom:1px solid #1c2438}
th{color:#7d8aa0;font-weight:400}
button{padding:8px 6px;border:1px solid #2a3550;border-radius:6px;
  background:#1b2333;color:#dfe6f0;font:700 12px ui-monospace,monospace;
  cursor:pointer;flex:1}
button:hover{background:#243049}
button.ana{background:#1d4ed8;border-color:#60a5fa;color:#fff}
button.tehlike{background:#7f1d1d;border-color:#ef4444}
button.baslat{background:#14532d;border-color:#22c55e;color:#c9f7d5}
button.baslat:hover{background:#166534}
button:disabled{opacity:.4;cursor:not-allowed}
button:disabled:hover{background:#1b2333}
.satir{display:flex;gap:6px;margin-top:8px}
label{display:block;color:#7d8aa0;font-size:11px;margin-top:8px}
input,select{width:100%;padding:6px;background:#0b0e13;color:#dfe6f0;
  border:1px solid #2a3550;border-radius:4px;font:12px ui-monospace,monospace}
.mesaj{margin-top:10px;font-size:11px;min-height:34px;color:#ffd166}
.sonuk{color:#7d8aa0}
.cubuk{height:6px;background:#0b0e13;border:1px solid #2a3550;border-radius:3px;
  margin-top:6px;overflow:hidden}
.cubuk i{display:block;height:100%;background:#2f7dd1;width:0}
.pilcubuk{position:relative;height:14px;background:#0b0e13;border:1px solid #2a3550;
  border-radius:4px;overflow:hidden;margin-bottom:7px}
.pilcubuk i{display:block;height:100%;width:0;transition:width .3s}
.iyi{color:#5fe08a}.orta{color:#ffd166}.kotu2{color:#ff7b7b}
</style></head><body>
<div class=ust><b>TALON — GÖREV PLANI</b>
  <span id=r_bagli class="rozet kotu">MAVLINK</span>
  <span id=r_ev class="rozet kotu">EV NOKTASI</span>
  <span id=r_karo class="rozet uyari">KARO</span>
  <span id=r_mod class="rozet uyari">MOD</span>
  <span id=r_n class="rozet uyari">0 nokta</span>
  <span style="flex:1"></span><span id=r_mesaj class=sonuk></span>
</div>
<main>
  <div class="kutu harita">
    <h3>Harita — tıkla: nokta ekle · sürükle: kaydır ·
        sağ tık: son noktayı sil · tekerlek: yakınlaş</h3>
    <canvas id=plan></canvas>
    <div class=zum><button id=b_zin>+</button><button id=b_zout>−</button>
      <button id=b_eve title="EV noktasına dön">⌖</button></div>
    <div class=olcubar id=olcubar><span id=olcu_yazi>100 m</span><div
      id=olcu_cizgi style="width:80px"></div></div>
    <div class=katki>© OpenStreetMap katkıcıları</div>
  </div>
  <div>
    <div class=kutu>
      <h3>Talon — canlı</h3>
      <div class=pilcubuk><i id=t_pil></i></div>
      <table id=t_telem></table>
    </div>
    <div class=kutu style="margin-top:10px">
      <h3>Görev</h3>
      <label>Kalkış irtifası (m)</label><input id=kalkis type=number value=50>
      <label>Varsayılan waypoint irtifası (m)</label>
      <input id=irtifa type=number value=80>
      <label>Görev bitince</label>
      <select id=bitince><option value=rtl>EVE DÖN (RTL)</option>
        <option value=loiter>HAVADA BEKLE (LOITER)</option></select>
      <div class=satir><button id=b_yukle class=ana>GÖREVİ YÜKLE</button></div>
      <div class=satir>
        <button id=b_baslat class=baslat disabled>GÖREVİ BAŞLAT (AUTO)</button>
      </div>
      <div class=satir>
        <button id=b_dur>DURDUR (LOITER)</button>
      </div>
      <div class=satir>
        <button id=b_geri>SON NOKTAYI SİL</button>
        <button id=b_temizle>TÜMÜNÜ SİL</button>
      </div>
      <div class=satir>
        <button id=b_aractan_sil class=tehlike>ARAÇTAKİ GÖREVİ SİL</button>
      </div>
      <div class=mesaj id=mesaj></div>
    </div>
    <div class=kutu style="margin-top:10px">
      <h3>Harita önbelleği (çevrimdışı)</h3>
      <div id=karo_bilgi class=sonuk style="font-size:11px">…</div>
      <label>Yarıçap (m)</label><input id=k_yaricap type=number value=2000>
      <label>Zoom aralığı</label>
      <select id=k_zoom>
        <option value="14-16">14-16 — hızlı, kaba (~1 dk)</option>
        <option value="14-17" selected>14-17 — önerilen (~1 dk)</option>
        <option value="14-18">14-18 — en detaylı (~5 dk)</option>
      </select>
      <div class=satir><button id=b_indir>ALANI İNDİR</button></div>
      <div class=cubuk><i id=k_cubuk></i></div>
      <div id=k_durum class=sonuk style="font-size:11px;margin-top:5px"></div>
    </div>
    <div class=kutu style="margin-top:10px">
      <h3>Noktalar</h3>
      <table id=liste><tr><th>#</th><th>kuzey</th><th>doğu</th>
        <th>irtifa</th><th>uzaklık</th></tr></table>
    </div>
  </div>
</main>
<script>
// ---------------------------------------------------------------- projeksiyon
// gercek/konum.py YerelCerceve ile BİREBİR AYNI formül. Waypoint'i lat/lon
// olarak tutuyoruz (yerdeki fiziksel nokta budur); yüklemeden hemen önce
// EV'e göre metreye çeviriyoruz, çünkü sunucudaki gorev_kur() metre bekliyor
// (R72/R73 bekçileri o sözleşmeyi koruyor). Gidiş-dönüş aynı formül olduğu
// için hata milimetre altındadır.
// E2 konum.py ile AYNI ŞEKİLDE türetilir (sabiti elle kısaltmak,
// iki tarafın sessizce ayrışmasına açık kapı bırakır — R76).
const A=6378137.0, F=1/298.257223563, E2=F*(2-F), RAD=Math.PI/180;
function MN(lat){const s=Math.sin(lat*RAD), t=1-E2*s*s;
  return [A*(1-E2)/Math.pow(t,1.5), A/Math.sqrt(t)];}
function metreye(lat,lon,lat0,lon0){const [M,N]=MN(lat0);
  return [(lat-lat0)*RAD*M, (lon-lon0)*RAD*N*Math.cos(lat0*RAD)];}
function dereceye(k,d,lat0,lon0){const [M,N]=MN(lat0);
  return [lat0+(k/M)/RAD, lon0+(d/(N*Math.cos(lat0*RAD)))/RAD];}

// -------------------------------------------------------------- harita durumu
let N=[], ev=null, konum=null, yon=null, bagli=false, evVar=false;
let z=16, mLat=41.0, mLon=29.0, merkezKuruldu=false;
// ?merkez=ENLEM,BOYLAM[,ZOOM] — GPS fix yokken (kapalı ortam) haritayı
// elle bir yere oturtmak için. Verilirse EV geldiğinde merkez KAYMAZ.
{const q=new URLSearchParams(location.search).get("merkez");
 if(q){const p=q.split(",").map(parseFloat);
   if(p.length>=2&&isFinite(p[0])&&isFinite(p[1])){
     mLat=p[0];mLon=p[1];merkezKuruldu=true;
     if(p.length>2&&isFinite(p[2]))z=Math.max(3,Math.min(19,p[2]|0));}}}
const c=document.getElementById("plan"), g=c.getContext("2d");

// Web Mercator: dünya, zoom z'de 256*2^z piksel.
function dunya(){return 256*Math.pow(2,z);}
function pxX(lon){return (lon+180)/360*dunya();}
function pxY(lat){return (1-Math.asinh(Math.tan(lat*RAD))/Math.PI)/2*dunya();}
function lonX(px){return px/dunya()*360-180;}
function latY(py){return Math.atan(Math.sinh(Math.PI*(1-2*py/dunya())))/RAD;}
let W=0,H=0,x0=0,y0=0;   // görüntü penceresinin sol-üst dünya pikseli
function boyut(){const r=c.getBoundingClientRect(),o=devicePixelRatio||1;
  if(c.width!==Math.round(r.width*o)||c.height!==Math.round(r.height*o)){
    c.width=Math.round(r.width*o);c.height=Math.round(r.height*o);}
  g.setTransform(o,0,0,o,0,0);W=r.width;H=r.height;
  x0=pxX(mLon)-W/2; y0=pxY(mLat)-H/2;}
function ekran(lat,lon){return [pxX(lon)-x0, pxY(lat)-y0];}
function konumu(sx,sy){return [latY(y0+sy), lonX(x0+sx)];}
function mpp(){return 156543.03392*Math.cos(mLat*RAD)/Math.pow(2,z);}

// ------------------------------------------------------------------ karo önbl.
const KIMG=new Map(), KYOK=new Set();
let eksik=0;
function karoAl(zz,x,y){
  const k=zz+"/"+x+"/"+y;
  if(KYOK.has(k))return null;
  let im=KIMG.get(k);
  if(im)return im.tam?im:null;
  im=new Image(); im.tam=false;
  im.onload=()=>{im.tam=true;iste();};
  im.onerror=()=>{KYOK.delete(k);KYOK.add(k);KIMG.delete(k);iste();};
  im.src="/karo/"+k+".png";
  KIMG.set(k,im);
  return null;
}
function karolariUnut(){KYOK.clear();KIMG.clear();iste();}

let kirli=false;
function iste(){if(kirli)return;kirli=true;
  requestAnimationFrame(()=>{kirli=false;ciz();});}

// ----------------------------------------------------------------------- çizim
function karolariCiz(){
  const n=Math.pow(2,z);
  const tx0=Math.floor(x0/256), tx1=Math.floor((x0+W)/256);
  const ty0=Math.floor(y0/256), ty1=Math.floor((y0+H)/256);
  eksik=0;
  for(let tx=tx0;tx<=tx1;tx++)for(let ty=ty0;ty<=ty1;ty++){
    const ex=tx*256-x0, ey=ty*256-y0;
    if(tx<0||ty<0||tx>=n||ty>=n)continue;
    const im=karoAl(z,tx,ty);
    if(im){g.drawImage(im,ex,ey,256,256);}
    else{
      eksik++;
      // karo yoksa: koyu blok + ince ızgara. Kullanıcı "harita bozuk"
      // sanmasın diye AÇIKÇA yazıyoruz.
      g.fillStyle="#0f141c";g.fillRect(ex,ey,256,256);
      g.strokeStyle="#1a2130";g.lineWidth=1;g.strokeRect(ex+.5,ey+.5,255,255);
    }
  }
  if(eksik){
    g.fillStyle="#ffd166";g.font="12px monospace";
    g.fillText("⚠ bu bölgenin karoları indirilmemiş — sağdaki "+
      "\"ALANI İNDİR\"",12,H-14);
  }
}
function isaret(lat,lon,renk,yazi,r){
  const p=ekran(lat,lon);
  if(p[0]<-40||p[0]>W+40||p[1]<-40||p[1]>H+40)return null;
  g.fillStyle=renk;g.beginPath();g.arc(p[0],p[1],r||6,0,6.284);g.fill();
  g.strokeStyle="#0b0e13";g.lineWidth=2;g.stroke();
  if(yazi){g.fillStyle=renk;g.font="bold 10px monospace";
    g.fillText(yazi,p[0]+10,p[1]+4);}
  return p;
}
function ucakCiz(){
  if(!konum)return;
  const p=ekran(konum[0],konum[1]);
  g.save();g.translate(p[0],p[1]);
  if(yon!==null)g.rotate(yon*RAD);
  g.fillStyle="#ffd166";g.strokeStyle="#0b0e13";g.lineWidth=1.5;
  g.beginPath();g.moveTo(0,-11);g.lineTo(7,9);g.lineTo(0,5);g.lineTo(-7,9);
  g.closePath();g.fill();g.stroke();g.restore();
  g.fillStyle="#ffd166";g.font="bold 10px monospace";
  g.fillText("TALON "+Math.round(konum[2])+"m",p[0]+12,p[1]+4);
}
function ciz(){
  boyut(); g.clearRect(0,0,W,H);
  karolariCiz();
  // rota
  if(N.length&&ev){
    const noktalar=[ekran(ev[0],ev[1])].concat(N.map(n=>ekran(n.lat,n.lon)));
    g.strokeStyle="#2f7dd1";g.lineWidth=2.5;g.beginPath();
    g.moveTo(noktalar[0][0],noktalar[0][1]);
    for(let i=1;i<noktalar.length;i++)g.lineTo(noktalar[i][0],noktalar[i][1]);
    g.stroke();
  }else if(N.length){
    const p=N.map(n=>ekran(n.lat,n.lon));
    g.strokeStyle="#2f7dd1";g.lineWidth=2.5;g.beginPath();
    g.moveTo(p[0][0],p[0][1]);
    for(let i=1;i<p.length;i++)g.lineTo(p[i][0],p[i][1]);
    g.stroke();
  }
  N.forEach((n,i)=>{
    const p=isaret(n.lat,n.lon,"#6fb2ff",null,8);
    if(!p)return;
    g.fillStyle="#0b0e13";g.font="bold 10px monospace";
    g.fillText(String(i+1),p[0]-(i>8?6:3),p[1]+4);
    g.fillStyle="#9ccaff";g.font="10px monospace";
    g.fillText(n.irtifa+"m",p[0]+11,p[1]-9);
  });
  if(ev)isaret(ev[0],ev[1],"#5fe08a","EV",7);
  ucakCiz();
  olcuGuncelle();
}
function olcuGuncelle(){
  const m=mpp();
  // 80 px'e en yakın "güzel" sayı
  let hedef=80*m, adim=Math.pow(10,Math.floor(Math.log10(hedef)));
  for(const k of [1,2,5,10]){if(adim*k>=hedef){adim*=k;break;}}
  const gen=Math.round(adim/m);
  document.getElementById("olcu_cizgi").style.width=gen+"px";
  document.getElementById("olcu_yazi").textContent=
    adim>=1000?(adim/1000)+" km":adim+" m";
}

// -------------------------------------------------------------- etkileşim
let suru=null, kaydi=false;
c.addEventListener("pointerdown",e=>{
  c.setPointerCapture(e.pointerId);
  suru={x:e.clientX,y:e.clientY};kaydi=false;});
c.addEventListener("pointermove",e=>{
  if(!suru)return;
  const dx=e.clientX-suru.x, dy=e.clientY-suru.y;
  if(Math.abs(dx)+Math.abs(dy)>3){kaydi=true;c.classList.add("suru");}
  if(!kaydi)return;
  mLon=lonX(pxX(mLon)-dx); mLat=latY(pxY(mLat)-dy);
  suru={x:e.clientX,y:e.clientY};iste();});
c.addEventListener("pointerup",e=>{
  c.classList.remove("suru");
  const s=suru;suru=null;
  if(kaydi||!s)return;
  const r=c.getBoundingClientRect();
  const [lat,lon]=konumu(e.clientX-r.left,e.clientY-r.top);
  N.push({lat:lat,lon:lon,
          irtifa:parseInt(document.getElementById("irtifa").value)||80});
  guncelle();});
c.addEventListener("pointercancel",()=>{suru=null;c.classList.remove("suru");});
c.addEventListener("contextmenu",e=>{e.preventDefault();N.pop();guncelle();});
function zumla(dz,sx,sy){
  const yeni=Math.max(3,Math.min(19,z+dz));
  if(yeni===z)return;
  // imlecin altındaki nokta yerinde kalsın
  let lat=mLat, lon=mLon;
  if(sx!==undefined){const p=konumu(sx,sy);lat=p[0];lon=p[1];}
  z=yeni; boyut();
  if(sx!==undefined){
    // yeni zoom'da imlecin altına aynı noktayı getir
    const hedef=[pxX(lon),pxY(lat)];
    x0=hedef[0]-sx; y0=hedef[1]-sy;
    mLon=lonX(x0+W/2); mLat=latY(y0+H/2);
  }
  iste();}
c.addEventListener("wheel",e=>{e.preventDefault();
  const r=c.getBoundingClientRect();
  zumla(e.deltaY>0?-1:1,e.clientX-r.left,e.clientY-r.top);},{passive:false});
document.getElementById("b_zin").onclick=()=>zumla(1);
document.getElementById("b_zout").onclick=()=>zumla(-1);
document.getElementById("b_eve").onclick=()=>{
  if(ev){mLat=ev[0];mLon=ev[1];iste();}
  else mes("⛔ EV noktası yok — GPS fix bekleniyor",1);};

// ------------------------------------------------------------------- tablo
function guncelle(){
  iste();
  document.getElementById("r_n").textContent=N.length+" nokta";
  let h="<tr><th>#</th><th>kuzey</th><th>doğu</th><th>irtifa</th>"+
        "<th>uzaklık</th></tr>";
  N.forEach((n,i)=>{
    let k="—",d="—",u="—";
    if(ev){const m=metreye(n.lat,n.lon,ev[0],ev[1]);
      k=Math.round(m[0]);d=Math.round(m[1]);
      u=Math.round(Math.hypot(m[0],m[1]))+" m";}
    h+=`<tr><td>${i+1}</td><td>${k}</td><td>${d}</td>`+
       `<td>${n.irtifa}</td><td>${u}</td></tr>`;});
  document.getElementById("liste").innerHTML=h;
}
const mes=(t,k)=>{const e=document.getElementById("mesaj");
  e.textContent=t;e.style.color=k?"#ff7b7b":"#5fe08a";};
document.getElementById("b_geri").onclick=()=>{N.pop();guncelle();};
document.getElementById("b_temizle").onclick=()=>{N=[];guncelle();};
document.getElementById("b_yukle").onclick=async()=>{
  if(!N.length){mes("⛔ hiç waypoint yok",1);return;}
  if(!evVar){mes("⛔ EV noktası yok — GPS fix bekleniyor",1);return;}
  const metre=N.map(n=>{const m=metreye(n.lat,n.lon,ev[0],ev[1]);
    return {kuzey:m[0],dogu:m[1],irtifa:n.irtifa};});
  mes("yükleniyor…");
  const r=await (await fetch("/api/yukle",{method:"POST",body:JSON.stringify({
    noktalar:metre, kalkis:parseInt(document.getElementById("kalkis").value)||50,
    bitince:document.getElementById("bitince").value})})).json();
  mes(r.mesaj, !r.ok);};
document.getElementById("b_baslat").onclick=async()=>{
  // ⛔ Bu düğme uçağı OTONOM UÇUŞA sokar. Yanlışlıkla basılmasın.
  if(!confirm("GÖREV BAŞLATILACAK.\n\nUçak AUTO moduna alınacak ve "+
     "kalkış/rota kendiliğinden işleyecek.\n\nHer şey hazır mı?"))return;
  mes("AUTO'ya geçiliyor…");
  const r=await (await fetch("/api/baslat",{method:"POST",body:"{}"})).json();
  mes(r.mesaj,!r.ok);};
document.getElementById("b_dur").onclick=async()=>{
  mes("LOITER'a geçiliyor…");
  const r=await (await fetch("/api/dur",{method:"POST",body:"{}"})).json();
  mes(r.mesaj,!r.ok);};
document.getElementById("b_aractan_sil").onclick=async()=>{
  if(!confirm("Araçtaki görev SİLİNSİN mi?"))return;
  const r=await (await fetch("/api/sil",{method:"POST",body:"{}"})).json();
  mes(r.mesaj,!r.ok);};

// ------------------------------------------------------------- karo indirme
document.getElementById("b_indir").onclick=async()=>{
  const zz=document.getElementById("k_zoom").value.split("-");
  const g_=document.getElementById("k_durum");
  const gov={yaricap:parseFloat(document.getElementById("k_yaricap").value)||2000,
             z_alt:parseInt(zz[0]), z_ust:parseInt(zz[1])};
  if(ev){gov.enlem=ev[0];gov.boylam=ev[1];}
  else {gov.enlem=mLat;gov.boylam=mLon;g_.textContent=
    "EV yok — HARİTA MERKEZİ kullanılıyor.";}
  const r=await (await fetch("/api/karo_indir",{method:"POST",
    body:JSON.stringify(gov)})).json();
  g_.textContent=r.mesaj;
};

// --------------------------------------------------------------------- döngü
// EV yokken haritayı nereye oturtacağız: en son İNDİRİLEN alanın merkezi.
// (merkezKuruldu'yu true YAPMIYORUZ — EV gelince oraya kayabilsin.)
const kr_alan=d=>(d&&d.karo&&d.karo.alan)?d.karo.alan:null;
const rozet=(id,ok,t)=>{const e=document.getElementById(id);
  e.className="rozet "+(ok?"ok":"kotu");e.textContent=t;};
setInterval(async()=>{
  let d;try{d=await (await fetch("/api/durum")).json();}catch(e){return;}
  bagli=d.bagli; evVar=!!d.ev; ev=d.ev; konum=d.konum;
  yon=(d.yon===null||d.yon===undefined)?null:d.yon;
  if(ev&&!merkezKuruldu){mLat=ev[0];mLon=ev[1];merkezKuruldu=true;guncelle();}
  else if(!merkezKuruldu&&kr_alan(d)){const a=kr_alan(d);
    mLat=a.enlem;mLon=a.boylam;guncelle();}   // EV yoksa: indirilen alan
  else if(konum)iste();
  rozet("r_bagli",d.bagli,"MAVLINK "+(d.n_paket||0));
  rozet("r_ev",evVar,evVar?"EV ✔":"EV YOK (GPS)");
  const kr=d.karo||{};
  const kb=document.getElementById("r_karo");
  kb.className="rozet "+(kr.karo>0?"ok":"uyari");
  kb.textContent="KARO "+(kr.karo||0);
  document.getElementById("karo_bilgi").textContent=
    (kr.karo||0)+" karo · "+(kr.mb||0)+" MB · "+(kr.dizin||"");
  const ind=d.indirme;
  if(ind){
    const y=ind.toplam?100*ind.biten/ind.toplam:0;
    document.getElementById("k_cubuk").style.width=y.toFixed(1)+"%";
    document.getElementById("k_durum").textContent=
      (ind.calisiyor?"indiriliyor ":"bitti ")+ind.biten+"/"+ind.toplam+
      (ind.hata?("  hata "+ind.hata):"");
    if(!ind.calisiyor&&ind.biten>=ind.toplam&&!ind.temiz){
      ind.temiz=true;karolariUnut();}
    if(ind.calisiyor&&ind.biten%25===0)karolariUnut();
  }
  // MOD rozeti + BAŞLAT'ın açılma koşulu. Kullanıcı NEDEN kapalı olduğunu
  // düğmenin üstüne gelince görsün — sessiz gri düğme en kötüsü.
  const mb=document.getElementById("r_mod");
  mb.className="rozet "+((d.mod==="AUTO")?"ok":"uyari");
  mb.textContent=(d.mod||"MOD")+(d.armli?" · ARMLI":" · DISARM");
  const bb=document.getElementById("b_baslat");
  let engel=null;
  if(!d.bagli)engel="MAVLink bağlı değil";
  else if(!d.gorev)engel="önce GÖREVİ YÜKLE";
  else if(!d.armli)engel="araç ARM değil";
  bb.disabled=!!engel;
  bb.title=engel?("kapalı: "+engel):"uçağı AUTO moduna alır";
  // ---- TALON CANLI TELEMETRİSİ ----
  const sat=(a,b)=>`<tr><td style="color:#7d8aa0">${a}</td>`+
    `<td style="text-align:right;font-weight:700">${b}</td></tr>`;
  const n1=(v,b)=>(v==null?"—":(v.toFixed?v.toFixed(1):v)+(b||""));
  const FIX={0:"yok",1:"yok",2:"2D",3:"3D",4:"3D+",5:"RTK",6:"RTK"};
  if(d.pil_v!=null){
    // ⚠ HÜCRE SAYISI TAHMİN EDİLMEZ: yüzde geliyorsa o kullanılır.
    //   Yoksa çubuk boş kalır ama gerilim yine yazılır.
    const y=(d.pil_yuzde!=null?d.pil_yuzde:0);
    const e=document.getElementById("t_pil");
    e.style.width=y+"%";
    e.style.background=(y<20?"#ff7b7b":y<40?"#ffd166":"#5fe08a");
  }
  document.getElementById("t_telem").innerHTML=
    sat("bağlantı",d.bagli
        ?'<span class=iyi>BAĞLI</span> '+(d.n_paket||0)
        :'<span class=kotu2>KOPUK</span>')+
    sat("mod",'<b>'+(d.mod||"—")+'</b>'+(d.armli?" · ARMLI":" · disarm"))+
    sat("GPS",(FIX[d.fix]||"—")+"  ·  "+(d.uydu??"—")+" uydu")+
    sat("pil",(d.pil_v!=null?d.pil_v.toFixed(2)+" V":"—")+
        (d.pil_yuzde!=null?("  ·  "+d.pil_yuzde+"%"):""))+
    sat("irtifa",n1(d.irtifa," m"))+
    sat("hız",n1(d.hiz," m/s")+(d.hava_hizi!=null
        ?('  <span style="color:#7d8aa0">hava '+d.hava_hizi.toFixed(1)+'</span>'):""))+
    sat("tırmanış",n1(d.tirmanis," m/s"))+
    sat("gaz",(d.gaz??"—")+" %")+
    sat("yön",n1(d.yon,"°"))+
    sat("aktif öğe",(d.aktif_oge??"—"));
  document.getElementById("r_mesaj").textContent=d.son_mesaj||"";
},700);
addEventListener("resize",iste);
guncelle();
</script></body></html>"""


class _H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _y(self, kod, tur, g):
        self.send_response(kod)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(g)))
        self.end_headers()
        try:
            self.wfile.write(g)
        except Exception:
            pass

    def _c(self, ok, mesaj, **ek):
        """Kısa JSON cevabı."""
        return self._y(200, "application/json",
                       json.dumps({"ok": bool(ok), "mesaj": mesaj,
                                   **ek}).encode())

    def do_GET(self):
        # Sorgu dizesini AYIR: "/?merkez=41,29" de kök sayfadır.
        self.path = self.path.split("?", 1)[0]
        if self.path == "/":
            return self._y(200, "text/html; charset=utf-8", SAYFA.encode())
        if self.path.startswith("/karo/"):
            # ⛔ YALNIZ ÖNBELLEKTEN. Sahada internet olmayabilir; burada
            #   ağa gitmek, panelin her karoda saniyelerce ASILMASINA yol
            #   açardı. İndirme AYRI bir adımdır (--indir).
            try:
                z, x, y = [int(v) for v in
                           self.path[6:].replace(".png", "").split("/")]
            except Exception:
                return self._y(400, "text/plain", b"gecersiz karo")
            veri = KARO.oku(z, x, y)
            if veri is None:
                return self._y(404, "text/plain", b"karo yok")
            return self._y(200, "image/png", veri)
        if self.path == "/api/karo_durum":
            return self._y(200, "application/json",
                           json.dumps(KARO.onbellek_durumu()).encode())
        if self.path == "/api/durum":
            ev, sebep = _ev_al()
            with _kilit:
                d = {"bagli": _D["bagli"], "n_paket": _D["n_paket"],
                     "son_mesaj": _D["son_mesaj"]}
            d["ev"] = ev
            d["ev_sebep"] = sebep
            d["konum"] = _D["konum"]
            d["yon"] = _D["yon"]
            for a in ("hiz", "hava_hizi", "gaz", "irtifa", "tirmanis",
                      "uydu", "fix", "pil_v", "pil_yuzde", "aktif_oge"):
                d[a] = _D[a]
            d["mod"] = _D["mod"]
            d["armli"] = _D["armli"]
            d["gorev"] = _D["gorev"]
            d["indirme"] = _D["indirme"]
            d["karo"] = KARO.onbellek_durumu()
            return self._y(200, "application/json", json.dumps(d).encode())
        self._y(404, "text/plain", b"yok")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            g = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            g = {}
        if self.path == "/api/yukle":
            ev, sebep = _ev_al()
            if ev is None:
                return self._y(200, "application/json",
                               json.dumps({"ok": False, "mesaj": sebep}).encode())
            try:
                ogeler = gorev_kur(g.get("noktalar", []), ev,
                                   kalkis_irtifa=float(g.get("kalkis", 50)),
                                   bitince=str(g.get("bitince", "rtl")))
            except Exception as e:
                return self._y(200, "application/json", json.dumps(
                    {"ok": False, "mesaj": "görev kurulamadı: %s" % e}).encode())
            ok, ay = gorev_yukle(ogeler)
            with _kilit:
                # ⛔ Arayüz (localhost:8000) araçtaki görevi GERİ OKUMAZ —
                #   yalnız KENDİ yüklediğini hatırlar. Buradan yüklenen
                #   görev onun için görünmezdir ve BAŞLAT düğmesi kapalı
                #   kalır. Bu yüzden başlatmayı da BURASI yapar.
                _D["gorev"] = {"oge": len(ogeler), "zaman": time.time(),
                               "ilk_wp_seq": 2} if ok else None
            mesaj = ("✔ %d öğe yüklendi (%s). Şimdi GÖREVİ BAŞLAT."
                     % (len(ogeler), sebep)) if ok else \
                    ("⛔ " + str(ay.get("hata")))
            return self._y(200, "application/json",
                           json.dumps({"ok": ok, "mesaj": mesaj,
                                       "oge": len(ogeler), **ay}).encode())
        if self.path == "/api/baslat":
            with _kilit:
                gorev, mod, armli = _D["gorev"], _D["mod"], _D["armli"]
                m = _D["mav"]
            if m is None:
                return self._c(False, "MAVLink bağlı değil")
            if not gorev:
                return self._c(False, "önce GÖREVİ YÜKLE")
            if not MOD_NO:
                return self._c(False, "mod tablosu okunamadı — başlatılamaz")
            if not armli:
                return self._c(False, "araç ARM değil — önce arayüzden ARM et")

            havada = _havada()
            # 1) BAŞLANGIÇ ÖĞESİNİ SABİTLE.
            #    MIS_RESTART=0 olduğu için AUTO'ya girmek görevi KALDIĞI
            #    YERDEN sürdürür; kullanıcı baştan başlayacağını sanır.
            #    Ayrıca son öğe (RTL) üzerinde kalmak aracın "In landing
            #    sequence" deyip ARM'ı reddetmesine yol açıyor.
            baslangic = gorev["ilk_wp_seq"] if havada else 1
            m.mav.mission_set_current_send(
                m.target_system, m.target_component, int(baslangic))
            time.sleep(0.3)

            # 2) YERDEYKEN ZATEN OTOMATİK MODDAYSAK ÖNCE ÇIK.
            #    Araç zaten AUTO'daysa "AUTO'ya geç" komutu hiçbir şey
            #    yapmaz ve ArduPlane'in kalkış tetikleyicisi (elden atış
            #    algılama) HİÇ ÇALIŞMAZ: uçak arm'lı yerde bekler ve
            #    DISARM_DELAY dolunca kendiliğinden disarm olur.
            #    (Arayüzde 22 Ağu 2026 SITL'de ölçülmüş: 600 s irtifa 0.)
            #    ⛔ HAVADAYKEN YAPILMAZ — uçuş ortasında moddan çıkmak
            #    rotayı bozar.
            ara = None
            if not havada and (mod or "").lower() in _OTOMATIK_MODLAR:
                komut_mod("fbwa", deneme=2)
                ara = "FBWA"
                time.sleep(0.5)

            ok = komut_mod("auto")
            if ok:
                mesaj = ("✔ AUTO — görev %d. öğeden başlıyor%s"
                         % (baslangic, " (kalkış atlandı, uçak havada)"
                            if havada else ""))
                if ara:
                    mesaj += " · araya %s girildi (kalkış tetiği için)" % ara
            else:
                with _kilit:
                    sm = _D["son_mesaj"]
                mesaj = ("⛔ AUTO'ya geçilemedi. Araç ne diyor: %s"
                         % (sm or "—"))
            return self._c(ok, mesaj, mod="AUTO" if ok else None,
                           baslangic=int(baslangic), havada=havada)

        if self.path == "/api/dur":
            with _kilit:
                m = _D["mav"]
            if m is None:
                return self._c(False, "MAVLink bağlı değil")
            ok = komut_mod("loiter")
            return self._c(ok, "✔ LOITER — uçak bulunduğu yerde tur atıyor"
                           if ok else "⛔ LOITER'a geçilemedi")

        if self.path == "/api/karo_indir":
            ev, sebep = _ev_al()
            e = g.get("enlem"); b = g.get("boylam")
            if e is None or b is None:
                if ev is None:
                    return self._y(200, "application/json", json.dumps(
                        {"ok": False, "mesaj": "merkez yok: " + sebep}).encode())
                e, b = ev[0], ev[1]
            calisan = _D.get("indirme")
            if calisan and calisan.get("calisiyor"):
                # ⛔ İKİ İNDİRME AYNI ANDA = OSM'ye saniyede 16 istek.
                #   OSM gönüllü sunucuları; bu, IP'nin engellenmesine yol
                #   açar ve sahada harita indiremezsin.
                return self._y(200, "application/json", json.dumps(
                    {"ok": False, "mesaj": "zaten indirme sürüyor (%d/%d)"
                     % (calisan.get("biten", 0), calisan.get("toplam", 0))}
                ).encode())
            yaricap = float(g.get("yaricap", 2000))
            za, zu = int(g.get("z_alt", 14)), int(g.get("z_ust", 17))
            liste = KARO.alan_karolari(e, b, yaricap, za, zu)
            _D["indirme"] = {"toplam": len(liste), "biten": 0, "hata": 0,
                             "calisiyor": True}

            def _is():
                def ilerle(i, n, ind, varr, hata):
                    _D["indirme"].update(biten=i, toplam=n, hata=hata)
                KARO.alan_indir(e, b, yaricap, za, zu, ilerleme=ilerle)
                _D["indirme"]["calisiyor"] = False
            threading.Thread(target=_is, daemon=True).start()
            return self._y(200, "application/json", json.dumps(
                {"ok": True, "mesaj": "%d karo indiriliyor (~%.0f MB)"
                 % (len(liste), len(liste) * 0.02),
                 "toplam": len(liste)}).encode())
        if self.path == "/api/sil":
            ok, m = gorev_sil()
            return self._y(200, "application/json",
                           json.dumps({"ok": ok, "mesaj": m}).encode())
        self._y(404, "application/json", b'{"ok":0}')


def main():
    ap = argparse.ArgumentParser(description="Talon görev planlayıcı")
    ap.add_argument("--mav", default="udp:127.0.0.1:14554",
                    help="yayıncının ALT SÜREÇ aynası")
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--indir", nargs="?", const="oto", default=None,
                    metavar="ENLEM,BOYLAM",
                    help="uçuş alanı karolarını indir ve çık "
                         "(boş bırakılırsa araçtan konum alınır)")
    ap.add_argument("--yaricap", type=float, default=2000.0)
    ap.add_argument("--z", default="14-17", help="zoom aralığı, ör. 14-17")
    a = ap.parse_args()
    print("=" * 66)
    if a.indir is not None:
        # ⛔ İndirme modunda SUNUCU AÇILMAZ. Sunucu afişini basmak
        #   "panel ayakta" sanısı yaratıyordu.
        print("  HARİTA KAROLARI — çevrimdışı önbelleğe indirme")
        print("=" * 66)
        try:
            za, zu = [int(v) for v in a.z.split("-")]
            if not (0 <= za <= zu <= 19):
                raise ValueError
        except ValueError:
            print("  ⛔ --z '%s' geçersiz. Örnek: --z 14-17" % a.z)
            return 2
        if a.indir == "oto":
            threading.Thread(target=_mav_dongu, args=(a.mav,), daemon=True).start()
            print("  araçtan konum bekleniyor (en fazla 20 s)…")
            for _ in range(40):
                ev, _s = _ev_al()
                if ev:
                    break
                time.sleep(0.5)
            if not ev:
                print("  ⛔ araçtan konum alınamadı. Elle ver:")
                print("     --indir 41.1050,29.0230")
                return 2
            e, b = ev[0], ev[1]
        else:
            try:
                e, b = [float(v) for v in a.indir.split(",")]
                if not (-90 <= e <= 90 and -180 <= b <= 180):
                    raise ValueError("aralık dışı")
            except ValueError:
                print("  ⛔ '%s' bir koordinat değil.\n" % a.indir)
                print("  Koordinatı ŞÖYLE yaz (nokta ondalık, virgülle "
                      "ayrılmış):")
                print("      python3 gorev_plani.py --indir 41.00820,28.97840"
                      " --yaricap 2000 --z 14-17\n")
                print("  Uçuş alanının koordinatını bilmiyorsan:")
                print("    · Google Maps'te alana SAĞ TIKLA — en üstte "
                      "çıkan sayı çifti odur, tıklayınca kopyalanır.")
                print("    · Ya da Talon'u aç, GPS fix'i bekle ve "
                      "KOORDİNATSIZ çalıştır:")
                print("      python3 gorev_plani.py --indir --yaricap 2000"
                      " --z 14-17")
                print("      (bu, konumu aracın kendi GPS'inden alır — "
                      "önce ./baslat_talon.sh çalışıyor olmalı)")
                return 2
        liste = KARO.alan_karolari(e, b, a.yaricap, za, zu)
        print("  merkez %.5f, %.5f   yarıçap %.0f m   z %d-%d"
              % (e, b, a.yaricap, za, zu))
        print("  %d karo (~%.0f MB, ~%.0f dk) indirilecek."
              % (len(liste), len(liste) * 0.02, len(liste) * 0.12 / 60))
        print("  ⚠ OSM gönüllü sunucularından iniyor; saniyede ~8 istek.\n")

        def ilerle(i, n, ind, varr, hata):
            print("\r  %5d/%d  indi %d  vardı %d  hata %d   " %
                  (i, n, ind, varr, hata), end="", flush=True)
        ind, varr, hata = KARO.alan_indir(e, b, a.yaricap, za, zu,
                                          ilerleme=ilerle)
        print("\n\n  ✔ %d indirildi, %d zaten vardı, %d hata" % (ind, varr, hata))
        print("  önbellek: %s" % KARO.onbellek_durumu(taze=True))
        print("\n  Şimdi paneli aç:  python3 gorev_plani.py")
        return 0

    print("  TALON GÖREV PLANI — http://localhost:%d" % a.port)
    print("=" * 66)
    print("  MAVLink : %s   (yayıncının KENDİ aynası)" % a.mav)
    print("  ⛔ ÖNCE ./baslat_talon.sh çalışıyor olmalı.")
    print("  Tıkla -> waypoint ekle · sağ tık -> sil · YÜKLE -> araca gönder")
    print("  Sonra ARAYÜZDEN (localhost:8000) AUTO'ya geçip BAŞLAT.")
    print()

    threading.Thread(target=_mav_dongu, args=(a.mav,), daemon=True).start()
    s = ThreadingHTTPServer(("0.0.0.0", a.port), _H)
    s.daemon_threads = True
    try:
        s.serve_forever()
    except KeyboardInterrupt:
        print("\n  kapandı.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
