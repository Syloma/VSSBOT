import json
import socket
import subprocess
import time
import urllib.request
import urllib.error

import websocket


class ChromeDOM:
    def __init__(self, adb: str, adb_address: str, port: int = 9222) -> None:
        self.adb = adb
        self.adb_address = adb_address
        self.port = port
        self.sayfa_id: str | None = None

    def baglan(self) -> None:
        subprocess.run(
            [self.adb, "-s", self.adb_address, "forward", f"tcp:{self.port}",
             "localabstract:chrome_devtools_remote"],
            capture_output=True,
            check=True,
        )
        sayfalar = [s for s in self._sayfalar() if s.get("type") == "page"]
        ticarion = [s for s in sayfalar if "ticariononline.com" in s.get("url", "")]
        if not ticarion:
            raise RuntimeError("Açık Ticarion Chrome sekmesi bulunamadı.")
        # Yeniden bağlantıda çalışan sekmeyi koru. Sekmeleri kapatmak CAPTCHA'nın
        # açtığı/taşıdığı doğru oyun sekmesini yanlışlıkla yok edebiliyordu.
        mevcut = next((s for s in ticarion if s.get("id") == self.sayfa_id), None)
        self.sayfa_id = (mevcut or ticarion[0])["id"]

    def _sayfalar(self) -> list[dict]:
        son_hata: Exception | None = None
        for deneme in range(1, 6):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json", timeout=5) as yanit:
                    return json.load(yanit)
            except (ConnectionResetError, OSError, socket.timeout, urllib.error.URLError, json.JSONDecodeError) as hata:
                son_hata = hata
                if deneme == 5:
                    break
                time.sleep(1)
        raise RuntimeError(f"Chrome debug bağlantısı kurulamadı: {son_hata}") from son_hata

    def gereksiz_ticarion_sekmelerini_kapat(self) -> int:
        """Takip edilen oyun sekmesini koruyup eski Ticarion sekmelerini kapatır."""
        if not self.sayfa_id:
            return 0
        kapatilan = 0
        for sayfa in self._sayfalar():
            if (
                sayfa.get("type") != "page"
                or sayfa.get("id") == self.sayfa_id
                or "ticariononline.com" not in sayfa.get("url", "")
            ):
                continue
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/json/close/{sayfa['id']}", timeout=3
                ) as yanit:
                    yanit.read()
                kapatilan += 1
            except (OSError, urllib.error.URLError):
                pass
        if kapatilan:
            print(f"{kapatilan} eski Ticarion sekmesi kapatıldı.", flush=True)
        return kapatilan

    def _sayfa(self, url_parcasi: str = "ticariononline.com") -> dict:
        sayfalar = [s for s in self._sayfalar() if s.get("type") == "page"]
        if self.sayfa_id:
            takip_edilen = next((s for s in sayfalar if s.get("id") == self.sayfa_id), None)
            if takip_edilen:
                return takip_edilen
        uygun = [s for s in sayfalar if url_parcasi in s.get("url", "")]
        if not uygun:
            raise RuntimeError(f"Chrome sekmesi bulunamadı: {url_parcasi}")
        self.sayfa_id = uygun[0]["id"]
        return uygun[0]

    def adres(self) -> str:
        return self._sayfa().get("url", "")

    def calistir(self, javascript: str, url_parcasi: str = "ticariononline.com"):
        sayfa = self._sayfa(url_parcasi)
        ws = websocket.create_connection(
            sayfa["webSocketDebuggerUrl"], timeout=10, suppress_origin=True
        )
        try:
            ws.send(json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": javascript,
                    "awaitPromise": True,
                    "returnByValue": True,
                },
            }))
            while True:
                cevap = json.loads(ws.recv())
                if cevap.get("id") == 1:
                    if cevap.get("result", {}).get("exceptionDetails"):
                        ayrinti = cevap["result"]["exceptionDetails"]
                        istisna = ayrinti.get("exception", {})
                        aciklama = istisna.get("description") or istisna.get("value")
                        mesaj = aciklama or ayrinti.get("text", "JavaScript çalıştırma hatası")
                        satir = ayrinti.get("lineNumber")
                        sutun = ayrinti.get("columnNumber")
                        if satir is not None:
                            mesaj = f"{mesaj} (JavaScript satır {satir + 1}, sütun {(sutun or 0) + 1})"
                        raise RuntimeError(mesaj)
                    sonuc = cevap.get("result", {}).get("result", {})
                    if sonuc.get("subtype") == "error":
                        raise RuntimeError(sonuc.get("description", "JavaScript hatası"))
                    return sonuc.get("value")
        finally:
            ws.close()

    def site_verisini_temizle(self, origin: str) -> None:
        sayfa = self._sayfa()
        ws = websocket.create_connection(
            sayfa["webSocketDebuggerUrl"], timeout=10, suppress_origin=True
        )
        try:
            ws.send(json.dumps({
                "id": 1,
                "method": "Storage.clearDataForOrigin",
                "params": {"origin": origin, "storageTypes": "cookies"},
            }))
            while True:
                cevap = json.loads(ws.recv())
                if cevap.get("id") == 1:
                    if "error" in cevap:
                        raise RuntimeError(cevap["error"].get("message", "Oturum temizleme hatası"))
                    return
        finally:
            ws.close()

    def secici_bekle(self, secici: str, saniye: int = 30) -> None:
        bitis = time.time() + saniye
        while time.time() < bitis:
            try:
                if self.calistir(f"Boolean(document.querySelector({json.dumps(secici)}))"):
                    return
            except (OSError, RuntimeError, urllib.error.URLError):
                pass
            time.sleep(0.5)
        raise TimeoutError(f"Sayfa öğesi bulunamadı: {secici}")

    def url_bekle(self, url_parcasi: str, saniye: int = 30) -> None:
        bitis = time.time() + saniye
        while time.time() < bitis:
            try:
                if url_parcasi in self._sayfa().get("url", ""):
                    return
            except (OSError, RuntimeError, urllib.error.URLError):
                pass
            time.sleep(0.5)
        raise TimeoutError(f"Chrome adresi beklenirken süre doldu: {url_parcasi}")

    def yeni_sayfa_bekle(self, url_parcalari: list[str], saniye: int = 60) -> str:
        baslangic_idleri = {
            sayfa.get("id") for sayfa in self._sayfalar() if sayfa.get("type") == "page"
        }
        bitis = time.time() + saniye
        while time.time() < bitis:
            try:
                sayfalar = [s for s in self._sayfalar() if s.get("type") == "page"]
                # Önce izlenen sekmeye bak. Eski/stale sekmelerin yanlış sonuç
                # olarak seçilmesini engelleyen temel kural budur.
                takip = next((s for s in sayfalar if s.get("id") == self.sayfa_id), None)
                adaylar = ([takip] if takip else []) + [
                    s for s in sayfalar
                    if s.get("id") != self.sayfa_id and s.get("id") not in baslangic_idleri
                ]
                for sayfa in adaylar:
                    if not sayfa:
                        continue
                    adres = sayfa.get("url", "")
                    if any(p in adres for p in url_parcalari):
                        self.sayfa_id = sayfa["id"]
                        self.gereksiz_ticarion_sekmelerini_kapat()
                        return adres
            except (OSError, RuntimeError, urllib.error.URLError):
                pass
            time.sleep(0.5)
        raise TimeoutError(f"Yeni Chrome sayfası beklenirken süre doldu: {url_parcalari}")

    def tikla(self, secici: str) -> None:
        self.secici_bekle(secici)
        self.calistir(f"document.querySelector({json.dumps(secici)}).click(); true")

    def yaz(self, secici: str, metin: str) -> None:
        self.secici_bekle(secici)
        self.calistir(
            "(() => {"
            f"const e=document.querySelector({json.dumps(secici)});"
            f"e.value={json.dumps(metin)};"
            "e.dispatchEvent(new Event('input',{bubbles:true}));"
            "e.dispatchEvent(new Event('change',{bubbles:true}));"
            "return true;})()"
        )

    def adrese_git(self, adres: str) -> None:
        sayfa = self._sayfa()
        ws = websocket.create_connection(
            sayfa["webSocketDebuggerUrl"], timeout=10, suppress_origin=True
        )
        try:
            ws.send(json.dumps({
                "id": 1,
                "method": "Page.navigate",
                "params": {"url": adres},
            }))
            while True:
                cevap = json.loads(ws.recv())
                if cevap.get("id") == 1:
                    if "error" in cevap:
                        raise RuntimeError(cevap["error"].get("message", "Sayfa açılamadı"))
                    return
        finally:
            ws.close()
