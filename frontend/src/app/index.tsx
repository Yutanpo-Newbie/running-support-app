import { useEffect, useRef, useState } from "react";
import * as Location from "expo-location";
import {
  Button,
  Modal,
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

import * as Speech from "expo-speech";

import AsyncStorage from "@react-native-async-storage/async-storage";

import {
  LOCATION_TASK_NAME,
  BG_POINTS_KEY,
} from "../services/backgroundLocation";

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

  // =====================================
  // 15.1 走行状態
  // =====================================

  type RunStatus =
    | "idle"
    | "running"
    | "cancelled"
    | "completed";

  const [runStatus, setRunStatus] =
    useState<RunStatus>("idle");

  // =====================================
  // 15.2 走行時間・実走行距離
  // =====================================

  // 走行時間（秒）
  const [elapsedSeconds, setElapsedSeconds] =
    useState(0);

  // 実際に走行した距離（km）
  const [runDistanceKm, setRunDistanceKm] =
    useState(0);

  // =====================================
  // 15.4 GPS走行軌跡
  // =====================================

  const [runTrack, setRunTrack] = useState<
    {
      latitude: number;
      longitude: number;
    }[]
  >([]);

  const resultMapRef = useRef<MapView>(null);

  // 走行開始時刻
  const runStartTimeRef =
    useRef<number | null>(null);

  // 直前の有効なGPS座標と取得時刻
  const previousRunLocationRef = useRef<{
    latitude: number;
    longitude: number;
    timestamp: number;
  } | null>(null);

  // =====================================
  // 15.2 走行タイマー
  // =====================================

  useEffect(() => {

    if (runStatus !== "running") {
      return;
    }

    const interval = setInterval(() => {

      if (runStartTimeRef.current === null) {
        return;
      }

      const elapsed = Math.floor(
        (Date.now() - runStartTimeRef.current) / 1000
      );

      setElapsedSeconds(elapsed);

    }, 1000);

    return () => {
      clearInterval(interval);
    };

  }, [runStatus]);

  const [currentTurnIndex, setCurrentTurnIndex] =
    useState(0);

  const activeCheckpointRef =
    useRef<number | "start" | null>(null);

  // =====================================
  // 15.3 周回完了判定用
  // =====================================

  // 次に順番どおり通過すべきチェックポイント
  const nextExpectedCheckpointRef =
    useRef(0);

  // GOALへの到着を判定してよいか
  const goalArmedRef =
    useRef(false);

  // 走行開始後、STARTから離れたか
  const hasLeftStartRef =
    useRef(false);

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

  const speakForTurn = (
    direction: "left" | "right" | "straight"
  ) => {

    let message = "";

    if (direction === "left") {
      message = "50メートル先、左です";
    } else if (direction === "right") {
      message = "50メートル先、右です";
    } else {
      message = "50メートル先、道なりです";
    }

    Speech.speak(
      message,
      {
        language: "ja-JP",
        rate: 0.9,
        pitch: 1.0,
        volume: 1.0,
      }
    );
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

  const checkBackgroundGps = async () => {

    const saved =
      await AsyncStorage.getItem(BG_POINTS_KEY);

    const points = saved ? JSON.parse(saved) : [];

    console.log("BACKGROUND GPS RESULT", {
      count: points.length,
      first: points[0],
      last: points[points.length - 1],
    });
  };



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


  // =====================================
  // 15.4 GPS走行軌跡の記録
  // =====================================

  useEffect(() => {

    if (
      runStatus !== "running" ||
      !currentLocation
    ) {
      return;
    }

    setRunTrack((previousTrack) => {

      // 最初のGPS位置
      if (previousTrack.length === 0) {
        return [currentLocation];
      }

      const lastPoint =
        previousTrack[previousTrack.length - 1];

      const movedMeters =
        calculateDistanceMeters(
          lastPoint.latitude,
          lastPoint.longitude,
          currentLocation.latitude,
          currentLocation.longitude
        );

      // 同一地点付近の重複データを除外
      if (movedMeters < 3) {
        return previousTrack;
      }

      // 新しいGPS座標を追加
      return [
        ...previousTrack,
        currentLocation,
      ];

    });

  }, [currentLocation, runStatus]);


  // =====================================
  // 15.2 GPSによる実走行距離の計測
  // =====================================

  useEffect(() => {

    // 走行中以外は記録しない
    if (
      runStatus !== "running" ||
      !currentLocation
    ) {
      return;
    }

    const now = Date.now();

    const previous =
      previousRunLocationRef.current;

    // 最初のGPS地点を記録
    if (!previous) {

      previousRunLocationRef.current = {
        ...currentLocation,
        timestamp: now,
      };

      return;
    }

    // 前回の地点からの距離（m）
    const movedMeters =
      calculateDistanceMeters(
        previous.latitude,
        previous.longitude,
        currentLocation.latitude,
        currentLocation.longitude
      );

    // 経過時間（秒）
    const timeDifference = Math.max(
      (now - previous.timestamp) / 1000,
      0.001
    );

    // 移動速度（m/s）
    const speed =
      movedMeters / timeDifference;

    // 長時間GPSが更新されなかった場合や
    // 不自然な移動があった場合は
    // 基準地点を現在地に更新する
    if (
      timeDifference > 10 ||
      movedMeters > 50 ||
      speed > 8
    ) {
      previousRunLocationRef.current = {
        ...currentLocation,
        timestamp: now,
      };

      return;
    }

    // 4m未満の移動は蓄積しておく
    if (movedMeters < 4) {
      return;
    }

    // 実走行距離を加算
    setRunDistanceKm(
      (previousDistance) =>
        previousDistance + movedMeters / 1000
    );

    // 次の比較用に現在地を保存
    previousRunLocationRef.current = {
      ...currentLocation,
      timestamp: now,
    };

  }, [currentLocation, runStatus]);

  // =====================================
  // ナビゲーション用
  // =====================================

  useEffect(() => {

    if (runStatus !== "running") {
      return;
    }

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

    if (
      distanceToStart !== null &&
      distanceToStart > 30
    ) {
      hasLeftStartRef.current = true;
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
      distanceToStart <= ARRIVAL_DISTANCE &&
      activeCheckpointRef.current === null
    ) {

      activeCheckpointRef.current = "start";

      // =====================================
      // 15.3 GOAL判定デバッグログ
      // =====================================

      console.log("GOAL CHECK", {
        currentTurnIndex,

        totalTurns: turnPoints.length,

        expected:
          nextExpectedCheckpointRef.current,

        goalArmed:
          goalArmedRef.current,

        hasLeftStart:
          hasLeftStartRef.current,

        distanceToStart,

        activeCheckpoint:
          activeCheckpointRef.current,

        runStatus,
      });

      // ---------------------------------
      // 1周完了
      // ---------------------------------

      if (
        hasLeftStartRef.current &&
        goalArmedRef.current &&
        nextExpectedCheckpointRef.current ===
        turnPoints.length
      ) {

        // 完了時刻を確定
        if (runStartTimeRef.current !== null) {
          setElapsedSeconds(
            Math.floor(
              (Date.now() -
                runStartTimeRef.current) / 1000
            )
          );
        }

        // 計測を停止
        runStartTimeRef.current = null;
        previousRunLocationRef.current = null;

        // ナビゲーションを停止
        Vibration.cancel();
        void Speech.stop();

        setRunStatus("completed");

        console.log("RUN COMPLETED", {
          elapsedSeconds,
          runDistanceKm,
          currentTurnIndex,
          expected: nextExpectedCheckpointRef.current,
          totalTurns: turnPoints.length,
        });

        setNavigationStatus(
          "1周完了！お疲れさまでした"
        );

        setDistanceToTurn(0);

        goalArmedRef.current = false;

        return;
      }

      // ---------------------------------
      // 途中でSTARTへ戻った場合
      // ---------------------------------

      setCurrentTurnIndex(0);
      setVibratedTurnIndex(null);

      // 順番の記録も最初から
      nextExpectedCheckpointRef.current = 0;
      goalArmedRef.current = false;

      setNavigationStatus(
        "START地点に戻りました"
      );

      setDistanceToTurn(null);

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


      // =====================================
      // 15.3 順番どおりの到達履歴
      // =====================================

      const expectedIndex =
        nextExpectedCheckpointRef.current;

      if (reachedIndex === expectedIndex) {

        // 期待していた次のCPに到達
        nextExpectedCheckpointRef.current =
          expectedIndex + 1;

        // 最終CPまで順番どおり到達
        if (
          nextExpectedCheckpointRef.current ===
          turnPoints.length
        ) {
          goalArmedRef.current = true;
        }

      } else if (
        reachedIndex < expectedIndex - 1
      ) {

        // 前のCPへ戻ったので
        // 順番の記録も戻す
        nextExpectedCheckpointRef.current =
          reachedIndex + 1;

        goalArmedRef.current = false;
      }

      // 期待する番号より先のCPを踏んでも、
      // 順番どおりの到達とはみなさない。



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

        // 振動
        vibrateForTurn(
          nextTurn.direction
        );

        // 音声
        speakForTurn(
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
    runStatus,
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

    if (runStatus === "running") {
      return;
    }

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
    if (runStatus === "running") {
      return;
    }

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


  // =====================================
  // 15.1 走行開始
  // =====================================

  const startRun = async () => {

    if (
      runStatus === "running" ||
      !currentRoute ||
      !currentLocation ||
      !routeStartLocation
    ) {
      return;
    }

    // チェックポイントを初期化
    setCurrentTurnIndex(0);
    setDistanceToTurn(null);
    setVibratedTurnIndex(null);

    // START付近で開始する場合、
    // GPSの揺れによる再入場を防ぐ
    const distanceToStart =
      calculateDistanceMeters(
        currentLocation.latitude,
        currentLocation.longitude,
        routeStartLocation.latitude,
        routeStartLocation.longitude
      );

    activeCheckpointRef.current =
      distanceToStart <= 20
        ? "start"
        : null;

    // 既存の通知をクリア
    Vibration.cancel();
    void Speech.stop();

    // 走行計測を初期化
    setElapsedSeconds(0);
    setRunDistanceKm(0);

    // 前回のGPS軌跡を消去
    setRunTrack([
      {
        latitude: currentLocation.latitude,
        longitude: currentLocation.longitude,
      },
    ]);

    // 開始時刻を記録
    const now = Date.now();
    runStartTimeRef.current = now;

    // 走行開始位置を記録
    previousRunLocationRef.current = {
      latitude: currentLocation.latitude,
      longitude: currentLocation.longitude,
      timestamp: now,
    };

    // 最初のチェックポイントから記録
    nextExpectedCheckpointRef.current = 0;

    // GOAL判定はまだ無効
    goalArmedRef.current = false;

    // STARTから離れていない
    hasLeftStartRef.current = false;


    // バックグラウンド位置情報の許可
    // const permission =
    //   await Location.requestBackgroundPermissionsAsync();

    // if (permission.status !== "granted") {
    //   setNavigationStatus(
    //     "バックグラウンド位置情報の許可が必要です"
    //   );
    //   return;
    // }

    // try {
    //   // 前回のGPS記録を初期化
    //   await AsyncStorage.setItem(
    //     BG_POINTS_KEY,
    //     JSON.stringify([])
    //   );

    //   const alreadyStarted =
    //     await Location.hasStartedLocationUpdatesAsync(
    //       LOCATION_TASK_NAME
    //     );

    //   if (!alreadyStarted) {
    //     await Location.startLocationUpdatesAsync(
    //       LOCATION_TASK_NAME,
    //       {
    //         accuracy: Location.Accuracy.High,
    //         distanceInterval: 5,
    //         activityType: Location.ActivityType.Fitness,
    //         pausesUpdatesAutomatically: false,
    //         showsBackgroundLocationIndicator: true,
    //         foregroundService: {
    //           notificationTitle: "ランニング記録中",
    //           notificationBody:
    //             "位置情報を記録しています",
    //         },
    //       }
    //     );
    //   }

    // } catch (error) {
    //   console.error("BG GPS START ERROR", error);
    //   setNavigationStatus(
    //     "GPSのバックグラウンド追跡開始に失敗"
    //   );
    //   return;
    // }


    // 走行開始
    setRunStatus("running");
    setNavigationStatus("走行中");

    // 詳細パネルを閉じる
    setIsPanelExpanded(false);
  };


  // =====================================
  // 15.1 走行中止
  // =====================================

  const cancelRun = async () => {

    if (runStatus !== "running") {
      return;
    }

    // 中止時点の経過時間を確定
    if (runStartTimeRef.current !== null) {

      setElapsedSeconds(
        Math.floor(
          (Date.now() - runStartTimeRef.current) / 1000
        )
      );
    }

    // 計測用Refをリセット
    runStartTimeRef.current = null;
    previousRunLocationRef.current = null;

    setRunStatus("cancelled");

    // const started =
    //   await Location.hasStartedLocationUpdatesAsync(
    //     LOCATION_TASK_NAME
    //   );

    // if (started) {
    //   await Location.stopLocationUpdatesAsync(
    //     LOCATION_TASK_NAME
    //   );
    // }

    goalArmedRef.current = false;
    nextExpectedCheckpointRef.current = 0;
    hasLeftStartRef.current = false;

    // 振動・音声を停止
    Vibration.cancel();
    void Speech.stop();

    setDistanceToTurn(null);
    setVibratedTurnIndex(null);

    // チェックポイントの入場状態を解除
    activeCheckpointRef.current = null;

    setNavigationStatus(
      "走行を中止しました"
    );
  };


  // =====================================
  // 15.4 結果画面を閉じる
  // =====================================

  const closeResult = () => {

    // 通常のルート選択画面へ戻る
    setRunStatus("idle");

    // ナビ状態を初期化
    setCurrentTurnIndex(0);
    setDistanceToTurn(null);
    setVibratedTurnIndex(null);

    // チェックポイント判定を初期化
    activeCheckpointRef.current = null;

    nextExpectedCheckpointRef.current = 0;
    goalArmedRef.current = false;
    hasLeftStartRef.current = false;

    // 計測用Refを初期化
    runStartTimeRef.current = null;
    previousRunLocationRef.current = null;

    Vibration.cancel();
    void Speech.stop();

    // ルートは維持して再走行可能にする
    setNavigationStatus(
      "ルート取得済み・走行待機中"
    );

    setIsPanelExpanded(false);
  };


  // =====================================
  // 開発用：1周完了を強制実行
  // =====================================

  const completeRunForTest = () => {

    if (runStatus !== "running") {
      return;
    }

    // 経過時間を確定
    if (runStartTimeRef.current !== null) {
      setElapsedSeconds(
        Math.floor(
          (Date.now() - runStartTimeRef.current) / 1000
        )
      );
    }

    // 計測を停止
    runStartTimeRef.current = null;
    previousRunLocationRef.current = null;

    // 通知を停止
    Vibration.cancel();
    void Speech.stop();

    // 画面の案内番号を最終状態にする
    if (currentRoute) {
      setCurrentTurnIndex(
        currentRoute.turn_points.length
      );
    }

    setDistanceToTurn(0);
    setNavigationStatus(
      "1周完了！お疲れさまでした"
    );

    // 結果パネルを開く
    setRunStatus("completed");
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


        {/* =====================================
          15.4 ランニング結果画面
      ===================================== */}

        <Modal
          visible={runStatus === "completed"}
          animationType="slide"
          presentationStyle="fullScreen"
          onRequestClose={closeResult}
        >
          <View style={styles.resultScreen}>

            <Text style={styles.resultTitle}>
              ランニング結果
            </Text>

            <Text style={styles.resultMessage}>
              1周完了！お疲れさまでした
            </Text>

            {/* 結果地図 */}
            <View style={styles.resultMapContainer}>

              <MapView
                ref={resultMapRef}
                style={styles.resultMap}
                initialRegion={{
                  latitude:
                    routeCoordinates[0]?.latitude ??
                    currentLocation?.latitude ??
                    startLocation.latitude,

                  longitude:
                    routeCoordinates[0]?.longitude ??
                    currentLocation?.longitude ??
                    startLocation.longitude,

                  latitudeDelta: 0.015,
                  longitudeDelta: 0.015,
                }}
                onMapReady={() => {
                  const points = [
                    ...routeCoordinates,
                    ...runTrack,
                  ];

                  if (points.length >= 2) {
                    resultMapRef.current?.fitToCoordinates(
                      points,
                      {
                        edgePadding: {
                          top: 45,
                          right: 35,
                          bottom: 45,
                          left: 35,
                        },
                        animated: false,
                      }
                    );
                  }
                }}
              >

                {/* 提案されたルート：青 */}
                {routeCoordinates.length >= 2 && (
                  <Polyline
                    coordinates={routeCoordinates}
                    strokeColor="#2563EB"
                    strokeWidth={4}
                  />
                )}

                {/* 実際のGPS走行軌跡：緑 */}
                {runTrack.length >= 2 && (
                  <Polyline
                    coordinates={runTrack}
                    strokeColor="#16A34A"
                    strokeWidth={5}
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

              </MapView>

            </View>

            <View style={styles.resultLegend}>
              <Text style={styles.resultLegendText}>
                🔵 提案ルート
              </Text>

              <Text style={styles.resultLegendText}>
                🟢 GPS走行軌跡
              </Text>
            </View>

            {/* 走行記録 */}
            <View style={styles.resultStats}>

              <View style={styles.resultStatItem}>
                <Text style={styles.resultStatLabel}>
                  走行時間
                </Text>

                <Text style={styles.resultStatValue}>
                  {formatRunTime(elapsedSeconds)}
                </Text>
              </View>

              <View style={styles.resultStatItem}>
                <Text style={styles.resultStatLabel}>
                  実走行距離
                </Text>

                <Text style={styles.resultStatValue}>
                  {runDistanceKm.toFixed(2)} km
                </Text>
              </View>

              <View style={styles.resultStatItem}>
                <Text style={styles.resultStatLabel}>
                  平均ペース
                </Text>

                <Text style={styles.resultStatValue}>
                  {formatAveragePace(
                    elapsedSeconds,
                    runDistanceKm
                  )}
                </Text>
              </View>

            </View>

            {/* 閉じるボタン */}
            <Pressable
              style={styles.closeResultButton}
              onPress={closeResult}
            >
              <Text style={styles.closeResultText}>
                閉じてルート選択に戻る
              </Text>
            </Pressable>

          </View>
        </Modal>



        {/* =========================
          常に表示するナビ情報
      ========================== */}
        <View style={styles.navigationSummary}>

          <Text style={styles.navigationMainText}>
            {navigationStatus}
          </Text>

          <Button
            title="バックグラウンドGPS確認"
            onPress={checkBackgroundGps}
          />

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

          {/* =====================================
    15.2 ランニング情報
===================================== */}

          <View style={styles.runStatsContainer}>

            <View style={styles.runStatItem}>
              <Text style={styles.runStatLabel}>
                走行時間
              </Text>

              <Text style={styles.runStatValue}>
                {formatRunTime(elapsedSeconds)}
              </Text>
            </View>

            <View style={styles.runStatItem}>
              <Text style={styles.runStatLabel}>
                実走行距離
              </Text>

              <Text style={styles.runStatValue}>
                {runDistanceKm.toFixed(2)} km
              </Text>
            </View>

            <View style={styles.runStatItem}>
              <Text style={styles.runStatLabel}>
                平均ペース
              </Text>

              <Text style={styles.runStatValue}>
                {formatAveragePace(
                  elapsedSeconds,
                  runDistanceKm
                )}
              </Text>
            </View>

          </View>

          {/* =========================
    15.1 走行開始・中止
========================= */}

          <View style={styles.runButtonContainer}>

            {runStatus === "completed" ? (

              <View style={styles.runButton}>
                <Text style={styles.completedRunText}>
                  ✓ 1周完了！
                </Text>
              </View>

            ) : runStatus === "running" ? (

              <Pressable
                onPress={cancelRun}
                style={[
                  styles.runButton,
                  styles.cancelRunButton,
                ]}
              >
                <Text style={styles.runButtonText}>
                  ■ 走行中止
                </Text>
              </Pressable>

            ) : (

              <Pressable
                onPress={startRun}
                disabled={
                  !currentRoute ||
                  !currentLocation ||
                  !routeStartLocation
                }
                style={[
                  styles.runButton,
                  styles.startRunButton,

                  (!currentRoute ||
                    !currentLocation ||
                    !routeStartLocation) &&
                  styles.disabledRunButton,
                ]}
              >
                <Text style={styles.runButtonText}>
                  ▶ 走行開始
                </Text>
              </Pressable>

            )}

          </View>

          {/* 開発者専用：強制ゴール */}
          {__DEV__ && runStatus === "running" && (

            <Pressable
              style={styles.testCompleteButton}
              onPress={completeRunForTest}
            >
              <Text style={styles.testCompleteButtonText}>
                🧪 テスト：1周完了
              </Text>
            </Pressable>

          )}

        </View>


        {/* =========================
          展開時のみ表示
      ========================== */}
        {isPanelExpanded && runStatus !== "running" && (

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

// =====================================
// 秒数を HH:MM:SS に変換
// =====================================

function formatRunTime(totalSeconds: number) {

  const hours =
    Math.floor(totalSeconds / 3600);

  const minutes =
    Math.floor((totalSeconds % 3600) / 60);

  const seconds =
    totalSeconds % 60;

  return [
    hours,
    minutes,
    seconds,
  ]
    .map((value) =>
      String(value).padStart(2, "0")
    )
    .join(":");
}


// =====================================
// 平均ペース表示
// =====================================

function formatAveragePace(
  seconds: number,
  distanceKm: number
) {

  if (distanceKm < 0.05) {
    return "--";
  }

  const paceSeconds =
    Math.round(seconds / distanceKm);

  const minutes =
    Math.floor(paceSeconds / 60);

  const remainingSeconds =
    paceSeconds % 60;

  return (
    `${minutes}'${String(remainingSeconds).padStart(2, "0")}"/km`
  );
}


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

  runButtonContainer: {
    marginTop: 12,
  },

  runButton: {
    paddingVertical: 14,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
  },

  startRunButton: {
    backgroundColor: "#16A34A",
  },

  cancelRunButton: {
    backgroundColor: "#DC2626",
  },

  disabledRunButton: {
    backgroundColor: "#9CA3AF",
  },

  runButtonText: {
    color: "#FFFFFF",
    fontSize: 17,
    fontWeight: "bold",
  },

  runStatsContainer: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 12,
    paddingVertical: 10,
    paddingHorizontal: 8,
    backgroundColor: "#F3F4F6",
    borderRadius: 12,
  },

  runStatItem: {
    flex: 1,
    alignItems: "center",
  },

  runStatLabel: {
    fontSize: 11,
    color: "#6B7280",
    marginBottom: 4,
  },

  runStatValue: {
    fontSize: 14,
    fontWeight: "bold",
    color: "#111827",
  },

  completedRunText: {
    color: "#16A34A",
    fontSize: 18,
    fontWeight: "bold",
    textAlign: "center",
  },


  // =====================================
  // 15.4 ランニング結果画面
  // =====================================

  resultScreen: {
    flex: 1,
    backgroundColor: "#FFFFFF",
    paddingTop: 65,
    paddingHorizontal: 20,
    paddingBottom: 30,
  },

  resultTitle: {
    fontSize: 24,
    fontWeight: "bold",
    color: "#111827",
    textAlign: "center",
    marginBottom: 10,
  },

  resultMessage: {
    fontSize: 19,
    fontWeight: "bold",
    color: "#16A34A",
    textAlign: "center",
    marginBottom: 20,
  },

  resultMapContainer: {
    height: 280,
    borderRadius: 16,
    overflow: "hidden",
    backgroundColor: "#E5E7EB",
  },

  resultMap: {
    width: "100%",
    height: "100%",
  },

  resultLegend: {
    flexDirection: "row",
    justifyContent: "center",
    gap: 20,
    marginTop: 12,
    marginBottom: 24,
  },

  resultLegendText: {
    fontSize: 13,
    color: "#4B5563",
  },

  resultStats: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 22,
    paddingHorizontal: 8,
    backgroundColor: "#F3F4F6",
    borderRadius: 14,
  },

  resultStatItem: {
    flex: 1,
    alignItems: "center",
  },

  resultStatLabel: {
    fontSize: 12,
    color: "#6B7280",
    marginBottom: 8,
  },

  resultStatValue: {
    fontSize: 15,
    fontWeight: "bold",
    color: "#111827",
  },

  closeResultButton: {
    marginTop: "auto",
    backgroundColor: "#2563EB",
    borderRadius: 14,
    paddingVertical: 17,
    alignItems: "center",
    justifyContent: "center",
  },

  closeResultText: {
    color: "#FFFFFF",
    fontSize: 16,
    fontWeight: "bold",
  },

  testCompleteButton: {
    marginTop: 10,
    paddingVertical: 12,
    borderRadius: 12,
    backgroundColor: "#EDE9FE",
    borderWidth: 1,
    borderColor: "#A78BFA",
    alignItems: "center",
  },

  testCompleteButtonText: {
    fontSize: 13,
    fontWeight: "bold",
    color: "#6D28D9",
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