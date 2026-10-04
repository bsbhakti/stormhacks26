import CoreBluetooth
import Foundation
import Observation
import UIKit

@MainActor
@Observable
final class BLEProximityManager: NSObject {
    var availability: BluetoothAvailability = .unknown
    var isScanning = false
    var nameFilter = ""
    var discoveredDevices: [DiscoveredDevice] = []
    var trackedDevice: DiscoveredDevice?
    var rawRSSI: Int?
    var smoothedRSSI: Double?
    var zone: ProximityZone = .unknown
    var trend: SignalTrend = .unknown
    var estimatedDistance: Double?
    var lastSignalDate: Date?
    var statusMessage = "Tap Find Patient to request the next tag"
    var phase: TriagePhase = .searching
    var assistingPatientName = ""
    var assistanceStartedAt: Date?
    var currentAssignment: PatientAssignment?
    var isFindingPatient = false
    var isUpdatingServer = false
    var serverError: String?

    private var central: CBCentralManager?
    private var peripherals: [UUID: CBPeripheral] = [:]
    private var trackedPeripheral: CBPeripheral?
    private var rssiPollTask: Task<Void, Never>?
    private var staleCheckTask: Task<Void, Never>?
    private var lastTrendRSSI: Double?

    override init() {
        super.init()
        let defaults = UserDefaults.standard
        defaults.removeObject(forKey: "ble.targetAdvertisedName")
        defaults.removeObject(forKey: "ble.targetNameFilter")
        defaults.removeObject(forKey: "ble.targetIdentifier")
        central = CBCentralManager(delegate: self, queue: .main)
    }

    var targetAdvertisedName: String {
        AdvertisedName.normalized(nameFilter)
    }

    var canScan: Bool {
        availability == .poweredOn
    }

    var visibleDevices: [DiscoveredDevice] {
        discoveredDevices.filter(matchesFilter)
    }

    func startScan() {
        guard let central, central.state == .poweredOn else {
            statusMessage = availability.message
            return
        }

        isScanning = true
        if let trackedDevice {
            statusMessage = "Locating \(trackedDevice.displayName)…"
        } else if !targetAdvertisedName.isEmpty {
            statusMessage = "Scanning for tag “\(targetAdvertisedName)”…"
        } else {
            statusMessage = "Scanning for patient tags…"
        }

        central.scanForPeripherals(
            withServices: nil,
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: true]
        )
        startStaleSignalMonitor()
    }

    func stopScan() {
        central?.stopScan()
        isScanning = false
        if trackedDevice == nil {
            statusMessage = "Scan stopped"
        }
    }

    func track(_ device: DiscoveredDevice) {
        if device.hasAdvertisedName {
            nameFilter = device.advertisedName
        }
        trackedDevice = device
        rawRSSI = device.rssi
        applyRSSI(device.rssi)
        lastSignalDate = device.lastSeen
        zone = ProximityZone(rssi: device.rssi)
        statusMessage = "Locating \(device.displayName)"
        phase = .locating

        if let peripheral = peripherals[device.id] {
            trackedPeripheral = peripheral
            central?.connect(peripheral, options: nil)
        }

        if !isScanning {
            startScan()
        }

        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
    }

    func markPatientFound() {
        assistingPatientName = trackedDevice?.displayName ?? targetAdvertisedName
        assistanceStartedAt = Date()
        endLocationSession()
        phase = .assisting
        statusMessage = assistingPatientName.isEmpty
            ? "Assisting patient"
            : "Assisting \(assistingPatientName)"
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        Task {
            do {
                if let currentAssignment {
                    try await TriageAPI.markAssignmentFound(id: currentAssignment.id)
                }
            } catch {
                await MainActor.run {
                    serverError = error.localizedDescription
                    statusMessage = "Patient found, but the server was not updated."
                }
            }
        }
    }

    func findPatient() {
        Task { await requestNextPatient() }
    }

    func finishAssistance(outcome: PatientOutcome) {
        Task { await completeAssistance(outcome: outcome) }
    }

    private func requestNextPatient() async {
        guard phase == .searching, !isFindingPatient else { return }
        isFindingPatient = true
        serverError = nil
        statusMessage = "Requesting the next patient…"
        defer { isFindingPatient = false }

        do {
            let assignment = try await TriageAPI.nextAssignment()
            currentAssignment = assignment
            nameFilter = assignment.name
            statusMessage = "Looking for tag “\(assignment.name)”"
            phase = .locating
            if canScan {
                startScan()
            }
        } catch {
            serverError = error.localizedDescription
            statusMessage = "Could not get a patient from the server."
        }
    }

    private func completeAssistance(outcome: PatientOutcome) async {
        guard phase == .assisting, !isUpdatingServer else { return }
        isUpdatingServer = true
        serverError = nil
        statusMessage = "Updating the triage server…"
        defer { isUpdatingServer = false }

        do {
            if let currentAssignment {
                try await TriageAPI.completeAssignment(id: currentAssignment.id, outcome: outcome)
            }
            returnToSearch()
        } catch {
            serverError = error.localizedDescription
            statusMessage = "Could not update the server. Try again."
        }
    }

    private func returnToSearch() {
        currentAssignment = nil
        assistingPatientName = ""
        assistanceStartedAt = nil
        serverError = nil
        endLocationSession()
        central?.stopScan()
        isScanning = false
        phase = .searching
        statusMessage = "Tap Find Patient to request the next tag"
    }

    private func endLocationSession() {
        rssiPollTask?.cancel()
        rssiPollTask = nil

        if let trackedPeripheral {
            central?.cancelPeripheralConnection(trackedPeripheral)
        }

        trackedPeripheral = nil
        trackedDevice = nil
        rawRSSI = nil
        smoothedRSSI = nil
        estimatedDistance = nil
        lastTrendRSSI = nil
        lastSignalDate = nil
        zone = .unknown
        trend = .unknown
        nameFilter = ""
        discoveredDevices = []
    }

    func applyTargetName() {
        guard trackedDevice == nil, !targetAdvertisedName.isEmpty else { return }
        if let match = discoveredDevices
            .filter(matchesTargetName)
            .max(by: { $0.rssi < $1.rssi }) {
            track(match)
        } else if !isScanning {
            startScan()
        }
    }

    func openSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        UIApplication.shared.open(url)
    }

    private func matchesFilter(_ device: DiscoveredDevice) -> Bool {
        guard device.hasAdvertisedName else { return false }
        guard !targetAdvertisedName.isEmpty else { return true }
        return AdvertisedName.contains(device.advertisedName, query: targetAdvertisedName)
            || AdvertisedName.matches(device.advertisedName, target: targetAdvertisedName)
    }

    private func matchesTargetName(_ device: DiscoveredDevice) -> Bool {
        guard device.hasAdvertisedName, !targetAdvertisedName.isEmpty else { return false }
        return AdvertisedName.matches(device.advertisedName, target: targetAdvertisedName)
    }

    private func applyRSSI(_ rssi: Int) {
        guard rssi != 127 else { return }

        rawRSSI = rssi
        lastSignalDate = Date()

        let incoming = Double(rssi)
        if let smoothedRSSI {
            self.smoothedRSSI = (0.35 * incoming) + (0.65 * smoothedRSSI)
        } else {
            smoothedRSSI = incoming
        }

        if let smoothedRSSI {
            estimatedDistance = ProximityMath.estimatedDistanceMeters(rssi: Int(smoothedRSSI.rounded()))
            updateTrend(using: smoothedRSSI)
        }

        let nextZone = ProximityZone(rssi: Int((smoothedRSSI ?? incoming).rounded()))
        if nextZone != zone {
            zone = nextZone
            playZoneHaptic(nextZone)
        } else {
            zone = nextZone
        }
    }

    private func updateTrend(using smoothed: Double) {
        defer { lastTrendRSSI = smoothed }

        guard let lastTrendRSSI else {
            trend = .unknown
            return
        }

        let delta = smoothed - lastTrendRSSI
        if delta >= 1.5 {
            if trend != .warmer {
                UIImpactFeedbackGenerator(style: .light).impactOccurred()
            }
            trend = .warmer
        } else if delta <= -1.5 {
            trend = .colder
        } else {
            trend = .steady
        }
    }

    private func playZoneHaptic(_ zone: ProximityZone) {
        switch zone {
        case .immediate:
            UINotificationFeedbackGenerator().notificationOccurred(.success)
        case .near:
            UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        case .mid:
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
        default:
            break
        }
    }

    private func upsertDiscoveredDevice(
        peripheral: CBPeripheral,
        rssi: Int,
        advertisementData: [String: Any]
    ) {
        peripherals[peripheral.identifier] = peripheral

        let packetName = advertisementData[CBAdvertisementDataLocalNameKey] as? String
        let existing = discoveredDevices.first(where: { $0.id == peripheral.identifier })
        // Later packets often omit the local name to save bytes. Keep the last advertised name.
        let advertisedName = AdvertisedName.normalized(packetName ?? existing?.advertisedName ?? "")

        let device = DiscoveredDevice(
            id: peripheral.identifier,
            advertisedName: advertisedName,
            rssi: rssi,
            lastSeen: Date()
        )

        if let index = discoveredDevices.firstIndex(where: { $0.id == device.id }) {
            discoveredDevices[index] = device
        } else {
            discoveredDevices.append(device)
        }

        discoveredDevices.sort { $0.rssi > $1.rssi }

        if let trackedDevice, AdvertisedName.matches(trackedDevice.advertisedName, target: device.advertisedName)
            || trackedDevice.id == device.id {
            // Follow the strongest advertisement using this name, even if iOS
            // assigns a new peripheral identifier.
            if device.rssi >= trackedDevice.rssi || trackedDevice.id == device.id {
                self.trackedDevice = device
                if trackedPeripheral?.identifier != peripheral.identifier {
                    if let trackedPeripheral {
                        central?.cancelPeripheralConnection(trackedPeripheral)
                    }
                    trackedPeripheral = peripheral
                    central?.connect(peripheral, options: nil)
                }
            }
            applyRSSI(rssi)
            return
        }

        if trackedDevice == nil, matchesTargetName(device) {
            track(device)
        }
    }

    private func startRSSIPolling(for peripheral: CBPeripheral) {
        rssiPollTask?.cancel()
        rssiPollTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self, self.trackedPeripheral === peripheral else { return }
                peripheral.readRSSI()
                try? await Task.sleep(for: .milliseconds(700))
            }
        }
    }

    private func startStaleSignalMonitor() {
        staleCheckTask?.cancel()
        staleCheckTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(500))
                guard let self else { return }
                self.markStaleSignalIfNeeded()
            }
        }
    }

    private func markStaleSignalIfNeeded() {
        guard trackedDevice != nil, let lastSignalDate else { return }
        if Date().timeIntervalSince(lastSignalDate) > ProximityMath.staleSignalInterval {
            zone = .lost
            trend = .unknown
            statusMessage = "Signal dropped. Keep moving and scanning."
        }
    }

    private func applyBluetoothState(_ state: CBManagerState) {
        switch state {
        case .poweredOn:
            availability = .poweredOn
            if phase == .locating {
                startScan()
            } else if phase == .searching {
                statusMessage = "Tap Find Patient to request the next tag"
            }
        case .poweredOff:
            availability = .poweredOff
            isScanning = false
            statusMessage = BluetoothAvailability.poweredOff.message
        case .unauthorized:
            availability = .unauthorized
            isScanning = false
            statusMessage = BluetoothAvailability.unauthorized.message
        case .unsupported:
            availability = .unsupported
            isScanning = false
            statusMessage = BluetoothAvailability.unsupported.message
        case .resetting:
            availability = .resetting
            isScanning = false
            statusMessage = BluetoothAvailability.resetting.message
        case .unknown:
            availability = .unknown
            statusMessage = BluetoothAvailability.unknown.message
        @unknown default:
            availability = .unknown
            statusMessage = BluetoothAvailability.unknown.message
        }
    }
}

extension BLEProximityManager: CBCentralManagerDelegate, CBPeripheralDelegate {
    nonisolated func centralManagerDidUpdateState(_ central: CBCentralManager) {
        let state = central.state
        Task { @MainActor in
            self.applyBluetoothState(state)
        }
    }

    nonisolated func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String: Any],
        rssi RSSI: NSNumber
    ) {
        let identifier = peripheral.identifier
        let rssi = RSSI.intValue
        let advertisement = advertisementData
        Task { @MainActor in
            self.peripherals[identifier] = peripheral
            self.upsertDiscoveredDevice(
                peripheral: peripheral,
                rssi: rssi,
                advertisementData: advertisement
            )
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        Task { @MainActor in
            guard self.trackedDevice?.id == peripheral.identifier else { return }
            peripheral.delegate = self
            self.statusMessage = "Connected for live RSSI updates"
            self.startRSSIPolling(for: peripheral)
        }
    }

    nonisolated func centralManager(
        _ central: CBCentralManager,
        didFailToConnect peripheral: CBPeripheral,
        error: Error?
    ) {
        Task { @MainActor in
            guard self.trackedDevice?.id == peripheral.identifier else { return }
            self.statusMessage = "Could not connect. Using advertisement RSSI instead."
        }
    }

    nonisolated func centralManager(
        _ central: CBCentralManager,
        didDisconnectPeripheral peripheral: CBPeripheral,
        error: Error?
    ) {
        Task { @MainActor in
            guard self.trackedDevice?.id == peripheral.identifier else { return }
            self.rssiPollTask?.cancel()
            self.statusMessage = "Disconnected. Still following advertisement RSSI."
            if self.canScan, self.isScanning {
                self.central?.connect(peripheral, options: nil)
            }
        }
    }

    nonisolated func peripheral(_ peripheral: CBPeripheral, didReadRSSI RSSI: NSNumber, error: Error?) {
        let rssi = RSSI.intValue
        Task { @MainActor in
            guard error == nil, self.trackedDevice?.id == peripheral.identifier else { return }
            self.applyRSSI(rssi)
            if var device = self.trackedDevice {
                device.rssi = rssi
                device.lastSeen = Date()
                self.trackedDevice = device
            }
        }
    }
}
