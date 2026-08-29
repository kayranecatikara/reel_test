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
if KOK not in sys.path:
    sys.path.insert(0, KOK)

from gercek.konum import YerelCerceve            # noqa: E402

_D = {"mav": None, "ev": None, "konum": None, "kip": None, "bagli": False,
      "son_mesaj": "", "n_paket": 0}
_kilit = threading.Lock()


# ======================================================================
#  MAVLINK
# ======================================================================
def _mav_dongu(adres):
    from pymavlink import mavutil
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
                    elif t == "HOME_POSITION":
                        _D["ev"] = (msg.latitude / 1e7, msg.longitude / 1e7,
                                    msg.altitude / 1000.0)
                    elif t == "HEARTBEAT":
                        _D["kip"] = msg.custom_mode
                    elif t == "STATUSTEXT":
                        _D["son_mesaj"] = msg.text.strip()
        except Exception as e:
            with _kilit:
                _D["bagli"] = False
                _D["son_mesaj"] = "bağlantı: %s" % e
            time.sleep(2.0)


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
     background:#131924;border-bottom:1px solid #223}
.ust b{font-size:15px;letter-spacing:1px}
.rozet{padding:3px 9px;border-radius:4px;font-weight:700;font-size:12px}
.ok{background:#123d1e;color:#5fe08a}.kotu{background:#3d1212;color:#ff7b7b}
.uyari{background:#3d3312;color:#ffd166}
main{display:grid;grid-template-columns:1fr 320px;gap:10px;padding:10px}
@media(max-width:900px){main{grid-template-columns:1fr}}
.kutu{background:#131924;border:1px solid #223;border-radius:8px;padding:10px}
.kutu h3{font-size:11px;letter-spacing:1.5px;color:#7d8aa0;margin-bottom:7px;
         text-transform:uppercase}
#plan{width:100%;height:70vh;min-height:380px;display:block;background:#080b10;
      border-radius:6px;cursor:crosshair;touch-action:none}
table{width:100%;border-collapse:collapse;font-size:12px}
td,th{padding:3px 4px;text-align:left;border-bottom:1px solid #1c2438}
th{color:#7d8aa0;font-weight:400}
button{padding:8px 6px;border:1px solid #2a3550;border-radius:6px;
  background:#1b2333;color:#dfe6f0;font:700 12px ui-monospace,monospace;
  cursor:pointer;flex:1}
button:hover{background:#243049}
button.ana{background:#1d4ed8;border-color:#60a5fa;color:#fff}
button.tehlike{background:#7f1d1d;border-color:#ef4444}
.satir{display:flex;gap:6px;margin-top:8px}
label{display:block;color:#7d8aa0;font-size:11px;margin-top:8px}
input,select{width:100%;padding:6px;background:#0b0e13;color:#dfe6f0;
  border:1px solid #2a3550;border-radius:4px;font:12px ui-monospace,monospace}
.mesaj{margin-top:10px;font-size:11px;min-height:34px;color:#ffd166}
.sonuk{color:#7d8aa0}
</style></head><body>
<div class=ust><b>TALON — GÖREV PLANI</b>
  <span id=r_bagli class="rozet kotu">MAVLINK</span>
  <span id=r_ev class="rozet kotu">EV NOKTASI</span>
  <span id=r_n class="rozet uyari">0 nokta</span>
  <span style="flex:1"></span><span id=r_mesaj class=sonuk></span>
</div>
<main>
  <div class=kutu>
    <h3>Plan — tıkla: nokta ekle · sağ tık: son noktayı sil ·
        tekerlek: ölçek</h3>
    <canvas id=plan></canvas>
  </div>
  <div>
    <div class=kutu>
      <h3>Görev</h3>
      <label>Kalkış irtifası (m)</label><input id=kalkis type=number value=50>
      <label>Varsayılan waypoint irtifası (m)</label>
      <input id=irtifa type=number value=80>
      <label>Görev bitince</label>
      <select id=bitince><option value=rtl>EVE DÖN (RTL)</option>
        <option value=loiter>HAVADA BEKLE (LOITER)</option></select>
      <div class=satir><button id=b_yukle class=ana>GÖREVİ YÜKLE</button></div>
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
      <h3>Noktalar</h3>
      <table id=liste><tr><th>#</th><th>kuzey</th><th>doğu</th>
        <th>irtifa</th><th>uzaklık</th></tr></table>
    </div>
  </div>
</main>
<script>
let N=[], ev=null, olcek=1.0, bagli=false, evVar=false;
const c=document.getElementById("plan"), g=c.getContext("2d");
function boyut(){const r=c.getBoundingClientRect(),o=devicePixelRatio||1;
  c.width=Math.round(r.width*o);c.height=Math.round(r.height*o);
  g.setTransform(o,0,0,o,0,0);return[r.width,r.height];}
function menzil(){let r=200;for(const n of N)r=Math.max(r,Math.abs(n.kuzey),Math.abs(n.dogu));return r*1.2;}
function K(W,H){return Math.min(W,H)*0.42/menzil()*olcek;}
function ekranaC(n,W,H,k){return [W/2+n.dogu*k, H/2-n.kuzey*k];}   // doğu=sağ, kuzey=yukarı
function ciz(){
  const [W,H]=boyut(); g.clearRect(0,0,W,H); const k=K(W,H), cx=W/2, cy=H/2;
  const r=menzil(); const adim=Math.pow(10,Math.round(Math.log10(r/3)));
  g.strokeStyle="#18202e";g.lineWidth=1;g.beginPath();
  for(let i=-6;i<=6;i++){
    g.moveTo(cx+i*adim*k,0);g.lineTo(cx+i*adim*k,H);
    g.moveTo(0,cy+i*adim*k);g.lineTo(W,cy+i*adim*k);}
  g.stroke();
  g.strokeStyle="#2a3550";g.beginPath();
  g.moveTo(cx,0);g.lineTo(cx,H);g.moveTo(0,cy);g.lineTo(W,cy);g.stroke();
  g.fillStyle="#3d5a80";g.font="11px monospace";
  g.fillText("KUZEY",cx+5,14); g.fillText("DOĞU",W-42,cy-6);
  g.fillText(adim+" m",cx+adim*k-14,cy+14);
  // rota
  if(N.length){
    g.strokeStyle="#2f7dd1";g.lineWidth=2;g.beginPath();
    g.moveTo(cx,cy);
    for(const n of N){const p=ekranaC(n,W,H,k);g.lineTo(p[0],p[1]);}
    g.stroke();
    N.forEach((n,i)=>{const p=ekranaC(n,W,H,k);
      g.fillStyle="#6fb2ff";g.beginPath();g.arc(p[0],p[1],7,0,6.284);g.fill();
      g.fillStyle="#0b0e13";g.font="bold 10px monospace";
      g.fillText(String(i+1),p[0]-(i>8?6:3),p[1]+4);
      g.fillStyle="#7d8aa0";g.font="10px monospace";
      g.fillText(n.irtifa+"m",p[0]+11,p[1]-8);});
  }
  // ev
  g.fillStyle="#5fe08a";g.beginPath();g.arc(cx,cy,6,0,6.284);g.fill();
  g.fillStyle="#5fe08a";g.font="10px monospace";g.fillText("EV",cx+9,cy+4);
}
c.addEventListener("click",e=>{
  const r=c.getBoundingClientRect(),[W,H]=[r.width,r.height],k=K(W,H);
  N.push({dogu:Math.round(((e.clientX-r.left)-W/2)/k),
          kuzey:Math.round((H/2-(e.clientY-r.top))/k),
          irtifa:parseInt(document.getElementById("irtifa").value)||80});
  guncelle();});
c.addEventListener("contextmenu",e=>{e.preventDefault();N.pop();guncelle();});
c.addEventListener("wheel",e=>{e.preventDefault();
  olcek*=(e.deltaY>0?0.9:1.1);olcek=Math.max(0.2,Math.min(6,olcek));ciz();},
  {passive:false});
function guncelle(){
  ciz();
  document.getElementById("r_n").textContent=N.length+" nokta";
  let h="<tr><th>#</th><th>kuzey</th><th>doğu</th><th>irtifa</th><th>uzaklık</th></tr>";
  N.forEach((n,i)=>{h+=`<tr><td>${i+1}</td><td>${n.kuzey}</td><td>${n.dogu}</td>`+
    `<td>${n.irtifa}</td><td>${Math.round(Math.hypot(n.kuzey,n.dogu))} m</td></tr>`;});
  document.getElementById("liste").innerHTML=h;
}
const mes=(t,k)=>{const e=document.getElementById("mesaj");
  e.textContent=t;e.style.color=k?"#ff7b7b":"#5fe08a";};
document.getElementById("b_geri").onclick=()=>{N.pop();guncelle();};
document.getElementById("b_temizle").onclick=()=>{N=[];guncelle();};
document.getElementById("b_yukle").onclick=async()=>{
  if(!N.length){mes("⛔ hiç waypoint yok",1);return;}
  if(!evVar){mes("⛔ EV noktası yok — GPS fix bekleniyor",1);return;}
  mes("yükleniyor…");
  const r=await (await fetch("/api/yukle",{method:"POST",body:JSON.stringify({
    noktalar:N, kalkis:parseInt(document.getElementById("kalkis").value)||50,
    bitince:document.getElementById("bitince").value})})).json();
  mes(r.mesaj, !r.ok);};
document.getElementById("b_aractan_sil").onclick=async()=>{
  if(!confirm("Araçtaki görev SİLİNSİN mi?"))return;
  const r=await (await fetch("/api/sil",{method:"POST",body:"{}"})).json();
  mes(r.mesaj,!r.ok);};
const rozet=(id,ok,t)=>{const e=document.getElementById(id);
  e.className="rozet "+(ok?"ok":"kotu");e.textContent=t;};
setInterval(async()=>{
  let d;try{d=await (await fetch("/api/durum")).json();}catch(e){return;}
  bagli=d.bagli; evVar=!!d.ev;
  rozet("r_bagli",d.bagli,"MAVLINK "+(d.n_paket||0));
  rozet("r_ev",evVar,evVar?"EV ✔":"EV YOK (GPS)");
  document.getElementById("r_mesaj").textContent=d.son_mesaj||"";
},700);
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

    def do_GET(self):
        if self.path == "/":
            return self._y(200, "text/html; charset=utf-8", SAYFA.encode())
        if self.path == "/api/durum":
            ev, sebep = _ev_al()
            with _kilit:
                d = {"bagli": _D["bagli"], "n_paket": _D["n_paket"],
                     "son_mesaj": _D["son_mesaj"]}
            d["ev"] = ev
            d["ev_sebep"] = sebep
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
            mesaj = ("✔ %d öğe yüklendi (%s). Uçurmak için ARAYÜZDEN AUTO'ya "
                     "geçin." % (len(ogeler), sebep)) if ok else \
                    ("⛔ " + str(ay.get("hata")))
            return self._y(200, "application/json",
                           json.dumps({"ok": ok, "mesaj": mesaj,
                                       "oge": len(ogeler), **ay}).encode())
        if self.path == "/api/sil":
            ok, m = gorev_sil()
            return self._y(200, "application/json",
                           json.dumps({"ok": ok, "mesaj": m}).encode())
        self._y(404, "application/json", b'{"ok":0}')


def main():
    ap = argparse.ArgumentParser(description="Talon görev planlayıcı")
    ap.add_argument("--mav", default="udp:127.0.0.1:14550",
                    help="yayıncının ALT SÜREÇ aynası")
    ap.add_argument("--port", type=int, default=8010)
    a = ap.parse_args()
    print("=" * 66)
    print("  TALON GÖREV PLANI — http://localhost:%d" % a.port)
    print("=" * 66)
    print("  MAVLink : %s   (yayıncının alt süreç aynası)" % a.mav)
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
