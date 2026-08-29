import Foundation
import Security

protocol CredentialVault: Sendable {
    func load() async throws -> TokenCredentials?
    func save(_ credentials: TokenCredentials) async throws
    func delete() async throws
}

enum CredentialError: LocalizedError, Sendable, Equatable {
    case keychain(OSStatus)
    case invalidData

    var errorDescription: String? {
        switch self {
        case .keychain(let status):
            "Keychain operation failed (OSStatus \(status))."
        case .invalidData:
            "Stored credentials are unreadable."
        }
    }
}

actor KeychainCredentialStore: CredentialVault {
    private let service: String
    private let accessGroup: String
    private let account = "dialectic-session"

    init(service: String = "org.somacura.capture.credentials", accessGroup: String) {
        self.service = service
        self.accessGroup = accessGroup
    }

    func load() throws -> TokenCredentials? {
        var query = baseQuery()
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else { throw CredentialError.keychain(status) }
        guard let data = result as? Data else { throw CredentialError.invalidData }
        do {
            return try CaptureJSON.decoder().decode(TokenCredentials.self, from: data)
        } catch {
            throw CredentialError.invalidData
        }
    }

    func save(_ credentials: TokenCredentials) throws {
        let data = try CaptureJSON.encoder().encode(credentials)
        let query = baseQuery()
        let updates = [kSecValueData as String: data]
        let updateStatus = SecItemUpdate(query as CFDictionary, updates as CFDictionary)
        if updateStatus == errSecSuccess { return }
        guard updateStatus == errSecItemNotFound else {
            throw CredentialError.keychain(updateStatus)
        }
        var addition = query
        addition[kSecValueData as String] = data
        addition[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        let addStatus = SecItemAdd(addition as CFDictionary, nil)
        guard addStatus == errSecSuccess else { throw CredentialError.keychain(addStatus) }
    }

    func delete() throws {
        let status = SecItemDelete(baseQuery() as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw CredentialError.keychain(status)
        }
    }

    private func baseQuery() -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecAttrAccessGroup as String: accessGroup,
        ]
    }
}

enum DialecticAPIError: LocalizedError, Sendable, Equatable {
    case notAuthenticated
    case invalidResponse
    case transport(String)
    case server(status: Int, detail: String)

    var errorDescription: String? {
        switch self {
        case .notAuthenticated:
            "Sign in to file this capture."
        case .invalidResponse:
            "Dialectic returned an invalid response."
        case .transport(let message):
            "Dialectic is unreachable: \(message)"
        case .server(_, let detail):
            detail
        }
    }

    var category: String {
        switch self {
        case .notAuthenticated: "authentication"
        case .invalidResponse: "invalid_response"
        case .transport: "network"
        case .server(let status, _): "http_\(status)"
        }
    }

    var isTransient: Bool {
        switch self {
        case .transport: true
        case .server(let status, _): status >= 500 || status == 408 || status == 429
        case .notAuthenticated, .invalidResponse: false
        }
    }
}

actor DialecticAPIClient {
    private struct SignInRequest: Codable {
        let email: String
        let password: String
    }

    private struct RefreshRequest: Codable {
        let refreshToken: String
    }

    private struct TokenResponse: Codable {
        let accessToken: String
        let refreshToken: String
        let userId: UUID
        let displayName: String?

        var credentials: TokenCredentials {
            TokenCredentials(
                accessToken: accessToken,
                refreshToken: refreshToken,
                userId: userId,
                displayName: displayName
            )
        }
    }

    private struct RoomResponse: Codable {
        let id: UUID
        let name: String?
        let token: String
        let isHome: Bool

        var destination: RoomDestination {
            RoomDestination(
                id: id,
                name: name?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false
                    ? name!
                    : "Unnamed Room",
                token: token,
                isHome: isHome
            )
        }
    }

    private struct ErrorResponse: Codable {
        let detail: String?
    }

    private let configuration: AppConfiguration
    private let credentials: any CredentialVault
    private let session: URLSession

    init(
        configuration: AppConfiguration,
        credentials: any CredentialVault,
        session: URLSession = .shared
    ) {
        self.configuration = configuration
        self.credentials = credentials
        self.session = session
    }

    func login(email: String, password: String) async throws -> TokenCredentials {
        let body = try CaptureJSON.encoder().encode(
            SignInRequest(email: email, password: password)
        )
        let data = try await send(
            path: "/auth/login",
            method: "POST",
            body: body,
            accessToken: nil,
            roomToken: nil
        )
        let response = try decode(TokenResponse.self, from: data)
        try await credentials.save(response.credentials)
        return response.credentials
    }

    func rooms() async throws -> [RoomDestination] {
        let data = try await authorized(
            path: "/users/me/rooms",
            method: "GET",
            body: nil,
            roomToken: nil
        )
        return try decode([RoomResponse].self, from: data)
            .map(\.destination)
            .sorted { lhs, rhs in
                if lhs.isHome != rhs.isHome { return lhs.isHome }
                return lhs.name.localizedCaseInsensitiveCompare(rhs.name) == .orderedAscending
            }
    }

    func file(
        _ envelope: CaptureEnvelope,
        to destination: RoomDestination
    ) async throws -> CaptureServerResponse {
        let body = try CaptureJSON.encoder().encode(envelope)
        let data = try await authorized(
            path: "/rooms/\(destination.id.uuidString)/reading/capture",
            method: "POST",
            body: body,
            roomToken: destination.token
        )
        let response = try decode(CaptureServerResponse.self, from: data)
        guard response.reading.roomId == destination.id,
              response.reading.url == envelope.logicalURL,
              response.reading.source == "browser_capture",
              response.revision.captureId == envelope.captureId,
              response.revision.captureMode == envelope.captureMode,
              response.revision.contentSha256 == envelope.contentSha256 else {
            throw DialecticAPIError.invalidResponse
        }
        if response.revision.isCurrent {
            guard response.reading.currentRevisionId == response.revision.id,
                  response.reading.contentSha256 == response.revision.contentSha256,
                  response.reading.currentCapturedAt == response.revision.capturedAt else {
                throw DialecticAPIError.invalidResponse
            }
        } else if response.reading.currentRevisionId == response.revision.id {
            throw DialecticAPIError.invalidResponse
        }
        return response
    }

    private func authorized(
        path: String,
        method: String,
        body: Data?,
        roomToken: String?
    ) async throws -> Data {
        guard var current = try await credentials.load() else {
            throw DialecticAPIError.notAuthenticated
        }
        do {
            return try await send(
                path: path,
                method: method,
                body: body,
                accessToken: current.accessToken,
                roomToken: roomToken
            )
        } catch DialecticAPIError.server(let status, _) where status == 401 {
            do {
                current = try await refresh(current)
            } catch DialecticAPIError.server(let refreshStatus, _)
                where refreshStatus == 401 {
                try await credentials.delete()
                throw DialecticAPIError.notAuthenticated
            }
            do {
                return try await send(
                    path: path,
                    method: method,
                    body: body,
                    accessToken: current.accessToken,
                    roomToken: roomToken
                )
            } catch DialecticAPIError.server(let retryStatus, _)
                where retryStatus == 401 && roomToken == nil {
                try await credentials.delete()
                throw DialecticAPIError.notAuthenticated
            }
        }
    }

    private func refresh(_ current: TokenCredentials) async throws -> TokenCredentials {
        let body = try CaptureJSON.encoder().encode(
            RefreshRequest(refreshToken: current.refreshToken)
        )
        let data = try await send(
            path: "/auth/refresh",
            method: "POST",
            body: body,
            accessToken: nil,
            roomToken: nil
        )
        let refreshed = try decode(TokenResponse.self, from: data).credentials
        try await credentials.save(refreshed)
        return refreshed
    }

    private func send(
        path: String,
        method: String,
        body: Data?,
        accessToken: String?,
        roomToken: String?
    ) async throws -> Data {
        guard let url = URL(string: path, relativeTo: configuration.baseURL) else {
            throw DialecticAPIError.invalidResponse
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if body != nil {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if let accessToken {
            request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        }
        if let roomToken {
            request.setValue(roomToken, forHTTPHeaderField: "X-Room-Token")
        }

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw DialecticAPIError.transport(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else {
            throw DialecticAPIError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            let detail = (try? CaptureJSON.decoder().decode(ErrorResponse.self, from: data).detail)
                ?? HTTPURLResponse.localizedString(forStatusCode: http.statusCode)
            throw DialecticAPIError.server(status: http.statusCode, detail: detail)
        }
        return data
    }

    private func decode<Value: Decodable>(
        _ type: Value.Type,
        from data: Data
    ) throws -> Value {
        do {
            return try CaptureJSON.decoder().decode(type, from: data)
        } catch {
            throw DialecticAPIError.invalidResponse
        }
    }
}
