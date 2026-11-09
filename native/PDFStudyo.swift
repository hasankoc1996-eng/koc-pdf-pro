// Koç PDF Pro — yerel Mac uygulaması.
// Python sunucusunu (app.py) arka planda başlatır; arayüz, macOS sekmeleri hâlinde açılan
// pencerelerdeki WKWebView'larda gösterilir. Her sekme kendi belgesini tutar.
import Cocoa
import PDFKit
import UniformTypeIdentifiers
import WebKit

let port = 5055
let baseURL = URL(string: "http://127.0.0.1:\(port)/")!
var appKey: String?   // motorun uygulama anahtarı (yalnızca kurulum paketlerinde)

func projectDir() -> URL {
    if let path = Bundle.main.object(forInfoDictionaryKey: "PDFStudyoProjectPath") as? String,
       FileManager.default.fileExists(atPath: path) {
        return URL(fileURLWithPath: path)
    }
    // Proje iCloud'la eşitlenen Masaüstünde değil: orada dosyalar buluta boşaltılınca motor açılamıyordu
    return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Projeler/PDF-Studyo")
}

func jsString(_ value: Any) -> String {
    (try? JSONSerialization.data(withJSONObject: [value])).flatMap { String(data: $0, encoding: .utf8) }
        .map { String($0.dropFirst().dropLast()) } ?? "null"
}

// "Son Açılanlar"dan seçilen belgeleri NSDocument yerine okuyucuya yönlendirir.
final class DocumentController: NSDocumentController {
    override func openDocument(withContentsOf url: URL, display displayDocument: Bool,
                               completionHandler: @escaping (NSDocument?, Bool, Error?) -> Void) {
        (NSApp.delegate as? AppDelegate)?.openFiles([url])
        completionHandler(nil, false, nil)
    }
}

// WKUserContentController işleyicisini güçlü tutar; sekme kapanınca bellekte kalmasın diye zayıf aracı.
final class WeakScriptHandler: NSObject, WKScriptMessageHandler {
    weak var target: WKScriptMessageHandler?
    init(_ target: WKScriptMessageHandler) { self.target = target }
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.userContentController(controller, didReceive: message)
    }
}

// Pencereye bırakılan dosyaların diskteki yolunu sayfaya bildirir: "Kaydet" açılan dosyanın üzerine yazabilsin
// (sayfadaki dosya seçme penceresinde seçilenler için de: runOpenPanelWith).
final class DropWebView: WKWebView {
    var onDropPaths: (([String]) -> Void)?

    /// Sayfa başlık çubuğunun altına uzanır ve en üstteki bu yükseklikte başlık satırını kendisi çizer. O şeride
    /// tıklamaları web sayfası aldığı için pencereyi sürükleme ve çift tıklama (sistem ayarındaki büyüt / küçült)
    /// burada yapılır.
    static let titlebarHeight: CGFloat = 28

    override func mouseDown(with event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        let fromTop = isFlipped ? point.y : bounds.height - point.y
        guard fromTop < DropWebView.titlebarHeight, let window else { return super.mouseDown(with: event) }
        if event.clickCount == 2 {
            switch UserDefaults.standard.string(forKey: "AppleActionOnDoubleClick") {
            case "Minimize": window.miniaturize(nil)
            case "None": break
            default: window.zoom(nil)
            }
        } else {
            window.performDrag(with: event)
        }
    }
    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        let urls = sender.draggingPasteboard.readObjects(forClasses: [NSURL.self],
                                                         options: [.urlReadingFileURLsOnly: true]) as? [URL] ?? []
        if !urls.isEmpty { onDropPaths?(urls.map { $0.path }) }
        return super.performDragOperation(sender)
    }
}

// MARK: - Sekme

final class Tab: NSObject, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate, WKScriptMessageHandler {
    static var nextID = 1
    let id: Int
    let webView: WKWebView
    unowned let app: AppDelegate
    var title = "Koç PDF Pro"           // sekme çubuğunda görünen ad
    var window: NSWindow { app.window }  // tüm sekmeler tek pencerede
    var pendingPaths: [String] = []      // sayfa hazır olmadan gelen "aç" istekleri
    var pageReady = false
    var hasUnsavedChanges = false
    var hasDocument = false
    var route = ""
    var documentPath: String?
    var acceptFilter = ""
    var downloadTargets: [ObjectIdentifier: URL] = [:]
    var splashShownAt: Date?             // açılış ekranı ne zaman gösterildi
    var sharePicker: NSSharingServicePicker?

    init(app: AppDelegate) {
        self.app = app
        id = Tab.nextID
        Tab.nextID += 1
        let config = WKWebViewConfiguration()
        config.userContentController.addUserScript(Tab.bootScript())
        webView = DropWebView(frame: .zero, configuration: config)
        webView.pageZoom = AppDelegate.uiZoom
        super.init()
        config.userContentController.add(WeakScriptHandler(self), name: "pdfstudyo")
        (webView as? DropWebView)?.onDropPaths = { [weak self] paths in
            self?.evaluate("window.PDFSTUDYO_dropPaths = {paths: \(jsString(paths)), t: Date.now()}")
        }
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = false
        webView.setValue(false, forKey: "drawsBackground")
        webView.autoresizingMask = [.width, .height]
    }

    /// Sayfa açılmadan önce çalışan betik: yerel uygulama işareti, seçili görünüm modu ve arayüz büyüklüğü.
    static func bootScript() -> WKUserScript {
        let theme = UserDefaults.standard.string(forKey: "theme") ?? "auto"
        // PDFSTUDYO_TITLEBAR: sayfa başlık çubuğunun altına uzanır; başlık satırını (pencere düğmelerinin yanında
        // "Koç PDF Pro") sayfa bu yükseklikte çizer
        return WKUserScript(source: "window.PDFSTUDYO_NATIVE = true; window.PDFSTUDYO_TITLEBAR = \(Int(DropWebView.titlebarHeight)); "
                            + "window.PDFSTUDYO_THEME = \(jsString(theme)); window.PDFSTUDYO_UIZOOM = \(AppDelegate.uiZoom);",
                            injectionTime: .atDocumentStart, forMainFrameOnly: true)
    }

    func refreshBootScript() {
        let content = webView.configuration.userContentController
        content.removeAllUserScripts()
        content.addUserScript(Tab.bootScript())
    }

    /// Bu sekme yeni bir belge için kullanılabilir mi? (boş ana sayfa ya da boş okuyucu)
    var isFresh: Bool {
        !hasDocument && !hasUnsavedChanges && pendingPaths.isEmpty && documentPath == nil
            && (route == "" || route == "reader")
    }

    func loadApp() {
        var parts = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
        // Kurulum paketi: motor yalnızca kendi anahtarını bilen pencereye cevap verir (bkz. app.py, APP_KEY)
        if let key = appKey { parts.queryItems = [URLQueryItem(name: "anahtar", value: key)] }
        // PDF ile açıldıysa doğrudan okuyucuyu yükle (ana sayfa görünüp kaybolmasın)
        if !pendingPaths.isEmpty { parts.fragment = "/reader" }
        webView.load(URLRequest(url: parts.url!))
    }

    func open(_ path: String) {
        pendingPaths.append(path)
        documentPath = path
        deliverPendingPaths()
    }

    func deliverPendingPaths() {
        guard pageReady, !pendingPaths.isEmpty else { return }
        let paths = pendingPaths
        pendingPaths = []
        webView.evaluateJavaScript("window.PDFSTUDYO_openPaths && window.PDFSTUDYO_openPaths(\(jsString(paths)))")
    }

    // MARK: Açılış ekranı

    /// Açılış ekranı kaybolması dahil 2 saniye sürer; motor daha geç hazır olursa onu bekler.
    static let splashTotal: TimeInterval = 2.0
    static let splashFadeOut: TimeInterval = 0.55
    static let splashMinimum: TimeInterval = splashTotal - splashFadeOut

    static let splashLogo: String = {
        guard let url = Bundle.main.url(forResource: "splash", withExtension: "png"),
              let data = try? Data(contentsOf: url) else { return "" }
        return "data:image/png;base64," + data.base64EncodedString()
    }()

    /// Motor hazırlanırken: logo belirir, ilerleme çizgisi dolar. İnternet gerekmez (logo uygulamanın içinde).
    func showSplash() {
        splashShownAt = Date()
        let theme = UserDefaults.standard.string(forKey: "theme") ?? "auto"
        let html = """
        <!doctype html><html data-theme="\(theme)"><head><meta charset="utf-8"><style>
        :root { color-scheme: light dark; --bg: #f4f5f7; --text: #1c2024; --muted: #6b7280;
                --track: rgba(0,0,0,.08); --accent: #d6453d; }
        :root[data-theme="dark"] { --bg: #15171a; --text: #e8eaed; --muted: #9aa1aa; --track: rgba(255,255,255,.1); --accent: #ef5a50; }
        @media (prefers-color-scheme: dark) {
          :root:not([data-theme="light"]) { --bg: #15171a; --text: #e8eaed; --muted: #9aa1aa; --track: rgba(255,255,255,.1); --accent: #ef5a50; }
        }
        html, body { margin: 0; height: 100%; }
        body { background: var(--bg); color: var(--text); display: grid; place-items: center; overflow: hidden;
               font: 15px -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif; -webkit-user-select: none; cursor: default; }
        .wrap { display: flex; flex-direction: column; align-items: center; margin-top: -24px;
                transition: opacity .35s ease, transform .35s ease; }
        .logo { width: 128px; height: 128px; filter: drop-shadow(0 14px 22px rgba(214,69,61,.30)) drop-shadow(0 2px 4px rgba(0,0,0,.14));
                animation: pop .75s cubic-bezier(.2,.9,.25,1.2) both; }
        .logo[src=""] { display: none; }
        h1 { margin: 20px 0 0; font-size: 26px; font-weight: 700; letter-spacing: -.01em; animation: rise .5s .22s ease-out both; }
        .bar { width: 180px; height: 3px; border-radius: 3px; background: var(--track); margin-top: 18px; overflow: hidden;
               animation: rise .5s .32s ease-out both; }
        .bar i { display: block; height: 100%; width: 0; background: var(--accent); border-radius: 3px;
                 animation: load \(String(format: "%.2f", Tab.splashMinimum - 0.4))s .4s cubic-bezier(.3,.4,.4,1) forwards; }
        .copy { position: fixed; left: 0; right: 0; bottom: 22px; text-align: center; font-size: 11.5px; color: var(--muted);
                animation: fade .6s .5s both; transition: opacity .3s; }
        body.out .wrap { opacity: 0; transform: scale(.97); }
        body.out .copy { opacity: 0; }
        @keyframes pop { from { opacity: 0; transform: scale(.82); } to { opacity: 1; transform: scale(1); } }
        @keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
        @keyframes fade { from { opacity: 0; } to { opacity: 1; } }
        @keyframes load { to { width: 85%; } }
        @media (prefers-reduced-motion: reduce) { * { animation-duration: 1ms !important; animation-delay: 0s !important; } }
        </style></head><body>
        <div class="wrap"><img class="logo" src="\(Tab.splashLogo)" alt=""><h1>Koç PDF Pro</h1><div class="bar"><i></i></div></div>
        <div class="copy">© 2026 Hasan Koç · Açık kaynak (GNU AGPL-3.0)</div>
        <script>
        // Motor hazır: çizgi bulunduğu yerden sonuna kadar dolar, sonra her şey yumuşakça kaybolur
        function finish() {
          const bar = document.querySelector('.bar i');
          const width = getComputedStyle(bar).width;
          bar.style.animation = 'none';
          bar.style.width = width;
          bar.offsetWidth;
          bar.style.transition = 'width .2s ease-out';
          bar.style.width = '100%';
          setTimeout(() => document.body.classList.add('out'), 200);
        }
        </script></body></html>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }

    /// Motor hazır: açılış ekranı en kısa süresini doldurunca kaybolur ve uygulama açılır.
    func finishSplash() {
        guard let shown = splashShownAt else { return loadApp() }
        splashShownAt = nil
        let wait = max(0, Tab.splashMinimum - Date().timeIntervalSince(shown))
        DispatchQueue.main.asyncAfter(deadline: .now() + wait) { [weak self] in
            self?.webView.evaluateJavaScript("window.finish && finish()")
            DispatchQueue.main.asyncAfter(deadline: .now() + Tab.splashFadeOut) { [weak self] in self?.loadApp() }
        }
    }

    func showLoading(_ message: String, spinner: Bool = true) {
        splashShownAt = nil
        let safe = message.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: "\n", with: "<br>")
        let html = """
        <!doctype html><html><head><meta charset="utf-8"><style>
        :root { color-scheme: light dark; }
        body { margin:0; height:100vh; display:grid; place-items:center; background:Canvas; color:CanvasText;
               font: 15px -apple-system, sans-serif; text-align:center; }
        .s { width:28px; height:28px; margin:0 auto 16px; border:3px solid rgba(127,127,127,.25);
             border-top-color:#d6453d; border-radius:50%; animation:r .8s linear infinite; }
        @keyframes r { to { transform: rotate(360deg); } }
        </style></head><body><div>\(spinner ? "<div class=s></div>" : "")<div>\(safe)</div></div></body></html>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }

    func evaluate(_ js: String) { webView.evaluateJavaScript(js) }

    // MARK: Sekmenin kapanışı

    /// Kaydedilmemiş değişiklik varsa sorar: Kaydet (⌘S gibi) / Farklı Kaydet… / Kaydetmeden Kapat / Vazgeç.
    /// done(true) → kapatılabilir. Kaydetmeyi sayfa yapar (karartma ve e-imza soruları dahil); vazgeçilir ya da
    /// kaydedilemezse sekme açık kalır.
    func confirmClose(_ done: @escaping (Bool) -> Void) {
        guard hasUnsavedChanges else { return done(true) }
        let alert = NSAlert()
        alert.messageText = "“\(title)” sekmesinde kaydedilmemiş değişiklikler var"
        alert.informativeText = "Kapatmadan önce kaydetmek ister misiniz? Kaydetmezseniz değişiklikler kaybolur."
        alert.addButton(withTitle: "Kaydet")
        alert.addButton(withTitle: "Farklı Kaydet…")
        alert.addButton(withTitle: "Kaydetmeden Kapat")
        alert.addButton(withTitle: "Vazgeç").keyEquivalent = "\u{1b}"   // Esc
        alert.alertStyle = .warning
        alert.beginSheetModal(for: window) { response in
            switch response {
            case .alertFirstButtonReturn: self.saveForClose(asNew: false, done)
            case .alertSecondButtonReturn: self.saveForClose(asNew: true, done)
            case .alertThirdButtonReturn: done(true)
            default: done(false)
            }
        }
    }

    /// Sayfadaki kaydetmeyi çalıştırır (uyarı kapandıktan sonra: kaydetme penceresi açılabilsin). done(kaydedildi mi)
    func saveForClose(asNew: Bool, _ done: @escaping (Bool) -> Void) {
        DispatchQueue.main.async {
            self.webView.callAsyncJavaScript(
                "return window.PDFSTUDYO_saveForClose ? await window.PDFSTUDYO_saveForClose(asNew) : false",
                arguments: ["asNew": asNew], in: nil, in: .page) { result in
                guard case .success(let value) = result else { return done(false) }
                done((value as? Bool) ?? (value as? NSNumber)?.boolValue ?? false)
            }
        }
    }

    func teardown() {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "pdfstudyo")
        webView.stopLoading()
        webView.removeFromSuperview()
    }

    // MARK: Gezinme ve indirme

    /// Uygulamanın kendi sayfası mı: şema, sunucu adı ve port birlikte. Bilgisayardaki başka yerel servislerin
    /// sayfaları (başka port) uygulama penceresinde açılmaz, varsayılan tarayıcıya gider.
    func isLocal(_ url: URL) -> Bool {
        url.scheme == "http" && (url.host == "127.0.0.1" || url.host == "localhost") && url.port == port
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if action.shouldPerformDownload { return decisionHandler(.download) }
        guard let url = action.request.url else { return decisionHandler(.allow) }
        if url.isFileURL { return decisionHandler(.cancel) }  // pencereye bırakılan dosya sayfayı değiştirmesin
        if url.scheme == "mailto" || url.scheme == "tel" {   // e-posta → Mail, telefon → FaceTime
            NSWorkspace.shared.open(url)
            return decisionHandler(.cancel)
        }
        if (url.scheme == "http" || url.scheme == "https") && !isLocal(url) {
            NSWorkspace.shared.open(url)
            return decisionHandler(.cancel)
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        pageReady = false
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard let url = webView.url, isLocal(url) else { return }
        pageReady = true
        app.sendTabs(to: self)   // sayfanın sekme çubuğu tüm sekmeleri göstersin
        deliverPendingPaths()
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        webView.reload()
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if let http = response.response as? HTTPURLResponse,
           let disposition = http.value(forHTTPHeaderField: "Content-Disposition"),
           disposition.lowercased().contains("attachment") {
            return decisionHandler(.download)
        }
        decisionHandler(response.canShowMIMEType ? .allow : .download)
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        download.delegate = self
    }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                  suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = suggestedFilename
        panel.directoryURL = app.saveDirectory(preferred: nil)
        panel.canCreateDirectories = true
        panel.beginSheetModal(for: window) { result in
            guard result == .OK, let url = panel.url else { return completionHandler(nil) }
            self.app.rememberSaveDirectory(url.deletingLastPathComponent())
            try? FileManager.default.removeItem(at: url)  // üzerine yazma panelde onaylandı
            self.downloadTargets[ObjectIdentifier(download)] = url
            completionHandler(url)
        }
    }

    func downloadDidFinish(_ download: WKDownload) {
        guard let url = downloadTargets.removeValue(forKey: ObjectIdentifier(download)) else { return }
        evaluate("window.PDFSTUDYO_saved && window.PDFSTUDYO_saved(\(jsString(url.path)))")
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        downloadTargets.removeValue(forKey: ObjectIdentifier(download))
        let alert = NSAlert()
        alert.messageText = "Dosya kaydedilemedi"
        alert.informativeText = error.localizedDescription
        alert.beginSheetModal(for: window)
    }

    // MARK: Dosya seçme ve uyarı pencereleri

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        let types = contentTypes(for: acceptFilter)
        if !types.isEmpty { panel.allowedContentTypes = types }
        acceptFilter = ""
        panel.beginSheetModal(for: window) { result in
            // Seçilen dosyaların diskteki yolu da sayfaya bildirilir (bırakılan dosyalardaki gibi): ana sayfadan
            // seçilen PDF kopya gibi değil, kendi yeriyle açılsın (son açılanlara girsin, Kaydet üzerine yazsın)
            if result == .OK {
                self.evaluate("window.PDFSTUDYO_dropPaths = {paths: \(jsString(panel.urls.map { $0.path })), t: Date.now()}")
            }
            completionHandler(result == .OK ? panel.urls : nil)
        }
    }

    func contentTypes(for accept: String) -> [UTType] {
        var types: [UTType] = []
        for part in accept.split(separator: ",").map({ $0.trimmingCharacters(in: .whitespaces).lowercased() }) {
            if part == "image/*" {
                types.append(.image)
            } else if part.hasPrefix("."), let type = UTType(filenameExtension: String(part.dropFirst())) {
                types.append(type)
            }
        }
        return types
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "Tamam")
        alert.beginSheetModal(for: window) { _ in completionHandler() }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "Tamam")
        alert.addButton(withTitle: "Vazgeç")
        alert.beginSheetModal(for: window) { response in completionHandler(response == .alertFirstButtonReturn) }
    }

    // MARK: Sayfadan gelen mesajlar

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        // Köprüyü yalnızca uygulamanın kendi sayfası kullanabilir: başka adres ya da porttan yüklenmiş bir çerçeve
        // (iframe dahil) dosya açma, kaydetme, paylaşma gibi yerel komutları çalıştıramaz
        let origin = message.frameInfo.securityOrigin
        guard origin.protocol == "http", origin.host == "127.0.0.1" || origin.host == "localhost",
              origin.port == port else { return }
        guard let body = message.body as? [String: Any], let action = body["action"] as? String else { return }
        switch action {
        case "accept":
            acceptFilter = body["value"] as? String ?? ""
        case "quit":
            NSApp.terminate(nil)
        case "state":
            // Sayfa durumu: kaydedilmemiş değişiklik, açık belge, hangi ekran
            hasUnsavedChanges = body["unsaved"] as? Bool ?? false
            hasDocument = body["hasDoc"] as? Bool ?? false
            route = body["route"] as? String ?? ""
            if !hasDocument && pendingPaths.isEmpty { documentPath = nil }
            app.tabsChanged()
        case "theme":
            if let value = body["value"] as? String { app.setTheme(value, from: self) }
        case "uiZoom":   // Ayarlar › Görünüm › Arayüz büyüklüğü
            if let value = body["value"] as? Double { app.setUIZoom(value) }
        case "clearRecent":   // Ayarlar › Belgeler: Dosya › Son Açılanlar menüsü de temizlensin
            NSDocumentController.shared.clearRecentDocuments(nil)
        case "openPDF":
            app.showOpenPanel(for: window)
        case "document":
            // Sekme başlığı: açık belgenin adı (ve Finder'daki yeri)
            let name = (body["name"] as? String).flatMap { $0.isEmpty ? nil : $0 }
            if let path = body["path"] as? String, !path.isEmpty {
                documentPath = path
                title = name ?? URL(fileURLWithPath: path).lastPathComponent
            } else {
                title = name ?? "Koç PDF Pro"
            }
            app.tabsChanged()
        case "selectTab":
            if let id = body["id"] as? Int, let tab = app.tabs.first(where: { $0.id == id }) { app.select(tab) }
        case "closeTab":
            if let id = body["id"] as? Int, let tab = app.tabs.first(where: { $0.id == id }) { app.close(tab) }
        case "newTab":
            app.newTab()
        case "openPaths":   // Önceki sürümler: yedeği yeni sekmede aç
            if let paths = body["paths"] as? [String] { app.openFiles(paths.map { URL(fileURLWithPath: $0) }) }
        case "savePanel":
            showSavePanel(body)
        case "folderPanel":
            showFolderPanel(body)
        case "openPanel":
            showFilePanel(body)
        case "share":
            if let path = body["path"] as? String { showSharePicker(path, rect: body["rect"] as? [String: Any]) }
        case "mail":
            composeMail(body)
        case "copyFile":   // PDF'i dosya olarak panoya: Finder'a, Mail'e, UYAP'a ⌘V ile yapıştırılır
            if let path = body["path"] as? String {
                let pasteboard = NSPasteboard.general
                pasteboard.clearContents()
                reply(body["id"], pasteboard.writeObjects([URL(fileURLWithPath: path) as NSURL]))
            }
        case "reveal":
            if let path = body["path"] as? String {
                NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
            }
        case "print":
            if let url = body["url"] as? String { app.printPDF(from: url, name: body["name"] as? String ?? "PDF", in: self) }
        case "defaultStatus":
            app.reportDefaultStatus(to: self)
        case "setDefaultPDF":
            app.makeDefaultPDFApp(reportTo: self)
        default:
            break
        }
    }

    // MARK: Kaydetme ve seçme pencereleri (sonuç sayfaya PDFSTUDYO_reply ile döner)

    func reply(_ id: Any?, _ value: Any?) {
        evaluate("window.PDFSTUDYO_reply && window.PDFSTUDYO_reply(\(jsString(id ?? NSNull())), \(jsString(value ?? NSNull())))")
    }

    /// Farklı Kaydet: dosya adı ve yeri seçilir; aynı adlı dosya varsa macOS üzerine yazmayı sorar.
    func showSavePanel(_ body: [String: Any]) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = body["name"] as? String ?? "belge.pdf"
        panel.canCreateDirectories = true
        panel.isExtensionHidden = false
        let types = (body["types"] as? [String] ?? []).compactMap { UTType(filenameExtension: $0) }
        if !types.isEmpty { panel.allowedContentTypes = types }
        panel.directoryURL = app.saveDirectory(preferred: body["directory"] as? String)
        panel.beginSheetModal(for: window) { result in
            guard result == .OK, let url = panel.url else { return self.reply(body["id"], nil) }
            self.app.rememberSaveDirectory(url.deletingLastPathComponent())
            self.reply(body["id"], url.path)
        }
    }

    /// Birden çok dosya: kaydedilecek klasör seçilir.
    func showFolderPanel(_ body: [String: Any]) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.prompt = "Buraya Kaydet"
        panel.message = body["message"] as? String ?? "Dosyaların kaydedileceği klasörü seçin"
        panel.directoryURL = app.saveDirectory(preferred: body["directory"] as? String)
        panel.beginSheetModal(for: window) { result in
            guard result == .OK, let url = panel.url else { return self.reply(body["id"], nil) }
            self.app.rememberSaveDirectory(url)
            self.reply(body["id"], url.path)
        }
    }

    /// Sorun bildir: varsayılan e-posta programında alıcısı, konusu ve rapor dosyası ekli yeni ileti.
    /// Açılamazsa sayfaya false döner; sayfa mailto bağlantısına ve "Klasörde göster"e geçer.
    func composeMail(_ body: [String: Any]) {
        var items: [Any] = [body["body"] as? String ?? ""]
        if let path = body["path"] as? String { items.append(URL(fileURLWithPath: path)) }
        guard let service = NSSharingService(named: .composeEmail), service.canPerform(withItems: items) else {
            return reply(body["id"], false)
        }
        service.recipients = [body["to"] as? String ?? ""]
        service.subject = body["subject"] as? String ?? ""
        service.perform(withItems: items)
        reply(body["id"], true)
    }

    /// Paylaş: macOS'un paylaşım menüsü (Mail, Mesajlar, AirDrop, Notlar…), tıklanan düğmenin altında.
    func showSharePicker(_ path: String, rect: [String: Any]?) {
        guard FileManager.default.fileExists(atPath: path) else { return }
        let bounds = webView.bounds
        var anchor = NSRect(x: bounds.midX, y: bounds.midY, width: 1, height: 1)
        if let r = rect, let x = r["x"] as? Double, let top = r["y"] as? Double,
           let w = r["w"] as? Double, let h = r["h"] as? Double {
            anchor = NSRect(x: x, y: webView.isFlipped ? top : bounds.height - top - h, width: w, height: h)
        }
        let picker = NSSharingServicePicker(items: [URL(fileURLWithPath: path)])
        sharePicker = picker
        picker.show(relativeTo: anchor, of: webView, preferredEdge: webView.isFlipped ? .maxY : .minY)
    }

    /// Dosya seçme (diskteki yolu da bilinsin diye): düzenleyicinin "Aç" düğmesi.
    func showFilePanel(_ body: [String: Any]) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = body["multiple"] as? Bool ?? false
        panel.canChooseDirectories = false
        let types = contentTypes(for: body["accept"] as? String ?? "")
        if !types.isEmpty { panel.allowedContentTypes = types }
        panel.directoryURL = app.saveDirectory(preferred: body["directory"] as? String)
        panel.beginSheetModal(for: window) { result in
            guard result == .OK else { return self.reply(body["id"], nil) }
            panel.urls.forEach { NSDocumentController.shared.noteNewRecentDocumentURL($0) }
            self.reply(body["id"], panel.urls.map { $0.path })
        }
    }
}

// MARK: - Uygulama

// Sekme sayfalarını taşıyan görünüm (sol üst köşe başlangıç)
final class TabContainer: NSView {
    override var isFlipped: Bool { true }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate, NSWindowDelegate {
    var tabs: [Tab] = []
    var selected: Tab?
    var windowCloseConfirmed = false
    var tabsUpdateQueued = false
    lazy var window: NSWindow = makeWindow()
    var server: Process?
    var serverReady = false
    var startupError: String?
    var recentMenu: NSMenu!
    var themeMenu: NSMenu!
    static let themes: [(value: String, title: String)] = [("auto", "Otomatik (Mac ayarı)"), ("light", "Gündüz"), ("dark", "Gece")]

    var activeTab: Tab? { selected ?? tabs.last }

    /// Sekme çubuğuyla aynı renk: başlık çubuğu ve sekmeler tek bir şerit gibi görünür (gece / gündüz)
    static let stripColor = NSColor(name: nil) { appearance in
        appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            ? NSColor(srgbRed: 0x0d / 255, green: 0x0f / 255, blue: 0x11 / 255, alpha: 1)
            : NSColor(srgbRed: 0xe4 / 255, green: 0xe6 / 255, blue: 0xea / 255, alpha: 1)
    }

    func makeWindow() -> NSWindow {
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1320, height: 860),
                         styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                         backing: .buffered, defer: false)
        w.title = "Koç PDF Pro"
        w.minSize = NSSize(width: 960, height: 620)
        w.titlebarAppearsTransparent = true
        w.titleVisibility = .hidden          // başlık satırını sayfa çiziyor (sola yaslı, kalın); belge adı sekmede
        w.backgroundColor = AppDelegate.stripColor
        w.tabbingMode = .disallowed          // sekmeleri uygulamanın kendi sekme çubuğu gösterir
        w.isReleasedWhenClosed = false
        w.delegate = self
        let container = TabContainer()
        container.autoresizesSubviews = true
        w.contentView = container
        w.center()
        w.setFrameAutosaveName("PDFStudyoMainWindow")
        return w
    }

    // MARK: Yaşam döngüsü

    func applicationWillFinishLaunching(_ notification: Notification) {
        // Seçili görünüm modunu pencereler açılmadan uygula (başlık çubuğu doğru renkte açılsın)
        applyAppearance(UserDefaults.standard.string(forKey: "theme") ?? "auto")
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        if tabs.isEmpty { newTab() }  // PDF ile açıldıysa sekmeler zaten oluşturuldu
        checkServer { alive in
            if alive { self.serverDidStart() } else { self.launchServer() }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        // Yalnızca okuma yapıldıysa hiçbir şey sormadan kapanır. Kaydedilmemiş sekmeler sırayla sorulur; hepsi
        // tamamsa çıkış yeniden istenir (bu kez sormadan).
        guard tabs.contains(where: { $0.hasUnsavedChanges }), !windowCloseConfirmed else { return .terminateNow }
        confirmDirtyTabs { ok in
            guard ok else { return }
            self.windowCloseConfirmed = true
            NSApp.terminate(nil)
        }
        return .terminateCancel
    }

    /// Kaydedilmemiş değişikliği olan sekmeler sırayla öne getirilip sorulur (Kaydet / Farklı Kaydet… / Kaydetmeden
    /// Kapat / Vazgeç). done(true): hepsi kaydedildi ya da kaydetmeden kapatılmaları seçildi; biri "Vazgeç" derse false.
    func confirmDirtyTabs(_ done: @escaping (Bool) -> Void) {
        let dirty = tabs.filter { $0.hasUnsavedChanges }
        func ask(_ k: Int) {
            guard k < dirty.count else { return done(true) }
            select(dirty[k])
            dirty[k].confirmClose { ok in ok ? ask(k + 1) : done(false) }
        }
        ask(0)
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let server = server, server.isRunning {
            server.terminate()
        }
    }

    // MARK: Sekmeler

    @discardableResult
    func newTab() -> Tab {
        let tab = Tab(app: self)
        tabs.append(tab)
        tab.webView.frame = window.contentView?.bounds ?? .zero
        window.contentView?.addSubview(tab.webView)
        select(tab)
        window.makeKeyAndOrderFront(nil)
        if serverReady {
            // loadApp, bekleyen PDF yoksa ana sayfayı açar; PDF atanırsa okuyucuya geçer
            DispatchQueue.main.async { tab.loadApp() }
        } else if let error = startupError {
            tab.showLoading(error, spinner: false)
        } else {
            tab.showSplash()
        }
        return tab
    }

    func select(_ tab: Tab) {
        selected = tab
        for t in tabs { t.webView.isHidden = t !== tab }
        tab.webView.frame = window.contentView?.bounds ?? .zero
        window.makeFirstResponder(tab.webView)
        tabsChanged()
    }

    /// Sekmeyi kapatır (kaydedilmemiş değişiklik varsa sorar); son sekme kapanınca pencere ve uygulama kapanır.
    func close(_ tab: Tab) {
        tab.confirmClose { ok in
            guard ok, let index = self.tabs.firstIndex(where: { $0 === tab }) else { return }
            tab.teardown()
            self.tabs.remove(at: index)
            if self.tabs.isEmpty {
                self.windowCloseConfirmed = true
                self.window.close()
                return
            }
            if self.selected === tab { self.select(self.tabs[min(index, self.tabs.count - 1)]) } else { self.tabsChanged() }
        }
    }

    /// Sekme listesi değişti: pencere başlığını güncelle, tüm sayfaların sekme çubuğuna bildir (bir kez)
    func tabsChanged() {
        if let tab = selected {
            window.title = tab.title
            window.representedURL = tab.documentPath.map { URL(fileURLWithPath: $0) }
        }
        window.isDocumentEdited = tabs.contains { $0.hasUnsavedChanges }   // kapat düğmesinde nokta
        guard !tabsUpdateQueued else { return }
        tabsUpdateQueued = true
        DispatchQueue.main.async {
            self.tabsUpdateQueued = false
            self.tabs.filter { $0.pageReady }.forEach { self.sendTabs(to: $0) }
        }
    }

    func sendTabs(to tab: Tab) {
        let list: [[String: Any]] = tabs.map { [
            "id": $0.id, "title": $0.title, "path": $0.documentPath ?? NSNull(),
            "active": $0 === selected, "unsaved": $0.hasUnsavedChanges, "doc": $0.hasDocument,
        ] }
        tab.evaluate("window.PDFSTUDYO_tabs && window.PDFSTUDYO_tabs(\(jsString(list)))")
    }

    // Menü: ⌘T yeni sekme, ⌘W sekmeyi kapat, ⌃⇥ / ⌃⇧⇥ sekmeler arasında gezin
    @objc func newWindowForTab(_ sender: Any?) {
        newTab()
    }

    @objc func closeCurrentTab() {
        if let tab = selected { close(tab) }
    }

    @objc func selectNextTab() { stepTab(1) }
    @objc func selectPreviousTab() { stepTab(-1) }

    func stepTab(_ delta: Int) {
        guard let tab = selected, let i = tabs.firstIndex(where: { $0 === tab }), tabs.count > 1 else { return }
        select(tabs[(i + delta + tabs.count) % tabs.count])
    }

    // Pencerenin kapat düğmesi: tüm sekmeler kapanır (kaydedilmemiş varsa bir kez sorulur)
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if !tabs.contains(where: { $0.hasUnsavedChanges }) || windowCloseConfirmed { return true }
        confirmDirtyTabs { ok in
            guard ok else { return }
            self.windowCloseConfirmed = true
            self.window.close()
        }
        return false
    }

    func windowWillClose(_ notification: Notification) {
        tabs.forEach { $0.teardown() }
        tabs.removeAll()
        selected = nil
    }

    // MARK: Sunucu

    func checkServer(_ done: @escaping (Bool) -> Void) {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/status"))
        request.timeoutInterval = 1
        URLSession.shared.dataTask(with: request) { _, response, _ in
            let ok = (response as? HTTPURLResponse)?.statusCode == 200
            DispatchQueue.main.async { done(ok) }
        }.resume()
    }

    func launchServer() {
        let process = Process()
        // Taşınabilir sürüm: sunucu uygulamanın içine gömülü (Python kurulumu gerekmez)
        let embedded = Bundle.main.resourceURL?.appendingPathComponent("server/kocpdf-server")
        if let embedded = embedded, FileManager.default.isExecutableFile(atPath: embedded.path) {
            process.executableURL = embedded
            process.arguments = ["--no-browser"]
            process.currentDirectoryURL = embedded.deletingLastPathComponent()
        } else {
            // Geliştirme sürümü: proje klasöründeki Python ortamı
            let dir = projectDir()
            let python = dir.appendingPathComponent(".venv/bin/python")
            guard FileManager.default.isExecutableFile(atPath: python.path) else {
                return fail("Koç PDF Pro dosyaları bulunamadı:\n\(dir.path)\n\nPDF-Studyo klasörü taşınmış veya silinmiş olabilir.")
            }
            process.executableURL = python
            process.arguments = ["-W", "ignore", dir.appendingPathComponent("app.py").path, "--no-browser"]
            process.currentDirectoryURL = dir
        }
        var env = ProcessInfo.processInfo.environment
        env["PDFSTUDYO_PARENT_PID"] = String(getpid())
        // Metin tanıma yardımcısı (Apple Vision) uygulamanın içinde
        if let ocr = Bundle.main.executableURL?.deletingLastPathComponent().appendingPathComponent("kocpdf-ocr"),
           FileManager.default.isExecutableFile(atPath: ocr.path) {
            env["PDFSTUDYO_OCR_BIN"] = ocr.path
        }
        env["PYTHONUNBUFFERED"] = "1"
        process.environment = env
        let logs = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs")
        try? FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        let logURL = logs.appendingPathComponent("PDFStudyo.log")
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        if let handle = try? FileHandle(forWritingTo: logURL) {
            handle.seekToEndOfFile()
            process.standardOutput = handle
            process.standardError = handle
        }
        do {
            try process.run()
            server = process
            waitForServer(attempt: 0)
        } catch {
            fail("Sunucu başlatılamadı: \(error.localizedDescription)")
        }
    }

    func waitForServer(attempt: Int) {
        checkServer { alive in
            if alive { return self.serverDidStart() }
            if let server = self.server, !server.isRunning {
                return self.fail("Sunucu beklenmedik şekilde kapandı.\nAyrıntılar: ~/Library/Logs/PDFStudyo.log")
            }
            if attempt > 120 {
                return self.fail("Sunucu yanıt vermedi.\nAyrıntılar: ~/Library/Logs/PDFStudyo.log")
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { self.waitForServer(attempt: attempt + 1) }
        }
    }

    func serverDidStart() {
        // Kurulum paketinde motor her açılışta yeni bir uygulama anahtarı yazar; geliştirme sürümünde dosya yoktur
        let keyFile = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Caches/PDFStudyo/oturum")
        appKey = (try? String(contentsOf: keyFile, encoding: .utf8))?.trimmingCharacters(in: .whitespacesAndNewlines)
        if appKey?.isEmpty == true { appKey = nil }
        serverReady = true
        tabs.forEach { $0.finishSplash() }
    }

    func fail(_ message: String) {
        startupError = message
        tabs.forEach { $0.showLoading(message, spinner: false) }
    }

    // MARK: Kaydetme klasörü

    /// Önce belgenin kendi klasörü, sonra en son kaydedilen klasör, en son Masaüstü.
    func saveDirectory(preferred: String?) -> URL? {
        var isDir: ObjCBool = false
        for path in [preferred, UserDefaults.standard.string(forKey: "lastSaveDirectory")] {
            if let path = path, !path.isEmpty, FileManager.default.fileExists(atPath: path, isDirectory: &isDir), isDir.boolValue {
                return URL(fileURLWithPath: path)
            }
        }
        return FileManager.default.urls(for: .desktopDirectory, in: .userDomainMask).first
    }

    func rememberSaveDirectory(_ url: URL) {
        UserDefaults.standard.set(url.path, forKey: "lastSaveDirectory")
    }

    // MARK: Gece / gündüz modu

    func applyAppearance(_ value: String) {
        switch value {
        case "dark": NSApp.appearance = NSAppearance(named: .darkAqua)
        case "light": NSApp.appearance = NSAppearance(named: .aqua)
        default: NSApp.appearance = nil   // Mac'in ayarını izle
        }
    }

    /// Bir sekmeden ya da menüden gelen seçim: kaydet, pencereye uygula, diğer sekmelere bildir.
    func setTheme(_ value: String, from source: Tab?) {
        guard AppDelegate.themes.contains(where: { $0.value == value }) else { return }
        UserDefaults.standard.set(value, forKey: "theme")
        applyAppearance(value)
        tabs.forEach { $0.refreshBootScript() }   // yeniden yüklenen sekme de güncel modla açılsın
        for tab in tabs where tab !== source {
            tab.evaluate("window.PDFSTUDYO_applyTheme && window.PDFSTUDYO_applyTheme(\(jsString(value)))")
        }
    }

    @objc func chooseTheme(_ sender: NSMenuItem) {
        if let value = sender.representedObject as? String { setTheme(value, from: nil) }
    }

    // MARK: Arayüz büyüklüğü (Ayarlar ya da Görünüm menüsü): bütün sekmelere uygulanır, hatırlanır

    static var uiZoom: Double { UserDefaults.standard.object(forKey: "uiZoom") as? Double ?? 1.0 }

    func setUIZoom(_ value: Double) {
        let zoom = min(max((value * 100).rounded() / 100, 0.6), 2.0)
        UserDefaults.standard.set(zoom, forKey: "uiZoom")
        for tab in tabs {
            tab.webView.pageZoom = zoom
            tab.refreshBootScript()   // yeniden yüklenen sekme de bilsin
            tab.evaluate("window.PDFSTUDYO_UIZOOM = \(zoom)")   // Ayarlar penceresi doğru değeri göstersin
        }
    }

    // MARK: Belge açma (Finder, Dock, menü)

    func application(_ application: NSApplication, open urls: [URL]) {
        openFiles(urls)
    }

    /// Her PDF ayrı sekmede açılır; boş bir sekme varsa o kullanılır, zaten açıksa o sekmeye geçilir.
    func openFiles(_ urls: [URL]) {
        let paths = urls.filter { $0.isFileURL && ["pdf", "udf"].contains($0.pathExtension.lowercased()) }.map { $0.path }
        guard !paths.isEmpty else { return }
        var last: Tab?
        for path in paths {
            NSDocumentController.shared.noteNewRecentDocumentURL(URL(fileURLWithPath: path))
            if let open = tabs.first(where: { $0.documentPath == path }) {
                last = open
                continue
            }
            let tab = (activeTab?.isFresh == true) ? activeTab! : newTab()
            tab.open(path)
            last = tab
        }
        if let last = last { select(last) }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc func openDocumentPanel() {
        if tabs.isEmpty { newTab() }
        showOpenPanel(for: window)
    }

    func showOpenPanel(for window: NSWindow) {
        let panel = NSOpenPanel()
        // PDF ve UYAP belgeleri (.udf)
        panel.allowedContentTypes = [.pdf] + (UTType(filenameExtension: "udf").map { [$0] } ?? [])
        panel.allowsMultipleSelection = true   // birden çok seçilirse her biri ayrı sekmede
        panel.directoryURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first
        panel.beginSheetModal(for: window) { result in
            if result == .OK { self.openFiles(panel.urls) }
        }
    }

    @objc func openRecent(_ sender: NSMenuItem) {
        if let url = sender.representedObject as? URL { openFiles([url]) }
    }

    @objc func clearRecent() {
        NSDocumentController.shared.clearRecentDocuments(nil)
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        if menu === themeMenu {
            let current = UserDefaults.standard.string(forKey: "theme") ?? "auto"
            menu.items.forEach { $0.state = ($0.representedObject as? String) == current ? .on : .off }
            return
        }
        guard menu === recentMenu else { return }
        menu.removeAllItems()
        let urls = NSDocumentController.shared.recentDocumentURLs.filter { FileManager.default.fileExists(atPath: $0.path) }
        for url in urls {
            let item = NSMenuItem(title: url.lastPathComponent, action: #selector(openRecent(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = url
            item.image = NSWorkspace.shared.icon(forFile: url.path)
            item.image?.size = NSSize(width: 16, height: 16)
            item.toolTip = url.path
            menu.addItem(item)
        }
        if urls.isEmpty {
            menu.addItem(withTitle: "Henüz belge yok", action: nil, keyEquivalent: "").isEnabled = false
        }
        menu.addItem(.separator())
        let clear = NSMenuItem(title: "Menüyü Temizle", action: urls.isEmpty ? nil : #selector(clearRecent), keyEquivalent: "")
        clear.target = self
        menu.addItem(clear)
    }

    // MARK: Varsayılan PDF uygulaması

    func isDefaultPDFApp() -> Bool {
        guard let app = NSWorkspace.shared.urlForApplication(toOpen: .pdf) else { return false }
        return Bundle(url: app)?.bundleIdentifier == Bundle.main.bundleIdentifier
    }

    func reportDefaultStatus(to tab: Tab, message: String? = nil) {
        let msg = message.map(jsString) ?? "null"
        tab.evaluate("window.PDFSTUDYO_defaultStatus && window.PDFSTUDYO_defaultStatus(\(isDefaultPDFApp()), \(msg))")
    }

    func makeDefaultPDFApp(reportTo tab: Tab) {
        NSWorkspace.shared.setDefaultApplication(at: Bundle.main.bundleURL, toOpen: .pdf) { error in
            DispatchQueue.main.async {
                if let error = error {
                    self.reportDefaultStatus(to: tab, message: "Varsayılan yapılamadı: \(error.localizedDescription)")
                } else {
                    self.reportDefaultStatus(to: tab, message: self.isDefaultPDFApp() ? "PDF'ler artık Koç PDF Pro ile açılacak." : nil)
                }
            }
        }
    }

    // MARK: Yazdırma

    func printPDF(from urlString: String, name: String, in tab: Tab) {
        guard let url = URL(string: urlString) else { return }
        URLSession.shared.dataTask(with: url) { data, _, _ in
            DispatchQueue.main.async {
                guard let data = data, let doc = PDFDocument(data: data),
                      let op = doc.printOperation(for: NSPrintInfo.shared, scalingMode: .pageScaleToFit, autoRotate: true)
                else {
                    let alert = NSAlert()
                    alert.messageText = "Belge yazdırılamadı"
                    alert.beginSheetModal(for: tab.window)
                    return
                }
                op.jobTitle = name
                op.showsPrintPanel = true
                op.showsProgressPanel = true
                op.runModal(for: tab.window, delegate: nil, didRun: nil, contextInfo: nil)
            }
        }.resume()
    }

    // MARK: Menü

    func buildMenu() {
        let main = NSMenu()

        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Koç PDF Pro Hakkında",
                        action: #selector(showAbout), keyEquivalent: "").target = self
        appMenu.addItem(menuItem("Güncellemeleri Denetle…", #selector(checkUpdates), ""))
        appMenu.addItem(.separator())
        appMenu.addItem(menuItem("Ayarlar…", #selector(showSettings), ","))
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Koç PDF Pro'yu Gizle", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        let others = appMenu.addItem(withTitle: "Diğerlerini Gizle",
                                     action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h")
        others.keyEquivalentModifierMask = [.command, .option]
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Koç PDF Pro'dan Çık", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        addSubmenu(appMenu, to: main)

        let file = NSMenu(title: "Dosya")
        file.addItem(menuItem("Yeni Sekme", #selector(newWindowForTab(_:)), "t"))
        file.addItem(menuItem("PDF Aç…", #selector(openDocumentPanel), "o"))
        recentMenu = NSMenu(title: "Son Açılanlar")
        recentMenu.delegate = self
        let recentItem = file.addItem(withTitle: "Son Açılanlar", action: nil, keyEquivalent: "")
        recentItem.submenu = recentMenu
        file.addItem(.separator())
        file.addItem(menuItem("Kaydet", #selector(saveDocument), "s"))
        let saveAs = menuItem("Farklı Kaydet…", #selector(saveDocumentAs), "s")
        saveAs.keyEquivalentModifierMask = [.command, .shift]
        file.addItem(saveAs)
        file.addItem(menuItem("Paylaş…", #selector(shareDocument), ""))
        file.addItem(.separator())
        file.addItem(menuItem("Ana Sayfa", #selector(goHome), "1"))
        file.addItem(menuItem("PDF Okuyucu ve Düzenleyici", #selector(goReader), "2"))
        file.addItem(.separator())
        file.addItem(menuItem("Sekmeyi Kapat", #selector(closeCurrentTab), "w"))
        let closeWindow = file.addItem(withTitle: "Pencereyi Kapat", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        closeWindow.keyEquivalentModifierMask = [.command, .shift]
        addSubmenu(file, to: main)

        let edit = NSMenu(title: "Düzen")
        edit.addItem(withTitle: "Geri Al", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = edit.addItem(withTitle: "Yinele", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        edit.addItem(withTitle: "Kes", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Kopyala", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Yapıştır", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Tümünü Seç", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        addSubmenu(edit, to: main)

        let view = NSMenu(title: "Görünüm")
        themeMenu = NSMenu(title: "Gece / Gündüz Modu")
        themeMenu.delegate = self
        for theme in AppDelegate.themes {
            let item = NSMenuItem(title: theme.title, action: #selector(chooseTheme(_:)), keyEquivalent: "")
            item.target = self
            item.representedObject = theme.value
            themeMenu.addItem(item)
        }
        view.addItem(withTitle: "Gece / Gündüz Modu", action: nil, keyEquivalent: "").submenu = themeMenu
        view.addItem(.separator())
        view.addItem(menuItem("Yeniden Yükle", #selector(reloadPage), "r"))
        view.addItem(.separator())
        view.addItem(menuItem("Arayüzü Büyüt", #selector(zoomIn), "+"))
        view.addItem(menuItem("Arayüzü Küçült", #selector(zoomOut), "-"))
        view.addItem(menuItem("Gerçek Boyut", #selector(zoomReset), "0"))
        view.addItem(.separator())
        let full = view.addItem(withTitle: "Tam Ekran", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        full.keyEquivalentModifierMask = [.command, .control]
        addSubmenu(view, to: main)

        let windowMenu = NSMenu(title: "Pencere")
        windowMenu.addItem(withTitle: "Küçült", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "Yakınlaştır", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        windowMenu.addItem(.separator())
        let next = menuItem("Sonraki Sekme", #selector(selectNextTab), "\t")
        next.keyEquivalentModifierMask = [.control]
        windowMenu.addItem(next)
        let prev = menuItem("Önceki Sekme", #selector(selectPreviousTab), "\t")
        prev.keyEquivalentModifierMask = [.control, .shift]
        windowMenu.addItem(prev)
        addSubmenu(windowMenu, to: main)
        NSApp.windowsMenu = windowMenu

        let help = NSMenu(title: "Yardım")
        help.addItem(menuItem("Klavye Kısayolları", #selector(showShortcuts), "/"))
        help.addItem(menuItem("Sorun Bildir…", #selector(reportProblem), ""))
        addSubmenu(help, to: main)
        NSApp.helpMenu = help

        NSApp.mainMenu = main
    }

    func menuItem(_ title: String, _ action: Selector, _ key: String) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.target = self
        return item
    }

    func addSubmenu(_ menu: NSMenu, to main: NSMenu) {
        let item = NSMenuItem()
        item.submenu = menu
        main.addItem(item)
    }

    @objc func showAbout() {
        let center = NSMutableParagraphStyle()
        center.alignment = .center
        let small: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 11),
                                                    .foregroundColor: NSColor.secondaryLabelColor,
                                                    .paragraphStyle: center]
        let credits = NSMutableAttributedString(string: "Yerel PDF okuma, dönüştürme ve düzenleme\n\n"
                                                + "Açık kaynak, GNU AGPL-3.0 lisansıyla. Kaynak kodu:\n", attributes: small)
        var source = small
        source[.link] = URL(string: "https://github.com/hasankoc1996-eng/koc-pdf-pro")!
        credits.append(NSAttributedString(string: "github.com/hasankoc1996-eng/koc-pdf-pro", attributes: source))
        credits.append(NSAttributedString(string: "\n\nİletişim: Hasan Koç\nGörüş, öneri ve geliştirme fikirleriniz için:\n",
                                          attributes: small))
        var link = small
        link[.link] = URL(string: "mailto:hasankoc1996@icloud.com")!
        credits.append(NSAttributedString(string: "hasankoc1996@icloud.com", attributes: link))
        // Sürüm Info.plist'ten (surum.txt, build.sh yazar): "Sürüm 1.0.0"; parantezli derleme numarası gösterilmez
        NSApp.orderFrontStandardAboutPanel(options: [.credits: credits, .version: ""])
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc func goHome() { activeTab?.evaluate("location.hash = '#/'") }
    @objc func showShortcuts() { activeTab?.evaluate("window.PDFSTUDYO_shortcuts && window.PDFSTUDYO_shortcuts()") }
    @objc func reportProblem() { activeTab?.evaluate("window.PDFSTUDYO_report && window.PDFSTUDYO_report()") }
    @objc func saveDocument() { activeTab?.evaluate("window.PDFSTUDYO_save && window.PDFSTUDYO_save(false)") }
    @objc func saveDocumentAs() { activeTab?.evaluate("window.PDFSTUDYO_save && window.PDFSTUDYO_save(true)") }
    @objc func shareDocument() { activeTab?.evaluate("window.PDFSTUDYO_share && window.PDFSTUDYO_share()") }
    @objc func goReader() { activeTab?.evaluate("location.hash = '#/reader'") }
    @objc func reloadPage() { activeTab?.webView.reload() }
    @objc func checkUpdates() { activeTab?.evaluate("window.PDFSTUDYO_checkUpdates && window.PDFSTUDYO_checkUpdates()") }
    @objc func showSettings() { activeTab?.evaluate("window.PDFSTUDYO_settings && window.PDFSTUDYO_settings()") }
    @objc func zoomIn() { setUIZoom(AppDelegate.uiZoom + 0.1) }
    @objc func zoomOut() { setUIZoom(AppDelegate.uiZoom - 0.1) }
    @objc func zoomReset() { setUIZoom(1.0) }
}

let app = NSApplication.shared
_ = DocumentController()  // ilk oluşturulan, paylaşılan belge denetleyicisi olur
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
