import { useEffect, useRef, useState } from "react";
import * as Location from "expo-location";
import {
  Button,
  Pressable,
  StyleSheet,
  Text,
  View,
  Vibration,
} from "react-native";

import MapView, {
  Marker,
  Polyline,
} from "react-native-maps";

type TurnPoint = {
  lat: number;
  lon: number;
  direction: "left" | "right" | "straight";
  instruction: string;
};

type RouteCandidate = {
  id: string;
  name: string;
  distance_km: number;
  total_score: number;
  intersections: number;

  geometry: {
    type: string;
    coordinates: number[][];
  };

  turn_points: TurnPoint[];
};


type RoutePriority =
  | "distance"
  | "easy"
  | "load";


export default function HomeScreen() {
  const startLocation = {
    //latitude: 35.8721,
    //longitude: 140.0106,
    latitude: 35.8644,
    longitude: 140.0206,
  };

  const [currentLocation, setCurrentLocation] =
    useState<{
      latitude: number;
      longitude: number;
    } | null>(null);

  const [routeStartLocation, setRouteStartLocation] =
    useState<{
      latitude: number;
      longitude: number;
    } | null>(null);

  const mapStartLocation =
    currentLocation ?? startLocation;

  const [locationStatus, setLocationStatus] =
    useState("現在地未取得");

  const [currentTurnIndex, setCurrentTurnIndex] =
    useState(0);

  const [closestDistanceToTurn, setClosestDistanceToTurn] =
    useState<number | null>(null);

  const [distanceToTurn, setDistanceToTurn] =
    useState<number | null>(null);

  const [navigationStatus, setNavigationStatus] =
    useState("ナビ待機中");

  const mapRef = useRef<MapView>(null);

  const vibrateForTurn = (
    direction: "left" | "right" | "straight"
  ) => {
    if (direction === "left") {
      // 左折：1回
      Vibration.vibrate();
    }

    if (direction === "right") {
      // 右折：2回
      Vibration.vibrate([0, 400, 300, 400]);
    }
  };

  const [vibratedTurnIndex, setVibratedTurnIndex] =
    useState<number | null>(null);

  useEffect(() => {
    if (!currentLocation) {
      return;
    }

    mapRef.current?.animateCamera(
      {
        center: {
          latitude: currentLocation.latitude,
          longitude: currentLocation.longitude,
        },
      },
      {
        duration: 500,
      }
    );

  }, [currentLocation]);



  useEffect(() => {
    let subscription: Location.LocationSubscription | null = null;

    const startLocationTracking = async () => {
      try {
        setLocationStatus("位置情報追跡準備中...");

        const { status } =
          await Location.requestForegroundPermissionsAsync();

        if (status !== "granted") {
          setLocationStatus("位置情報の許可がありません");
          return;
        }

        subscription =
          await Location.watchPositionAsync(
            {
              accuracy: Location.Accuracy.High,
              distanceInterval: 5,
              timeInterval: 2000,
            },
            (location) => {
              setCurrentLocation({
                latitude: location.coords.latitude,
                longitude: location.coords.longitude,
              });

              setLocationStatus("GPS追跡中");
            }
          );

      } catch (error) {
        console.error(error);
        setLocationStatus("位置情報追跡失敗");
      }
    };

    startLocationTracking();

    return () => {
      if (subscription) {
        subscription.remove();
      }
    };
  }, []);

  const [distanceKm, setDistanceKm] =
    useState(2.0);

  const [priority, setPriority] =
    useState<RoutePriority>("easy");


  const [routes, setRoutes] =
    useState<RouteCandidate[]>([]);

  const [selectedRouteIndex, setSelectedRouteIndex] =
    useState(0);

  const currentRoute =
    routes[selectedRouteIndex];

  useEffect(() => {
    if (!currentLocation) {
      return;
    }

    if (!currentRoute) {
      return;
    }

    const turnPoints = currentRoute.turn_points;

    if (
      !turnPoints ||
      currentTurnIndex >= turnPoints.length
    ) {
      setNavigationStatus("すべての案内地点を通過しました");
      setDistanceToTurn(null);
      return;
    }

    const nextTurn =
      turnPoints[currentTurnIndex];

    const distance =
      calculateDistanceMeters(
        currentLocation.latitude,
        currentLocation.longitude,
        nextTurn.lat,
        nextTurn.lon
      );

    setDistanceToTurn(distance);

    // 最接近距離を記録
    if (
      closestDistanceToTurn === null ||
      distance < closestDistanceToTurn
    ) {
      setClosestDistanceToTurn(distance);
    }

    // 50m以内
    if (distance <= 50) {
      if (nextTurn.direction === "right") {
        setNavigationStatus("右折まで50m以内"); 8
      } else if (nextTurn.direction === "left") {
        setNavigationStatus("左折まで50m以内");
      } else {
        setNavigationStatus("道なりです");
      }
    } else {
      setNavigationStatus(
        `次の案内まで約${Math.round(distance)}m`
      );
    }

    // 一度近づいたあと、離れ始めたら「通過」と判定
    if (
      closestDistanceToTurn !== null &&
      closestDistanceToTurn <= 50 &&
      distance > closestDistanceToTurn + 10
    ) {
      setCurrentTurnIndex(
        (prevIndex) => prevIndex + 1
      );

      setClosestDistanceToTurn(null);
      setDistanceToTurn(null);
    }

  }, [
    currentLocation,
    currentRoute,
    currentTurnIndex,
    closestDistanceToTurn,
  ]);

  const [routeCoordinates, setRouteCoordinates] =
    useState<
      {
        latitude: number;
        longitude: number;
      }[]
    >([]);

  const [status, setStatus] =
    useState("ルート未取得");


  const convertCoordinates = (
    route: RouteCandidate
  ) => {
    return route.geometry.coordinates.map(
      (coordinate) => ({
        longitude: coordinate[0],
        latitude: coordinate[1],
      })
    );
  };


  const selectRoute = (
    index: number
  ) => {
    const selectedRoute = routes[index];

    if (!selectedRoute) {
      return;
    }

    setSelectedRouteIndex(index);

    setRouteCoordinates(
      convertCoordinates(selectedRoute)
    );
  };


  const decreaseDistance = () => {
    setDistanceKm((current) =>
      Math.max(1.0, current - 0.5)
    );
  };


  const increaseDistance = () => {
    setDistanceKm((current) =>
      Math.min(5.0, current + 0.5)
    );
  };


  const getPreferences = () => {
    switch (priority) {

      case "distance":
        return {
          avoid_traffic: false,
          avoid_signals: false,
          avoid_intersections: false,
          elevation_mode: "normal",
        };

      case "easy":
        return {
          avoid_traffic: true,
          avoid_signals: true,
          avoid_intersections: true,
          elevation_mode: "low",
        };

      case "load":
        return {
          avoid_traffic: true,
          avoid_signals: false,
          avoid_intersections: false,
          elevation_mode: "high",
        };
    }
  };


  const fetchRoutes = async () => {
    const requestStart =
      currentLocation ?? startLocation;

    setRouteStartLocation({
      latitude: requestStart.latitude,
      longitude: requestStart.longitude,
    });

    try {
      setStatus("取得中...");

      const response = await fetch(
        "http://192.168.40.145:8000/api/routes/suggest",
        {
          method: "POST",

          headers: {
            "Content-Type": "application/json",
          },

          body: JSON.stringify({
            start: {
              lat: requestStart.latitude,
              lon: requestStart.longitude,
            },

            distance_km: distanceKm,

            preferences: getPreferences(),
          }),
        }
      );


      if (!response.ok) {
        throw new Error(
          `HTTP Error: ${response.status}`
        );
      }

      const data = await response.json();

      const fetchedRoutes: RouteCandidate[] =
        data.routes;


      if (fetchedRoutes.length === 0) {
        setStatus("ルートなし");
        return;
      }


      setRoutes(fetchedRoutes);

      setSelectedRouteIndex(0);

      setRouteCoordinates(
        convertCoordinates(
          fetchedRoutes[0]
        )
      );

      setStatus("取得成功");

    } catch (error) {
      console.error(error);

      setStatus("取得失敗");
    }
  };





  return (
    <View style={styles.container}>

      <MapView
        ref={mapRef}
        style={styles.map}
        initialRegion={{
          latitude: mapStartLocation.latitude,
          longitude: mapStartLocation.longitude,
          latitudeDelta: 0.02,
          longitudeDelta: 0.02,
        }}
      >

        {routeCoordinates.length > 0 && (
          <Polyline
            coordinates={routeCoordinates}
            strokeWidth={6}
            strokeColor="blue"
          />
        )}


        {routeStartLocation && (
          <Marker
            coordinate={routeStartLocation}
            title="START / GOAL"
            pinColor="green"
          />
        )}

        {currentLocation && (
          <Marker
            coordinate={currentLocation}
            title="現在地"
            description="GPSで取得した現在地"
            pinColor="red"
          />
        )}

      </MapView>


      <View style={styles.panel}>

        {/* 距離入力 */}
        <View style={styles.distanceRow}>

          <Text style={styles.locationText}>
            {locationStatus}
          </Text>
          <Text style={styles.navigationText}>
            {navigationStatus}
          </Text>

          {distanceToTurn !== null && (
            <Text>
              次の案内地点まで：
              {Math.round(distanceToTurn)} m
            </Text>
          )}

          {currentRoute?.turn_points?.length > 0 && (
            <Text>
              案内ポイント：
              {currentTurnIndex + 1}
              /
              {currentRoute.turn_points.length}
            </Text>
          )}

          <Text style={styles.sectionTitle}>
            走行距離
          </Text>

          <View style={styles.distanceControls}>

            <Pressable
              onPress={decreaseDistance}
              style={styles.distanceButton}
            >
              <Text style={styles.distanceButtonText}>
                −
              </Text>
            </Pressable>

            <Text style={styles.distanceValue}>
              {distanceKm.toFixed(1)} km
            </Text>

            <Pressable
              onPress={increaseDistance}
              style={styles.distanceButton}
            >
              <Text style={styles.distanceButtonText}>
                ＋
              </Text>
            </Pressable>

          </View>

        </View>


        {/* 重視条件 */}
        <Text style={styles.sectionTitle}>
          重視条件
        </Text>

        <View style={styles.priorityButtons}>

          <PriorityButton
            label="距離"
            selected={priority === "distance"}
            onPress={() =>
              setPriority("distance")
            }
          />

          <PriorityButton
            label="走りやすさ"
            selected={priority === "easy"}
            onPress={() =>
              setPriority("easy")
            }
          />

          <PriorityButton
            label="負荷"
            selected={priority === "load"}
            onPress={() =>
              setPriority("load")
            }
          />

        </View>


        {currentRoute ? (
          <>
            <Text style={styles.routeName}>
              {currentRoute.name}
            </Text>

            <Text>
              距離：
              {currentRoute.distance_km.toFixed(1)}
              km
            </Text>

            <Text>
              Score：
              {currentRoute.total_score.toFixed(0)}
            </Text>

            <Text>
              交差点：
              {currentRoute.intersections}
            </Text>
          </>
        ) : (
          <Text style={styles.status}>
            {status}
          </Text>
        )}


        {routes.length > 0 && (

          <View style={styles.routeButtons}>

            {routes.map(
              (route, index) => (

                <Pressable
                  key={route.id}
                  onPress={() =>
                    selectRoute(index)
                  }
                  style={[
                    styles.routeButton,

                    selectedRouteIndex === index &&
                    styles.selectedRouteButton,
                  ]}
                >

                  <Text
                    style={[
                      styles.routeButtonText,

                      selectedRouteIndex === index &&
                      styles.selectedRouteButtonText,
                    ]}
                  >
                    候補{index + 1}
                  </Text>

                </Pressable>
              )
            )}

          </View>

        )}


        <Button
          title="ルート取得"
          onPress={fetchRoutes}
        />

      </View>

    </View>
  );
}


type PriorityButtonProps = {
  label: string;
  selected: boolean;
  onPress: () => void;
};


function PriorityButton({
  label,
  selected,
  onPress,
}: PriorityButtonProps) {

  return (
    <Pressable
      onPress={onPress}
      style={[
        styles.priorityButton,

        selected &&
        styles.selectedPriorityButton,
      ]}
    >

      <Text
        style={[
          styles.priorityButtonText,

          selected &&
          styles.selectedPriorityButtonText,
        ]}
      >
        {label}
      </Text>

    </Pressable>
  );
}


const styles = StyleSheet.create({

  container: {
    flex: 1,
  },

  map: {
    flex: 1,
  },

  panel: {
    position: "absolute",
    top: 60,
    left: 20,
    right: 20,

    backgroundColor: "white",

    padding: 15,

    borderRadius: 12,
  },

  locationText: {
    fontWeight: "bold",
    marginBottom: 10,
  },

  navigationText: {
    fontWeight: "bold",
    marginBottom: 5,
  },

  sectionTitle: {
    fontWeight: "bold",
    marginBottom: 6,
  },

  distanceRow: {
    marginBottom: 12,
  },

  distanceControls: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },

  distanceButton: {
    width: 44,
    height: 40,

    borderRadius: 8,

    backgroundColor: "#007AFF",

    alignItems: "center",
    justifyContent: "center",
  },

  distanceButtonText: {
    color: "white",
    fontSize: 22,
    fontWeight: "bold",
  },

  distanceValue: {
    fontSize: 18,
    fontWeight: "bold",
  },

  priorityButtons: {
    flexDirection: "row",

    gap: 8,

    marginBottom: 14,
  },

  priorityButton: {
    flex: 1,

    paddingVertical: 9,

    backgroundColor: "#eeeeee",

    borderRadius: 8,

    alignItems: "center",
  },

  selectedPriorityButton: {
    backgroundColor: "#007AFF",
  },

  priorityButtonText: {
    color: "#007AFF",

    fontWeight: "bold",

    fontSize: 12,
  },

  selectedPriorityButtonText: {
    color: "white",
  },

  status: {
    marginBottom: 10,
    fontWeight: "bold",
  },

  routeName: {
    fontSize: 16,
    fontWeight: "bold",
    marginBottom: 5,
  },

  routeButtons: {
    flexDirection: "row",

    marginTop: 10,
    marginBottom: 10,

    gap: 8,
  },

  routeButton: {
    flex: 1,

    paddingVertical: 10,

    backgroundColor: "#eeeeee",

    borderRadius: 8,

    alignItems: "center",
  },

  selectedRouteButton: {
    backgroundColor: "#007AFF",
  },

  routeButtonText: {
    color: "#007AFF",
    fontWeight: "bold",
  },

  selectedRouteButtonText: {
    color: "white",
  },

});

function calculateDistanceMeters(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number
) {
  const earthRadius = 6371000;

  const toRadians = (degree: number) =>
    (degree * Math.PI) / 180;

  const dLat = toRadians(lat2 - lat1);
  const dLon = toRadians(lon2 - lon1);

  const latitude1 = toRadians(lat1);
  const latitude2 = toRadians(lat2);

  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(latitude1) *
    Math.cos(latitude2) *
    Math.sin(dLon / 2) ** 2;

  const c =
    2 *
    Math.atan2(
      Math.sqrt(a),
      Math.sqrt(1 - a)
    );

  return earthRadius * c;
}