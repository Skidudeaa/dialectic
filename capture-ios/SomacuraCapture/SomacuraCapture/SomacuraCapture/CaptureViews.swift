import SwiftUI
import UIKit

enum CaptureTheme {
    static let void = Color(red: 0.045, green: 0.027, blue: 0.016)
    static let obsidian = Color(red: 0.085, green: 0.067, blue: 0.052)
    static let well = Color(red: 0.12, green: 0.10, blue: 0.075)
    static let amber = Color(red: 0.91, green: 0.61, blue: 0.29)
    static let teal = Color(red: 0.25, green: 0.76, blue: 0.67)
    static let ink = Color(red: 0.94, green: 0.90, blue: 0.82)
    static let mutedInk = Color(red: 0.68, green: 0.63, blue: 0.54)
    static let danger = Color(red: 0.95, green: 0.39, blue: 0.30)
}

struct CaptureRootView: View {
    @State private var model: CaptureAppModel

    init(model: CaptureAppModel) {
        _model = State(wrappedValue: model)
    }

    var body: some View {
        Group {
            switch model.session {
            case .starting:
                ProgressView("Opening the capture queue…")
                    .tint(CaptureTheme.amber)
            case .signedOut:
                SignInView(model: model)
            case .signedIn:
                CaptureDashboardView(model: model)
            case .failed(let message):
                ConfigurationFailureView(message: message)
            }
        }
        .preferredColorScheme(.dark)
        .tint(CaptureTheme.amber)
        .background(CaptureTheme.void.ignoresSafeArea())
        .task { await model.start() }
    }
}

struct ConfigurationFailureView: View {
    let message: String

    var body: some View {
        ContentUnavailableView(
            "Capture queue unavailable",
            systemImage: "externaldrive.badge.exclamationmark",
            description: Text(message)
        )
        .foregroundStyle(CaptureTheme.ink)
        .background(CaptureTheme.void)
    }
}

private struct SignInView: View {
    let model: CaptureAppModel
    @State private var email = ""
    @State private var password = ""
    @FocusState private var focusedField: Field?

    private enum Field {
        case email
        case password
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Somacura Capture")
                            .font(.largeTitle.weight(.semibold))
                            .foregroundStyle(CaptureTheme.ink)
                        Text("One tap in Safari. Exact Markdown committed locally before the network.")
                            .foregroundStyle(CaptureTheme.mutedInk)
                    }
                    .padding(.vertical, 8)
                }
                .listRowBackground(CaptureTheme.obsidian)

                Section("Dialectic account") {
                    TextField("Email", text: $email)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .textContentType(.username)
                        .focused($focusedField, equals: .email)
                    SecureField("Password", text: $password)
                        .textContentType(.password)
                        .focused($focusedField, equals: .password)
                        .onSubmit { signIn() }
                    Button(model.isWorking ? "Signing in…" : "Sign in") { signIn() }
                        .disabled(model.isWorking || email.isEmpty || password.isEmpty)
                }
                .listRowBackground(CaptureTheme.obsidian)

                if let banner = model.banner {
                    Section {
                        Label(banner, systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(CaptureTheme.danger)
                    }
                    .listRowBackground(CaptureTheme.obsidian)
                }

                Section("Enable the Safari action") {
                    Text("Open Settings › Apps › Safari › Extensions, enable Somacura Capture, and allow it on the page when Safari asks.")
                        .foregroundStyle(CaptureTheme.mutedInk)
                }
                .listRowBackground(CaptureTheme.obsidian)
            }
            .scrollContentBackground(.hidden)
            .background(CaptureTheme.void)
            .navigationTitle("Capture appliance")
            .onAppear { focusedField = .email }
        }
    }

    private func signIn() {
        focusedField = nil
        Task { await model.signIn(email: email, password: password) }
    }
}

private enum CaptureSheet: String, Identifiable {
    case destination
    var id: String { rawValue }
}

private struct CaptureDashboardView: View {
    let model: CaptureAppModel
    @State private var selectedCaptureID: UUID?
    @State private var activeSheet: CaptureSheet?

    var body: some View {
        NavigationSplitView {
            List(selection: $selectedCaptureID) {
                Section {
                    CaptureDock(
                        destination: model.defaultRoom?.name ?? "Choose room",
                        pendingCount: model.pendingCount,
                        oldestAge: model.oldestPendingAge,
                        isWorking: model.isWorking,
                        chooseDestination: { activeSheet = .destination },
                        retry: { Task { await model.retryAll() } }
                    )
                    .listRowInsets(EdgeInsets(top: 8, leading: 12, bottom: 12, trailing: 12))
                    .listRowBackground(CaptureTheme.void)
                    .listRowSeparator(.hidden)
                }

                captureSection(
                    "Queued / needs attention",
                    captures: model.captures.filter { $0.state.status != .filed }
                )
                captureSection(
                    "Filed archive",
                    captures: model.captures.filter { $0.state.status == .filed }
                )

                Section("Safari") {
                    Text("Tap the Somacura Capture toolbar action. The containing app does not need to be open.")
                        .font(.callout)
                        .foregroundStyle(CaptureTheme.mutedInk)
                }
                .listRowBackground(CaptureTheme.obsidian)
            }
            .listStyle(.sidebar)
            .scrollContentBackground(.hidden)
            .background(CaptureTheme.void)
            .navigationTitle("Reading Rail")
            .refreshable {
                try? await model.refreshCaptures()
                await model.refreshRooms()
            }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Sign out") { Task { await model.signOut() } }
                }
            }
        } detail: {
            if let id = selectedCaptureID,
               let capture = model.captures.first(where: { $0.id == id }) {
                CaptureDetailView(model: model, capture: capture)
            } else {
                ContentUnavailableView(
                    "Select a capture",
                    systemImage: "doc.text.magnifyingglass",
                    description: Text("Queued and filed Markdown stays available here.")
                )
                .foregroundStyle(CaptureTheme.ink)
                .background(CaptureTheme.void)
            }
        }
        .sheet(item: $activeSheet) { sheet in
            switch sheet {
            case .destination:
                DestinationSheet(model: model)
            }
        }
        .overlay(alignment: .bottom) {
            if let banner = model.banner {
                Text(banner)
                    .font(.callout.weight(.medium))
                    .foregroundStyle(CaptureTheme.ink)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(CaptureTheme.obsidian, in: .rect(cornerRadius: 10))
                    .overlay {
                        RoundedRectangle(cornerRadius: 10)
                            .stroke(CaptureTheme.danger.opacity(0.8), lineWidth: 1)
                    }
                    .padding()
                    .accessibilityLabel("Error: \(banner)")
            }
        }
    }

    @ViewBuilder
    private func captureSection(_ title: String, captures: [QueuedCapture]) -> some View {
        Section(title) {
            if captures.isEmpty {
                Text(title.hasPrefix("Filed") ? "Nothing filed yet." : "Queue clear.")
                    .foregroundStyle(CaptureTheme.mutedInk)
            } else {
                ForEach(captures) { capture in
                    CaptureRow(capture: capture)
                        .tag(capture.id)
                }
            }
        }
        .listRowBackground(CaptureTheme.obsidian)
    }
}

private struct CaptureDock: View {
    let destination: String
    let pendingCount: Int
    let oldestAge: String
    let isWorking: Bool
    let chooseDestination: () -> Void
    let retry: () -> Void

    private let columns = [GridItem(.adaptive(minimum: 118), spacing: 8)]

    var body: some View {
        LazyVGrid(columns: columns, spacing: 8) {
            DockTile(
                title: "Destination",
                value: destination,
                symbol: "tray.and.arrow.down",
                accent: CaptureTheme.teal,
                action: chooseDestination
            )
            DockTile(
                title: "Mode",
                value: "Auto",
                detail: "selection → article → fallback",
                symbol: "wand.and.rays",
                accent: CaptureTheme.amber
            )
            DockTile(
                title: "Queue",
                value: "\(pendingCount)",
                detail: pendingCount == 0 ? "clear" : "oldest \(oldestAge)",
                symbol: "shippingbox",
                accent: pendingCount == 0 ? CaptureTheme.teal : CaptureTheme.amber
            )
            DockTile(
                title: "Retry",
                value: isWorking ? "Working" : "Run",
                symbol: "arrow.clockwise",
                accent: CaptureTheme.teal,
                disabled: isWorking || pendingCount == 0,
                action: retry
            )
            DockTile(
                title: "Archive",
                value: "Local",
                detail: "filed Markdown retained",
                symbol: "archivebox",
                accent: CaptureTheme.mutedInk
            )
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Capture Dock")
    }
}

private struct DockTile: View {
    let title: String
    let value: String
    var detail: String? = nil
    let symbol: String
    let accent: Color
    var disabled = false
    var action: (() -> Void)? = nil

    private var accessibilityText: String {
        "\(title), \(value)\(detail.map { ", \($0)" } ?? "")"
    }

    var body: some View {
        if let action {
            Button(action: action) { content }
                .buttonStyle(.plain)
                .disabled(disabled)
                .accessibilityLabel(accessibilityText)
                .accessibilityIdentifier("capture-dock-\(title.lowercased())")
        } else {
            content
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(accessibilityText)
        }
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: 5) {
            Label(title.uppercased(), systemImage: symbol)
                .font(.caption.weight(.semibold))
                .foregroundStyle(accent)
            Text(value)
                .font(.headline.monospacedDigit())
                .foregroundStyle(CaptureTheme.ink)
                .lineLimit(2)
            if let detail {
                Text(detail)
                    .font(.caption2)
                    .foregroundStyle(CaptureTheme.mutedInk)
                    .lineLimit(2)
            }
        }
        .frame(maxWidth: .infinity, minHeight: 76, alignment: .topLeading)
        .padding(10)
        .background(CaptureTheme.well, in: .rect(cornerRadius: 9))
        .overlay {
            RoundedRectangle(cornerRadius: 9)
                .stroke(accent.opacity(0.48), lineWidth: 1)
        }
        .contentShape(Rectangle())
        .opacity(disabled ? 0.5 : 1)
    }
}

private struct CaptureRow: View {
    let capture: QueuedCapture

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline) {
                Text(capture.displayTitle)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(CaptureTheme.ink)
                    .lineLimit(2)
                Spacer(minLength: 8)
                StatusLabel(status: capture.state.status)
            }
            HStack(spacing: 8) {
                Text(capture.envelope?.site ?? capture.envelope?.url.host() ?? "Local capture")
                if let mode = capture.envelope?.captureMode {
                    Text(mode.rawValue.replacingOccurrences(of: "_", with: " "))
                }
                if let date = capture.envelope?.capturedAt {
                    Text(date, style: .relative)
                }
            }
            .font(.caption)
            .foregroundStyle(CaptureTheme.mutedInk)
            if let error = capture.state.lastError, capture.state.status != .filed {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(CaptureTheme.danger)
                    .lineLimit(2)
            }
        }
        .padding(.vertical, 5)
        .contentShape(Rectangle())
    }
}

private struct StatusLabel: View {
    let status: DeliveryStatus

    var body: some View {
        Text(label)
            .font(.caption2.weight(.bold))
            .foregroundStyle(color)
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .background(color.opacity(0.12), in: .capsule)
    }

    private var label: String {
        switch status {
        case .pending: "QUEUED"
        case .filing: "FILING"
        case .filed: "FILED"
        case .needsAttention: "NEEDS ATTENTION"
        }
    }

    private var color: Color {
        switch status {
        case .filed: CaptureTheme.teal
        case .pending, .filing: CaptureTheme.amber
        case .needsAttention: CaptureTheme.danger
        }
    }
}

private struct DestinationSheet: View {
    let model: CaptureAppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List(model.rooms) { room in
                Button {
                    Task {
                        await model.chooseDefaultRoom(room)
                        dismiss()
                    }
                } label: {
                    HStack {
                        VStack(alignment: .leading) {
                            Text(room.name)
                            if room.isHome {
                                Text("Home")
                                    .font(.caption)
                                    .foregroundStyle(CaptureTheme.mutedInk)
                            }
                        }
                        Spacer()
                        if model.defaultRoom?.id == room.id {
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundStyle(CaptureTheme.teal)
                        }
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .listRowBackground(CaptureTheme.obsidian)
            }
            .scrollContentBackground(.hidden)
            .background(CaptureTheme.void)
            .navigationTitle("Destination")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Refresh") { Task { await model.refreshRooms() } }
                }
            }
        }
    }
}

private struct CaptureDetailView: View {
    let model: CaptureAppModel
    let capture: QueuedCapture
    @State private var markdown: String?
    @State private var loadError: String?
    @State private var confirmDelete = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 7) {
                    Text(capture.displayTitle)
                        .font(.largeTitle.weight(.semibold))
                        .foregroundStyle(CaptureTheme.ink)
                    HStack {
                        StatusLabel(status: capture.state.status)
                        if let mode = capture.envelope?.captureMode {
                            Text(mode.rawValue.replacingOccurrences(of: "_", with: " "))
                                .foregroundStyle(CaptureTheme.mutedInk)
                        }
                    }
                    if let url = capture.envelope?.url {
                        Link(destination: url) {
                            Label(url.host() ?? url.absoluteString, systemImage: "safari")
                        }
                    }
                }

                metadata

                if let loadError {
                    Label(loadError, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(CaptureTheme.danger)
                } else if let markdown {
                    MarkdownPreview(markdown: markdown)
                } else {
                    ProgressView("Reading local Markdown…")
                }
            }
            .frame(maxWidth: 760, alignment: .leading)
            .padding(22)
        }
        .background(CaptureTheme.void)
        .navigationTitle("Capture")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                Button {
                    if let markdown { UIPasteboard.general.string = markdown }
                } label: {
                    Label("Copy Markdown", systemImage: "doc.on.doc")
                }
                .disabled(markdown == nil)
                ShareLink(item: capture.contentURL) {
                    Label("Export Markdown", systemImage: "square.and.arrow.up")
                }
                if capture.state.status != .filed {
                    Button {
                        Task { await model.retry(capture.id) }
                    } label: {
                        Label("Retry", systemImage: "arrow.clockwise")
                    }
                }
                Button(role: .destructive) {
                    confirmDelete = true
                } label: {
                    Label("Delete local copy", systemImage: "trash")
                }
            }
        }
        .task(id: capture.id) {
            do {
                markdown = try await model.markdown(capture.id)
            } catch {
                loadError = error.localizedDescription
            }
        }
        .alert("Delete local Markdown?", isPresented: $confirmDelete) {
            Button("Delete", role: .destructive) {
                Task { await model.delete(capture.id) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The server revision is unchanged. This removes only this device’s local queue copy.")
        }
    }

    private var metadata: some View {
        Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 7) {
            detailRow("Captured", capture.envelope?.capturedAt.formatted() ?? "Unknown")
            detailRow("SHA-256", capture.envelope?.contentSha256 ?? "Unavailable")
            detailRow("Attempts", "\(capture.state.attempts)")
            if let room = capture.state.destinationRoomName {
                detailRow(capture.state.status == .filed ? "Filed to" : "Last destination", room)
            }
            if let error = capture.state.lastError {
                detailRow("Last error", error)
            }
        }
        .font(.callout)
    }

    private func detailRow(_ label: String, _ value: String) -> some View {
        GridRow {
            Text(label.uppercased())
                .font(.caption.weight(.semibold))
                .foregroundStyle(CaptureTheme.mutedInk)
            Text(value)
                .foregroundStyle(CaptureTheme.ink)
                .textSelection(.enabled)
        }
    }
}

private struct MarkdownPreview: View {
    let markdown: String

    var body: some View {
        Group {
            if let attributed = try? AttributedString(
                markdown: markdown,
                options: .init(interpretedSyntax: .full)
            ) {
                Text(attributed)
            } else {
                Text(markdown)
            }
        }
        .font(.body)
        .foregroundStyle(CaptureTheme.ink)
        .lineSpacing(5)
        .textSelection(.enabled)
        .frame(maxWidth: 680, alignment: .leading)
        .padding(18)
        .background(CaptureTheme.obsidian, in: .rect(cornerRadius: 10))
        .overlay {
            RoundedRectangle(cornerRadius: 10)
                .stroke(CaptureTheme.amber.opacity(0.28), lineWidth: 1)
        }
    }
}

#Preview("Signed out") {
    ConfigurationFailureView(message: "Preview uses no live App Group or network.")
}
