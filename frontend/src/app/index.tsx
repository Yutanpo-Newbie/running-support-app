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

  const [isPanelExpanded, setIsPanelExpanded] =
    useState(false);

  const [locationStatus, setLocationStatus] =
    useState("現在地未取得");

  const [currentTurnIndex, setCurrentTurnIndex] =
    useState(0);

  const activeCheckpointRef =
    useRef<number | "start" | null>(null);

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

    const turnPoints =
      currentRoute.turn_points;

    if (
      !turnPoints ||
      turnPoints.length === 0
    ) {
      return;
    }


    // =====================================
    // 設定
    // =====================================

    // チェックポイント到達判定
    const ARRIVAL_DISTANCE = 20;

    // 一度入ったチェックポイントから
    // この距離以上離れたら再入場可能にする
    const EXIT_DISTANCE = 30;


    // =====================================
    // STARTまでの距離
    // =====================================

    let distanceToStart: number | null =
      null;

    if (routeStartLocation) {

      distanceToStart =
        calculateDistanceMeters(
          currentLocation.latitude,
          currentLocation.longitude,
          routeStartLocation.latitude,
          routeStartLocation.longitude
        );
    }


    // =====================================
    // 各turn pointまでの距離を計算
    // =====================================

    const checkpointDistances =
      turnPoints.map(
        (turnPoint, index) => {

          const distance =
            calculateDistanceMeters(
              currentLocation.latitude,
              currentLocation.longitude,
              turnPoint.lat,
              turnPoint.lon
            );

          return {
            index,
            distance,
          };
        }
      );


    // =====================================
    // 一番近いチェックポイント
    // =====================================

    const nearestCheckpoint =
      checkpointDistances.reduce(
        (nearest, current) => {

          if (
            current.distance <
            nearest.distance
          ) {
            return current;
          }

          return nearest;
        }
      );


    // =====================================
    // 現在入っているチェックポイントの
    // ロック解除
    // =====================================

    if (
      activeCheckpointRef.current !== null
    ) {

      // STARTにいる場合
      if (
        activeCheckpointRef.current ===
        "start"
      ) {

        if (
          distanceToStart !== null &&
          distanceToStart >
          EXIT_DISTANCE
        ) {

          activeCheckpointRef.current =
            null;
        }

      } else {

        const activeIndex =
          activeCheckpointRef.current;

        const activeDistance =
          checkpointDistances[
            activeIndex
          ]?.distance;


        if (
          activeDistance !== undefined &&
          activeDistance >
          EXIT_DISTANCE
        ) {

          activeCheckpointRef.current =
            null;
        }
      }
    }


    // =====================================
    // START地点に入った
    // =====================================

    if (
      distanceToStart !== null &&
      distanceToStart <=
      ARRIVAL_DISTANCE &&
      activeCheckpointRef.current === null
    ) {

      activeCheckpointRef.current =
        "start";


      // 全チェックポイント終了後ならGOAL
      if (
        currentTurnIndex >=
        turnPoints.length
      ) {

        setNavigationStatus(
          "GOALに到着しました"
        );

        setDistanceToTurn(0);

        return;
      }


      // 途中から逆走してSTARTへ戻った
      setCurrentTurnIndex(0);

      setVibratedTurnIndex(null);

      setNavigationStatus(
        "START地点に戻りました"
      );

      return;
    }


    // =====================================
    // いずれかのチェックポイントに到達
    // =====================================

    if (
      nearestCheckpoint.distance <=
      ARRIVAL_DISTANCE &&
      activeCheckpointRef.current === null
    ) {

      const reachedIndex =
        nearestCheckpoint.index;


      activeCheckpointRef.current =
        reachedIndex;


      // 例：
      //
      // turnPoints[0] に到達
      // → 次はturnPoints[1]
      // → currentTurnIndex = 1
      //
      // 逆走してturnPoints[0]へ戻っても
      // → currentTurnIndex = 1
      //
      // つまり方向判定不要
      const nextIndex =
        reachedIndex + 1;


      setCurrentTurnIndex(
        nextIndex
      );

      setVibratedTurnIndex(
        null
      );


      // 最終チェックポイント
      if (
        nextIndex >=
        turnPoints.length
      ) {

        setNavigationStatus(
          "最終チェックポイント到達"
        );

        setDistanceToTurn(null);

        return;
      }


      setNavigationStatus(
        `チェックポイント${reachedIndex + 1
        }到達`
      );

      return;
    }


    // =====================================
    // 次に案内するチェックポイント
    // =====================================

    if (
      currentTurnIndex >=
      turnPoints.length
    ) {

      setNavigationStatus(
        "GOALへ向かってください"
      );

      if (
        distanceToStart !== null
      ) {

        setDistanceToTurn(
          distanceToStart
        );
      }

      return;
    }


    const nextTurn =
      turnPoints[currentTurnIndex];


    const distanceToNextTurn =
      calculateDistanceMeters(
        currentLocation.latitude,
        currentLocation.longitude,
        nextTurn.lat,
        nextTurn.lon
      );


    setDistanceToTurn(
      distanceToNextTurn
    );


    // =====================================
    // 50m振動
    // =====================================

    if (
      distanceToNextTurn <= 50
    ) {

      if (
        vibratedTurnIndex !==
        currentTurnIndex
      ) {

        vibrateForTurn(
          nextTurn.direction
        );

        setVibratedTurnIndex(
          currentTurnIndex
        );
      }


      if (
        nextTurn.direction ===
        "right"
      ) {

        setNavigationStatus(
          "右折まで50m以内"
        );

      } else if (
        nextTurn.direction ===
        "left"
      ) {

        setNavigationStatus(
          "左折まで50m以内"
        );

      } else {

        setNavigationStatus(
          "道なりです"
        );
      }

    } else {

      setNavigationStatus(
        `次の案内まで約${Math.round(
          distanceToNextTurn
        )}m`
      );
    }


  }, [
    currentLocation,
    currentRoute,
    currentTurnIndex,
    routeStartLocation,
    vibratedTurnIndex,
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

    const selectedRoute =
      routes[index];

    if (!selectedRoute) {
      return;
    }

    setSelectedRouteIndex(index);

    setCurrentTurnIndex(0);

    setDistanceToTurn(null);

    setVibratedTurnIndex(null);

    activeCheckpointRef.current =
      null;

    setNavigationStatus(
      "ナビ待機中"
    );

    setRouteCoordinates(
      convertCoordinates(
        selectedRoute
      )
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
      setCurrentTurnIndex(0);
      setDistanceToTurn(null);
      setVibratedTurnIndex(null);
      activeCheckpointRef.current =
        null;
      setNavigationStatus(
        "ナビ開始"
      );

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

      {/* =========================
        MAP
    ========================== */}
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

        {/* ルート */}
        {routeCoordinates.length > 0 && (
          <Polyline
            coordinates={routeCoordinates}
            strokeWidth={6}
            strokeColor="blue"
          />
        )}

        {/* START / GOAL */}
        {routeStartLocation && (
          <Marker
            coordinate={routeStartLocation}
            title="START / GOAL"
            pinColor="green"
          />
        )}

        {/* 現在地 */}
        {currentLocation && (
          <Marker
            coordinate={currentLocation}
            title="現在地"
            description="GPSで取得した現在地"
            pinColor="red"
          />
        )}

      </MapView>


      {/* =========================
        BOTTOM PANEL
    ========================== */}
      <View
        style={[
          styles.panel,
          isPanelExpanded
            ? styles.panelExpanded
            : styles.panelCollapsed,
        ]}
      >

        {/* パネル開閉 */}
        <Pressable
          style={styles.panelHandle}
          onPress={() =>
            setIsPanelExpanded(
              (previous) => !previous
            )
          }
        >

          <View style={styles.handleBar} />

          <Text style={styles.panelToggleText}>
            {isPanelExpanded
              ? "閉じる"
              : "詳細を見る"}
          </Text>

        </Pressable>


        {/* =========================
          常に表示するナビ情報
      ========================== */}
        <View style={styles.navigationSummary}>

          <Text style={styles.navigationMainText}>
            {navigationStatus}
          </Text>

          <View style={styles.navigationRow}>

            {/* 案内ポイント */}
            {currentRoute?.turn_points?.length > 0 && (
              <Text style={styles.navigationSubText}>
                案内：
                {Math.min(
                  currentTurnIndex + 1,
                  currentRoute.turn_points.length
                )}
                /
                {currentRoute.turn_points.length}

              </Text>
            )}
            {/* 次の案内までの距離 */}
            {distanceToTurn !== null && (
              <Text style={styles.navigationDistance}>
                {Math.round(distanceToTurn)}m
              </Text>
            )}

          </View>

          {/* GPS状態 */}
          <Text style={styles.locationText}>
            {locationStatus}
          </Text>

        </View>


        {/* =========================
          展開時のみ表示
      ========================== */}
        {isPanelExpanded && (

          <View style={styles.panelDetails}>

            {/* -------------------------
              距離入力
          -------------------------- */}
            <View style={styles.distanceRow}>

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


            {/* -------------------------
              重視条件
          -------------------------- */}
            <Text style={styles.sectionTitle}>
              重視条件
            </Text>

            <View style={styles.priorityButtons}>

              <PriorityButton
                label="距離"
                selected={
                  priority === "distance"
                }
                onPress={() =>
                  setPriority("distance")
                }
              />

              <PriorityButton
                label="走りやすさ"
                selected={
                  priority === "easy"
                }
                onPress={() =>
                  setPriority("easy")
                }
              />

              <PriorityButton
                label="負荷"
                selected={
                  priority === "load"
                }
                onPress={() =>
                  setPriority("load")
                }
              />

            </View>


            {/* -------------------------
              選択中ルート情報
          -------------------------- */}
            {currentRoute ? (

              <View style={styles.routeInfo}>

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

              </View>

            ) : (

              <Text style={styles.status}>
                {status}
              </Text>

            )}


            {/* -------------------------
              ルート候補
          -------------------------- */}
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


            {/* -------------------------
              ルート取得
          -------------------------- */}
            <View style={styles.fetchButtonContainer}>

              <Button
                title="ルート取得"
                onPress={fetchRoutes}
              />

            </View>

          </View>

        )}

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
    left: 12,
    right: 12,
    bottom: 20,

    backgroundColor: "white",
    borderRadius: 20,

    paddingHorizontal: 16,
    paddingBottom: 14,

    shadowColor: "#000",
    shadowOffset: {
      width: 0,
      height: 3,
    },
    shadowOpacity: 0.2,
    shadowRadius: 6,

    elevation: 8,
  },

  panelCollapsed: {
    minHeight: 125,
  },

  panelExpanded: {
    maxHeight: "70%",
  },

  panelHandle: {
    alignItems: "center",
    paddingTop: 8,
    paddingBottom: 4,
  },

  handleBar: {
    width: 45,
    height: 5,
    borderRadius: 3,
    backgroundColor: "#cccccc",
    marginBottom: 4,
  },

  panelToggleText: {
    fontSize: 12,
    color: "#555555",
  },

  navigationSummary: {
    paddingTop: 4,
    paddingBottom: 8,
  },

  navigationMainText: {
    fontSize: 20,
    fontWeight: "700",
    textAlign: "center",
  },

  navigationRow: {
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 20,
    marginTop: 6,
  },

  navigationSubText: {
    fontSize: 14,
    color: "#555555",
  },

  navigationDistance: {
    fontSize: 22,
    fontWeight: "700",
  },

  locationText: {
    textAlign: "center",
    fontSize: 12,
    color: "#777777",
    marginTop: 4,
  },

  panelDetails: {
    marginTop: 8,
  },

  routeInfo: {
    marginTop: 12,
    marginBottom: 8,
  },

  fetchButtonContainer: {
    marginTop: 12,
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