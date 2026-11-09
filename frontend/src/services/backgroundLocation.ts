
import * as TaskManager from "expo-task-manager";
import * as Location from "expo-location";
import AsyncStorage from "@react-native-async-storage/async-storage";

export const LOCATION_TASK_NAME =
  "running-background-location";

export const BG_POINTS_KEY =
  "running-background-points";

type SavedPoint = {
  latitude: number;
  longitude: number;
  timestamp: number;
  accuracy: number | null;
};

// Reactコンポーネントの外で定義する
TaskManager.defineTask(
  LOCATION_TASK_NAME,
  async ({ data, error }) => {

    if (error) {
      console.error("BG GPS ERROR", error);
      return;
    }

    const locations = (
      data as {
        locations?: Location.LocationObject[];
      } | undefined
    )?.locations;

    if (!locations || locations.length === 0) {
      return;
    }

    const newPoints: SavedPoint[] =
      locations.map((location) => ({
        latitude: location.coords.latitude,
        longitude: location.coords.longitude,
        timestamp: location.timestamp,
        accuracy: location.coords.accuracy,
      }));

    try {
      const saved =
        await AsyncStorage.getItem(BG_POINTS_KEY);

      const oldPoints: SavedPoint[] =
        saved ? JSON.parse(saved) : [];

      const allPoints = [
        ...oldPoints,
        ...newPoints,
      ].slice(-5000);

      await AsyncStorage.setItem(
        BG_POINTS_KEY,
        JSON.stringify(allPoints)
      );

      console.log(
        "BG GPS SAVED",
        newPoints.length,
        "total:",
        allPoints.length
      );

    } catch (e) {
      console.error("BG GPS SAVE ERROR", e);
    }
  }
);
