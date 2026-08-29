//
//  SafariWebExtensionHandler.swift
//  SomacuraCapture Extension
//
//  Created by Thomas Amosson on 2026.08.28.
//

import SafariServices

final class SafariWebExtensionHandler: NSObject, NSExtensionRequestHandling {
    private static let maximumNativeMessageBytes = 4_250_000
    private static let requestKeys: Set<String> = ["type", "capture"]
    private static let captureKeys: Set<String> = [
        "capture_id", "url", "canonical_url", "title", "author", "site",
        "published", "description", "language", "word_count", "capture_mode",
        "markdown", "content_sha256", "captured_at", "note", "extraction",
    ]
    private static let extractionKeys: Set<String> = [
        "engine", "engine_version", "client_version", "fallback_reason",
    ]

    private let runtime: Result<CaptureRuntime, Error>

    override init() {
        runtime = Result { try CaptureRuntime.live() }
        super.init()
    }

    func beginRequest(with context: NSExtensionContext) {
        let request = context.inputItems.first as? NSExtensionItem
        let message = request?.userInfo?[SFExtensionMessageKey]
        Task {
            let result = await handle(message)
            let response = NSExtensionItem()
            response.userInfo = [SFExtensionMessageKey: dictionary(result)]
            context.completeRequest(returningItems: [response], completionHandler: nil)
        }
    }

    private func handle(_ message: Any?) async -> NativeQueueResult {
        do {
            guard let message,
                  JSONSerialization.isValidJSONObject(message) else {
                throw CaptureError.invalidCapture("native message is not JSON")
            }
            guard let dictionary = message as? [String: Any],
                  Set(dictionary.keys) == Self.requestKeys,
                  let capture = dictionary["capture"] as? [String: Any],
                  Set(capture.keys) == Self.captureKeys,
                  let extraction = capture["extraction"] as? [String: Any],
                  Set(extraction.keys) == Self.extractionKeys else {
                throw CaptureError.invalidCapture("native message fields do not match the capture contract")
            }
            let data = try JSONSerialization.data(withJSONObject: message)
            guard data.count <= Self.maximumNativeMessageBytes else {
                throw CaptureError.invalidCapture("native message exceeds the local size limit")
            }
            let request = try CaptureJSON.decoder().decode(NativeQueueRequest.self, from: data)
            guard request.type == "queue_capture" else {
                throw CaptureError.invalidCapture("unsupported native message type")
            }
            let live = try runtime.get()
            return try await live.delivery.queueAndFile(request.capture)
        } catch {
            return NativeQueueResult(
                localDurable: false,
                deliveryStatus: .needsAttention,
                roomName: nil,
                errorCategory: "local_write",
                errorMessage: bounded(error.localizedDescription)
            )
        }
    }

    private func dictionary(_ result: NativeQueueResult) -> [String: Any] {
        guard let data = try? CaptureJSON.encoder().encode(result),
              let value = try? JSONSerialization.jsonObject(with: data),
              let dictionary = value as? [String: Any] else {
            return [
                "local_durable": false,
                "delivery_status": "needs_attention",
                "error_category": "native_response",
                "error_message": "The native response could not be encoded.",
            ]
        }
        return dictionary
    }

    private func bounded(_ value: String, maximum: Int = 180) -> String {
        let normalized = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard normalized.count > maximum else { return normalized }
        return String(normalized.prefix(maximum - 1)) + "…"
    }
}
