import SwiftUI
import AppKit
import Network
import UniformTypeIdentifiers
import Darwin

private let portNumber: UInt16 = 7365

struct Entry: Codable, Identifiable, Hashable {
    var name: String
    var isDir: Bool
    var size: Int? = nil
    var id: String { name }
}

private struct Meta: Codable {
    var type: String            // "clip" | "file" | "ping" | "ls" | "lsr" | "get" | "err"
    var name: String? = nil     // file : nom du fichier ; lsr : compte utilisateur distant
    var size: Int? = nil        // file : taille en octets
    var text: String? = nil     // clip : texte ; err : message
    var path: String? = nil     // ls/get : chemin distant ; file : dossier de destination ; lsr : chemin canonique
    var entries: [Entry]? = nil // lsr : contenu du dossier
}

enum ClipMode: String, CaseIterable {
    case both, send, receive, off
}

/// Un Mac PartageLAN détecté sur le réseau local (répond au ping sur le port 7365).
struct ScanHost: Identifiable, Equatable {
    var id: String { ip }
    let ip: String
    let user: String
    let os: String
}

enum Theme: String, CaseIterable, Identifiable {
    case system, clair, sombre, ocean, sepia
    var id: String { rawValue }
    var label: String {
        switch self {
        case .system: return "Système"
        case .clair: return "Clair"
        case .sombre: return "Sombre"
        case .ocean: return "Océan"
        case .sepia: return "Sépia"
        }
    }
    var colorScheme: ColorScheme? {
        switch self {
        case .system: return nil
        case .clair, .sepia: return .light
        case .sombre, .ocean: return .dark
        }
    }
    var accent: Color? {
        switch self {
        case .ocean: return .cyan
        case .sepia: return Color(red: 0.55, green: 0.35, blue: 0.15)
        default: return nil
        }
    }
    var background: Color? {
        switch self {
        case .ocean: return Color(red: 0.07, green: 0.12, blue: 0.18)
        case .sepia: return Color(red: 0.96, green: 0.93, blue: 0.86)
        default: return nil
        }
    }
}

/// Garantit qu'une complétion n'est appelée qu'une seule fois (timeout vs état).
private final class Once {
    private let lock = NSLock()
    private var done = false
    func run(_ f: () -> Void) {
        lock.lock(); defer { lock.unlock() }
        guard !done else { return }
        done = true
        f()
    }
}

// MARK: - Panneau de navigation (local ou distant)

final class PaneModel: ObservableObject {
    @Published var path: String {
        didSet { UserDefaults.standard.set(path, forKey: key) }
    }
    @Published var entries: [Entry] = []
    @Published var selection = Set<String>()
    @Published var errorText: String?
    @Published var loading = false
    /// Chargeur injecté (local = FileManager, distant = réseau). Complétion SUR LE FIL PRINCIPAL.
    var loader: ((String, @escaping (String?, [Entry], String?) -> Void) -> Void)?

    private let key: String

    init(key: String) {
        self.key = key
        path = UserDefaults.standard.string(forKey: key) ?? "~"
    }

    func reload() {
        guard let loader else { return }
        loading = true
        errorText = nil
        loader(path) { [weak self] canonical, list, err in
            guard let self else { return }
            self.loading = false
            if let err {
                self.errorText = err
                return
            }
            if let canonical { self.path = canonical }
            self.entries = list
            self.selection.removeAll()
        }
    }

    func enter(_ name: String) {
        path = (path as NSString).appendingPathComponent(name)
        reload()
    }

    func up() {
        let parent = (path as NSString).deletingLastPathComponent
        path = parent.isEmpty ? "/" : parent
        reload()
    }

    func fullPath(_ name: String) -> String {
        (path as NSString).appendingPathComponent(name)
    }

    func selectedFiles() -> [Entry] {
        entries.filter { selection.contains($0.name) && !$0.isDir }
    }
}

// MARK: - Moteur

final class PartageEngine: ObservableObject {
    @Published var peerIP: String {
        didSet { UserDefaults.standard.set(peerIP, forKey: "peerIP") }
    }
    @Published var clipMode: ClipMode {
        didSet {
            UserDefaults.standard.set(clipMode.rawValue, forKey: "clipMode")
            lastChangeCount = NSPasteboard.general.changeCount // évite d'envoyer une vieille copie au changement de mode
        }
    }
    /// Dossier local où arrivent les fichiers POUSSÉS par l'autre Mac (affiché avec ~).
    @Published var receiveDirPath: String {
        didSet { UserDefaults.standard.set(receiveDirPath, forKey: "receiveDir") }
    }
    @Published var status = "Démarrage…"
    @Published var journal: [String] = []
    @Published var remoteUser: String?
    @Published var remoteOS: String?
    @Published var scanResults: [ScanHost] = []
    @Published var isScanning = false
    @Published var theme: Theme {
        didSet { UserDefaults.standard.set(theme.rawValue, forKey: "theme") }
    }

    let localPane = PaneModel(key: "localPanePath")
    let remotePane = PaneModel(key: "remotePanePath")

    var receiveDirURL: URL { URL(fileURLWithPath: (receiveDirPath as NSString).expandingTildeInPath) }
    let localName = NSUserName()
    let localIP: String

    private var listener: NWListener?
    private var pollTimer: Timer?
    private var lastChangeCount = NSPasteboard.general.changeCount
    private var lastRemoteText: String?
    private var sendFailureNoted = false

    init() {
        let locals = Self.localIPv4()
        localIP = locals.first(where: { $0.hasPrefix("10.0.0.") }) ?? (locals.first ?? "?")
        let guess: String
        if locals.contains("10.0.0.4") { guess = "10.0.0.5" }
        else if locals.contains("10.0.0.5") { guess = "10.0.0.4" }
        else { guess = "10.0.0.4" }
        peerIP = UserDefaults.standard.string(forKey: "peerIP") ?? guess
        clipMode = ClipMode(rawValue: UserDefaults.standard.string(forKey: "clipMode") ?? "") ?? .both
        theme = Theme(rawValue: UserDefaults.standard.string(forKey: "theme") ?? "") ?? .system
        receiveDirPath = UserDefaults.standard.string(forKey: "receiveDir") ?? "~/Downloads"
        localPane.loader = { [weak self] p, done in self?.listLocal(p, completion: done) }
        remotePane.loader = { [weak self] p, done in self?.listRemote(p, completion: done) }
        startListener()
        startPolling()
    }

    // MARK: Réception (serveur)

    private func startListener() {
        do {
            let l = try NWListener(using: .tcp, on: NWEndpoint.Port(rawValue: portNumber)!)
            l.newConnectionHandler = { [weak self] conn in self?.handle(conn) }
            l.stateUpdateHandler = { [weak self] st in
                DispatchQueue.main.async {
                    guard let self else { return }
                    switch st {
                    case .ready:
                        self.status = "Ici : \(self.localName) (\(self.localIP)) — à l'écoute sur le port \(portNumber)"
                    case .failed(let e):
                        self.status = "Écoute impossible : \(e.localizedDescription) (l'app est-elle déjà ouverte ?)"
                    default: break
                    }
                }
            }
            l.start(queue: .global())
            listener = l
        } catch {
            status = "Écoute impossible : \(error.localizedDescription)"
        }
    }

    private func handle(_ conn: NWConnection) {
        conn.start(queue: .global())
        readFrame(conn) { [weak self] meta in
            guard let self, let meta else { conn.cancel(); return }
            switch meta.type {
            case "clip":
                if let text = meta.text { self.applyRemoteClipboard(text) }
                conn.cancel()
            case "file":
                if let name = meta.name, let size = meta.size, size >= 0 {
                    var dir = self.receiveDirURL
                    if let want = meta.path, !want.isEmpty {
                        if let ok = Self.validDir(want) {
                            dir = ok
                        } else {
                            self.log("Dossier demandé invalide (\(want)) → \(dir.path)")
                        }
                    }
                    self.receiveBody(conn, name: name, size: size, into: dir, verb: "Reçu")
                } else { conn.cancel() }
            case "ping":
                self.log("Ping reçu de l'autre machine ✓")
                self.writeFrame(conn, Meta(type: "pong", name: NSUserName(), text: Self.osDescription),
                                final: true) { _ in conn.cancel() }
            case "ls":
                self.handleList(conn, path: meta.path)
            case "get":
                self.handleGet(conn, path: meta.path)
            default:
                conn.cancel()
            }
        }
    }

    /// Lit une trame [UInt32 longueur][JSON Meta].
    private func readFrame(_ conn: NWConnection, completion: @escaping (Meta?) -> Void) {
        readExactly(conn, 4) { [weak self] head in
            guard let self, let head else { completion(nil); return }
            let len = head.withUnsafeBytes { Int(UInt32(bigEndian: $0.load(as: UInt32.self))) }
            guard len > 0, len < 50_000_000 else { completion(nil); return }
            self.readExactly(conn, len) { data in
                guard let data, let meta = try? JSONDecoder().decode(Meta.self, from: data) else {
                    completion(nil); return
                }
                completion(meta)
            }
        }
    }

    private func readExactly(_ conn: NWConnection, _ n: Int, completion: @escaping (Data?) -> Void) {
        conn.receive(minimumIncompleteLength: n, maximumLength: n) { data, _, _, _ in
            if let data, data.count == n { completion(data) } else { completion(nil) }
        }
    }

    private func writeFrame(_ conn: NWConnection, _ meta: Meta, final: Bool, completion: @escaping (Bool) -> Void) {
        guard let data = try? JSONEncoder().encode(meta) else { completion(false); return }
        var frame = withUnsafeBytes(of: UInt32(data.count).bigEndian) { Data($0) }
        frame.append(data)
        if final {
            conn.send(content: frame, contentContext: .finalMessage, isComplete: true,
                      completion: .contentProcessed { err in completion(err == nil) })
        } else {
            conn.send(content: frame, completion: .contentProcessed { err in completion(err == nil) })
        }
    }

    private func handleList(_ conn: NWConnection, path: String?) {
        let p = Self.expand(path)
        var isDir: ObjCBool = false
        guard FileManager.default.fileExists(atPath: p, isDirectory: &isDir), isDir.boolValue else {
            writeFrame(conn, Meta(type: "err", text: "Dossier introuvable : \(p)"), final: true) { _ in conn.cancel() }
            return
        }
        let entries = Self.listDirectory(p)
        writeFrame(conn, Meta(type: "lsr", name: NSUserName(), text: Self.osDescription, path: p, entries: entries),
                   final: true) { _ in
            conn.cancel()
        }
    }

    private func handleGet(_ conn: NWConnection, path: String?) {
        let p = Self.expand(path)
        var isDir: ObjCBool = false
        guard FileManager.default.fileExists(atPath: p, isDirectory: &isDir), !isDir.boolValue else {
            writeFrame(conn, Meta(type: "err", text: "Fichier introuvable : \(p)"), final: true) { _ in conn.cancel() }
            return
        }
        let url = URL(fileURLWithPath: p)
        let size = ((try? FileManager.default.attributesOfItem(atPath: p)[.size]) as? NSNumber)?.intValue ?? 0
        writeFrame(conn, Meta(type: "file", name: url.lastPathComponent, size: size), final: false) { [weak self] ok in
            guard ok, let self else { conn.cancel(); return }
            self.sendFileBody(conn, url: url) { done in
                conn.cancel()
                self.log(done ? "Servi à l'autre Mac : \(url.lastPathComponent) (\(Self.human(size)))"
                              : "Envoi interrompu : \(url.lastPathComponent)")
            }
        }
    }

    /// Lit `size` octets sur `conn` et les écrit dans `dir` sous `name` (dédoublonné).
    private func receiveBody(_ conn: NWConnection, name: String, size: Int, into dir: URL,
                             verb: String, done: (() -> Void)? = nil) {
        let safeName = (name as NSString).lastPathComponent
        let url = uniqueURL(in: dir, for: safeName.isEmpty ? "fichier_recu" : safeName)
        FileManager.default.createFile(atPath: url.path, contents: nil)
        guard let fh = try? FileHandle(forWritingTo: url) else {
            conn.cancel()
            log("Impossible d'écrire dans \(dir.path)")
            DispatchQueue.main.async { done?() }
            return
        }
        var remaining = size
        func step() {
            if remaining <= 0 {
                try? fh.close()
                conn.cancel()
                self.log("\(verb) : \(url.lastPathComponent) (\(Self.human(size))) → \(dir.path)")
                DispatchQueue.main.async { done?() }
                return
            }
            conn.receive(minimumIncompleteLength: 1, maximumLength: min(remaining, 1 << 16)) { data, _, complete, err in
                if let data, !data.isEmpty {
                    try? fh.write(contentsOf: data)
                    remaining -= data.count
                }
                if err != nil || (complete && remaining > 0) {
                    try? fh.close()
                    conn.cancel()
                    self.log("Réception interrompue : \(safeName)")
                    DispatchQueue.main.async { done?() }
                    return
                }
                step()
            }
        }
        step()
    }

    private func applyRemoteClipboard(_ text: String) {
        DispatchQueue.main.async {
            guard self.clipMode == .both || self.clipMode == .receive else {
                self.log("Presse-papier reçu ignoré (réception coupée)")
                return
            }
            self.lastRemoteText = text
            let pb = NSPasteboard.general
            pb.clearContents()
            pb.setString(text, forType: .string)
            self.lastChangeCount = pb.changeCount
            self.log("Presse-papier reçu (\(text.count) caractères)")
        }
    }

    // MARK: Presse-papier sortant

    private func startPolling() {
        pollTimer = Timer.scheduledTimer(withTimeInterval: 0.6, repeats: true) { [weak self] _ in
            self?.pollClipboard()
        }
    }

    private func pollClipboard() {
        guard clipMode == .both || clipMode == .send else { return }
        let pb = NSPasteboard.general
        guard pb.changeCount != lastChangeCount else { return }
        lastChangeCount = pb.changeCount
        guard let text = pb.string(forType: .string), !text.isEmpty, text != lastRemoteText else { return }
        send(meta: Meta(type: "clip", text: text)) { [weak self] ok in
            guard let self else { return }
            if ok {
                self.sendFailureNoted = false
                self.log("Presse-papier envoyé (\(text.count) caractères)")
            } else if !self.sendFailureNoted {
                self.sendFailureNoted = true
                self.log("Autre Mac injoignable — presse-papier non transmis (app ouverte là-bas ?)")
            }
        }
    }

    // MARK: Envoi (client)

    func ping() {
        request(Meta(type: "ping")) { [weak self] resp, conn in
            conn?.cancel()
            DispatchQueue.main.async {
                guard let self else { return }
                if let resp, resp.type == "pong" {
                    if let u = resp.name { self.remoteUser = u }
                    if let os = resp.text { self.remoteOS = os }
                    self.log("Autre machine joignable ✓ — \(resp.name ?? "?") · \(resp.text ?? "OS inconnu")")
                } else {
                    self.log("Autre machine injoignable ✗ — vérifier que l'app y est ouverte")
                }
            }
        }
    }

    // MARK: Scan réseau

    /// Sonde tout le sous-réseau /24 local pour trouver les autres Macs faisant tourner PartageLAN.
    /// Remplit `scanResults` au fur et à mesure ; sélectionne l'IP automatiquement si un seul Mac répond.
    func scanNetwork() {
        guard !isScanning else { return }
        guard let prefix = Self.subnetPrefix(localIP) else {
            log("Scan impossible : IP locale inexploitable (\(localIP))")
            return
        }
        DispatchQueue.main.async {
            self.scanResults = []
            self.isScanning = true
        }
        log("Scan du réseau \(prefix)x…")
        // Toute la boucle part en fond : `gate.wait()` bloque, ne doit pas figer le fil principal.
        DispatchQueue.global().async {
            let group = DispatchGroup()
            let gate = DispatchSemaphore(value: 32) // borne les connexions simultanées
            let queue = DispatchQueue(label: "fr.vemao.partagelan.scan", attributes: .concurrent)
            for i in 1...254 {
                let ip = "\(prefix)\(i)"
                if ip == self.localIP { continue }
                gate.wait()
                group.enter()
                queue.async {
                    self.pingHost(ip) { host in
                        if let host {
                            DispatchQueue.main.async {
                                if !self.scanResults.contains(where: { $0.ip == host.ip }) {
                                    self.scanResults.append(host)
                                    // Tri par dernier octet pour un affichage stable.
                                    self.scanResults.sort {
                                        (Int($0.ip.split(separator: ".").last ?? "0") ?? 0)
                                            < (Int($1.ip.split(separator: ".").last ?? "0") ?? 0)
                                    }
                                }
                            }
                            self.log("Trouvé : \(host.user) · \(host.ip) · \(host.os)")
                        }
                        gate.signal()
                        group.leave()
                    }
                }
            }
            group.notify(queue: .main) {
                self.isScanning = false
                let n = self.scanResults.count
                self.log("Scan terminé — \(n) Mac PartageLAN trouvé\(n > 1 ? "s" : "")")
                if n == 1 { self.peerIP = self.scanResults[0].ip }
            }
        }
    }

    /// Ping un host arbitraire sur le port PartageLAN. Complétion = ScanHost si pong, nil sinon.
    /// Indépendant de `peerIP`/`request` (qui visent le pair courant) — réservé au scan.
    private func pingHost(_ ip: String, completion: @escaping (ScanHost?) -> Void) {
        guard let port = NWEndpoint.Port(rawValue: portNumber) else { completion(nil); return }
        let conn = NWConnection(host: NWEndpoint.Host(ip), port: port, using: .tcp)
        let once = Once()
        let finish: (ScanHost?) -> Void = { host in
            once.run { conn.cancel(); completion(host) }
        }
        // Timeout court : jusqu'à 253 hôtes à sonder, on ne peut pas attendre longtemps par hôte.
        DispatchQueue.global().asyncAfter(deadline: .now() + 1.0) { finish(nil) }
        conn.stateUpdateHandler = { [weak self] st in
            switch st {
            case .ready:
                guard let self else { finish(nil); return }
                self.writeFrame(conn, Meta(type: "ping"), final: false) { ok in
                    guard ok else { finish(nil); return }
                    self.readFrame(conn) { resp in
                        guard let resp, resp.type == "pong" else { finish(nil); return }
                        finish(ScanHost(ip: ip, user: resp.name ?? "?", os: resp.text ?? "OS inconnu"))
                    }
                }
            case .failed, .waiting:
                finish(nil)
            default:
                break
            }
        }
        conn.start(queue: .global())
    }

    /// Extrait le préfixe /24 d'une IPv4 ("10.0.0.42" → "10.0.0."), ou nil si non exploitable.
    static func subnetPrefix(_ ip: String) -> String? {
        let parts = ip.split(separator: ".")
        guard parts.count == 4, parts.allSatisfy({ Int($0) != nil }) else { return nil }
        return "\(parts[0]).\(parts[1]).\(parts[2])."
    }

    /// Envoie des fichiers locaux vers `destDir` sur l'autre Mac (nil = son dossier de réception).
    func sendFiles(_ urls: [URL], destDir: String?, completion: (() -> Void)? = nil) {
        var pending = urls.count
        let oneDone = {
            DispatchQueue.main.async {
                pending -= 1
                if pending <= 0 { completion?() }
            }
        }
        if urls.isEmpty { DispatchQueue.main.async { completion?() }; return }
        for url in urls {
            var isDir: ObjCBool = false
            FileManager.default.fileExists(atPath: url.path, isDirectory: &isDir)
            if isDir.boolValue {
                log("Dossier ignoré : \(url.lastPathComponent) (compressez-le en .zip d'abord)")
                oneDone()
                continue
            }
            let size = ((try? FileManager.default.attributesOfItem(atPath: url.path)[.size]) as? NSNumber)?.intValue ?? 0
            log("Envoi : \(url.lastPathComponent) (\(Self.human(size)))…")
            send(meta: Meta(type: "file", name: url.lastPathComponent, size: size, path: destDir), payload: url) { [weak self] ok in
                self?.log(ok ? "Envoyé : \(url.lastPathComponent) ✓" : "ÉCHEC d'envoi : \(url.lastPathComponent)")
                oneDone()
            }
        }
    }

    /// Récupère des fichiers DEPUIS l'autre Mac vers le dossier local `dir`.
    func fetchRemoteFiles(_ remotePaths: [String], to dir: URL, completion: (() -> Void)? = nil) {
        var pending = remotePaths.count
        let oneDone = {
            DispatchQueue.main.async {
                pending -= 1
                if pending <= 0 { completion?() }
            }
        }
        if remotePaths.isEmpty { DispatchQueue.main.async { completion?() }; return }
        for remotePath in remotePaths {
            let display = (remotePath as NSString).lastPathComponent
            log("Récupération : \(display)…")
            request(Meta(type: "get", path: remotePath)) { [weak self] resp, conn in
                guard let self else { conn?.cancel(); oneDone(); return }
                guard let resp, let conn else {
                    self.log("Autre Mac injoignable ✗")
                    oneDone()
                    return
                }
                guard resp.type == "file", let name = resp.name, let size = resp.size else {
                    self.log("Erreur distante : \(resp.text ?? "réponse inattendue")")
                    conn.cancel()
                    oneDone()
                    return
                }
                self.receiveBody(conn, name: name, size: size, into: dir, verb: "Récupéré", done: oneDone)
            }
        }
    }

    /// Liste un dossier LOCAL. Complétion sur le fil principal.
    func listLocal(_ path: String, completion: @escaping (String?, [Entry], String?) -> Void) {
        DispatchQueue.global().async {
            let p = Self.expand(path)
            var isDir: ObjCBool = false
            guard FileManager.default.fileExists(atPath: p, isDirectory: &isDir), isDir.boolValue else {
                DispatchQueue.main.async { completion(nil, [], "Dossier introuvable : \(p)") }
                return
            }
            let entries = Self.listDirectory(p)
            DispatchQueue.main.async { completion(p, entries, nil) }
        }
    }

    /// Liste un dossier de l'AUTRE Mac. Complétion sur le fil principal.
    func listRemote(_ path: String, completion: @escaping (String?, [Entry], String?) -> Void) {
        request(Meta(type: "ls", path: path)) { [weak self] resp, conn in
            conn?.cancel()
            DispatchQueue.main.async {
                guard let resp else {
                    completion(nil, [], "Autre Mac injoignable ✗ (app ouverte là-bas ?)")
                    return
                }
                if resp.type == "lsr" {
                    if let u = resp.name { self?.remoteUser = u }
                    if let os = resp.text { self?.remoteOS = os }
                    completion(resp.path, resp.entries ?? [], nil)
                } else {
                    completion(nil, [], resp.text ?? "Erreur inconnue")
                }
            }
        }
    }

    func chooseReceiveDir() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.directoryURL = receiveDirURL
        panel.prompt = "Choisir"
        panel.begin { [weak self] resp in
            guard resp == .OK, let url = panel.urls.first else { return }
            DispatchQueue.main.async {
                self?.receiveDirPath = (url.path as NSString).abbreviatingWithTildeInPath
            }
        }
    }

    /// Envoie une trame et rend la connexion + la première trame de réponse (le demandeur garde la main).
    private func request(_ meta: Meta, completion: @escaping (Meta?, NWConnection?) -> Void) {
        guard let port = NWEndpoint.Port(rawValue: portNumber) else { completion(nil, nil); return }
        let host = NWEndpoint.Host(peerIP.trimmingCharacters(in: .whitespaces))
        let conn = NWConnection(host: host, port: port, using: .tcp)
        let once = Once()
        let fail = { once.run { conn.cancel(); completion(nil, nil) } }
        DispatchQueue.global().asyncAfter(deadline: .now() + 15) { fail() }
        conn.stateUpdateHandler = { [weak self] st in
            switch st {
            case .ready:
                guard let self else { fail(); return }
                self.writeFrame(conn, meta, final: false) { ok in
                    guard ok else { fail(); return }
                    self.readFrame(conn) { resp in
                        guard let resp else { fail(); return }
                        once.run { completion(resp, conn) }
                    }
                }
            case .failed, .waiting:
                fail()
            default:
                break
            }
        }
        conn.start(queue: .global())
    }

    private func send(meta: Meta, payload: URL? = nil, completion: @escaping (Bool) -> Void) {
        guard let port = NWEndpoint.Port(rawValue: portNumber) else { completion(false); return }
        let host = NWEndpoint.Host(peerIP.trimmingCharacters(in: .whitespaces))
        let conn = NWConnection(host: host, port: port, using: .tcp)
        let once = Once()
        let finish: (Bool) -> Void = { ok in
            once.run {
                conn.cancel()
                completion(ok)
            }
        }
        // Garde-fou (pair éteint, IP erronée…) — large pour laisser passer les gros fichiers.
        DispatchQueue.global().asyncAfter(deadline: .now() + (payload == nil ? 5 : 600)) { finish(false) }
        conn.stateUpdateHandler = { [weak self] st in
            switch st {
            case .ready:
                guard let self else { finish(false); return }
                self.writeFrame(conn, meta, final: false) { ok in
                    guard ok else { finish(false); return }
                    if let payload {
                        self.sendFileBody(conn, url: payload, finish: finish)
                    } else {
                        conn.send(content: nil, contentContext: .finalMessage, isComplete: true,
                                  completion: .contentProcessed { _ in finish(true) })
                    }
                }
            case .failed, .waiting:
                finish(false)
            default:
                break
            }
        }
        conn.start(queue: .global())
    }

    private func sendFileBody(_ conn: NWConnection, url: URL, finish: @escaping (Bool) -> Void) {
        guard let fh = try? FileHandle(forReadingFrom: url) else { finish(false); return }
        func step() {
            let data = try? fh.read(upToCount: 1 << 16)
            if let data, !data.isEmpty {
                conn.send(content: data, completion: .contentProcessed { err in
                    if err != nil { try? fh.close(); finish(false) } else { step() }
                })
            } else {
                try? fh.close()
                conn.send(content: nil, contentContext: .finalMessage, isComplete: true,
                          completion: .contentProcessed { _ in finish(true) })
            }
        }
        step()
    }

    // MARK: Utilitaires

    static func expand(_ path: String?) -> String {
        let raw = (path?.isEmpty == false) ? path! : "~"
        return (raw as NSString).expandingTildeInPath
    }

    static func validDir(_ path: String?) -> URL? {
        guard let path, !path.trimmingCharacters(in: .whitespaces).isEmpty else { return nil }
        let p = (path as NSString).expandingTildeInPath
        var isDir: ObjCBool = false
        guard FileManager.default.fileExists(atPath: p, isDirectory: &isDir), isDir.boolValue,
              FileManager.default.isWritableFile(atPath: p) else { return nil }
        return URL(fileURLWithPath: p)
    }

    static func listDirectory(_ p: String) -> [Entry] {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: p)) ?? []
        var entries: [Entry] = []
        for n in names where !n.hasPrefix(".") {
            var d: ObjCBool = false
            let full = (p as NSString).appendingPathComponent(n)
            FileManager.default.fileExists(atPath: full, isDirectory: &d)
            let size = d.boolValue ? nil
                : ((try? FileManager.default.attributesOfItem(atPath: full)[.size]) as? NSNumber)?.intValue
            entries.append(Entry(name: n, isDir: d.boolValue, size: size))
        }
        entries.sort { ($0.isDir ? 0 : 1, $0.name.lowercased()) < ($1.isDir ? 0 : 1, $1.name.lowercased()) }
        return entries
    }

    private func uniqueURL(in dir: URL, for name: String) -> URL {
        var url = dir.appendingPathComponent(name)
        let base = (name as NSString).deletingPathExtension
        let ext = (name as NSString).pathExtension
        var i = 2
        while FileManager.default.fileExists(atPath: url.path) {
            let candidate = ext.isEmpty ? "\(base) \(i)" : "\(base) \(i).\(ext)"
            url = dir.appendingPathComponent(candidate)
            i += 1
        }
        return url
    }

    private func log(_ s: String) {
        DispatchQueue.main.async {
            let df = DateFormatter()
            df.dateFormat = "HH:mm:ss"
            self.journal.append("\(df.string(from: Date()))  \(s)")
            if self.journal.count > 100 { self.journal.removeFirst(self.journal.count - 100) }
        }
    }

    static func human(_ bytes: Int) -> String {
        ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file)
    }

    static var osDescription: String {
        let v = ProcessInfo.processInfo.operatingSystemVersion
        return "macOS \(v.majorVersion).\(v.minorVersion)"
    }

    static func localIPv4() -> [String] {
        var addrs: [String] = []
        var ifaddr: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&ifaddr) == 0, let first = ifaddr else { return [] }
        defer { freeifaddrs(ifaddr) }
        for ptr in sequence(first: first, next: { $0.pointee.ifa_next }) {
            let ifa = ptr.pointee
            guard let sa = ifa.ifa_addr, sa.pointee.sa_family == UInt8(AF_INET) else { continue }
            var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            if getnameinfo(sa, socklen_t(sa.pointee.sa_len), &host, socklen_t(host.count), nil, 0, NI_NUMERICHOST) == 0 {
                addrs.append(String(cString: host))
            }
        }
        return addrs
    }
}

// MARK: - Vue d'un panneau

struct PaneView: View {
    let title: String
    let subtitle: String
    @ObservedObject var model: PaneModel
    /// Double-clic sur un fichier (les dossiers s'ouvrent toujours).
    var onFileDoubleClick: ((Entry) -> Void)? = nil
    /// Si présent : accepte le dépôt de fichiers (URLs) sur le panneau.
    var onDropURLs: (([URL]) -> Void)? = nil
    /// Panneau distant : champ IP + bouton Tester dans l'en-tête.
    var peerIP: Binding<String>? = nil
    var onTest: (() -> Void)? = nil
    /// Panneau distant : scan réseau (bouton + menu des Macs détectés).
    var scanResults: [ScanHost] = []
    var isScanning: Bool = false
    var onScan: (() -> Void)? = nil
    var onSelectHost: ((String) -> Void)? = nil

    @State private var dropTargeted = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 1) {
                    Text(title)
                        .font(.headline)
                        .textSelection(.enabled)
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
                Spacer()
                if let peerIP, let onTest {
                    TextField("10.0.0.x", text: peerIP)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 100)
                        .onSubmit { onTest(); model.reload() }
                        .help("Adresse IP de la machine distante (l'app PartageLAN doit y être ouverte)")
                    Button("Tester") { onTest() }
                        .help("Vérifier que la machine distante répond, et récupérer son compte et son système")
                    if let onScan, let onSelectHost {
                        Menu {
                            if isScanning {
                                Text("Scan en cours…")
                            } else if scanResults.isEmpty {
                                Text("Aucun Mac trouvé")
                            } else {
                                ForEach(scanResults) { host in
                                    Button {
                                        onSelectHost(host.ip)
                                        onTest()
                                        model.reload()
                                    } label: {
                                        Text("\(host.ip == peerIP.wrappedValue ? "✓ " : "")\(host.user) · \(host.ip) · \(host.os)")
                                    }
                                }
                            }
                            Divider()
                            Button("Relancer le scan") { onScan() }
                                .disabled(isScanning)
                        } label: {
                            Label(isScanning ? "Scan…" : "Scanner",
                                  systemImage: "antenna.radiowaves.left.and.right")
                        } primaryAction: {
                            onScan()
                        }
                        .frame(width: 96)
                        .help("Chercher les autres Macs PartageLAN sur le réseau local (clic) ; menu = choisir un Mac détecté")
                    }
                }
            }
            HStack(spacing: 4) {
                Button { model.up() } label: { Image(systemName: "arrow.up") }
                    .help("Remonter au dossier parent")
                TextField("Chemin", text: $model.path)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size: 11))
                    .onSubmit { model.reload() }
                    .help("Chemin du dossier affiché — tapez un chemin puis Entrée pour s'y rendre")
                Button { model.reload() } label: { Image(systemName: "arrow.clockwise") }
                    .help("Rafraîchir le contenu du dossier")
            }
            list
                .overlay {
                    if model.loading { ProgressView().controlSize(.small) }
                }
            HStack {
                if let err = model.errorText {
                    Text(err)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .lineLimit(1)
                        .textSelection(.enabled)
                        .help(err)
                } else {
                    Text("\(model.entries.count) éléments — \(model.selection.count) sélectionné(s)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
                Spacer()
            }
        }
    }

    @ViewBuilder
    private var list: some View {
        let base = List(selection: $model.selection) {
            ForEach(model.entries) { e in
                HStack {
                    Image(systemName: e.isDir ? "folder.fill" : "doc")
                        .foregroundStyle(e.isDir ? Color.accentColor : Color.secondary)
                    Text(e.name)
                        .lineLimit(1)
                        .truncationMode(.middle)
                    Spacer()
                    if let s = e.size {
                        Text(PartageEngine.human(s))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .contentShape(Rectangle())
                .onTapGesture(count: 2) {
                    if e.isDir {
                        model.enter(e.name)
                    } else {
                        onFileDoubleClick?(e)
                    }
                }
                .help(e.isDir ? "Double-clic : ouvrir le dossier « \(e.name) »"
                              : "Clic : sélectionner (⌘-clic : sélection multiple)"
                                + (onFileDoubleClick != nil ? " — double-clic : récupérer le fichier" : ""))
                .tag(e.name)
            }
        }
        .listStyle(.bordered)
        .frame(minHeight: 200, maxHeight: .infinity)

        if let onDropURLs {
            base
                .overlay {
                    if dropTargeted {
                        RoundedRectangle(cornerRadius: 6)
                            .strokeBorder(Color.accentColor, lineWidth: 2)
                    }
                }
                .onDrop(of: [.fileURL], isTargeted: $dropTargeted) { providers in
                    for p in providers {
                        p.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, _ in
                            var url: URL?
                            if let data = item as? Data { url = URL(dataRepresentation: data, relativeTo: nil) }
                            else if let u = item as? URL { url = u }
                            if let url {
                                DispatchQueue.main.async { onDropURLs([url]) }
                            }
                        }
                    }
                    return true
                }
        } else {
            base
        }
    }
}

// MARK: - Fenêtre principale

struct ContentView: View {
    @EnvironmentObject var engine: PartageEngine

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Picker("Presse-papier :", selection: $engine.clipMode) {
                    Text("Les 2 sens").tag(ClipMode.both)
                    Text("Envoi seul").tag(ClipMode.send)
                    Text("Réception seule").tag(ClipMode.receive)
                    Text("Coupé").tag(ClipMode.off)
                }
                .pickerStyle(.menu)
                .fixedSize()
                .help("Sens de partage du presse-papier (texte) : les deux sens, envoi seul, réception seule, ou coupé")
                Spacer()
                Picker("Thème :", selection: $engine.theme) {
                    ForEach(Theme.allCases) { t in
                        Text(t.label).tag(t)
                    }
                }
                .pickerStyle(.menu)
                .fixedSize()
                .help("Apparence de la fenêtre : Système, Clair, Sombre, Océan ou Sépia")
            }

            HStack(alignment: .top, spacing: 8) {
                PaneView(
                    title: "Machine locale — \(engine.localName)",
                    subtitle: "\(engine.localIP) · \(PartageEngine.osDescription)",
                    model: engine.localPane
                )

                VStack(spacing: 10) {
                    Spacer().frame(height: 70)
                    Button {
                        sendSelection()
                    } label: {
                        Image(systemName: "arrow.right")
                    }
                    .help("Copier la sélection locale vers le dossier distant affiché")
                    .disabled(engine.localPane.selectedFiles().isEmpty)
                    Button {
                        fetchSelection()
                    } label: {
                        Image(systemName: "arrow.left")
                    }
                    .help("Copier la sélection distante vers le dossier local affiché")
                    .disabled(engine.remotePane.selectedFiles().isEmpty)
                }

                PaneView(
                    title: "Machine distante — \(engine.remoteUser ?? "?")",
                    subtitle: "\(engine.peerIP) · \(engine.remoteOS ?? "système inconnu — cliquer « Tester »")",
                    model: engine.remotePane,
                    onFileDoubleClick: { e in
                        engine.fetchRemoteFiles([engine.remotePane.fullPath(e.name)],
                                                to: localPaneURL()) {
                            engine.localPane.reload()
                        }
                    },
                    onDropURLs: { urls in
                        engine.sendFiles(urls, destDir: engine.remotePane.path) {
                            engine.remotePane.reload()
                        }
                    },
                    peerIP: $engine.peerIP,
                    onTest: { engine.ping() },
                    scanResults: engine.scanResults,
                    isScanning: engine.isScanning,
                    onScan: { engine.scanNetwork() },
                    onSelectHost: { engine.peerIP = $0 }
                )
            }
            .layoutPriority(1)

            HStack(spacing: 6) {
                Text("Fichiers poussés par l'autre machine reçus dans :")
                    .font(.caption)
                Text(engine.receiveDirPath)
                    .font(.caption)
                    .fontWeight(.medium)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .textSelection(.enabled)
                    .help("Dossier local où arrivent les fichiers envoyés spontanément par l'autre machine")
                Button("Choisir…") { engine.chooseReceiveDir() }
                    .controlSize(.small)
                    .help("Changer le dossier de réception")
                Button("Ouvrir") { NSWorkspace.shared.open(engine.receiveDirURL) }
                    .controlSize(.small)
                    .help("Ouvrir le dossier de réception dans le Finder")
                Spacer()
                Text(engine.status)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                    .help(engine.status)
            }

            HStack(alignment: .top, spacing: 6) {
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 2) {
                            ForEach(Array(engine.journal.enumerated()), id: \.offset) { i, line in
                                Text(line)
                                    .font(.system(size: 11, design: .monospaced))
                                    .textSelection(.enabled)
                                    .id(i)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .onChange(of: engine.journal.count) { n in
                        if n > 0 { proxy.scrollTo(n - 1, anchor: .bottom) }
                    }
                }
                .frame(height: 90)
                Button {
                    let pb = NSPasteboard.general
                    pb.clearContents()
                    pb.setString(engine.journal.joined(separator: "\n"), forType: .string)
                } label: {
                    Image(systemName: "doc.on.doc")
                }
                .help("Copier tout le journal dans le presse-papier")
            }
        }
        .padding(14)
        .frame(minWidth: 780, minHeight: 540)
        .background(engine.theme.background ?? Color.clear)
        .tint(engine.theme.accent)
        .preferredColorScheme(engine.theme.colorScheme)
        .onAppear {
            engine.ping()
            engine.localPane.reload()
            engine.remotePane.reload()
        }
    }

    private func localPaneURL() -> URL {
        URL(fileURLWithPath: PartageEngine.expand(engine.localPane.path))
    }

    private func sendSelection() {
        let urls = engine.localPane.selectedFiles().map {
            URL(fileURLWithPath: engine.localPane.fullPath($0.name))
        }
        engine.sendFiles(urls, destDir: engine.remotePane.path) {
            engine.remotePane.reload()
        }
    }

    private func fetchSelection() {
        let paths = engine.remotePane.selectedFiles().map { engine.remotePane.fullPath($0.name) }
        engine.fetchRemoteFiles(paths, to: localPaneURL()) {
            engine.localPane.reload()
        }
    }
}

@main
struct PartageLANApp: App {
    @StateObject private var engine = PartageEngine()

    var body: some Scene {
        WindowGroup("Partage LAN") {
            ContentView()
                .environmentObject(engine)
        }

        // Icône + menu rapide dans la barre de menus macOS (haut de l'écran).
        MenuBarExtra("Partage LAN", systemImage: "arrow.left.arrow.right") {
            MenuBarContent(engine: engine)
        }
    }
}

/// Contenu du menu de la barre de menus : statut du pair + actions rapides.
struct MenuBarContent: View {
    @ObservedObject var engine: PartageEngine

    var body: some View {
        Text("Ici : \(engine.localName) · \(engine.localIP)")
        if let user = engine.remoteUser {
            Text("Pair joignable : \(user) · \(engine.peerIP)")
        } else {
            Text("Pair : \(engine.peerIP) (non testé)")
        }
        Divider()
        Button("Ouvrir la fenêtre") {
            NSApp.activate(ignoringOtherApps: true)
            for window in NSApp.windows where window.canBecomeMain {
                window.makeKeyAndOrderFront(nil)
            }
        }
        Button("Tester le pair") { engine.ping() }
        Button(engine.isScanning ? "Scan en cours…" : "Scanner le réseau") {
            engine.scanNetwork()
        }
        .disabled(engine.isScanning)
        Divider()
        Button("Quitter PartageLAN") { NSApplication.shared.terminate(nil) }
    }
}
