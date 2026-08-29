import CryptoKit
import Foundation
import XCTest
@testable import SomacuraCapture

final class CaptureQueueTests: XCTestCase {
    private var rootURL: URL!
    private var queue: CaptureQueue!

    override func setUpWithError() throws {
        rootURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("SomacuraCaptureTests-\(UUID().uuidString)", isDirectory: true)
        queue = try CaptureQueue(rootURL: rootURL)
    }

    override func tearDownWithError() throws {
        if let rootURL {
            try? FileManager.default.removeItem(at: rootURL)
        }
    }

    func testCommitWritesExactArtifactBeforeAnyDeliveryState() async throws {
        let envelope = makeEnvelope()
        let queued = try await queue.commit(envelope)

        XCTAssertEqual(queued.state, .pending)
        let content = try Data(contentsOf: queued.contentURL)
        XCTAssertEqual(content, Data(envelope.markdown.utf8))
        XCTAssertEqual(hexDigest(content), envelope.contentSha256)
        XCTAssertTrue(FileManager.default.fileExists(
            atPath: queued.directoryURL.appendingPathComponent("capture.json").path
        ))
        XCTAssertTrue(FileManager.default.fileExists(
            atPath: queued.directoryURL.appendingPathComponent("state.json").path
        ))
        let metadataData = try Data(
            contentsOf: queued.directoryURL.appendingPathComponent("capture.json")
        )
        XCTAssertFalse(String(decoding: metadataData, as: UTF8.self).contains(envelope.markdown))
    }

    func testSameCaptureIsIdempotentButMutatedBodyNeverOverwrites() async throws {
        let envelope = makeEnvelope()
        let first = try await queue.commit(envelope)
        let replay = try await queue.commit(envelope)
        XCTAssertEqual(first, replay)

        let changedBody = envelope.markdown + "changed\n"
        let changed = makeEnvelope(
            id: envelope.captureId,
            markdown: changedBody
        )
        do {
            _ = try await queue.commit(changed)
            XCTFail("Expected immutable capture collision")
        } catch let error as CaptureError {
            XCTAssertEqual(error, .captureCollision(envelope.captureId))
        }
        let stored = try await queue.load(envelope.captureId)
        XCTAssertEqual(stored.envelope?.markdown, envelope.markdown)
        XCTAssertEqual(stored.state.status, .needsAttention)
    }

    func testSeparateProcessActorsSerializeTheSameSharedCommit() async throws {
        let secondQueue = try CaptureQueue(rootURL: rootURL)
        var expectedIds = Set<UUID>()
        for _ in 0..<20 {
            let envelope = makeEnvelope(id: UUID())
            expectedIds.insert(envelope.captureId)
            async let first = queue.commit(envelope)
            async let second = secondQueue.commit(envelope)
            let results = try await [first, second]

            XCTAssertEqual(results[0].envelope, envelope)
            XCTAssertEqual(results[1].envelope, envelope)
        }
        let entries = try await queue.list()
        XCTAssertEqual(Set(entries.map(\.id)), expectedIds)
    }

    func testInterruptedFilingRecoversToPendingAndKeepsMarkdown() async throws {
        let envelope = makeEnvelope()
        _ = try await queue.commit(envelope)
        _ = try await queue.markFiling(
            envelope.captureId,
            destination: makeDestination(),
            now: Date(timeIntervalSince1970: 1)
        )

        try await queue.recoverInterruptedAttempts(
            now: Date(timeIntervalSince1970: 1_000),
            filingTimeout: 10
        )

        let recovered = try await queue.load(envelope.captureId)
        XCTAssertEqual(recovered.state.status, .pending)
        XCTAssertEqual(recovered.state.errorCategory, "interrupted")
        XCTAssertEqual(recovered.envelope?.markdown, envelope.markdown)
    }

    func testFiledCaptureRetainsLocalMarkdown() async throws {
        let envelope = makeEnvelope()
        _ = try await queue.commit(envelope)
        let started = try await queue.markFiling(
            envelope.captureId,
            destination: makeDestination()
        )
        let attempt = try XCTUnwrap(started)
        _ = try await queue.markFiled(
            envelope.captureId,
            attemptId: attempt.id,
            response: makeResponse(envelope)
        )

        let filed = try await queue.load(envelope.captureId)
        XCTAssertEqual(filed.state.status, .filed)
        let storedMarkdown = try await queue.markdown(envelope.captureId)
        XCTAssertEqual(storedMarkdown, envelope.markdown)
        XCTAssertTrue(FileManager.default.fileExists(atPath: filed.contentURL.path))
        let stateAttributes = try FileManager.default.attributesOfItem(
            atPath: filed.directoryURL.appendingPathComponent("state.json").path
        )
        let protection = stateAttributes[.protectionKey] as? FileProtectionType
        #if targetEnvironment(simulator)
        XCTAssertTrue(protection == nil || protection == .complete)
        #else
        XCTAssertEqual(protection, .complete)
        #endif
    }

    func testAttemptLeasePreventsDuplicateAndStaleTerminalWrites() async throws {
        let envelope = makeEnvelope()
        _ = try await queue.commit(envelope)
        let firstStarted = try await queue.markFiling(
            envelope.captureId,
            destination: makeDestination(),
            now: Date(timeIntervalSince1970: 1)
        )
        let first = try XCTUnwrap(firstStarted)
        let otherProcess = try CaptureQueue(rootURL: rootURL)
        let duplicate = try await otherProcess.markFiling(
            envelope.captureId,
            destination: makeDestination()
        )
        XCTAssertNil(duplicate)

        try await queue.recoverInterruptedAttempts(
            now: Date(timeIntervalSince1970: 1_000),
            filingTimeout: 10
        )
        let secondStarted = try await otherProcess.markFiling(
            envelope.captureId,
            destination: makeDestination(name: "Second destination")
        )
        let second = try XCTUnwrap(secondStarted)
        let staleSuccess = try await queue.markFiled(
            envelope.captureId,
            attemptId: first.id,
            response: makeResponse(envelope)
        )
        XCTAssertEqual(staleSuccess.state.status, .filing)
        XCTAssertEqual(staleSuccess.state.attemptId, second.id)
        XCTAssertEqual(staleSuccess.state.destinationRoomName, "Second destination")

        let filed = try await otherProcess.markFiled(
            envelope.captureId,
            attemptId: second.id,
            response: makeResponse(envelope)
        )
        XCTAssertEqual(filed.state.status, .filed)
        let lateFailure = try await queue.markPending(
            envelope.captureId,
            attemptId: first.id,
            category: "network",
            message: "late failure"
        )
        XCTAssertEqual(lateFailure.state.status, .filed)
        XCTAssertNil(lateFailure.state.lastError)
    }

    func testQueueRejectsRootAndChildSymlinksWithoutFollowingThem() async throws {
        let capturesURL = rootURL.appendingPathComponent("Captures", isDirectory: true)
        let realCapturesURL = rootURL.appendingPathComponent("RealCaptures", isDirectory: true)
        try FileManager.default.moveItem(at: capturesURL, to: realCapturesURL)
        try FileManager.default.createSymbolicLink(
            at: capturesURL,
            withDestinationURL: realCapturesURL
        )
        do {
            _ = try await queue.commit(makeEnvelope())
            XCTFail("Expected symlinked queue root to be rejected")
        } catch let error as CaptureError {
            guard case .queueLock = error else {
                return XCTFail("Unexpected error: \(error)")
            }
        }

        try FileManager.default.removeItem(at: capturesURL)
        try FileManager.default.moveItem(at: realCapturesURL, to: capturesURL)
        let envelope = makeEnvelope()
        let queued = try await queue.commit(envelope)
        let outsideState = rootURL.appendingPathComponent("outside-state")
        try Data("outside".utf8).write(to: outsideState)
        let stateURL = queued.directoryURL.appendingPathComponent("state.json")
        try FileManager.default.removeItem(at: stateURL)
        try FileManager.default.createSymbolicLink(
            at: stateURL,
            withDestinationURL: outsideState
        )

        let listed = try await queue.list()
        XCTAssertEqual(listed.count, 1)
        XCTAssertNil(listed[0].envelope)
        XCTAssertEqual(listed[0].state.status, .needsAttention)
        XCTAssertEqual(try Data(contentsOf: outsideState), Data("outside".utf8))
        do {
            _ = try await queue.markPending(
                envelope.captureId,
                category: "retry",
                message: "must not follow"
            )
            XCTFail("Expected symlinked state to be rejected")
        } catch let error as CaptureError {
            guard case .queueCorrupt = error else {
                return XCTFail("Unexpected error: \(error)")
            }
        }
        XCTAssertEqual(try Data(contentsOf: outsideState), Data("outside".utf8))
    }

    func testInvalidNativeMetadataNeverCreatesADurableQueueEntry() async throws {
        let nulMarkdown = "# Invalid\n\nNUL \0 body.\n"
        let invalid = [
            makeEnvelope(id: UUID(), url: URL(string: "http:hostless")!),
            makeEnvelope(id: UUID(), wordCount: -1),
            makeEnvelope(id: UUID(), markdown: nulMarkdown),
            makeEnvelope(
                id: UUID(),
                capturedAt: Date().addingTimeInterval(86_401)
            ),
            makeEnvelope(id: UUID(), title: String(repeating: "t", count: 1_001)),
        ]

        for envelope in invalid {
            do {
                _ = try await queue.commit(envelope)
                XCTFail("Expected malformed native capture to fail")
            } catch let error as CaptureError {
                guard case .invalidCapture = error else {
                    return XCTFail("Unexpected error: \(error)")
                }
            }
        }
        let entries = try await queue.list()
        XCTAssertTrue(entries.isEmpty)
    }

    private func makeEnvelope(
        id: UUID = UUID(uuidString: "00000000-0000-4000-8000-000000000001")!,
        markdown: String = "# Rendered browser truth\n\nExact body.\n",
        url: URL = URL(string: "https://example.com/article")!,
        title: String = "Rendered browser truth",
        wordCount: Int = 5,
        capturedAt: Date = Date(timeIntervalSince1970: 1_788_000_000)
    ) -> CaptureEnvelope {
        CaptureEnvelope(
            captureId: id,
            url: url,
            canonicalUrl: url,
            title: title,
            author: "A. Reporter",
            site: "Example",
            published: "2026-08-28",
            description: "Rendered description",
            language: "en",
            wordCount: wordCount,
            captureMode: .article,
            markdown: markdown,
            contentSha256: hexDigest(Data(markdown.utf8)),
            capturedAt: capturedAt,
            note: nil,
            extraction: CaptureExtraction(
                engine: "defuddle",
                engineVersion: "0.19.3",
                clientVersion: "0.1.0",
                fallbackReason: nil
            )
        )
    }

    private func makeResponse(_ envelope: CaptureEnvelope) -> CaptureServerResponse {
        let readingID = UUID(uuidString: "00000000-0000-4000-8000-000000000002")!
        let revisionID = UUID(uuidString: "00000000-0000-4000-8000-000000000003")!
        return CaptureServerResponse(
            reading: .init(
                id: readingID,
                roomId: UUID(uuidString: "00000000-0000-4000-8000-000000000004")!,
                url: envelope.logicalURL,
                title: envelope.title,
                site: envelope.site,
                source: "browser_capture",
                currentRevisionId: revisionID,
                currentCapturedAt: envelope.capturedAt,
                contentSha256: envelope.contentSha256
            ),
            revision: .init(
                id: revisionID,
                captureId: envelope.captureId,
                captureMode: envelope.captureMode,
                contentSha256: envelope.contentSha256,
                capturedAt: envelope.capturedAt,
                receivedAt: envelope.capturedAt,
                isCurrent: true
            ),
            idempotentReplay: false
        )
    }

    private func makeDestination(name: String = "Research") -> RoomDestination {
        RoomDestination(
            id: UUID(uuidString: "00000000-0000-4000-8000-000000000004")!,
            name: name,
            token: "room-token",
            isHome: false
        )
    }

    private func hexDigest(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}
