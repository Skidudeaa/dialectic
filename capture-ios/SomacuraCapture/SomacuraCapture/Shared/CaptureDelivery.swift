import Foundation

actor CaptureDeliveryService {
    private let queue: CaptureQueue
    private let api: DialecticAPIClient
    private let preferences: CapturePreferences

    init(
        queue: CaptureQueue,
        api: DialecticAPIClient,
        preferences: CapturePreferences
    ) {
        self.queue = queue
        self.api = api
        self.preferences = preferences
    }

    func queueAndFile(_ envelope: CaptureEnvelope) async throws -> NativeQueueResult {
        let queued = try await queue.commit(envelope)
        return await fileIfConfigured(queued.id)
    }

    func retry(_ id: UUID) async -> NativeQueueResult {
        await fileIfConfigured(id)
    }

    func retryAll() async -> [NativeQueueResult] {
        guard let captures = try? await queue.list() else { return [] }
        var results: [NativeQueueResult] = []
        for capture in captures where [.pending, .needsAttention].contains(capture.state.status) {
            results.append(await fileIfConfigured(capture.id))
        }
        return results
    }

    private func fileIfConfigured(_ id: UUID) async -> NativeQueueResult {
        let capture: QueuedCapture
        do {
            capture = try await queue.load(id)
        } catch {
            return NativeQueueResult(
                localDurable: false,
                deliveryStatus: .needsAttention,
                roomName: nil,
                errorCategory: "queue_read",
                errorMessage: bounded(error.localizedDescription)
            )
        }
        guard let envelope = capture.envelope else {
            return await needsAttention(
                id,
                roomName: nil,
                category: "queue_corrupt",
                message: "Capture metadata is unreadable."
            )
        }

        let destination: RoomDestination
        do {
            guard let configured = try await preferences.defaultRoom() else {
                let updated = try? await queue.markPending(
                    id,
                    category: "no_room",
                    message: "Choose a destination room in Somacura Capture."
                )
                return result(
                    from: updated,
                    roomName: nil,
                    fallbackStatus: .pending,
                    fallbackCategory: "no_room",
                    fallbackMessage: "Choose a destination room in Somacura Capture."
                )
            }
            destination = configured
        } catch {
            return await needsAttention(
                id,
                roomName: nil,
                category: "configuration",
                message: error.localizedDescription
            )
        }

        var attemptId: UUID?
        do {
            guard let attempt = try await queue.markFiling(
                id,
                destination: destination
            ) else {
                let current = try await queue.load(id)
                return result(
                    from: current,
                    roomName: destination.name,
                    fallbackStatus: current.state.status,
                    fallbackCategory: current.state.errorCategory,
                    fallbackMessage: current.state.lastError
                )
            }
            attemptId = attempt.id
            let response = try await api.file(envelope, to: destination)
            let updated = try await queue.markFiled(
                id,
                attemptId: attempt.id,
                response: response
            )
            return result(
                from: updated,
                roomName: destination.name,
                fallbackStatus: .filed,
                fallbackCategory: nil,
                fallbackMessage: nil
            )
        } catch let error as DialecticAPIError {
            if error.isTransient {
                let updated = try? await queue.markPending(
                    id,
                    attemptId: attemptId,
                    category: error.category,
                    message: bounded(error.localizedDescription)
                )
                return result(
                    from: updated,
                    roomName: destination.name,
                    fallbackStatus: .pending,
                    fallbackCategory: error.category,
                    fallbackMessage: bounded(error.localizedDescription)
                )
            }
            return await needsAttention(
                id,
                roomName: destination.name,
                attemptId: attemptId,
                category: error.category,
                message: error.localizedDescription
            )
        } catch {
            return await needsAttention(
                id,
                roomName: destination.name,
                attemptId: attemptId,
                category: "client",
                message: error.localizedDescription
            )
        }
    }

    private func needsAttention(
        _ id: UUID,
        roomName: String?,
        attemptId: UUID? = nil,
        category: String,
        message: String
    ) async -> NativeQueueResult {
        let updated = try? await queue.markNeedsAttention(
            id,
            attemptId: attemptId,
            category: category,
            message: bounded(message)
        )
        return result(
            from: updated,
            roomName: roomName,
            fallbackStatus: .needsAttention,
            fallbackCategory: category,
            fallbackMessage: bounded(message)
        )
    }

    private func result(
        from capture: QueuedCapture?,
        roomName: String?,
        fallbackStatus: DeliveryStatus,
        fallbackCategory: String?,
        fallbackMessage: String?
    ) -> NativeQueueResult {
        let status = capture?.state.status ?? fallbackStatus
        return NativeQueueResult(
            localDurable: true,
            deliveryStatus: status,
            roomName: roomName,
            errorCategory: status == .filed
                ? nil
                : capture?.state.errorCategory ?? fallbackCategory,
            errorMessage: status == .filed
                ? nil
                : capture?.state.lastError ?? fallbackMessage
        )
    }

    private func bounded(_ value: String, maximum: Int = 180) -> String {
        let normalized = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard normalized.count > maximum else { return normalized }
        return String(normalized.prefix(maximum - 1)) + "…"
    }
}

struct CaptureRuntime: Sendable {
    let configuration: AppConfiguration
    let queue: CaptureQueue
    let credentials: any CredentialVault
    let preferences: CapturePreferences
    let api: DialecticAPIClient
    let delivery: CaptureDeliveryService

    static func live(bundle: Bundle = .main) throws -> CaptureRuntime {
        let configuration = try AppConfiguration.live(bundle: bundle)
        let queue = try CaptureQueue(configuration: configuration)
        let credentials = KeychainCredentialStore(
            accessGroup: configuration.appGroupIdentifier
        )
        let preferences = try CapturePreferences(
            appGroupIdentifier: configuration.appGroupIdentifier
        )
        let api = DialecticAPIClient(
            configuration: configuration,
            credentials: credentials
        )
        let delivery = CaptureDeliveryService(
            queue: queue,
            api: api,
            preferences: preferences
        )
        return CaptureRuntime(
            configuration: configuration,
            queue: queue,
            credentials: credentials,
            preferences: preferences,
            api: api,
            delivery: delivery
        )
    }
}
