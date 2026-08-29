import CryptoKit
import Foundation
import XCTest
@testable import SomacuraCapture

actor InMemoryCredentialVault: CredentialVault {
    var value: TokenCredentials?

    init(_ value: TokenCredentials? = nil) {
        self.value = value
    }

    func load() -> TokenCredentials? { value }
    func save(_ credentials: TokenCredentials) { value = credentials }
    func delete() { value = nil }
}

final class StubURLProtocol: URLProtocol {
    nonisolated(unsafe) static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        do {
            guard let handler = Self.handler else { throw URLError(.badServerResponse) }
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

final class DialecticAPIClientTests: XCTestCase {
    override func tearDown() {
        StubURLProtocol.handler = nil
        super.tearDown()
    }

    func testCaptureUsesBearerRoomTokenAndExactMarkdown() async throws {
        let credentials = TokenCredentials(
            accessToken: "access-one",
            refreshToken: "refresh-one",
            userId: UUID(),
            displayName: "Amo"
        )
        let vault = InMemoryCredentialVault(credentials)
        let client = makeClient(vault: vault)
        let destination = RoomDestination(
            id: UUID(uuidString: "00000000-0000-4000-8000-000000000020")!,
            name: "Research",
            token: "room-token",
            isHome: false
        )
        let envelope = makeEnvelope()
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer access-one")
            XCTAssertEqual(request.value(forHTTPHeaderField: "X-Room-Token"), "room-token")
            let body = try self.bodyData(request)
            XCTAssertEqual(
                try CaptureJSON.decoder().decode(CaptureEnvelope.self, from: body),
                envelope
            )
            return (
                self.response(url: request.url!, status: 200),
                self.serverResponse(envelope, roomId: destination.id)
            )
        }

        let result = try await client.file(envelope, to: destination)
        XCTAssertEqual(result.revision.captureId, envelope.captureId)
    }

    func testOne401RefreshesAndRetriesOnceWithReplacementToken() async throws {
        let vault = InMemoryCredentialVault(TokenCredentials(
            accessToken: "expired",
            refreshToken: "refresh-one",
            userId: UUID(uuidString: "00000000-0000-4000-8000-000000000030")!,
            displayName: "Amo"
        ))
        let client = makeClient(vault: vault)
        let destination = RoomDestination(id: UUID(), name: "Research", token: "room", isHome: false)
        let envelope = makeEnvelope()
        var captureCalls = 0
        StubURLProtocol.handler = { request in
            if request.url?.path == "/auth/refresh" {
                return (
                    self.response(url: request.url!, status: 200),
                    try CaptureJSON.encoder().encode([
                        "access_token": "fresh",
                        "refresh_token": "refresh-two",
                        "user_id": "00000000-0000-4000-8000-000000000030",
                        "display_name": "Amo",
                    ])
                )
            }
            captureCalls += 1
            if captureCalls == 1 {
                return (
                    self.response(url: request.url!, status: 401),
                    Data("{\"detail\":\"expired\"}".utf8)
                )
            }
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer fresh")
            return (
                self.response(url: request.url!, status: 200),
                self.serverResponse(envelope, roomId: destination.id)
            )
        }

        _ = try await client.file(envelope, to: destination)
        XCTAssertEqual(captureCalls, 2)
        let storedCredentials = await vault.load()
        XCTAssertEqual(storedCredentials?.accessToken, "fresh")
    }

    func testRevokedRefreshDeletesStoredCredentials() async throws {
        let vault = InMemoryCredentialVault(TokenCredentials(
            accessToken: "expired",
            refreshToken: "revoked",
            userId: UUID(),
            displayName: "Amo"
        ))
        let client = makeClient(vault: vault)
        StubURLProtocol.handler = { request in
            if request.url?.path == "/auth/refresh" {
                return (
                    self.response(url: request.url!, status: 401),
                    Data("{\"detail\":\"Session not found or revoked\"}".utf8)
                )
            }
            return (
                self.response(url: request.url!, status: 401),
                Data("{\"detail\":\"expired\"}".utf8)
            )
        }

        do {
            _ = try await client.rooms()
            XCTFail("Expected revoked session")
        } catch let error as DialecticAPIError {
            XCTAssertEqual(error, .notAuthenticated)
        }
        let stored = await vault.load()
        XCTAssertNil(stored)
    }

    func testRoomToken401AfterRefreshPreservesAccountCredentials() async throws {
        let userId = UUID()
        let vault = InMemoryCredentialVault(TokenCredentials(
            accessToken: "expired",
            refreshToken: "valid-refresh",
            userId: userId,
            displayName: "Amo"
        ))
        let client = makeClient(vault: vault)
        let destination = RoomDestination(
            id: UUID(), name: "Stale Room", token: "stale-room-token", isHome: false
        )
        StubURLProtocol.handler = { request in
            if request.url?.path == "/auth/refresh" {
                return (
                    self.response(url: request.url!, status: 200),
                    try CaptureJSON.encoder().encode([
                        "access_token": "fresh",
                        "refresh_token": "valid-refresh",
                        "user_id": userId.uuidString,
                        "display_name": "Amo",
                    ])
                )
            }
            return (
                self.response(url: request.url!, status: 401),
                Data("{\"detail\":\"Invalid room token\"}".utf8)
            )
        }

        do {
            _ = try await client.file(makeEnvelope(), to: destination)
            XCTFail("Expected stale room token to remain a room error")
        } catch let error as DialecticAPIError {
            XCTAssertEqual(
                error,
                .server(status: 401, detail: "Invalid room token")
            )
        }
        let stored = await vault.load()
        XCTAssertEqual(stored?.accessToken, "fresh")
    }

    func testNoRoomStillCommitsLocallyAndReturnsQueued() async throws {
        let fixture = try deliveryFixture()
        defer { fixture.cleanup() }
        StubURLProtocol.handler = { _ in
            XCTFail("No destination must not touch the network")
            throw URLError(.badServerResponse)
        }

        let result = try await fixture.delivery.queueAndFile(makeEnvelope())

        XCTAssertTrue(result.localDurable)
        XCTAssertEqual(result.deliveryStatus, .pending)
        XCTAssertEqual(result.errorCategory, "no_room")
        let queued = try await fixture.queue.list()
        XCTAssertEqual(queued.first?.state.status, .pending)
    }

    func testServerFailureClassificationKeepsExactLocalArtifact() async throws {
        for (status, expected) in [(503, DeliveryStatus.pending), (422, .needsAttention)] {
            let fixture = try deliveryFixture()
            defer { fixture.cleanup() }
            try await fixture.preferences.setDefaultRoom(
                RoomDestination(id: UUID(), name: "Research", token: "room", isHome: false)
            )
            StubURLProtocol.handler = { request in
                (
                    self.response(url: request.url!, status: status),
                    Data("{\"detail\":\"server refused\"}".utf8)
                )
            }

            let envelope = makeEnvelope()
            let result = try await fixture.delivery.queueAndFile(envelope)

            XCTAssertEqual(result.deliveryStatus, expected)
            let storedMarkdown = try await fixture.queue.markdown(envelope.captureId)
            XCTAssertEqual(storedMarkdown, envelope.markdown)
        }
    }

    func testFiledCaptureKeepsItsDestinationAfterDefaultChanges() async throws {
        let fixture = try deliveryFixture()
        defer { fixture.cleanup() }
        let filedRoom = RoomDestination(
            id: UUID(uuidString: "00000000-0000-4000-8000-000000000060")!,
            name: "Filed Room",
            token: "filed-token",
            isHome: false
        )
        try await fixture.preferences.setDefaultRoom(filedRoom)
        let envelope = makeEnvelope()
        StubURLProtocol.handler = { request in
            (
                self.response(url: request.url!, status: 200),
                self.serverResponse(envelope, roomId: filedRoom.id)
            )
        }

        let result = try await fixture.delivery.queueAndFile(envelope)
        XCTAssertEqual(result.deliveryStatus, .filed)
        try await fixture.preferences.setDefaultRoom(
            RoomDestination(id: UUID(), name: "New Default", token: "new", isHome: false)
        )
        let stored = try await fixture.queue.load(envelope.captureId)
        XCTAssertEqual(stored.state.destinationRoomId, filedRoom.id)
        XCTAssertEqual(stored.state.destinationRoomName, filedRoom.name)
    }

    @MainActor
    func testModelSignsOutWhenRoomRefreshFindsRevokedSession() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("SomacuraModelTests-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let queue = try CaptureQueue(rootURL: root)
        let suite = "SomacuraModelTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let preferences = CapturePreferences(defaults: defaults)
        let vault = InMemoryCredentialVault(TokenCredentials(
            accessToken: "expired",
            refreshToken: "revoked",
            userId: UUID(),
            displayName: "Amo"
        ))
        let api = makeClient(vault: vault)
        let delivery = CaptureDeliveryService(
            queue: queue,
            api: api,
            preferences: preferences
        )
        let runtime = CaptureRuntime(
            configuration: AppConfiguration(
                baseURL: URL(string: "https://dialectic.test")!,
                appGroupIdentifier: "group.com.example.unconfigured.SomacuraCapture",
                nativeApplicationIdentifier: "com.example.unconfigured.SomacuraCapture"
            ),
            queue: queue,
            credentials: vault,
            preferences: preferences,
            api: api,
            delivery: delivery
        )
        StubURLProtocol.handler = { request in
            (
                self.response(url: request.url!, status: 401),
                Data("{\"detail\":\"revoked\"}".utf8)
            )
        }

        let model = CaptureAppModel(runtime: runtime)
        await model.start()

        XCTAssertEqual(model.session, .signedOut)
        XCTAssertTrue(model.rooms.isEmpty)
        let stored = await vault.load()
        XCTAssertNil(stored)
    }

    func testCaptureRejectsReceiptForDifferentRoomCaptureOrHash() async throws {
        let vault = InMemoryCredentialVault(TokenCredentials(
            accessToken: "access",
            refreshToken: "refresh",
            userId: UUID(),
            displayName: "Amo"
        ))
        let destination = RoomDestination(
            id: UUID(uuidString: "00000000-0000-4000-8000-000000000050")!,
            name: "Research",
            token: "room",
            isHome: false
        )
        let envelope = makeEnvelope()
        let wrongValues: [(UUID, UUID, String)] = [
            (UUID(), envelope.captureId, envelope.contentSha256),
            (destination.id, UUID(), envelope.contentSha256),
            (destination.id, envelope.captureId, String(repeating: "0", count: 64)),
        ]

        for (roomId, captureId, hash) in wrongValues {
            let client = makeClient(vault: vault)
            StubURLProtocol.handler = { request in
                let revisionId = UUID()
                let invalid = CaptureServerResponse(
                    reading: .init(
                        id: UUID(),
                        roomId: roomId,
                        url: envelope.logicalURL,
                        title: envelope.title,
                        site: envelope.site,
                        source: "browser_capture",
                        currentRevisionId: revisionId,
                        currentCapturedAt: envelope.capturedAt,
                        contentSha256: hash
                    ),
                    revision: .init(
                        id: revisionId,
                        captureId: captureId,
                        captureMode: envelope.captureMode,
                        contentSha256: hash,
                        capturedAt: envelope.capturedAt,
                        receivedAt: envelope.capturedAt,
                        isCurrent: true
                    ),
                    idempotentReplay: false
                )
                return (
                    self.response(url: request.url!, status: 200),
                    try CaptureJSON.encoder().encode(invalid)
                )
            }

            do {
                _ = try await client.file(envelope, to: destination)
                XCTFail("Expected mismatched receipt to be rejected")
            } catch let error as DialecticAPIError {
                XCTAssertEqual(error, .invalidResponse)
            }
        }
    }

    private func makeClient(vault: InMemoryCredentialVault) -> DialecticAPIClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubURLProtocol.self]
        return DialecticAPIClient(
            configuration: AppConfiguration(
                baseURL: URL(string: "https://dialectic.test")!,
                appGroupIdentifier: "group.com.example.unconfigured.SomacuraCapture",
                nativeApplicationIdentifier: "com.example.unconfigured.SomacuraCapture"
            ),
            credentials: vault,
            session: URLSession(configuration: config)
        )
    }

    private func deliveryFixture() throws -> (
        queue: CaptureQueue,
        preferences: CapturePreferences,
        delivery: CaptureDeliveryService,
        cleanup: () -> Void
    ) {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("SomacuraDeliveryTests-\(UUID().uuidString)", isDirectory: true)
        let queue = try CaptureQueue(rootURL: root)
        let suite = "SomacuraDeliveryTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        let preferences = CapturePreferences(defaults: defaults)
        let vault = InMemoryCredentialVault(TokenCredentials(
            accessToken: "access",
            refreshToken: "refresh",
            userId: UUID(),
            displayName: "Amo"
        ))
        let api = makeClient(vault: vault)
        let delivery = CaptureDeliveryService(
            queue: queue,
            api: api,
            preferences: preferences
        )
        return (
            queue,
            preferences,
            delivery,
            {
                try? FileManager.default.removeItem(at: root)
                defaults.removePersistentDomain(forName: suite)
            }
        )
    }

    private func response(url: URL, status: Int) -> HTTPURLResponse {
        HTTPURLResponse(
            url: url,
            statusCode: status,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        )!
    }

    private func bodyData(_ request: URLRequest) throws -> Data {
        if let body = request.httpBody { return body }
        let stream = try XCTUnwrap(request.httpBodyStream)
        stream.open()
        defer { stream.close() }
        var data = Data()
        let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 4096)
        defer { buffer.deallocate() }
        while stream.hasBytesAvailable {
            let count = stream.read(buffer, maxLength: 4096)
            if count < 0 { throw stream.streamError ?? URLError(.cannotDecodeContentData) }
            if count == 0 { break }
            data.append(buffer, count: count)
        }
        return data
    }

    private func makeEnvelope() -> CaptureEnvelope {
        let markdown = "# Exact\n\nBrowser body.\n"
        return CaptureEnvelope(
            captureId: UUID(uuidString: "00000000-0000-4000-8000-000000000040")!,
            url: URL(string: "https://example.com")!,
            canonicalUrl: URL(string: "https://example.com"),
            title: "Exact",
            author: nil,
            site: "Example",
            published: nil,
            description: nil,
            language: "en",
            wordCount: 4,
            captureMode: .article,
            markdown: markdown,
            contentSha256: SHA256.hash(data: Data(markdown.utf8))
                .map { String(format: "%02x", $0) }.joined(),
            capturedAt: Date(timeIntervalSince1970: 1_788_000_000),
            note: nil,
            extraction: CaptureExtraction(
                engine: "defuddle",
                engineVersion: "0.19.3",
                clientVersion: "0.1.0",
                fallbackReason: nil
            )
        )
    }

    private func serverResponse(_ envelope: CaptureEnvelope, roomId: UUID) -> Data {
        let revisionId = UUID()
        return try! CaptureJSON.encoder().encode(CaptureServerResponse(
            reading: .init(
                id: UUID(),
                roomId: roomId,
                url: envelope.logicalURL,
                title: envelope.title,
                site: envelope.site,
                source: "browser_capture",
                currentRevisionId: revisionId,
                currentCapturedAt: envelope.capturedAt,
                contentSha256: envelope.contentSha256
            ),
            revision: .init(
                id: revisionId,
                captureId: envelope.captureId,
                captureMode: envelope.captureMode,
                contentSha256: envelope.contentSha256,
                capturedAt: envelope.capturedAt,
                receivedAt: envelope.capturedAt,
                isCurrent: true
            ),
            idempotentReplay: false
        ))
    }
}
