#!/usr/bin/env python3
"""
markdown_basit.py — Küçük, bağımlılıksız Markdown → HTML dönüştürücü.

NEDEN VAR: Saha prosedürü (UCUS_PROSEDURU.md) sahada okunacak ve orada
İNTERNET OLMAYABİLİR — dosyayı ancak panelin kendisi servis ederse
görebilirsin. Harici bir markdown kütüphanesi kurmak yerine (yeni bağımlılık
= yeni kırılma noktası) kullandığımız söz dizimi kadarını burada karşılıyoruz.

DESTEKLENEN: başlıklar, tablolar, listeler, onay kutuları, kod blokları,
satır içi kod, kalın, alıntı, yatay çizgi, bağlantılar.

DESTEKLENMEYEN: iç içe listeler, resimler, dipnotlar, HTML gömme.
Prosedür dosyası bunları kullanmıyor; kullanacaksan burayı genişlet.
"""

import html
import re

_KOD = re.compile(r"`([^`]+)`")
_KALIN = re.compile(r"\*\*([^*]+)\*\*")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_CIPLAK_LINK = re.compile(r"(?<![\"'>=])(https?://[^\s<]+)")


def _satir_ici(metin):
    """Satır içi biçimlendirme. ÖNCE kaçış, SONRA biçim — sıra önemli."""
    s = html.escape(metin)
    # Kod önce: içindeki ** yıldızları kalın sayılmasın
    kodlar = []

    def _kod_sakla(m):
        kodlar.append(m.group(1))
        return f"\x00{len(kodlar) - 1}\x00"

    s = _KOD.sub(_kod_sakla, s)
    s = _KALIN.sub(r"<strong>\1</strong>", s)
    s = _LINK.sub(r'<a href="\2" rel="noreferrer">\1</a>', s)
    s = _CIPLAK_LINK.sub(r'<a href="\1" rel="noreferrer">\1</a>', s)
    for i, kod in enumerate(kodlar):
        s = s.replace(f"\x00{i}\x00", f"<code>{kod}</code>")
    return s


def _tablo_satiri(satir):
    """| a | b | → ['a', 'b']"""
    return [h.strip() for h in satir.strip().strip("|").split("|")]


def _ayirici_mi(satir):
    """|---|---| biçimindeki tablo ayırıcısı mı?"""
    s = satir.strip()
    if not s.startswith("|"):
        return False
    return all(set(h.strip()) <= set("-: ") and "-" in h
               for h in s.strip("|").split("|"))


def cevir(kaynak):
    """Markdown metnini HTML gövdesine çevirir."""
    satirlar = kaynak.split("\n")
    cikti = []
    i = 0
    liste_acik = False

    def liste_kapat():
        nonlocal liste_acik
        if liste_acik:
            cikti.append("</ul>")
            liste_acik = False

    while i < len(satirlar):
        satir = satirlar[i]

        # --- kod bloğu ---
        if satir.strip().startswith("```"):
            liste_kapat()
            i += 1
            blok = []
            while i < len(satirlar) and not satirlar[i].strip().startswith("```"):
                blok.append(html.escape(satirlar[i]))
                i += 1
            i += 1
            cikti.append("<pre><code>" + "\n".join(blok) + "</code></pre>")
            continue

        # --- tablo ---
        if (satir.strip().startswith("|") and i + 1 < len(satirlar)
                and _ayirici_mi(satirlar[i + 1])):
            liste_kapat()
            basliklar = _tablo_satiri(satir)
            i += 2
            govde = []
            while i < len(satirlar) and satirlar[i].strip().startswith("|"):
                govde.append(_tablo_satiri(satirlar[i]))
                i += 1
            cikti.append("<div class='tablo-kaydir'><table><thead><tr>"
                         + "".join(f"<th>{_satir_ici(h)}</th>" for h in basliklar)
                         + "</tr></thead><tbody>")
            for hucreler in govde:
                cikti.append("<tr>" + "".join(
                    f"<td>{_satir_ici(h)}</td>" for h in hucreler) + "</tr>")
            cikti.append("</tbody></table></div>")
            continue

        ciplak = satir.strip()

        # --- yatay çizgi ---
        if ciplak in ("---", "***", "___"):
            liste_kapat()
            cikti.append("<hr>")
            i += 1
            continue

        # --- başlık ---
        m = re.match(r"^(#{1,6})\s+(.*)$", ciplak)
        if m:
            liste_kapat()
            seviye = len(m.group(1))
            cikti.append(f"<h{seviye}>{_satir_ici(m.group(2))}</h{seviye}>")
            i += 1
            continue

        # --- alıntı ---
        if ciplak.startswith(">"):
            liste_kapat()
            blok = []
            while i < len(satirlar) and satirlar[i].strip().startswith(">"):
                blok.append(satirlar[i].strip().lstrip(">").strip())
                i += 1
            cikti.append("<blockquote>" + _satir_ici(" ".join(blok))
                         + "</blockquote>")
            continue

        # --- liste / onay kutusu ---
        m = re.match(r"^[-*]\s+(.*)$", ciplak)
        if m:
            if not liste_acik:
                cikti.append("<ul>")
                liste_acik = True
            icerik = m.group(1)
            kutu = ""
            if icerik.startswith("[ ] "):
                kutu, icerik = "<span class='kutu'>☐</span> ", icerik[4:]
            elif icerik[:4].lower() == "[x] ":
                kutu, icerik = "<span class='kutu bitti'>☑</span> ", icerik[4:]
            cikti.append(f"<li>{kutu}{_satir_ici(icerik)}</li>")
            i += 1
            continue

        # --- boş satır / paragraf ---
        if not ciplak:
            liste_kapat()
        else:
            liste_kapat()
            cikti.append(f"<p>{_satir_ici(ciplak)}</p>")
        i += 1

    liste_kapat()
    return "\n".join(cikti)


SAYFA = """<!doctype html>
<html lang="tr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{baslik}</title>
<style>
  :root {{
    --zemin:#0f1419; --panel:#1a2129; --panel2:#232c36; --cizgi:#2f3b47;
    --metin:#e3e8ed; --soluk:#8a97a5; --vurgu:#4a9eff; --iyi:#3ddc84;
    --uyari:#ffb340; --kotu:#ff5c5c;
  }}
  * {{ box-sizing:border-box }}
  body {{
    margin:0; padding:16px 14px 60px; background:var(--zemin); color:var(--metin);
    font:15px/1.65 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
    max-width:900px; margin-inline:auto; overflow-wrap:break-word;
  }}
  a {{ color:var(--vurgu) }}
  h1 {{ font-size:22px; margin:18px 0 10px; line-height:1.3 }}
  h2 {{ font-size:19px; margin:30px 0 10px; padding-top:12px;
       border-top:1px solid var(--cizgi) }}
  h3 {{ font-size:16px; margin:22px 0 8px; color:var(--vurgu) }}
  p {{ margin:10px 0 }}
  ul {{ margin:10px 0; padding-left:22px }}
  li {{ margin:6px 0 }}
  .kutu {{ color:var(--soluk); font-size:17px }}
  .kutu.bitti {{ color:var(--iyi) }}
  code {{
    background:var(--panel2); padding:2px 5px; border-radius:4px;
    font:13px ui-monospace,SFMono-Regular,Menlo,monospace; color:#ffd479;
  }}
  pre {{
    background:var(--panel); border:1px solid var(--cizgi); border-radius:8px;
    padding:12px; overflow-x:auto;
  }}
  pre code {{ background:none; padding:0; color:var(--metin) }}
  blockquote {{
    margin:14px 0; padding:10px 14px; background:var(--panel);
    border-left:3px solid var(--uyari); border-radius:0 8px 8px 0;
    color:#f0d9b0;
  }}
  .tablo-kaydir {{ overflow-x:auto; margin:14px 0 }}
  table {{ border-collapse:collapse; width:100%; min-width:340px; font-size:14px }}
  th,td {{ border:1px solid var(--cizgi); padding:8px 10px; text-align:left;
          vertical-align:top }}
  th {{ background:var(--panel2) }}
  tr:nth-child(even) td {{ background:rgba(255,255,255,.02) }}
  hr {{ border:none; border-top:1px solid var(--cizgi); margin:26px 0 }}
  .geri {{
    display:inline-block; margin-bottom:6px; padding:8px 14px;
    background:var(--panel2); border:1px solid var(--cizgi); border-radius:8px;
    color:var(--metin); text-decoration:none;
  }}
</style></head><body>
<a class="geri" href="/">← Arayüze dön</a>
{govde}
</body></html>"""


def sayfa(kaynak, baslik="Prosedür"):
    """Markdown metnini tam bir HTML sayfasına çevirir."""
    return SAYFA.format(baslik=html.escape(baslik), govde=cevir(kaynak))
