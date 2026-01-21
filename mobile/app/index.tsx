import { View, ActivityIndicator, StyleSheet } from 'react-native';

export default function IndexScreen() {
  // This screen briefly shows while the root layout determines
  // where to redirect based on session state
  return (
    <View style={styles.container}>
      <ActivityIndicator testID="activity-indicator" size="large" color="#3b82f6" />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
});
