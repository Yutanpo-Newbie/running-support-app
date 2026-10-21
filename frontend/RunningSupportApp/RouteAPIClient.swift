//
//  RouteAPIClient.swift
//  RunningSupportApp
//
//  Created by 白樺 on 2026/08/26.
//
import Foundation
import CoreLocation

struct RouteRequest: Codable {
    let start: StartPoint
    let distanceKm: Double
    let preferences: RoutePreferences
    
    enum CodingKeys: String, CodingKey {
        case start
        case distanceKm = "distance_km"
        case preferences
    }
}

struct StartPoint: Codable {
    let lat: Double
    let lon: Double
}

struct RoutePreferences: Codable {
    let avoidTraffic: Bool
    let avoidSignals: Bool
    let avoidIntersections: Bool
    let elevationMode: String
    
    enum CodingKeys: String, CodingKey {
        case avoidTraffic = "avoid_traffic"
        case avoidSignals = "avoid_signals"
        case avoidIntersections = "avoid_intersections"
        case elevationMode = "elevation_mode"
    }
}

struct RouteResponse: Codable {
    let routes: [RouteCandidate]
}

struct RouteCandidate: Codable, Identifiable {
    let id: String
    let name: String
    let distanceKm: Double
    let elevationGainM: Double
    let signals: Int
    let intersections: Int
    let trafficScore: Double
    let totalScore: Double
    let geometry: RouteGeometry
    
    enum CodingKeys: String, CodingKey {
        case id
        case name
        case distanceKm = "distance_km"
        case elevationGainM = "elevation_gain_m"
        case signals
        case intersections
        case trafficScore = "traffic_score"
        case totalScore = "total_score"
        case geometry
    }
}

struct RouteGeometry: Codable {
    let type: String
    let coordinates: [[Double]]
}

final class RouteAPIClient {
    private let baseURL = "http://192.168.40.145:8000"
    
    func fetchRoutes() async throws -> [RouteCandidate] {
        guard let url = URL(string: "\(baseURL)/api/routes/suggest") else {
            throw URLError(.badURL)
        }
        
        let requestBody = RouteRequest(
            start: StartPoint(
                lat: 35.8721,
                lon: 140.0106
            ),
            distanceKm: 2.0,
            preferences: RoutePreferences(
                avoidTraffic: true,
                avoidSignals: true,
                avoidIntersections: true,
                elevationMode: "low"
            )
        )
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(requestBody)
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        if let httpResponse = response as? HTTPURLResponse {
            print("Status Code:", httpResponse.statusCode)
        }
        
        let decodedResponse = try JSONDecoder().decode(RouteResponse.self, from: data)
        
        return decodedResponse.routes
    }
}

extension RouteCandidate {
    var lineCoordinates: [CLLocationCoordinate2D] {
        geometry.coordinates.compactMap { coordinate in
            guard coordinate.count >= 2 else {
                return nil
            }
            
            let lon = coordinate[0]
            let lat = coordinate[1]
            
            return CLLocationCoordinate2D(
                latitude: lat,
                longitude: lon
            )
        }
    }
}
