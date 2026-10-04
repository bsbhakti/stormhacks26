import Foundation

enum TriageServerConfig {
    /// Point this at the machine running `server/triage_server.py`.
    /// Use the Mac's LAN address for a physical iPhone, not localhost.
    static let baseURL = URL(string: "http://172.16.205.106:8080")!
}

struct PatientAssignment: Codable, Equatable {
    var id: String
    var name: String

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case tagName
        case advertisedName
    }

    init(id: String, name: String) {
        self.id = id
        self.name = name
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(String.self, forKey: .id) ?? UUID().uuidString
        if let name = try container.decodeIfPresent(String.self, forKey: .name) {
            self.name = name
        } else if let name = try container.decodeIfPresent(String.self, forKey: .tagName) {
            self.name = name
        } else {
            self.name = try container.decode(String.self, forKey: .advertisedName)
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encode(name, forKey: .name)
    }
}

enum PatientOutcome: String, Codable {
    case helped
    case needsFurtherHelp = "needs_further_help"
}

struct TriageAPIError: LocalizedError {
    var errorDescription: String?

    static let invalidResponse = TriageAPIError(errorDescription: "The triage server sent an invalid response.")
    static let missingName = TriageAPIError(errorDescription: "The triage server did not include a tag name.")
}

enum TriageAPI {
    static func nextAssignment() async throws -> PatientAssignment {
        let assignment = try await send(
            path: "/assignments/next",
            method: "POST",
            body: nil as Data?,
            as: PatientAssignment.self
        )
        let name = AdvertisedName.normalized(assignment.name)
        guard !name.isEmpty else { throw TriageAPIError.missingName }
        return PatientAssignment(id: assignment.id, name: name)
    }

    static func completeAssignment(id: String, outcome: PatientOutcome) async throws {
        struct Payload: Encodable {
            let status: PatientOutcome
        }
        struct OK: Decodable {}

        _ = try await send(
            path: "/assignments/\(id)/complete",
            method: "POST",
            body: Payload(status: outcome),
            as: OK.self
        )
    }

    private static func endpoint(_ path: String) throws -> URL {
        guard var components = URLComponents(url: TriageServerConfig.baseURL, resolvingAgainstBaseURL: false) else {
            throw TriageAPIError.invalidResponse
        }
        components.path = path.hasPrefix("/") ? path : "/" + path
        guard let url = components.url else { throw TriageAPIError.invalidResponse }
        return url
    }

    private static func send<Body: Encodable, Response: Decodable>(
        path: String,
        method: String,
        body: Body?,
        as type: Response.Type
    ) async throws -> Response {
        var request = URLRequest(url: try endpoint(path))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.timeoutInterval = 12

        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(body)
        }

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw TriageAPIError(errorDescription: serverMessage(from: data, response: response))
        }
        do {
            return try JSONDecoder().decode(Response.self, from: data)
        } catch {
            throw TriageAPIError.invalidResponse
        }
    }

    private static func serverMessage(from data: Data, response: URLResponse) -> String {
        if let http = response as? HTTPURLResponse,
           let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let message = object["error"] as? String {
            return message
        }
        if let http = response as? HTTPURLResponse {
            return "Triage server returned \(http.statusCode)."
        }
        return "Could not reach the triage server."
    }
}
