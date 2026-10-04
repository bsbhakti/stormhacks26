import Foundation

enum TriageServerConfig {
    /// Point this at the machine running `backend_serv/server.py`.
    /// Use the Mac's LAN address for a physical iPhone, not localhost.
    static let baseURL = URL(string: "http://172.16.205.106:5000")!
}

/// Patient care stage stored by the backend and sent to the ESP.
enum PatientCareStatus: Int, Codable {
    /// Available / back on the monitoring queue.
    case monitoring = 0
    /// A responder is on the way.
    case finding = 1
    /// The responder is with the patient.
    case found = 2
    /// Removed from the active queue.
    case stopped = 3
}

struct PatientAssignment: Codable, Equatable {
    var id: String
    var name: String
    var status: PatientCareStatus?

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case status
        case tagName
        case advertisedName
    }

    init(id: String, name: String, status: PatientCareStatus? = nil) {
        self.id = id
        self.name = name
        self.status = status
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(String.self, forKey: .id) ?? UUID().uuidString
        if let rawStatus = try container.decodeIfPresent(Int.self, forKey: .status) {
            status = PatientCareStatus(rawValue: rawStatus)
        } else {
            status = nil
        }
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
        try container.encodeIfPresent(status?.rawValue, forKey: .status)
    }
}

struct TriageAPIError: LocalizedError {
    var errorDescription: String?

    static let invalidResponse = TriageAPIError(errorDescription: "The triage server sent an invalid response.")
    static let missingName = TriageAPIError(errorDescription: "The triage server did not include a tag name.")
}

enum TriageAPI {
    static func nextAssignment() async throws -> PatientAssignment {
        var assignment = try await send(
            path: "/assignments/next",
            method: "POST",
            body: nil as Data?,
            as: PatientAssignment.self
        )
        assignment.name = AdvertisedName.normalized(assignment.name)
        assignment.status = assignment.status ?? .finding
        guard !assignment.name.isEmpty else { throw TriageAPIError.missingName }
        return assignment
    }

    static func markAssignmentFound(id: String) async throws {
        try await updateStatus(id: id, status: .found)
    }

    static func completeAssignment(id: String, status: PatientCareStatus) async throws {
        guard status == .monitoring || status == .stopped else {
            throw TriageAPIError(errorDescription: "Finished care must set status 0 or 3.")
        }
        try await updateStatus(id: id, status: status)
    }

    static func updateStatus(id: String, status: PatientCareStatus) async throws {
        struct Payload: Encodable {
            let status: Int
        }
        struct Response: Decodable {
            let id: String
            let status: Int?
        }

        let path = status == .found
            ? "/assignments/\(id)/found"
            : "/assignments/\(id)/status"
        let body = status == .found ? nil : Payload(status: status.rawValue)
        _ = try await send(
            path: path,
            method: "POST",
            body: body,
            as: Response.self
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

        let (data, response) = try URLSession.shared.data(for: request)
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
        if let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let message = object["error"] as? String {
            return message
        }
        if let http = response as? HTTPURLResponse {
            return "Triage server returned \(http.statusCode)."
        }
        return "Could not reach the triage server."
    }
}
