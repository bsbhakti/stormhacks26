import Foundation
import SwiftUI

struct DiscoveredDevice: Identifiable, Hashable {
    let id: UUID
    /// Name from the BLE advertisement payload (`CBAdvertisementDataLocalNameKey`).
    var advertisedName: String
    var rssi: Int
    var lastSeen: Date

    var displayName: String {
        advertisedName.isEmpty ? "Unnamed advertisement" : advertisedName
    }

    var hasAdvertisedName: Bool {
        !advertisedName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

enum TriagePhase: String {
    case searching
    case locating
    case assisting
}

enum AdvertisedName {
    static func normalized(_ name: String) -> String {
        name.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func matches(_ advertisedName: String, target: String) -> Bool {
        let lhs = normalized(advertisedName)
        let rhs = normalized(target)
        guard !lhs.isEmpty, !rhs.isEmpty else { return false }
        return lhs.caseInsensitiveCompare(rhs) == .orderedSame
    }

    static func contains(_ advertisedName: String, query: String) -> Bool {
        let haystack = normalized(advertisedName)
        let needle = normalized(query)
        guard !haystack.isEmpty, !needle.isEmpty else { return false }
        return haystack.range(of: needle, options: [.caseInsensitive, .diacriticInsensitive]) != nil
    }
}

enum ProximityZone: String, CaseIterable {
    case unknown
    case lost
    case far
    case mid
    case near
    case immediate

    init(rssi: Int?) {
        guard let rssi else {
            self = .unknown
            return
        }

        switch rssi {
        case -49...0:
            self = .immediate
        case -64 ... -50:
            self = .near
        case -79 ... -65:
            self = .mid
        default:
            self = .far
        }
    }

    var title: String {
        switch self {
        case .unknown: "Waiting for signal"
        case .lost: "Signal lost"
        case .far: "Far"
        case .mid: "Getting closer"
        case .near: "Near"
        case .immediate: "You are at the patient"
        }
    }

    var instruction: String {
        switch self {
        case .unknown:
            "Walk slowly and keep the phone uncovered. The tag can tell closeness, not direction."
        case .lost:
            "Tag signal dropped. Retrace your last few steps and sweep the phone left and right."
        case .far:
            "Walk in a straight line for several steps. If the signal drops, turn 90 degrees and try again."
        case .mid:
            "The patient tag is nearby. Slow down and sweep the phone in an arc."
        case .near:
            "You are close. Look around people, stretchers, and nearby cover."
        case .immediate:
            "You should be able to see or reach the patient."
        }
    }

    var color: Color {
        switch self {
        case .unknown, .lost: Color.secondary
        case .far: Color(red: 0.35, green: 0.55, blue: 0.95)
        case .mid: Color(red: 0.95, green: 0.72, blue: 0.20)
        case .near: Color(red: 0.98, green: 0.48, blue: 0.18)
        case .immediate: Color(red: 0.22, green: 0.82, blue: 0.45)
        }
    }

    var progress: Double {
        switch self {
        case .unknown, .lost: 0.08
        case .far: 0.28
        case .mid: 0.52
        case .near: 0.76
        case .immediate: 1.0
        }
    }
}

enum SignalTrend: String {
    case warmer
    case colder
    case steady
    case unknown

    var title: String {
        switch self {
        case .warmer: "Warmer"
        case .colder: "Colder"
        case .steady: "Holding"
        case .unknown: "Measuring"
        }
    }

    var systemImage: String {
        switch self {
        case .warmer: "arrow.up.right"
        case .colder: "arrow.down.right"
        case .steady: "arrow.left.and.right"
        case .unknown: "dot.radiowaves.left.and.right"
        }
    }
}

enum BluetoothAvailability: String {
    case unknown
    case poweredOn
    case poweredOff
    case unauthorized
    case unsupported
    case resetting

    var message: String {
        switch self {
        case .unknown:
            "Starting Bluetooth…"
        case .poweredOn:
            "Bluetooth is on"
        case .poweredOff:
            "Turn on Bluetooth in Control Center to scan."
        case .unauthorized:
            "Allow Bluetooth access for Rapid Triage in Settings."
        case .unsupported:
            "This device cannot scan for Bluetooth accessories."
        case .resetting:
            "Bluetooth is resetting. Scanning will resume automatically."
        }
    }
}

enum ProximityMath {
    /// Typical BLE advertisement RSSI at 1 meter. Override if your beacon publishes a calibrated Tx power.
    static let defaultTxPowerAtOneMeter = -59
    static let pathLossExponent = 2.2
    static let staleSignalInterval: TimeInterval = 3.5

    static func estimatedDistanceMeters(rssi: Int, txPower: Int = defaultTxPowerAtOneMeter) -> Double {
        pow(10, Double(txPower - rssi) / (10 * pathLossExponent))
    }

    static func formattedDistance(_ meters: Double) -> String {
        if meters < 1 {
            return String(format: "%.0f cm", meters * 100)
        }
        if meters < 10 {
            return String(format: "%.1f m", meters)
        }
        return String(format: "%.0f m", meters)
    }
}
