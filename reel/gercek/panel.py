# -*- coding: utf-8 -*-
"""
================================================================================
DRONE YER KONTROL PANELİ — canlı video + telemetri + MANUEL KUMANDA
================================================================================
Adres: http://<drone-bilgisayari>:8810

ÜÇ İŞİ VAR:
  1. GÖSTER  : canlı FPV, AV kilit dörtgeni, telemetri, sağlık
  2. SÜR     : iki sanal joystick ile MANUEL kontrol
  3. SEÇ     : MANUEL / OTONOM kipi ve ARM

⛔⛔ ÇUBUKLAR DOĞRUDAN ELRS'E GİTMEZ — HAKEMDEN (`komut.py`) GEÇER.
   Sebep: hakem, fiziksel kumandayı panele göre ÖNCELİKLİ tutar, bekçi
   zamanlayıcılarını işletir ve arm kuralını uygular. Paneli doğrudan
   bağlamak, o emniyet zincirini atlamak olurdu.

⛔ ARM KURALI: arm bir İNSAN kaynağından gelir (fiziksel kumanda ya da bu
   panel), GÜDÜMDEN ASLA. Panelde arm düğmesi BASILI TUTMA ister — tek
   tıkla yanlışlıkla arm edilemesin.

⚠ PANEL ÇUBUKLARI BAYATLARSA (sekme kapandı, WiFi düştü, sayfa dondu)
  hakem 0.5 s içinde onları YOK sayar. Donmuş bir çubuk değerini komut
  sanmak, aracı son verilen komutla sonsuza dek uçurmaktır.
================================================================================
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_D = {"kamera": None, "komut": None, "baglanti": None, "hedef": None,
      "sunucu": None, "kilitci": None, "beyin": None, "dikey": None,
      "son_kutu": None, "olcut": None}
_kosul = threading.Condition()
_kare_sayac = [0]


def kur(**kw):
    """Panelin okuyacağı nesneleri bağla (hepsi isteğe bağlı)."""
    _D.update({k: v for k, v in kw.items() if k in _D})


def kare_bildir():
    with _kosul:
        _kare_sayac[0] += 1
        _kosul.notify_all()


# ======================================================================
#  DURUM
# ======================================================================
def _durum():
    k = _D["kamera"]; ks = _D["komut"]; gb = _D["baglanti"]
    hd = _D["hedef"]; sv = _D["sunucu"]; dk = _D["dikey"]; by = _D["beyin"]
    d = {"t": round(time.time(), 2)}
    d["kamera"] = k.durum() if k else {"acik": False}
    if ks is not None:
        d["komut"] = dict(ks.durum)
        d["komut"]["kip"] = ks.kip
        d["komut"]["sayac"] = dict(ks.sayac)
    if gb is not None:
        d["arac"] = gb.saglik()
        try:
            x, y, z = gb.konum(); r, p, yw = gb.yonelim()
            vx, vy, vz = gb.hiz_vektoru()
            import math
            d["konum"] = {"kuzey": round(x, 1), "dogu": round(y, 1),
                          "yukari": round(z, 1)}
            d["durus"] = {"roll": round(math.degrees(r), 1),
                          "pitch": round(math.degrees(p), 1),
                          "yaw": round(math.degrees(yw), 1)}
            d["hiz"] = {"yatay": round(math.hypot(vx, vy), 1),
                        "dikey": round(vz, 1)}
        except Exception:
            pass
    if hd is not None:
        d["hedef"] = hd.durum()
    if sv is not None:
        d["sunucu"] = sv.durum()
    if dk is not None:
        d["dikey"] = {"aktif": dk.aktif, "pasif": dk.n_pasif_cagri,
                      **{a: b for a, b in dk.tani.items()}}
    if by is not None:
        d["gudum"] = {"durum": getattr(by, "durum", "-"),
                      "faz": getattr(by, "faz", "-")}
    if _D["son_kutu"]:
        d["kutu"] = _D["son_kutu"]
    if _D["olcut"] is not None:
        d["kilit"] = _D["olcut"]
    # Skydagger bağının kendi durumu (güvenli pencere, RC sayacı)
    if gb is not None and hasattr(gb.bag, "durum"):
        try:
            d["bag"] = gb.bag.durum()
        except Exception:
            pass
    return d


# ======================================================================
#  HTML
# ======================================================================
SAYFA = r"""<!doctype html><html lang=tr><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>AVCI DRONE — YER KONTROL</title><style>
*{box-sizing:border-box;margin:0;padding:0}
/* ⛔ `html` DE BOYANIR: yalnız body boyanınca, sayfa içeriğinden uzun
   kaydırıldığında ya da bir öğe yüksekliği bozulduğunda tarayıcı BEYAZ
   gösteriyordu (sahada görüldü 2026-08-29). */
html{background:#0b0e13}
body{background:#0b0e13;color:#dfe6f0;font:13px/1.45 ui-monospace,Menlo,Consolas,monospace;
     min-height:100vh}
.ust{display:flex;gap:10px;align-items:center;padding:8px 12px;background:#131924;
     border-bottom:1px solid #223}
.ust b{font-size:15px;letter-spacing:1px}
.rozet{padding:3px 9px;border-radius:4px;font-weight:700;font-size:12px}
.ok{background:#123d1e;color:#5fe08a}.kotu{background:#3d1212;color:#ff7b7b}
.uyari{background:#3d3312;color:#ffd166}
main{display:grid;grid-template-columns:1fr 330px;gap:10px;padding:10px}
@media(max-width:900px){main{grid-template-columns:1fr}}
.kutu{background:#131924;border:1px solid #223;border-radius:8px;padding:10px}
.kutu h3{font-size:11px;letter-spacing:1.5px;color:#7d8aa0;margin-bottom:7px;
         text-transform:uppercase}
/* ⛔ FPV KUTUSU SABİT ORANLI: kaynağı olmayan bir <img> tarayıcıya göre
   farklı yükseklik alır ve düzeni bozar (beyaz alan). Kap her zaman aynı
   yeri kaplar; görüntü içine oturur. */
.fpvkap{position:relative;width:100%;aspect-ratio:16/9;background:#000;
        border-radius:6px;overflow:hidden;display:flex;align-items:center;
        justify-content:center}
.fpvkap span{color:#7d8aa0;font-size:12px}
#fpv{width:100%;height:100%;object-fit:contain;display:none}
#fpv.var{display:block}
table{width:100%;border-collapse:collapse}
td{padding:2px 0}td:last-child{text-align:right;font-weight:700}
.sonuk{color:#7d8aa0}
.kumanda{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:8px}
.pad{position:relative;aspect-ratio:1;background:#0b0e13;border:1px solid #2a3550;
     border-radius:10px;touch-action:none;overflow:hidden}
.pad .cizgi{position:absolute;background:#1c2438}
.pad .yatay{left:0;right:0;top:50%;height:1px}
.pad .dikey{top:0;bottom:0;left:50%;width:1px}
.topuz{position:absolute;width:26%;height:26%;border-radius:50%;
       background:#2f7dd1;border:2px solid #6fb2ff;transform:translate(-50%,-50%);
       left:50%;top:50%;pointer-events:none;transition:none}
.pad.kilitli .topuz{background:#556;border-color:#889}
.pad .kilit{position:absolute;inset:0;display:none;align-items:center;
            justify-content:center;text-align:center;font-size:11px;
            color:#ffd166;background:rgba(11,14,19,.72);padding:6px;
            line-height:1.35}
.pad.kilitli .kilit{display:flex}
.pad .etiket{position:absolute;bottom:4px;left:0;right:0;text-align:center;
             font-size:10px;color:#7d8aa0}
.dugmeler{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
button{flex:1;min-width:78px;padding:9px 6px;border:1px solid #2a3550;border-radius:6px;
       background:#1b2333;color:#dfe6f0;font:700 12px ui-monospace,monospace;cursor:pointer}
button:hover{background:#243049}
button.aktif{background:#1d4ed8;border-color:#60a5fa;color:#fff}
button.arm{background:#7f1d1d;border-color:#ef4444}
button.armli{background:#166534;border-color:#4ade80}
.uyarilar{margin-top:8px;font-size:11px;color:#ffd166;min-height:16px}
</style></head><body>
<div class=ust>
  <b>AVCI DRONE — YER KONTROL</b>
  <span id=r_link class="rozet kotu">LINK</span>
  <span id=r_gps  class="rozet kotu">GPS</span>
  <span id=r_kip  class="rozet uyari">MANUEL</span>
  <span id=r_insan class="rozet uyari">girdi: —</span>
  <span id=r_arm  class="rozet kotu">DISARM</span>
  <span id=r_sunucu class="rozet kotu">SUNUCU</span>
  <span style="flex:1"></span>
  <span id=r_saat class=sonuk></span>
</div>
<main>
  <div class=kutu>
    <h3>FPV</h3>
    <div class=fpvkap><span id=fpvyok>kamera bekleniyor…</span>
      <img id=fpv alt=""></div>
  </div>
  <div>
    <div class=kutu>
      <h3>Manuel kumanda</h3>
      <div class=kumanda>
        <div class=pad id=padL><div class="cizgi yatay"></div><div class="cizgi dikey"></div>
          <div class=topuz id=topuzL></div><div class=kilit>KUMANDA SÜRÜYOR<br>pilot çubuğu bıraksın,<br>3 s sonra panel geri alır</div>
          <div class=etiket>GAZ / DÖNÜŞ</div></div>
        <div class=pad id=padR><div class="cizgi yatay"></div><div class="cizgi dikey"></div>
          <div class=topuz id=topuzR></div><div class=kilit>KUMANDA SÜRÜYOR<br>pilot çubuğu bıraksın,<br>3 s sonra panel geri alır</div>
          <div class=etiket>İLERİ / YANAL</div></div>
      </div>
      <div class=dugmeler>
        <button id=b_manuel class=aktif>MANUEL</button>
        <button id=b_otonom>OTONOM</button>
        <button id=b_arm class=arm>ARM (BASILI TUT)</button>
      </div>
      <div class=dugmeler>
        <button id=b_koken>KÖKEN KUR</button>
        <button id=b_kmd>KUMANDAYI YOK SAY</button>
        <span id=r_safe class="rozet uyari" style="flex:1;text-align:center">—</span>
      </div>
      <div class=uyarilar id=uyarilar></div>
    </div>
    <div class=kutu style="margin-top:10px">
      <h3>Telemetri</h3>
      <table id=telem></table>
    </div>
  </div>
</main>
<script>
// ⛔ JS HATALARI SESSİZ KALMASIN. Bir istisna, durum döngüsünü ya da
//   çubuk olaylarını sessizce öldürebilir; operatör bunu "donma" sanar.
//   Artık ekranda yazar ve konsola düşer.
let jsHata="";
window.addEventListener("error",e=>{ jsHata="JS: "+(e.message||"hata"); });
window.addEventListener("unhandledrejection",e=>{
  jsHata="JS(promise): "+((e.reason&&e.reason.message)||e.reason||"hata"); });
let S={thr:0,yaw:0,pitch:0,roll:0,arm:false,izin:false};
let kumandaVar=false, armBasili=false, kmdYokSay=false;
// ⛔ PANEL BEKÇİSİ: POST'lar gerçekten gidiyor mu? Donma SESSİZ olmamalı —
//   operatör "arayüz dondu mu, kumanda mı devraldı" diye tahmin etmemeli.
let sonBasarili=Date.now(), ucusta=0, postHata=0;
// ⛔ SEKME GÖRÜNÜRLÜK KONTROLÜ KALDIRILDI (kullanıcı kararı 2026-08-29):
//   "sekme arka plana düşünce o zamanlayıcıyı kısmayı falan kaldır, o
//    nasıl şey öyle niye donduruyor kontrolü sil onu".
//   Panel artık sekme gizlenince NE uyarı basar NE de çubuğu bırakır.
//   ⚠ Chrome'un kendi kısıtlaması yazılımla kapatılamaz; onun yerine
//     hakemin panel zaman aşımı 0.5 -> 1.5 s'e çıkarıldı, böylece kısa
//     kısıtlamalar paketi kesmez. Gerçek hız aşağıda "panel→sunucu"
//     satırında GÖRÜNÜR — uyarı değil, bilgi.
let postHz=0, postSay=0;
setInterval(()=>{ postHz=postSay; postSay=0; },1000);

function pad(el,topuz,eksenX,eksenY,merkezleY){
  // ⛔ AKTİF İŞARETÇİ KİMLİKLE TAKİP EDİLİR.
  //   Eski hâlde sadece bir `aktif` bayrağı vardı ve `pointerleave` de onu
  //   düşürüyordu. `setPointerCapture` ile sürüklerken sınır olayları
  //   tarayıcıdan tarayıcıya farklı davranır; işaretçi kimliği yakalanınca
  //   bu belirsizlik tamamen kalkar: yalnız BİZİM yakaladığımız işaretçinin
  //   up/cancel'ı çubuğu bırakır.
  let aktifId=null;
  const yerlestir=(x,y)=>{ topuz.style.left=(50+x*50)+"%"; topuz.style.top=(50-y*50)+"%"; };
  const oku=(ev)=>{
    const r=el.getBoundingClientRect();
    let x=((ev.clientX-r.left)/r.width)*2-1;
    let y=-(((ev.clientY-r.top)/r.height)*2-1);
    x=Math.max(-1,Math.min(1,x)); y=Math.max(-1,Math.min(1,y));
    S[eksenX]=x; S[eksenY]=y; yerlestir(x,y);
  };
  el.addEventListener("pointerdown",e=>{
    if(kumandaVar) return;
    aktifId=e.pointerId;
    try{ el.setPointerCapture(e.pointerId); }catch(_){}
    oku(e); e.preventDefault();
  });
  el.addEventListener("pointermove",e=>{ if(e.pointerId===aktifId) oku(e); });
  const birak=(e)=>{
    if(aktifId===null || (e && e.pointerId!==aktifId)) return;
    try{ el.releasePointerCapture(aktifId); }catch(_){}
    aktifId=null;
    S[eksenX]=0; if(merkezleY) S[eksenY]=0;
    yerlestir(S[eksenX],S[eksenY]);
  };
  el.addEventListener("pointerup",birak);
  el.addEventListener("pointercancel",birak);
  // ⛔ FARE TUŞU BASILIYKEN PENCERE DEĞİŞİRSE `pointerup` HİÇ GELMEZ ve
  //   çubuk takılı kalırdı. `blur` bunu kapatır.
  //   ⚠ `visibilitychange` KASTEN YOK (kullanıcı kararı): sekme arka plana
  //     düşünce çubuk BIRAKILMAZ.
  window.addEventListener("blur",()=>birak(null));
  return yerlestir;
}
// SOL: X=dönüş(merkeze döner), Y=gaz(MERKEZE DÖNMEZ — gaz çubuğu öyledir)
const yerL=pad(document.getElementById("padL"),document.getElementById("topuzL"),"yaw","thr",false);
// SAĞ: ikisi de merkeze döner
const yerR=pad(document.getElementById("padR"),document.getElementById("topuzR"),"roll","pitch",true);

document.getElementById("b_manuel").onclick=()=>kip("MANUEL");
document.getElementById("b_otonom").onclick=()=>kip("OTONOM");
function kip(k){ fetch("/api/kip",{method:"POST",body:JSON.stringify({kip:k})});
  document.getElementById("b_manuel").classList.toggle("aktif",k=="MANUEL");
  document.getElementById("b_otonom").classList.toggle("aktif",k=="OTONOM");
  S.izin=(k=="OTONOM"); }
// ⭐ YEREL KÖKEN — kalkıştan ÖNCE, araç YERDEYKEN basılır.
//    Bütün GPS koordinatları buna göre metreye çevrilir; uçuş ortasında
//    değiştirmek güdümün altındaki zemini kaydırmak demektir.
document.getElementById("b_koken").onclick=async()=>{
  const r=await (await fetch("/api/koken",{method:"POST",body:"{}"})).json();
  document.getElementById("uyarilar").textContent=r.mesaj||"";
  if(!r.ok && confirm(r.mesaj+"\n\nYine de ZORLA kurulsun mu? (zayıf fix "+
     "bütün uçuşu kaydırır)")){
    const z=await (await fetch("/api/koken",{method:"POST",
      body:JSON.stringify({zorla:true})})).json();
    document.getElementById("uyarilar").textContent=z.mesaj||"";
  }};
document.getElementById("b_kmd").onclick=(e)=>{
  kmdYokSay=!kmdYokSay;
  e.target.classList.toggle("aktif",kmdYokSay);
  e.target.textContent=kmdYokSay?"KUMANDA YOK SAYILIYOR":"KUMANDAYI YOK SAY";
};
// ⛔ ARM BASILI TUTMA İSTER — tek tıkla yanlışlıkla arm edilemesin
const bArm=document.getElementById("b_arm");
bArm.addEventListener("pointerdown",()=>{armBasili=true;S.arm=true;});
const armBirak=()=>{armBasili=false;S.arm=false;};
bArm.addEventListener("pointerup",armBirak);
bArm.addEventListener("pointerleave",armBirak);
bArm.addEventListener("pointercancel",armBirak);

// ⛔ ESKİ HÂLİ setInterval(...,33) İDİ VE GERİ BASINÇ YOKTU: önceki istek
//   bitmeden yenisi ateşleniyordu. Tarayıcının bağlantı havuzu (kaynak
//   başına ~6) MJPEG akışıyla birlikte dolduğunda istekler kuyruğa
//   yığılıyor ve arayüz tıkanıyor. Şimdi: bir seferde EN FAZLA BİR istek.
function manuelGonder(){
  if(ucusta>0){ setTimeout(manuelGonder,10); return; }
  ucusta++;
  fetch("/api/manuel",{method:"POST",body:JSON.stringify(S)})
    .then(r=>{ sonBasarili=Date.now(); postHata=0; postSay++; })
    .catch(e=>{ postHata++; })
    .finally(()=>{ ucusta--; setTimeout(manuelGonder,33); });
}
manuelGonder();

const sat=(a,b,s)=>`<tr><td class=sonuk>${a}</td><td class="${s||''}">${b}</td></tr>`;
function rozet(id,ok,metin){ const e=document.getElementById(id);
  e.className="rozet "+(ok===true?"ok":ok===false?"kotu":"uyari"); e.textContent=metin; }
let durumUcusta=false;
setInterval(async()=>{
  if(durumUcusta) return;               // geri basınç: kuyruk yığılmasın
  durumUcusta=true;
  let d; try{ d=await (await fetch("/api/durum")).json(); }
  catch(e){ durumUcusta=false; return; }
  durumUcusta=false;
  const a=d.arac||{}, k=d.komut||{}, kam=d.kamera||{}, sv=d.sunucu||{};
  rozet("r_link", a.canli===true, "LINK "+(a.link_lq>=0?a.link_lq+"%":"—"));
  rozet("r_gps",  a.koken===true, "GPS "+(a.uydu||0));
  rozet("r_kip",  k.kip=="OTONOM"?null:true, k.kip||"—");
  rozet("r_insan", k.insan?true:false, "girdi: "+(k.insan||"YOK"));
  rozet("r_arm",  !!k.arm, k.arm?"ARM":"DISARM");
  rozet("r_sunucu", sv.baglandi===true, "SUNUCU "+(sv.gonderilen||0));
  // ⛔ GÜVENLİ PENCERE (Skydagger rehberi §8): ilk saniyelerde YALNIZ SAFE
  //    basılır. Operatör bunu GÖRMELİ, yoksa "komut gitmiyor" sanır.
  // ⛔ KAMERA YOKKEN /video'YA BAĞLANMA: MJPEG kalıcı bir bağlantı tutar ve
  //   tarayıcının kaynak başına ~6 bağlantısından birini SÜREKLİ meşgul eder.
  //   Kare gelmeyecekse o slotu harcamanın anlamı yok.
  const fpv=document.getElementById("fpv"), fpvyok=document.getElementById("fpvyok");
  if(kam.acik===true && !fpv.getAttribute("src")){
    fpv.src="/video"; fpv.classList.add("var"); fpvyok.style.display="none"; }
  if(kam.acik!==true && fpv.getAttribute("src")){
    fpv.removeAttribute("src"); fpv.classList.remove("var");
    fpvyok.style.display=""; }
  const bg=d.bag||{};
  if(bg.guvenli_pencere) rozet("r_safe",null,"SAFE PENCERESİ "+bg.guvenli_kalan+" s");
  else rozet("r_safe", bg.acik===true, bg.acik===true
       ? ("BAĞ "+(bg.tasima||"").toUpperCase()+"  RC "+(bg.yazilan||0))
       : "BAĞ YOK");
  document.getElementById("r_saat").textContent=
    sv.saat?`${sv.saat.saat}:${String(sv.saat.dakika).padStart(2,"0")}:${String(sv.saat.saniye).padStart(2,"0")}`:"";
  // ⭐ KUMANDA TAKILI OLMAK YETMEZ, OYNATILMASI GEREKİR (kullanıcı kararı).
  //   Padler yalnız kumanda GERÇEKTEN sürerken kilitlenir; pilot çubuğu
  //   bıraktıktan 3 s sonra panel kendiliğinden geri alır.
  kumandaVar = (k.insan=="kumanda") && !kmdYokSay;
  document.getElementById("padL").classList.toggle("kilitli",kumandaVar);
  document.getElementById("padR").classList.toggle("kilitli",kumandaVar);
  if(kumandaVar && k.komut){ // fiziksel kumanda -> topuzlar ONU gösterir
    yerL(k.komut[3],k.komut[0]); yerR(k.komut[2],k.komut[1]); }
  const ko=d.konum||{}, du=d.durus||{}, hz=d.hiz||{}, hd=d.hedef||{}, g=d.gudum||{};
  document.getElementById("telem").innerHTML=
    sat("kaynak",(k.kaynak||"—")+(k.sebep&&k.sebep!="-"?" ("+k.sebep+")":""))+
    sat("güdüm",(g.durum||"—")+" / "+(g.faz||"—"))+
    sat("kuzey / doğu",(ko.kuzey??"—")+" / "+(ko.dogu??"—")+" m")+
    sat("yükseklik",(ko.yukari??"—")+" m")+
    sat("hız",(hz.yatay??"—")+" m/s   ↕ "+(hz.dikey??"—"))+
    sat("yatış / dikilme",(du.roll??"—")+"° / "+(du.pitch??"—")+"°")+
    sat("yönelme",(du.yaw??"—")+"°")+
    sat("hedef",hd.var?("var, yaş "+hd.yas+" s"):"YOK")+
    sat("hedef irtifa/hız",(hd.irtifa_ev??"—")+" m / "+(hd.hiz??"—")+" m/s")+
    sat("telemetri yaşı","gps "+(a.yas_gps??"—")+"  duruş "+(a.yas_durus??"—"))+
    sat("kamera",(kam.genislik||0)+"x"+(kam.yukseklik||0)+" @"+(kam.sayac||0))+
    sat("CRC hatası",a.crc_hata??"—")+
    sat("panel→sunucu",postHz+" Hz"+(postHata?("  ⛔ "+postHata+" hata"):""))+
    sat("kumanda",k.kmd_takili?(k.kmd_hakim?"SÜRÜYOR":"takılı, duruyor")
        :("aranıyor… "+((k.sayac&&k.sayac.kmd_arama)||0)+" deneme  "+
          "(EdgeTX USB Mode = Joystick?)"));
  let u=[];
  if(a.canli===false) u.push("⛔ TELEMETRİ AKMIYOR");
  if(a.koken===false) u.push("⚠ yerel köken kurulmadı (GPS fix bekleniyor)");
  if(k.sebep=="teslim_suresi") u.push("⛔ KUMANDA KOPUK — paket kesildi, AUTO-LAND");
  if(k.sebep=="gudum_bayat") u.push("⚠ güdüm bayat — çubuklara düşüldü");
  if(kam.acik===false) u.push("⚠ kamera yok — "+(kam.hata? kam.hata.slice(0,80)
        : "yakalama kartı takılı mı? (ls /dev/video*)"));
  // ⛔ PANEL BEKÇİSİ — donma SESSİZ olmasın
  const sessiz=(Date.now()-sonBasarili)/1000;
  if(sessiz>1.0) u.unshift("⛔ PANEL SUNUCUYA ULAŞAMIYOR ("+sessiz.toFixed(1)+
                           " s, "+postHata+" hata) — çubuklar GİTMİYOR");
  if(k.insan=="kumanda")
    u.unshift("ℹ KUMANDA SÜRÜYOR — pilot çubuğa dokundu; 3 s durursa panel geri alır");
  if(jsHata) u.unshift("⛔ "+jsHata);
  document.getElementById("uyarilar").textContent=u.join("   ");
},200);
</script></body></html>"""


# ======================================================================
#  SUNUCU
# ======================================================================
class _Islem(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _yaz(self, kod, tur, govde):
        self.send_response(kod)
        self.send_header("Content-Type", tur)
        self.send_header("Content-Length", str(len(govde)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(govde)
        except Exception:
            pass

    def do_GET(self):
        if self.path == "/":
            return self._yaz(200, "text/html; charset=utf-8",
                             SAYFA.encode("utf-8"))
        if self.path == "/api/durum":
            return self._yaz(200, "application/json",
                             json.dumps(_durum()).encode("utf-8"))
        if self.path == "/video":
            return self._video()
        self._yaz(404, "text/plain", b"yok")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            g = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            g = {}
        ks = _D["komut"]
        if self.path == "/api/manuel" and ks is not None:
            ks.panel_yaz(float(g.get("thr", 0.0)), float(g.get("pitch", 0.0)),
                         float(g.get("roll", 0.0)), float(g.get("yaw", 0.0)),
                         arm=bool(g.get("arm", False)),
                         otonom_izin=bool(g.get("izin", False)))
            return self._yaz(200, "application/json", b'{"ok":1}')
        if self.path == "/api/kip" and ks is not None:
            try:
                ks.kip_sec(str(g.get("kip", "MANUEL")).upper())
            except ValueError:
                return self._yaz(400, "application/json", b'{"ok":0}')
            return self._yaz(200, "application/json", b'{"ok":1}')
        if self.path == "/api/koken" and _D["baglanti"] is not None:
            ok, mesaj = _D["baglanti"].kokeni_kur(bool(g.get("zorla")))
            return self._yaz(200, "application/json",
                             json.dumps({"ok": ok, "mesaj": mesaj}).encode())
        self._yaz(404, "application/json", b'{"ok":0}')

    # ---------------- MJPEG ----------------
    def _video(self):
        import cv2
        self.send_response(200)
        self.send_header("Content-Type",
                         "multipart/x-mixed-replace; boundary=k")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        son = -1
        try:
            while True:
                kam = _D["kamera"]
                if kam is None:
                    time.sleep(0.2)
                    continue
                kare, _t, sayac = kam.son_kare()
                if kare is None or sayac == son:
                    time.sleep(0.02)
                    continue
                son = sayac
                kare = _cizim(kare.copy())
                ok, buf = cv2.imencode(".jpg", kare,
                                       [cv2.IMWRITE_JPEG_QUALITY, 75])
                if not ok:
                    continue
                b = buf.tobytes()
                self.wfile.write(b"--k\r\nContent-Type: image/jpeg\r\n"
                                 b"Content-Length: " + str(len(b)).encode() +
                                 b"\r\n\r\n" + b + b"\r\n")
        except Exception:
            return


def _cizim(kare):
    """AV kilit dörtgeni + kutu. ⛔ ÖLÇÜT `dow/gudum/kilit.py`den gelir."""
    import cv2
    from dow.ayarlar import Ayar
    h, w = kare.shape[:2]
    x0 = int(w * Ayar.KILIT_KIRP_X); x1 = int(w * (1 - Ayar.KILIT_KIRP_X))
    y0 = int(h * Ayar.KILIT_KIRP_Y); y1 = int(h * (1 - Ayar.KILIT_KIRP_Y))
    cv2.rectangle(kare, (x0, y0), (x1, y1), (90, 200, 255), 1)
    cv2.putText(kare, "AV", (x0 + 4, y0 + 16), cv2.FONT_HERSHEY_SIMPLEX,
                0.5, (90, 200, 255), 1)
    kutu = _D.get("son_kutu")
    if kutu:
        cx, cy, bw, bh = kutu[:4]
        p0 = (int(cx - bw / 2), int(cy - bh / 2))
        p1 = (int(cx + bw / 2), int(cy + bh / 2))
        kilitli = bool(_D.get("olcut", {}).get("bu_kare"))
        cv2.rectangle(kare, p0, p1, (90, 255, 120) if kilitli else (0, 165, 255), 2)
    o = _D.get("olcut") or {}
    if o:
        cv2.putText(kare, "KILIT %.1f/%.1f s" % (o.get("kilit_s", 0.0),
                                                 Ayar.KILIT_GEREKLI_S),
                    (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (90, 255, 120) if o.get("saglandi") else (200, 200, 200), 2)
    return kare


_sunucu = None


def baslat(port=None):
    global _sunucu
    port = port or int(os.environ.get("DOW_PANEL_PORT", 8810))
    _sunucu = ThreadingHTTPServer(("0.0.0.0", port), _Islem)
    _sunucu.daemon_threads = True
    threading.Thread(target=_sunucu.serve_forever, daemon=True,
                     name="panel").start()
    return port


def durdur():
    if _sunucu:
        _sunucu.shutdown()
