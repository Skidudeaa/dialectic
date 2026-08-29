import Foundation
import Observation

@MainActor
@Observable
final class CaptureAppModel {
    enum SessionState: Equatable {
        case starting
        case signedOut
        case signedIn(TokenCredentials)
        case failed(String)
    }

    private(set) var session: SessionState = .starting
    private(set) var rooms: [RoomDestination] = []
    private(set) var captures: [QueuedCapture] = []
    private(set) var defaultRoom: RoomDestination?
    private(set) var isWorking = false
    var banner: String?

    let configuration: AppConfiguration
    private let queue: CaptureQueue
    private let credentials: any CredentialVault
    private let preferences: CapturePreferences
    private let api: DialecticAPIClient
    private let delivery: CaptureDeliveryService

    init(runtime: CaptureRuntime) {
        configuration = runtime.configuration
        queue = runtime.queue
        credentials = runtime.credentials
        preferences = runtime.preferences
        api = runtime.api
        delivery = runtime.delivery
    }

    var pendingCount: Int {
        captures.filter { [.pending, .filing, .needsAttention].contains($0.state.status) }.count
    }

    var oldestPendingAge: String {
        guard let oldest = captures
            .filter({ [.pending, .filing, .needsAttention].contains($0.state.status) })
            .compactMap(\.envelope?.capturedAt)
            .min() else {
            return "clear"
        }
        let interval = max(0, Date().timeIntervalSince(oldest))
        if interval < 3600 { return "\(max(1, Int(interval / 60)))m" }
        if interval < 86_400 { return "\(Int(interval / 3600))h" }
        return "\(Int(interval / 86_400))d"
    }

    func start() async {
        isWorking = true
        defer { isWorking = false }
        do {
            try await queue.recoverInterruptedAttempts()
            defaultRoom = try await preferences.defaultRoom()
            try await refreshCaptures()
            if let stored = try await credentials.load() {
                session = .signedIn(stored)
                await refreshRooms()
            } else {
                session = .signedOut
            }
        } catch {
            session = .failed(error.localizedDescription)
        }
    }

    func signIn(email: String, password: String) async {
        isWorking = true
        banner = nil
        defer { isWorking = false }
        do {
            let signedIn = try await api.login(email: email, password: password)
            session = .signedIn(signedIn)
            await refreshRooms()
        } catch {
            banner = error.localizedDescription
            session = .signedOut
        }
    }

    func signOut() async {
        isWorking = true
        defer { isWorking = false }
        do {
            try await credentials.delete()
            session = .signedOut
            rooms = []
            defaultRoom = nil
            try await preferences.setDefaultRoom(nil)
            banner = nil
        } catch {
            banner = error.localizedDescription
        }
    }

    func refreshRooms() async {
        do {
            let fetched = try await api.rooms()
            rooms = fetched
            var destinationWasRemoved = false
            if let current = defaultRoom {
                if let refreshed = fetched.first(where: { $0.id == current.id }) {
                    defaultRoom = refreshed
                    try await preferences.setDefaultRoom(refreshed)
                } else {
                    destinationWasRemoved = true
                    defaultRoom = nil
                    try await preferences.setDefaultRoom(nil)
                    banner = "The previous destination is no longer available. Choose a room before retrying."
                }
            }
            if !destinationWasRemoved {
                banner = nil
            }
        } catch DialecticAPIError.notAuthenticated {
            await clearRevokedSession()
        } catch {
            banner = error.localizedDescription
        }
    }

    func chooseDefaultRoom(_ room: RoomDestination) async {
        do {
            try await preferences.setDefaultRoom(room)
            defaultRoom = room
            banner = nil
        } catch {
            banner = error.localizedDescription
        }
    }

    func retry(_ id: UUID) async {
        isWorking = true
        banner = nil
        let result = await delivery.retry(id)
        if result.errorCategory == DialecticAPIError.notAuthenticated.category {
            await clearRevokedSession()
        }
        do {
            try await refreshCaptures()
        } catch {
            banner = error.localizedDescription
        }
        isWorking = false
    }

    func retryAll() async {
        isWorking = true
        banner = nil
        let results = await delivery.retryAll()
        if results.contains(where: {
            $0.errorCategory == DialecticAPIError.notAuthenticated.category
        }) {
            await clearRevokedSession()
        }
        do {
            try await refreshCaptures()
        } catch {
            banner = error.localizedDescription
        }
        isWorking = false
    }

    func delete(_ id: UUID) async {
        do {
            try await queue.delete(id)
            try await refreshCaptures()
        } catch {
            banner = error.localizedDescription
        }
    }

    func markdown(_ id: UUID) async throws -> String {
        try await queue.markdown(id)
    }

    func refreshCaptures() async throws {
        do {
            captures = try await queue.list()
        } catch {
            banner = error.localizedDescription
            throw error
        }
    }

    private func clearRevokedSession() async {
        session = .signedOut
        rooms = []
        defaultRoom = nil
        try? await preferences.setDefaultRoom(nil)
        banner = "Your session ended. Sign in again before filing queued captures."
    }
}
