//
//  ContentView.swift
//  RunningSupportApp
//
//  Created by 白樺 on 2026/08/25.
//

import SwiftUI
import MapboxMaps
import CoreLocation

struct ContentView: View {
    @State private var routeCoordinates: [CLLocationCoordinate2D] = []
    @State private var currentRoute: RouteCandidate?
    @State private var statusText: String = "ルート未取得"
    
    private let routeAPIClient = RouteAPIClient()
    
    var body: some View {
        ZStack(alignment: .top) {
            Map(
                initialViewport: .camera(
                    center: CLLocationCoordinate2D(
                        latitude: 35.8721,
                        longitude: 140.0106
                    ),
                    zoom: 15,
                    bearing: 0,
                    pitch: 0
                )
            ) {
                if !routeCoordinates.isEmpty {
                    PolylineAnnotation(
                        lineCoordinates: routeCoordinates
                    )
                    .lineColor(StyleColor(.systemBlue))
                    .lineWidth(7)
                }
                
                if let startCoordinate = routeCoordinates.first {
                    MapViewAnnotation(coordinate: startCoordinate) {
                        RouteMarkerView(
                            title: "START / GOAL",
                            systemImageName: "figure.run",
                            backgroundColor: .green
                        )
                    }
                }
                
                if let oneKmCoordinate = coordinateAtDistance(
                    coordinates: routeCoordinates,
                    targetDistanceMeters: 1000
                ) {
                    MapViewAnnotation(coordinate: oneKmCoordinate) {
                        RouteMarkerView(
                            title: "1km",
                            systemImageName: "flag.fill",
                            backgroundColor: .orange
                        )
                    }
                }
            }
            .ignoresSafeArea()
            
            VStack(spacing: 10) {
                RouteInfoCardView(
                    route: currentRoute,
                    statusText: statusText
                )
                
                Button("ルート取得") {
                    Task {
                        await fetchRoute()
                    }
                }
                .font(.headline)
                .padding(.horizontal, 22)
                .padding(.vertical, 10)
                .background(.blue)
                .foregroundStyle(.white)
                .cornerRadius(14)
                .shadow(radius: 4)
            }
            .padding(.top, 55)
            .padding(.horizontal, 16)
        }
    }
    
    private func fetchRoute() async {
        statusText = "取得中..."
        
        do {
            let routes = try await routeAPIClient.fetchRoutes()
            
            guard let firstRoute = routes.first else {
                statusText = "ルートなし"
                currentRoute = nil
                routeCoordinates = []
                return
            }
            
            currentRoute = firstRoute
            routeCoordinates = firstRoute.lineCoordinates
            statusText = "取得成功"
        } catch {
            statusText = "取得失敗"
            print("Route fetch error:", error)
        }
    }
}

struct RouteInfoCardView: View {
    let route: RouteCandidate?
    let statusText: String
    
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let route {
                Text(route.name)
                    .font(.headline)
                
                HStack {
                    Text("距離: \(route.distanceKm, specifier: "%.1f")km")
                    Text("Score: \(route.totalScore, specifier: "%.0f")")
                    Text("交差点: \(route.intersections)")
                }
                .font(.subheadline)
            } else {
                Text(statusText)
                    .font(.headline)
                
                Text("ルート取得ボタンを押してください")
                    .font(.subheadline)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.white.opacity(0.92))
        .cornerRadius(16)
        .shadow(radius: 5)
    }
}

struct RouteMarkerView: View {
    let title: String
    let systemImageName: String
    let backgroundColor: Color
    
    var body: some View {
        HStack(spacing: 5) {
            Image(systemName: systemImageName)
            Text(title)
                .fontWeight(.bold)
        }
        .font(.caption)
        .foregroundStyle(.white)
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(backgroundColor)
        .cornerRadius(14)
        .shadow(radius: 4)
    }
}

func coordinateAtDistance(
    coordinates: [CLLocationCoordinate2D],
    targetDistanceMeters: Double
) -> CLLocationCoordinate2D? {
    guard coordinates.count >= 2 else {
        return nil
    }
    
    var accumulatedDistance: Double = 0
    
    for index in 0..<(coordinates.count - 1) {
        let start = coordinates[index]
        let end = coordinates[index + 1]
        
        let segmentDistance = distanceMeters(
            from: start,
            to: end
        )
        
        if accumulatedDistance + segmentDistance >= targetDistanceMeters {
            let remainingDistance = targetDistanceMeters - accumulatedDistance
            let ratio = remainingDistance / segmentDistance
            
            return interpolateCoordinate(
                from: start,
                to: end,
                ratio: ratio
            )
        }
        
        accumulatedDistance += segmentDistance
    }
    
    return coordinates.last
}

func distanceMeters(
    from start: CLLocationCoordinate2D,
    to end: CLLocationCoordinate2D
) -> Double {
    let startLocation = CLLocation(
        latitude: start.latitude,
        longitude: start.longitude
    )
    
    let endLocation = CLLocation(
        latitude: end.latitude,
        longitude: end.longitude
    )
    
    return startLocation.distance(from: endLocation)
}

func interpolateCoordinate(
    from start: CLLocationCoordinate2D,
    to end: CLLocationCoordinate2D,
    ratio: Double
) -> CLLocationCoordinate2D {
    let latitude = start.latitude + (end.latitude - start.latitude) * ratio
    let longitude = start.longitude + (end.longitude - start.longitude) * ratio
    
    return CLLocationCoordinate2D(
        latitude: latitude,
        longitude: longitude
    )
}

#Preview {
    ContentView()
}
