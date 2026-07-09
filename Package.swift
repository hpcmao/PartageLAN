// swift-tools-version:6.0
import PackageDescription

let package = Package(
    name: "PartageLAN",
    platforms: [.macOS(.v15)],
    targets: [
        .executableTarget(
            name: "PartageLAN",
            path: "Sources/PartageLAN",
            // Reste en mode langage Swift 5 : évite la concurrence stricte Swift 6
            // (le code réseau repose sur des closures/DispatchQueue capturant self).
            swiftSettings: [.swiftLanguageMode(.v5)]
        )
    ]
)
