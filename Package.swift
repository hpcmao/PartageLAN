// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "PartageLAN",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(name: "PartageLAN", path: "Sources/PartageLAN")
    ]
)
