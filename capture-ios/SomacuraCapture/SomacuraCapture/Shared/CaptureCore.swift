import CryptoKit
import Darwin
import Foundation

enum CaptureMode: String, Codable, Sendable, CaseIterable {
    case selection
    case article
    case pageFallback = "page_fallback"
}

enum DeliveryStatus: String, Codable, Sendable, CaseIterable {
    case pending
    case filing
    case filed
    case needsAttention = "needs_attention"
}

struct CaptureExtraction: Codable, Sendable, Equatable {
    let engine: String
    let engineVersion: String
    let clientVersion: String
    let fallbackReason: String?
}

struct CaptureEnvelope: Codable, Sendable, Equatable, Identifiable {
    let captureId: UUID
    let url: URL
    let canonicalUrl: URL?
    let title: String
    let author: String?
    let site: String?
    let published: String?
    let description: String?
    let language: String?
    let wordCount: Int
    let captureMode: CaptureMode
    let markdown: String
    let contentSha256: String
    let capturedAt: Date
    let note: String?
    let extraction: CaptureExtraction

    var id: UUID { captureId }
    var logicalURL: URL { canonicalUrl ?? url }
}

struct CaptureMetadata: Codable, Sendable, Equatable {
    let captureId: UUID
    let url: URL
    let canonicalUrl: URL?
    let title: String
    let author: String?
    let site: String?
    let published: String?
    let description: String?
    let language: String?
    let wordCount: Int
    let captureMode: CaptureMode
    let contentSha256: String
    let capturedAt: Date
    let note: String?
    let extraction: CaptureExtraction

    init(_ envelope: CaptureEnvelope) {
        captureId = envelope.captureId
        url = envelope.url
        canonicalUrl = envelope.canonicalUrl
        title = envelope.title
        author = envelope.author
        site = envelope.site
        published = envelope.published
        description = envelope.description
        language = envelope.language
        wordCount = envelope.wordCount
        captureMode = envelope.captureMode
        contentSha256 = envelope.contentSha256
        capturedAt = envelope.capturedAt
        note = envelope.note
        extraction = envelope.extraction
    }

    func envelope(markdown: String) -> CaptureEnvelope {
        CaptureEnvelope(
            captureId: captureId,
            url: url,
            canonicalUrl: canonicalUrl,
            title: title,
            author: author,
            site: site,
            published: published,
            description: description,
            language: language,
            wordCount: wordCount,
            captureMode: captureMode,
            markdown: markdown,
            contentSha256: contentSha256,
            capturedAt: capturedAt,
            note: note,
            extraction: extraction
        )
    }
}

struct CaptureState: Codable, Sendable, Equatable {
    var status: DeliveryStatus
    var attempts: Int
    var attemptId: UUID?
    var lastAttemptAt: Date?
    var lastError: String?
    var errorCategory: String?
    var destinationRoomId: UUID?
    var destinationRoomName: String?
    var readingId: UUID?
    var revisionId: UUID?
    var filedAt: Date?

    static let pending = CaptureState(
        status: .pending,
        attempts: 0,
        attemptId: nil,
        lastAttemptAt: nil,
        lastError: nil,
        errorCategory: nil,
        destinationRoomId: nil,
        destinationRoomName: nil,
        readingId: nil,
        revisionId: nil,
        filedAt: nil
    )
}

struct FilingAttempt: Sendable, Equatable {
    let id: UUID
    let capture: QueuedCapture
}

struct QueuedCapture: Identifiable, Sendable, Equatable {
    let id: UUID
    let envelope: CaptureEnvelope?
    let state: CaptureState
    let directoryURL: URL

    var contentURL: URL { directoryURL.appendingPathComponent("content.md") }
    var displayTitle: String { envelope?.title ?? "Malformed capture \(id.uuidString.prefix(8))" }
}

struct RoomDestination: Codable, Sendable, Equatable, Identifiable, Hashable {
    let id: UUID
    let name: String
    let token: String
    let isHome: Bool
}

struct TokenCredentials: Codable, Sendable, Equatable {
    let accessToken: String
    let refreshToken: String
    let userId: UUID
    let displayName: String?
}

struct CaptureServerResponse: Codable, Sendable, Equatable {
    struct Reading: Codable, Sendable, Equatable {
        let id: UUID
        let roomId: UUID
        let url: URL
        let title: String?
        let site: String?
        let source: String
        let currentRevisionId: UUID?
        let currentCapturedAt: Date?
        let contentSha256: String?
    }

    struct Revision: Codable, Sendable, Equatable {
        let id: UUID
        let captureId: UUID
        let captureMode: CaptureMode
        let contentSha256: String
        let capturedAt: Date
        let receivedAt: Date
        let isCurrent: Bool
    }

    let reading: Reading
    let revision: Revision
    let idempotentReplay: Bool
}

struct NativeQueueRequest: Codable, Sendable {
    let type: String
    let capture: CaptureEnvelope
}

struct NativeQueueResult: Codable, Sendable, Equatable {
    let localDurable: Bool
    let deliveryStatus: DeliveryStatus
    let roomName: String?
    let errorCategory: String?
    let errorMessage: String?
}

enum CaptureJSON {
    static func encoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.dateEncodingStrategy = .custom { date, encoder in
            var container = encoder.singleValueContainer()
            try container.encode(ISO8601DateFormatter.capture.string(from: date))
        }
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return encoder
    }

    static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .custom { decoder in
            let value = try decoder.singleValueContainer().decode(String.self)
            if let date = ISO8601DateFormatter.capture.date(from: value)
                ?? ISO8601DateFormatter.standard.date(from: value) {
                return date
            }
            throw DecodingError.dataCorruptedError(
                in: try decoder.singleValueContainer(),
                debugDescription: "Invalid ISO-8601 date"
            )
        }
        return decoder
    }
}

private extension ISO8601DateFormatter {
    static var capture: ISO8601DateFormatter {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }

    static var standard: ISO8601DateFormatter {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }
}

enum CaptureError: LocalizedError, Sendable, Equatable {
    case appGroupUnavailable(String)
    case invalidCapture(String)
    case captureCollision(UUID)
    case queueCorrupt(UUID, String)
    case queueLock(String)
    case missingCapture(UUID)

    var errorDescription: String? {
        switch self {
        case .appGroupUnavailable:
            "The App Group container is unavailable. Check signing and App Group configuration."
        case .invalidCapture(let reason):
            "The browser capture is invalid: \(reason)"
        case .captureCollision(let id):
            "Capture \(id.uuidString.prefix(8)) already exists with different content."
        case .queueCorrupt(let id, let reason):
            "Capture \(id.uuidString.prefix(8)) needs attention: \(reason)"
        case .queueLock(let reason):
            "The shared capture queue could not be locked: \(reason)"
        case .missingCapture(let id):
            "Capture \(id.uuidString.prefix(8)) is missing."
        }
    }
}

struct AppConfiguration: Sendable, Equatable {
    static let appGroupInfoKey = "SomacuraAppGroupIdentifier"
    static let placeholderPrefix = "com.example.unconfigured"

    let baseURL: URL
    let appGroupIdentifier: String
    let nativeApplicationIdentifier: String

    var signingIsConfigured: Bool {
        !appGroupIdentifier.contains(Self.placeholderPrefix)
            && !nativeApplicationIdentifier.contains(Self.placeholderPrefix)
    }

    static func live(bundle: Bundle = .main) throws -> AppConfiguration {
        guard let appGroup = bundle.object(
            forInfoDictionaryKey: appGroupInfoKey
        ) as? String, !appGroup.isEmpty else {
            throw CaptureError.appGroupUnavailable("missing Info.plist key")
        }
        guard let nativeIdentifier = bundle.bundleIdentifier else {
            throw CaptureError.appGroupUnavailable("missing bundle identifier")
        }
        return AppConfiguration(
            baseURL: URL(string: "https://dialectic.somacura.org")!,
            appGroupIdentifier: appGroup,
            nativeApplicationIdentifier: nativeIdentifier
        )
    }
}

actor CapturePreferences {
    private let defaults: UserDefaults
    private let destinationKey = "capture.default-room"

    init(appGroupIdentifier: String) throws {
        guard let defaults = UserDefaults(suiteName: appGroupIdentifier) else {
            throw CaptureError.appGroupUnavailable(appGroupIdentifier)
        }
        self.defaults = defaults
    }

    init(defaults: UserDefaults) {
        self.defaults = defaults
    }

    func defaultRoom() throws -> RoomDestination? {
        guard let data = defaults.data(forKey: destinationKey) else { return nil }
        return try CaptureJSON.decoder().decode(RoomDestination.self, from: data)
    }

    func setDefaultRoom(_ room: RoomDestination?) throws {
        if let room {
            defaults.set(try CaptureJSON.encoder().encode(room), forKey: destinationKey)
        } else {
            defaults.removeObject(forKey: destinationKey)
        }
    }
}

actor CaptureQueue {
    static let maximumMarkdownBytes = 2_000_000

    private let fileManager: FileManager
    private let capturesURL: URL

    init(configuration: AppConfiguration, fileManager: FileManager = .default) throws {
        guard let container = fileManager.containerURL(
            forSecurityApplicationGroupIdentifier: configuration.appGroupIdentifier
        ) else {
            throw CaptureError.appGroupUnavailable(configuration.appGroupIdentifier)
        }
        self.fileManager = fileManager
        capturesURL = container.appendingPathComponent("Captures", isDirectory: true)
        try Self.prepareDirectory(capturesURL, fileManager: fileManager)
    }

    init(rootURL: URL, fileManager: FileManager = .default) throws {
        self.fileManager = fileManager
        capturesURL = rootURL.appendingPathComponent("Captures", isDirectory: true)
        try Self.prepareDirectory(capturesURL, fileManager: fileManager)
    }

    func commit(_ envelope: CaptureEnvelope) throws -> QueuedCapture {
        try withExclusiveFileLock {
            try commitUnlocked(envelope)
        }
    }

    private func commitUnlocked(_ envelope: CaptureEnvelope) throws -> QueuedCapture {
        try validate(envelope)
        let finalURL = captureDirectory(envelope.captureId)
        if fileManager.fileExists(atPath: finalURL.path) {
            return try resolveExisting(envelope, at: finalURL)
        }

        let stagingURL = capturesURL.appendingPathComponent(
            ".staging-\(envelope.captureId.uuidString)-\(UUID().uuidString)",
            isDirectory: true
        )
        try Self.prepareDirectory(stagingURL, fileManager: fileManager)
        do {
            try protectedWrite(
                CaptureJSON.encoder().encode(CaptureMetadata(envelope)),
                to: stagingURL.appendingPathComponent("capture.json")
            )
            try protectedWrite(
                Data(envelope.markdown.utf8),
                to: stagingURL.appendingPathComponent("content.md")
            )
            try protectedWrite(
                CaptureJSON.encoder().encode(CaptureState.pending),
                to: stagingURL.appendingPathComponent("state.json")
            )
            do {
                try fileManager.moveItem(at: stagingURL, to: finalURL)
            } catch where fileManager.fileExists(atPath: finalURL.path) {
                try? fileManager.removeItem(at: stagingURL)
                return try resolveExisting(envelope, at: finalURL)
            }
        } catch {
            try? fileManager.removeItem(at: stagingURL)
            throw error
        }
        return try load(envelope.captureId)
    }

    func load(_ id: UUID) throws -> QueuedCapture {
        let directory = captureDirectory(id)
        let directoryDescriptor = try openCaptureDirectory(id)
        defer { close(directoryDescriptor) }
        do {
            let metadata = try CaptureJSON.decoder().decode(
                CaptureMetadata.self,
                from: try readRegularFile(
                    named: "capture.json",
                    directoryDescriptor: directoryDescriptor,
                    id: id,
                    maximumBytes: 65_536
                )
            )
            guard metadata.captureId == id else {
                throw CaptureError.queueCorrupt(id, "directory and metadata IDs differ")
            }
            let content = try readRegularFile(
                named: "content.md",
                directoryDescriptor: directoryDescriptor,
                id: id,
                maximumBytes: Self.maximumMarkdownBytes
            )
            guard let markdown = String(data: content, encoding: .utf8) else {
                throw CaptureError.queueCorrupt(id, "content.md is not UTF-8")
            }
            let state = try CaptureJSON.decoder().decode(
                CaptureState.self,
                from: try readRegularFile(
                    named: "state.json",
                    directoryDescriptor: directoryDescriptor,
                    id: id,
                    maximumBytes: 65_536
                )
            )
            let envelope = metadata.envelope(markdown: markdown)
            try validate(envelope)
            return QueuedCapture(id: id, envelope: envelope, state: state, directoryURL: directory)
        } catch let error as CaptureError {
            throw error
        } catch {
            throw CaptureError.queueCorrupt(id, error.localizedDescription)
        }
    }

    func list() throws -> [QueuedCapture] {
        let urls = try fileManager.contentsOfDirectory(
            at: capturesURL,
            includingPropertiesForKeys: [.isDirectoryKey, .isSymbolicLinkKey],
            options: [.skipsHiddenFiles]
        )
        let captures = urls.compactMap { url -> QueuedCapture? in
            guard let id = UUID(uuidString: url.lastPathComponent) else { return nil }
            do {
                return try load(id)
            } catch {
                let state = CaptureState(
                    status: .needsAttention,
                    attempts: 0,
                    attemptId: nil,
                    lastAttemptAt: nil,
                    lastError: error.localizedDescription,
                    errorCategory: "queue_corrupt",
                    destinationRoomId: nil,
                    destinationRoomName: nil,
                    readingId: nil,
                    revisionId: nil,
                    filedAt: nil
                )
                return QueuedCapture(id: id, envelope: nil, state: state, directoryURL: url)
            }
        }
        return captures.sorted { lhs, rhs in
            let lhsPriority = Self.priority(lhs.state.status)
            let rhsPriority = Self.priority(rhs.state.status)
            if lhsPriority != rhsPriority { return lhsPriority < rhsPriority }
            return (lhs.envelope?.capturedAt ?? .distantPast)
                > (rhs.envelope?.capturedAt ?? .distantPast)
        }
    }

    func markFiling(
        _ id: UUID,
        destination: RoomDestination,
        now: Date = Date(),
        attemptId: UUID = UUID()
    ) throws -> FilingAttempt? {
        try withExclusiveFileLock {
            let current = try load(id)
            guard ![.filing, .filed].contains(current.state.status) else {
                return nil
            }
            let capture = try mutateState(id) { state in
                state.status = .filing
                state.attempts += 1
                state.attemptId = attemptId
                state.lastAttemptAt = now
                state.lastError = nil
                state.errorCategory = nil
                state.destinationRoomId = destination.id
                state.destinationRoomName = destination.name
            }
            return FilingAttempt(id: attemptId, capture: capture)
        }
    }

    func markPending(
        _ id: UUID,
        attemptId: UUID? = nil,
        category: String?,
        message: String?
    ) throws -> QueuedCapture {
        try withExclusiveFileLock {
            try mutateState(id) { state in
                guard Self.canSettle(state, attemptId: attemptId) else { return }
                state.status = .pending
                state.attemptId = nil
                state.errorCategory = category
                state.lastError = message
            }
        }
    }

    func markNeedsAttention(
        _ id: UUID,
        attemptId: UUID? = nil,
        category: String,
        message: String
    ) throws -> QueuedCapture {
        try withExclusiveFileLock {
            try mutateState(id) { state in
                guard Self.canSettle(state, attemptId: attemptId) else { return }
                state.status = .needsAttention
                state.attemptId = nil
                state.errorCategory = category
                state.lastError = message
            }
        }
    }

    func markFiled(
        _ id: UUID,
        attemptId: UUID,
        response: CaptureServerResponse,
        now: Date = Date()
    ) throws -> QueuedCapture {
        try withExclusiveFileLock {
            try mutateState(id) { state in
                guard state.status == .filing, state.attemptId == attemptId else { return }
                state.status = .filed
                state.attemptId = nil
                state.errorCategory = nil
                state.lastError = nil
                state.readingId = response.reading.id
                state.revisionId = response.revision.id
                state.filedAt = now
            }
        }
    }

    func recoverInterruptedAttempts(
        now: Date = Date(),
        filingTimeout: TimeInterval = 120
    ) throws {
        try withExclusiveFileLock {
            let urls = try fileManager.contentsOfDirectory(
                at: capturesURL,
                includingPropertiesForKeys: [.isDirectoryKey],
                options: []
            )
            for url in urls where url.lastPathComponent.hasPrefix(".staging-") {
                try? fileManager.removeItem(at: url)
            }
            for url in urls {
                guard let id = UUID(uuidString: url.lastPathComponent),
                      let capture = try? load(id),
                      capture.state.status == .filing else { continue }
                let started = capture.state.lastAttemptAt ?? .distantPast
                if now.timeIntervalSince(started) >= filingTimeout {
                    _ = try mutateState(id) { state in
                        guard state.status == .filing,
                              state.attemptId == capture.state.attemptId else { return }
                        state.status = .pending
                        state.attemptId = nil
                        state.errorCategory = "interrupted"
                        state.lastError = "A filing attempt was interrupted and is ready to retry."
                    }
                }
            }
        }
    }

    func markdown(_ id: UUID) throws -> String {
        guard let envelope = try load(id).envelope else {
            throw CaptureError.queueCorrupt(id, "capture metadata is unreadable")
        }
        return envelope.markdown
    }

    func delete(_ id: UUID) throws {
        try withExclusiveFileLock {
            let directory = captureDirectory(id)
            guard fileManager.fileExists(atPath: directory.path) else {
                throw CaptureError.missingCapture(id)
            }
            try validateDirectory(directory, id: id)
            try fileManager.removeItem(at: directory)
        }
    }

    private func resolveExisting(
        _ envelope: CaptureEnvelope,
        at directory: URL
    ) throws -> QueuedCapture {
        let existing = try load(envelope.captureId)
        guard existing.envelope == envelope else {
            _ = try? mutateState(envelope.captureId) { state in
                guard ![.filing, .filed].contains(state.status) else { return }
                state.status = .needsAttention
                state.attemptId = nil
                state.errorCategory = "capture_collision"
                state.lastError = "This capture ID already belongs to different immutable content."
            }
            throw CaptureError.captureCollision(envelope.captureId)
        }
        return existing
    }

    private func mutateState(
        _ id: UUID,
        _ mutate: (inout CaptureState) -> Void
    ) throws -> QueuedCapture {
        let capture = try load(id)
        var state = capture.state
        mutate(&state)
        try writeState(state, id: id)
        return QueuedCapture(
            id: id,
            envelope: capture.envelope,
            state: state,
            directoryURL: capture.directoryURL
        )
    }

    private func writeState(_ state: CaptureState, id: UUID) throws {
        let directoryDescriptor = try openCaptureDirectory(id)
        defer { close(directoryDescriptor) }
        try atomicWriteRegularFile(
            CaptureJSON.encoder().encode(state),
            named: "state.json",
            directoryDescriptor: directoryDescriptor,
            id: id
        )
    }

    private func validate(_ envelope: CaptureEnvelope) throws {
        try validateHTTPURL(envelope.url, label: "source URL")
        if let canonicalURL = envelope.canonicalUrl {
            try validateHTTPURL(canonicalURL, label: "canonical URL")
        }
        try validateLength(envelope.title, maximum: 1_000, label: "title")
        try validateLength(envelope.author, maximum: 500, label: "author")
        try validateLength(envelope.site, maximum: 500, label: "site")
        try validateLength(envelope.published, maximum: 500, label: "published")
        try validateLength(envelope.description, maximum: 2_000, label: "description")
        try validateLength(envelope.language, maximum: 64, label: "language")
        try validateLength(envelope.note, maximum: 2_000, label: "note")
        guard (0...100_000_000).contains(envelope.wordCount) else {
            throw CaptureError.invalidCapture("word count is outside the server contract")
        }
        guard envelope.capturedAt <= Date().addingTimeInterval(86_400) else {
            throw CaptureError.invalidCapture("capture time is implausibly far in the future")
        }
        try validateLength(
            envelope.extraction.engine,
            minimum: 1,
            maximum: 100,
            label: "extraction engine"
        )
        try validateLength(
            envelope.extraction.engineVersion,
            minimum: 1,
            maximum: 100,
            label: "extraction engine version"
        )
        try validateLength(
            envelope.extraction.clientVersion,
            minimum: 1,
            maximum: 100,
            label: "capture client version"
        )
        try validateLength(
            envelope.extraction.fallbackReason,
            maximum: 1_000,
            label: "fallback reason"
        )
        let content = Data(envelope.markdown.utf8)
        guard !envelope.markdown.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw CaptureError.invalidCapture("Markdown is empty")
        }
        guard !envelope.markdown.contains("\0") else {
            throw CaptureError.invalidCapture("Markdown contains NUL")
        }
        guard content.count <= Self.maximumMarkdownBytes else {
            throw CaptureError.invalidCapture("Markdown exceeds 2,000,000 UTF-8 bytes")
        }
        let hash = SHA256.hash(data: content).map { String(format: "%02x", $0) }.joined()
        guard hash == envelope.contentSha256 else {
            throw CaptureError.invalidCapture("SHA-256 does not match content.md")
        }
    }

    private func validateHTTPURL(_ url: URL, label: String) throws {
        let value = url.absoluteString
        guard value.count <= 4_096,
              value.rangeOfCharacter(from: .whitespacesAndNewlines) == nil,
              value.rangeOfCharacter(from: .controlCharacters) == nil,
              ["http", "https"].contains(url.scheme?.lowercased() ?? ""),
              url.host?.isEmpty == false else {
            throw CaptureError.invalidCapture(
                "\(label) must be a hostful HTTP or HTTPS URL within 4,096 characters"
            )
        }
    }

    private func validateLength(
        _ value: String?,
        minimum: Int = 0,
        maximum: Int,
        label: String
    ) throws {
        guard let value else { return }
        guard (minimum...maximum).contains(value.count) else {
            throw CaptureError.invalidCapture(
                "\(label) must contain \(minimum)...\(maximum) characters"
            )
        }
    }

    private func captureDirectory(_ id: UUID) -> URL {
        capturesURL.appendingPathComponent(id.uuidString, isDirectory: true)
    }

    private func protectedWrite(_ data: Data, to url: URL) throws {
        try data.write(to: url, options: [.atomic, .completeFileProtection])
    }

    private func withExclusiveFileLock<Value>(
        _ operation: () throws -> Value
    ) throws -> Value {
        let directoryDescriptor = open(
            capturesURL.path,
            O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW
        )
        guard directoryDescriptor >= 0 else {
            throw CaptureError.queueLock(
                "queue directory: \(String(cString: strerror(errno)))"
            )
        }
        defer { close(directoryDescriptor) }
        // Lock the no-follow directory descriptor itself. Every app/extension
        // process opens the same App Group directory inode, and no child lock
        // path remains that could be swapped or followed.
        guard flock(directoryDescriptor, LOCK_EX) == 0 else {
            throw CaptureError.queueLock(String(cString: strerror(errno)))
        }
        defer { flock(directoryDescriptor, LOCK_UN) }
        return try operation()
    }

    private func validateDirectory(_ url: URL, id: UUID) throws {
        let descriptor = open(
            url.path,
            O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW
        )
        guard descriptor >= 0 else {
            throw CaptureError.queueCorrupt(id, "queue entry is not a regular directory")
        }
        close(descriptor)
    }

    private func openCaptureDirectory(_ id: UUID) throws -> Int32 {
        let descriptor = open(
            captureDirectory(id).path,
            O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW
        )
        guard descriptor >= 0 else {
            if errno == ENOENT { throw CaptureError.missingCapture(id) }
            throw CaptureError.queueCorrupt(id, "queue entry is not a regular directory")
        }
        return descriptor
    }

    private func readRegularFile(
        named name: String,
        directoryDescriptor: Int32,
        id: UUID,
        maximumBytes: Int
    ) throws -> Data {
        let descriptor = openat(
            directoryDescriptor,
            name,
            O_RDONLY | O_CLOEXEC | O_NOFOLLOW
        )
        guard descriptor >= 0 else {
            throw CaptureError.queueCorrupt(id, "\(name) is not a readable regular file")
        }
        defer { close(descriptor) }
        var fileStatus = stat()
        guard fstat(descriptor, &fileStatus) == 0,
              fileStatus.st_mode & S_IFMT == S_IFREG,
              fileStatus.st_size >= 0,
              fileStatus.st_size <= maximumBytes else {
            throw CaptureError.queueCorrupt(id, "\(name) is not a bounded regular file")
        }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: false)
        let data = try handle.readToEnd() ?? Data()
        guard data.count <= maximumBytes else {
            throw CaptureError.queueCorrupt(id, "\(name) exceeds its local size limit")
        }
        return data
    }

    private func atomicWriteRegularFile(
        _ data: Data,
        named name: String,
        directoryDescriptor: Int32,
        id: UUID
    ) throws {
        var existingStatus = stat()
        if fstatat(
            directoryDescriptor,
            name,
            &existingStatus,
            AT_SYMLINK_NOFOLLOW
        ) == 0 {
            guard existingStatus.st_mode & S_IFMT == S_IFREG else {
                throw CaptureError.queueCorrupt(id, "\(name) is not a regular file")
            }
        } else if errno != ENOENT {
            throw CaptureError.queueCorrupt(id, "\(name) could not be inspected")
        }

        let temporaryName = ".state-\(UUID().uuidString).tmp"
        let descriptor = openat(
            directoryDescriptor,
            temporaryName,
            O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW,
            S_IRUSR | S_IWUSR
        )
        guard descriptor >= 0 else {
            throw CaptureError.queueCorrupt(id, "state staging file could not be created")
        }
        var temporaryExists = true
        defer {
            close(descriptor)
            if temporaryExists {
                unlinkat(directoryDescriptor, temporaryName, 0)
            }
        }

        let temporaryURL = captureDirectory(id).appendingPathComponent(temporaryName)
        var descriptorStatus = stat()
        guard fstat(descriptor, &descriptorStatus) == 0 else {
            throw CaptureError.queueCorrupt(id, "state staging file could not be inspected")
        }
        try fileManager.setAttributes(
            [.protectionKey: FileProtectionType.complete],
            ofItemAtPath: temporaryURL.path
        )
        var protectedStatus = stat()
        let protectionAttributes = try fileManager.attributesOfItem(
            atPath: temporaryURL.path
        )
        let protection = protectionAttributes[.protectionKey] as? FileProtectionType
        #if targetEnvironment(simulator)
        let protectionIsValid = protection == nil || protection == .complete
        #else
        let protectionIsValid = protection == .complete
        #endif
        guard lstat(temporaryURL.path, &protectedStatus) == 0,
              protectedStatus.st_mode & S_IFMT == S_IFREG,
              protectedStatus.st_dev == descriptorStatus.st_dev,
              protectedStatus.st_ino == descriptorStatus.st_ino,
              protectionIsValid else {
            throw CaptureError.queueCorrupt(
                id,
                "state staging file is not fully protected (\(String(describing: protection)))"
            )
        }

        var writeError: Int32?
        data.withUnsafeBytes { bytes in
            var offset = 0
            while offset < bytes.count {
                guard let baseAddress = bytes.baseAddress else { break }
                let count = Darwin.write(
                    descriptor,
                    baseAddress.advanced(by: offset),
                    bytes.count - offset
                )
                if count < 0 {
                    writeError = errno
                    break
                }
                offset += count
            }
        }
        if let writeError {
            throw CaptureError.queueCorrupt(
                id,
                "state write failed: \(String(cString: strerror(writeError)))"
            )
        }
        guard fsync(descriptor) == 0 else {
            throw CaptureError.queueCorrupt(id, "state file could not be synchronized")
        }
        guard renameat(
            directoryDescriptor,
            temporaryName,
            directoryDescriptor,
            name
        ) == 0 else {
            throw CaptureError.queueCorrupt(id, "state file could not be committed")
        }
        temporaryExists = false
    }

    private static func prepareDirectory(
        _ url: URL,
        fileManager: FileManager
    ) throws {
        try fileManager.createDirectory(
            at: url,
            withIntermediateDirectories: true,
            attributes: [.protectionKey: FileProtectionType.complete]
        )
    }

    private static func priority(_ status: DeliveryStatus) -> Int {
        switch status {
        case .needsAttention: 0
        case .pending, .filing: 1
        case .filed: 2
        }
    }

    private static func canSettle(
        _ state: CaptureState,
        attemptId: UUID?
    ) -> Bool {
        if let attemptId {
            return state.status == .filing && state.attemptId == attemptId
        }
        return ![.filing, .filed].contains(state.status)
    }
}
