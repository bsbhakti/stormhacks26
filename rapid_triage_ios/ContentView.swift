import SwiftUI

struct ContentView: View {
    @State private var manager = BLEProximityManager()

    var body: some View {
        NavigationStack {
            Group {
                switch manager.phase {
                case .searching:
                    ScanView(manager: manager)
                case .locating:
                    FinderView(manager: manager)
                case .assisting:
                    AssistingPatientView(manager: manager)
                }
            }
            .background(AppTheme.background.ignoresSafeArea())
        }
        .preferredColorScheme(.dark)
    }
}

private enum AppTheme {
    static let background = Color(red: 0.06, green: 0.08, blue: 0.11)
    static let card = Color(red: 0.11, green: 0.14, blue: 0.18)
    static let stroke = Color.white.opacity(0.08)
}

struct ScanView: View {
    @Bindable var manager: BLEProximityManager

    var body: some View {
        VStack(spacing: 28) {
            Spacer()

            Image(systemName: "dot.radiowaves.left.and.right")
                .font(.system(size: 48))
                .foregroundStyle(Color(red: 0.35, green: 0.72, blue: 0.95))

            VStack(spacing: 10) {
                Text("Ready for the next patient")
                    .font(.title2.weight(.semibold))
                    .multilineTextAlignment(.center)
                Text("Find Patient asks the triage server for the next tag name, then guides you to that BLE advertisement.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }

            if manager.isFindingPatient {
                ProgressView()
                    .controlSize(.large)
            }

            if let serverError = manager.serverError {
                Text(serverError)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
            } else {
                Text(manager.statusMessage)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }

            if manager.availability == .unauthorized {
                Button("Open Settings") {
                    manager.openSettings()
                }
                .font(.footnote.weight(.semibold))
            }

            Spacer()

            Button {
                manager.findPatient()
            } label: {
                Text(manager.isFindingPatient ? "Requesting…" : "Find Patient")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(manager.isFindingPatient)

            #if targetEnvironment(simulator)
            Text("Bluetooth locating needs a physical iPhone. The Find Patient request still talks to the server.")
                .font(.footnote)
                .foregroundStyle(.orange)
                .multilineTextAlignment(.center)
            #endif
        }
        .padding(.horizontal, 24)
        .padding(.bottom, 16)
        .navigationTitle("Rapid Triage")
        .navigationBarTitleDisplayMode(.inline)
    }
}

struct FinderView: View {
    @Bindable var manager: BLEProximityManager
    @State private var pulse = false

    var body: some View {
        VStack(spacing: 24) {
            targetHeader
            radar
            metrics
            guidance
            Spacer(minLength: 8)
            if manager.isUpdatingServer {
                ProgressView("Updating server…")
            }
            Button(manager.isUpdatingServer ? "Updating…" : "Found patient") {
                manager.markPatientFound()
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .tint(Color(red: 0.22, green: 0.72, blue: 0.42))
            .disabled(manager.isUpdatingServer)
            .padding(.bottom, 16)
        }
        .padding(.horizontal, 20)
        .navigationTitle("Locate patient")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            pulse = true
            if !manager.isScanning {
                manager.startScan()
            }
        }
    }

    private var targetHeader: some View {
        VStack(spacing: 6) {
            Text(manager.trackedDevice?.displayName ?? manager.targetAdvertisedName)
                .font(.title2.weight(.semibold))
            if let serverError = manager.serverError {
                Text(serverError)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
            } else {
                Text(manager.statusMessage)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
        }
        .padding(.top, 8)
    }

    private var radar: some View {
        ZStack {
            ForEach(0..<4, id: \.self) { ring in
                Circle()
                    .stroke(manager.zone.color.opacity(0.18 + Double(ring) * 0.05), lineWidth: 1)
                    .scaleEffect(1 - Double(ring) * 0.18)
            }

            Circle()
                .fill(manager.zone.color.opacity(0.18))
                .scaleEffect(pulse ? manager.zone.progress : manager.zone.progress * 0.82)
                .animation(
                    .easeInOut(duration: pulseDuration).repeatForever(autoreverses: true),
                    value: pulse
                )

            Circle()
                .fill(manager.zone.color)
                .frame(width: 22, height: 22)
                .shadow(color: manager.zone.color.opacity(0.6), radius: 12)

            VStack {
                Spacer()
                Text(manager.zone.title)
                    .font(.headline)
                    .padding(.bottom, 18)
            }
        }
        .frame(width: 260, height: 260)
    }

    private var metrics: some View {
        HStack(spacing: 12) {
            MetricCard(
                title: "RSSI",
                value: manager.rawRSSI.map { "\($0)" } ?? "--",
                unit: "dBm"
            )
            MetricCard(
                title: "Distance",
                value: manager.estimatedDistance.map(ProximityMath.formattedDistance) ?? "--",
                unit: "approx"
            )
            MetricCard(
                title: "Trend",
                value: manager.trend.title,
                unit: "",
                symbol: manager.trend.systemImage
            )
        }
    }

    private var guidance: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: manager.trend.systemImage)
                Text(guidanceHeadline)
                    .font(.headline)
            }
            .foregroundStyle(manager.zone.color)

            Text(manager.zone.instruction)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            ProgressView(value: manager.zone.progress)
                .tint(manager.zone.color)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.card, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(AppTheme.stroke, lineWidth: 1)
        }
    }

    private var guidanceHeadline: String {
        switch manager.trend {
        case .warmer: "Keep walking this way"
        case .colder: "Turn and try another line"
        case .steady: "Hold still, then move again"
        case .unknown: "Establishing a baseline"
        }
    }

    private var pulseDuration: Double {
        switch manager.zone {
        case .immediate: 0.55
        case .near: 0.8
        case .mid: 1.1
        default: 1.6
        }
    }
}

struct AssistingPatientView: View {
    @Bindable var manager: BLEProximityManager

    var body: some View {
        VStack(spacing: 28) {
            Spacer()

            Image(systemName: "cross.case.fill")
                .font(.system(size: 54))
                .foregroundStyle(Color(red: 0.22, green: 0.72, blue: 0.42))

            VStack(spacing: 8) {
                Text("Assisting Patient")
                    .font(.largeTitle.weight(.bold))
                    .multilineTextAlignment(.center)
                Text(manager.assistingPatientName.isEmpty
                     ? "Stay with the patient until care is complete."
                     : "Tag \(manager.assistingPatientName)")
                    .font(.title3)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }

            TimelineView(.periodic(from: .now, by: 1)) { context in
                VStack(spacing: 6) {
                    Text("Time on scene")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Text(elapsedTime(at: context.date))
                        .font(.system(.title, design: .rounded).monospacedDigit().weight(.semibold))
                }
                .padding(16)
                .frame(maxWidth: .infinity)
                .background(AppTheme.card, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .stroke(AppTheme.stroke, lineWidth: 1)
                }
            }

            Text("When you are done, put this patient back on the monitoring queue or stop monitoring.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            if manager.isUpdatingServer {
                ProgressView("Updating server…")
            }

            if let serverError = manager.serverError {
                Text(serverError)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
            }

            Spacer()

            VStack(spacing: 12) {
                Button("Put back in monitoring") {
                    manager.finishAssistance(status: .monitoring)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .tint(Color(red: 0.22, green: 0.72, blue: 0.42))
                .disabled(manager.isUpdatingServer)

                Button("Stop monitoring") {
                    manager.finishAssistance(status: .stopped)
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .disabled(manager.isUpdatingServer)
            }
            .padding(.bottom, 16)
        }
        .padding(.horizontal, 24)
        .navigationTitle("On scene")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func elapsedTime(at now: Date) -> String {
        let start = manager.assistanceStartedAt ?? now
        let seconds = max(0, Int(now.timeIntervalSince(start)))
        return String(format: "%02d:%02d", seconds / 60, seconds % 60)
    }
}

struct MetricCard: View {
    let title: String
    let value: String
    var unit: String = ""
    var symbol: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title.uppercased())
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                if let symbol {
                    Image(systemName: symbol)
                }
                Text(value)
                    .font(.title3.weight(.semibold))
                    .minimumScaleFactor(0.7)
                    .lineLimit(1)
            }
            if !unit.isEmpty {
                Text(unit)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.card, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(AppTheme.stroke, lineWidth: 1)
        }
    }
}

struct SignalBars: View {
    let rssi: Int

    var body: some View {
        let filled = barsFilled
        HStack(alignment: .bottom, spacing: 3) {
            ForEach(0..<4, id: \.self) { index in
                RoundedRectangle(cornerRadius: 1.5)
                    .fill(index < filled ? ProximityZone(rssi: rssi).color : Color.white.opacity(0.15))
                    .frame(width: 4, height: CGFloat(8 + index * 4))
            }
        }
        .frame(width: 28)
    }

    private var barsFilled: Int {
        switch rssi {
        case -49...0: 4
        case -64 ... -50: 3
        case -79 ... -65: 2
        default: 1
        }
    }
}

#Preview {
    ContentView()
}
