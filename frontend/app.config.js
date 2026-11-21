
module.exports = ({ config }) => {
  const googleMapsApiKey =
    process.env.GOOGLE_MAPS_API_KEY;

  // キーがある場合だけAndroid用プラグインを追加
  const plugins = [...(config.plugins ?? [])];

  if (googleMapsApiKey) {
    plugins.push([
      "react-native-maps",
      {
        androidGoogleMapsApiKey: googleMapsApiKey,
      },
    ]);
  }

  return {
    ...config,
    plugins,
  };
};
